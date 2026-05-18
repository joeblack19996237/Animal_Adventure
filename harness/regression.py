from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from events import emit_event
from state import find_phase, halt_issue, save_state
from subprocess_runner import run_command
from verify import (
    REVIEW_REPORT_PATH,
    _cleanup_verification_artifacts,
    _prepare_verification_cmd,
    _select_test_cmd,
    _verification_cmd_kwargs,
)

if TYPE_CHECKING:
    from harness import Harness

logger = logging.getLogger(__name__)

REGRESSION_SOURCE = "regression"


def collect_regression_commands(
    harness: Harness, state: dict, through_phase_id: int | None = None
) -> list[list[str]]:
    commands: list[list[str]] = []
    seen_cmds: set[tuple[str, ...]] = set()
    for sp in state.get("phases", []):
        if through_phase_id is not None and int(sp["id"]) > int(through_phase_id):
            continue
        phase_type = harness.phase_type_for(sp["id"])
        method = getattr(harness, "verification_profiles_for", None)
        profiles = None
        if callable(method):
            try:
                profiles = method(sp["id"])
            except (AttributeError, TypeError):
                profiles = None
        if not isinstance(profiles, list) or not profiles:
            profiles = [harness.profile_for(sp["id"])]
        for profile in profiles:
            cmd = tuple(_select_test_cmd(profile, phase_type))
            if cmd not in seen_cmds:
                seen_cmds.add(cmd)
                commands.append(list(cmd))
    return commands


def run_phase_regression_gate(harness: Harness, state: dict, phase_id: int) -> bool:
    phase = find_phase(state, phase_id)
    if not phase:
        raise ValueError(f"Phase {phase_id} not found")

    regression = phase.setdefault("regression", {})
    regression["status"] = "running"
    regression["attempts"] = regression.get("attempts", 0) + 1
    regression["last_started_at"] = _now_iso()
    commands = collect_regression_commands(harness, state, through_phase_id=phase_id)
    regression["commands"] = commands
    save_state(state)

    evidence = _run_regression_commands(harness, commands, phase_id)
    regression["last_run"] = evidence
    regression["last_finished_at"] = _now_iso()

    failures = [item for item in evidence["commands"] if item.get("returncode") != 0]
    if not failures:
        regression["status"] = "passed"
        regression["last_error"] = []
        regression["passed_sha"] = _current_head()
        _mark_regression_issues_fixed(phase, regression["passed_sha"])
        save_state(state)
        logger.info("[REGRESSION] Phase %d full regression passed.", phase_id)
        return True

    regression["status"] = "failed"
    regression["last_error"] = [
        {
            "reason": "full regression failed before phase advancement",
            "failed_commands": [failure.get("cmd", []) for failure in failures],
        }
    ]
    issues = _record_regression_failures(harness, state, phase_id, failures)
    regression["issues"] = [issue["id"] for issue in issues]
    phase.setdefault("review", {})["status"] = "fixing"
    save_state(state)
    _append_regression_issues_to_review_report(issues)
    logger.warning(
        "[REGRESSION] Phase %d full regression failed with %d issue(s).",
        phase_id,
        len(issues),
    )
    return False


def _run_regression_commands(harness: Harness, commands: list[list[str]], phase_id: int):
    results = []
    kwargs = _verification_cmd_kwargs(harness)
    for command in commands:
        prepared = _prepare_verification_cmd(command)
        try:
            run_cmd, result = run_command(prepared, **kwargs)
            entry = {
                "cmd": run_cmd,
                "returncode": result.returncode,
                "stdout_tail": str(result.stdout or "")[-1000:],
                "stderr_tail": str(result.stderr or "")[-1000:],
            }
        except Exception as exc:
            run_cmd = prepared
            entry = {
                "cmd": run_cmd,
                "returncode": 127,
                "stdout_tail": "",
                "stderr_tail": str(exc)[-1000:],
            }
        emit_event(
            "verify_command",
            kind="phase_regression",
            phase_id=phase_id,
            cmd=run_cmd,
            returncode=entry["returncode"],
        )
        results.append(entry)
        if entry["returncode"] != 0:
            break
    _cleanup_verification_artifacts()
    return {"commands": results}


