from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
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
REGRESSION_PRODUCT_FAILURE = "product_failure"
REGRESSION_INFRA_FAILURE = "infra_failure"
REGRESSION_TIMEOUT = "timeout"
REGRESSION_BROWSER_COMPAT_FAILURE = "browser_compat_failure"
REGRESSION_BLOCKED_STATUSES = {"blocked", "error", "halted"}
REGRESSION_FAILURE_ARTIFACT_DIR = Path("workspace/regression")


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
        regression["failure_kind"] = None
        regression["blocker_kind"] = None
        regression["last_error"] = []
        regression["passed_sha"] = _current_head()
        _mark_regression_issues_fixed(phase, regression["passed_sha"])
        save_state(state)
        logger.info("[REGRESSION] Phase %d full regression passed.", phase_id)
        return True

    artifact_path = _write_regression_failure_artifact(phase_id, failures)
    for failure in failures:
        classification = classify_regression_failure(failure)
        failure["failure_kind"] = classification["kind"]
        failure["failure_reason"] = classification["reason"]

    failure_kinds = {failure.get("failure_kind") for failure in failures}
    regression["artifact_path"] = str(artifact_path)
    if failure_kinds and failure_kinds <= {
        REGRESSION_INFRA_FAILURE,
        REGRESSION_TIMEOUT,
    }:
        kind = (
            REGRESSION_TIMEOUT
            if REGRESSION_TIMEOUT in failure_kinds
            else REGRESSION_INFRA_FAILURE
        )
        regression["status"] = "blocked"
        regression["failure_kind"] = kind
        regression["blocker_kind"] = kind
        regression["last_error"] = [
            {
                "reason": "full regression blocked by harness or environment failure",
                "failure_kind": kind,
                "failed_commands": [failure.get("cmd", []) for failure in failures],
                "artifact_path": str(artifact_path),
                "details": [
                    failure.get("failure_reason") or _failure_reason(failure)
                    for failure in failures
                ],
            }
        ]
        regression["issues"] = []
        save_state(state)
        logger.error(
            "[REGRESSION] Phase %d blocked by %s; not sending to product FIX.",
            phase_id,
            kind,
        )
        return False

    # All failures are non-chromium browser-compat only → pass gate, log to tech_debt
    if failure_kinds and failure_kinds <= {REGRESSION_BROWSER_COMPAT_FAILURE}:
        regression["status"] = "passed"
        regression["failure_kind"] = REGRESSION_BROWSER_COMPAT_FAILURE
        regression["blocker_kind"] = None
        regression["last_error"] = []
        regression["passed_sha"] = _current_head()
        _mark_regression_issues_fixed(phase, regression["passed_sha"])
        _append_browser_compat_to_tech_debt(phase_id, failures)
        save_state(state)
        logger.warning(
            "[REGRESSION] Phase %d: all failures are browser-compat only "
            "(non-chromium); passing gate and logging to tech_debt.",
            phase_id,
        )
        return True

    regression["status"] = "failed"
    regression["failure_kind"] = REGRESSION_PRODUCT_FAILURE
    regression["blocker_kind"] = None
    regression["last_error"] = [
        {
            "reason": "full regression failed before phase advancement",
            "failure_kind": REGRESSION_PRODUCT_FAILURE,
            "failed_commands": [failure.get("cmd", []) for failure in failures],
            "artifact_path": str(artifact_path),
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


def _run_regression_commands(
    harness: Harness, commands: list[list[str]], phase_id: int
):
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
            issue["failure_kind"] = REGRESSION_PRODUCT_FAILURE
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
                "failure_kind": REGRESSION_PRODUCT_FAILURE,
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


def classify_regression_failure(failure: dict) -> dict:
    output = "\n".join(
        [
            str(failure.get("stdout_tail", "")),
            str(failure.get("stderr_tail", "")),
        ]
    )
    returncode = failure.get("returncode")
    if returncode == 124 or "command timed out after" in output.lower():
        return {
            "kind": REGRESSION_TIMEOUT,
            "reason": "regression command timed out; requires harness/operator triage",
        }
    if returncode == 127:
        return {
            "kind": REGRESSION_INFRA_FAILURE,
            "reason": "regression command failed before tests could run",
        }
    if _looks_like_infra_collection_failure(output):
        return {
            "kind": REGRESSION_INFRA_FAILURE,
            "reason": "regression failed while collecting temp/cache/harness artifacts",
        }
    if _looks_like_browser_compat_failure(output):
        return {
            "kind": REGRESSION_BROWSER_COMPAT_FAILURE,
            "reason": (
                "all test failures are non-chromium browser-project-specific "
                "(webkit/firefox); chromium passes — treat as compat warning"
            ),
        }
    return {
        "kind": REGRESSION_PRODUCT_FAILURE,
        "reason": "regression command reported product test failures",
    }


def regression_failure_blocks_fix(phase: dict | None) -> bool:
    regression = (phase or {}).get("regression", {})
    if regression.get("status") in REGRESSION_BLOCKED_STATUSES:
        return regression.get("failure_kind") in {
            REGRESSION_INFRA_FAILURE,
            REGRESSION_TIMEOUT,
        }
    return False


def _looks_like_infra_collection_failure(output: str) -> bool:
    lowered = output.replace("\\", "/").lower()
    infra_path_markers = (
        "/.tmp/",
        ".tmp/",
        "/.pytest_cache/",
        ".pytest_cache/",
        "workspace/verification-tmp",
        "pytest-of-",
    )
    infra_error_markers = (
        "permissionerror",
        "winerror 5",
        "file not found",
        "filenotfounderror",
        "error collecting",
        "errors during collection",
        "interrupted:",
    )
    return any(marker in lowered for marker in infra_path_markers) and any(
        marker in lowered for marker in infra_error_markers
    )


def _looks_like_browser_compat_failure(output: str) -> bool:
    """Return True when ALL Playwright failure lines carry a non-chromium
    browser project prefix. Conservative: any [chromium] failure → False.
    """
    failure_lines = re.findall(r"^\s+\[(\w[\w-]+)\]\s+›", output, re.MULTILINE)
    if not failure_lines:
        return False
    return all(proj.lower() != "chromium" for proj in failure_lines)


def _write_regression_failure_artifact(phase_id: int, failures: list[dict]) -> Path:
    REGRESSION_FAILURE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = REGRESSION_FAILURE_ARTIFACT_DIR / f"phase_{phase_id}_last_failure.log"
    blocks = []
    for failure in failures:
        blocks.extend(
            [
                f"Command: {_format_cmd(failure.get('cmd', []))}",
                f"Return code: {failure.get('returncode')}",
                "",
                "Stdout tail:",
                str(failure.get("stdout_tail", "")),
                "",
                "Stderr tail:",
                str(failure.get("stderr_tail", "")),
                "",
                "---",
                "",
            ]
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def _format_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_head() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _append_browser_compat_to_tech_debt(phase_id: int, failures: list[dict]) -> None:
    import json as _json

    from fix import TECH_DEBT_PATH, _tech_debt_existing_ids

    TECH_DEBT_PATH.parent.mkdir(exist_ok=True)
    entry_id = f"browser_compat_{phase_id}"
    if entry_id in _tech_debt_existing_ids():
        return
    reasons = [f.get("failure_reason", "browser-compat failure") for f in failures]
    entry = {
        "id": entry_id,
        "severity": "LOW",
        "dimension": "Regression",
        "file": "FULL_REGRESSION",
        "title": f"Phase {phase_id}: webkit/browser-compat e2e failures (chromium passes)",
        "status": "open",
        "attempts": 0,
        "files_changed": [],
        "fixed_sha": None,
        "last_error": reasons,
    }
    with open(TECH_DEBT_PATH, "a", encoding="utf-8") as fh:
        fh.write(_json.dumps(entry) + "\n")