def _record_regression_failures(
    harness: Harness, state: dict, phase_id: int, failures: list[dict]
) -> list[dict]:
    phase = find_phase(state, phase_id)
    if not phase:
        return []
    review = phase.setdefault("review", {})
    issues = review.setdefault("issues", [])
    recorded = []
    for failure in failures:
        key = _failure_key(failure)
        issue = next(
            (
                item
                for item in issues
                if item.get("source") == REGRESSION_SOURCE
                and item.get("regression_key") == key
            ),
            None,
        )
        reason = _failure_reason(failure)
        if issue:
            if issue.get("status") == "fixed":
                issue["attempts"] = issue.get("attempts", 0) + 1
            issue["status"] = "open"
            issue["severity"] = "HIGH"
            issue["regression_evidence"] = failure
            issue.setdefault("last_error", []).append(reason)
        else:
            issue = {
                "id": _next_issue_id(phase, issues),
                "severity": "HIGH",
                "dimension": "Regression",
                "file": "FULL_REGRESSION",
                "title": "Full regression failed before phase advancement",
                "status": "open",
                "attempts": 0,
                "files_changed": [],
                "fixed_sha": None,
                "last_error": [reason],
                "source": REGRESSION_SOURCE,
                "regression_key": key,
                "regression_evidence": failure,
            }
            issues.append(issue)
        if issue.get("attempts", 0) >= harness.config["max_attempts"]:
            save_state(state)
            halt_issue(
                state,
                phase_id,
                issue["id"],
                "full regression still fails after maximum fix attempts",
            )
        recorded.append(issue)
    return recorded


def _mark_regression_issues_fixed(phase: dict, sha: str | None) -> None:
    for issue in phase.get("review", {}).get("issues", []):
        if issue.get("source") != REGRESSION_SOURCE:
            continue
        if issue.get("status") in ("open", "error"):
            issue["status"] = "fixed"
            issue["fixed_sha"] = sha


def _append_regression_issues_to_review_report(issues: list[dict]) -> None:
    REVIEW_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        REVIEW_REPORT_PATH.read_text(encoding="utf-8")
        if REVIEW_REPORT_PATH.exists()
        else ""
    )
    blocks = []
    for issue in issues:
        if re.search(rf"(?<![\d.]){re.escape(issue['id'])}(?![\d.])", existing):
            continue
        evidence = issue.get("regression_evidence", {})
        blocks.append(
            "\n".join(
                [
                    f"## {issue['id']} - {issue['title']}",
                    "",
                    f"Severity: {issue['severity']}",
                    "Dimension: Regression",
                    f"File: {issue.get('file', 'FULL_REGRESSION')}",
                    "",
                    "The product full regression gate failed before advancing to the next phase.",
                    f"Command: `{_format_cmd(evidence.get('cmd', []))}`",
                    f"Return code: {evidence.get('returncode')}",
                    "",
                    "Stdout tail:",
                    "```",
                    str(evidence.get("stdout_tail", "")),
                    "```",
                    "",
                    "Stderr tail:",
                    "```",
                    str(evidence.get("stderr_tail", "")),
                    "```",
                    "",
                    "Fix the product code or tests without deleting, skipping, or weakening regression coverage.",
                ]
            )
        )
    if not blocks:
        return
    content = existing.rstrip()
    if content:
        content += "\n\n"
    content += "\n\n".join(blocks) + "\n"
    REVIEW_REPORT_PATH.write_text(content, encoding="utf-8")


def _next_issue_id(phase: dict, issues: list[dict]) -> str:
    phase_id = int(phase["id"])
    max_seq = 0
    for issue in issues:
        raw = str(issue.get("id", ""))
        if not raw.startswith(f"{phase_id}."):
            continue
        try:
            max_seq = max(max_seq, int(raw.split(".", 1)[1]))
        except ValueError:
            continue
    return f"{phase_id}.{max_seq + 1}"


def _failure_key(failure: dict) -> str:
    payload = "\0".join(
        [
            _format_cmd(failure.get("cmd", [])),
            str(failure.get("returncode", "")),
            str(failure.get("stderr_tail", ""))[-300:],
            str(failure.get("stdout_tail", ""))[-300:],
        ]
    )
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


def _failure_reason(failure: dict) -> str:
    cmd = _format_cmd(failure.get("cmd", []))
    return (
        f"full regression command failed: {cmd} "
        f"(returncode={failure.get('returncode')})"
    )


def _format_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_head() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()
