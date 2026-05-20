from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import agents
from calibrate import log_usage
from fix import _is_excluded_path
from spec_context import build_phase_spec_context
from state import (
    block_cleanup_external_dependency,
    find_issue,
    halt_issue,
    save_state,
    update_state,
)
from regression import collect_regression_commands
from subprocess_runner import run_command
from verify import verify_fix

if TYPE_CHECKING:
    from harness import Harness

logger = logging.getLogger(__name__)

TECH_DEBT_PATH = Path("workspace/tech_debt.jsonl")


def _phase_spec_context(state: dict, phase_id: int) -> str:
    phase = next(
        (p for p in state.get("phases", []) if p.get("id") == phase_id),
        {"id": phase_id},
    )
    spec_file = state.get("spec_file", "")
    if not spec_file:
        return ""
    return build_phase_spec_context(spec_file, phase)


def run_cleanup(harness: Harness, state: dict) -> None:
    all_exclude: set[str] = set()
    for sp in state.get("phases", []):
        all_exclude.update(
            harness.profile_for(sp["id"]).get("review_exclude_paths", [])
        )
    exclude_paths = list(all_exclude)

    _purge_excluded_from_tech_debt(exclude_paths)
    _rewrite_tech_debt_from_state(state, exclude_paths)

    verification_timeout = int(harness.config.get("verification_timeout", 900))

    if not _fixable_deferred(state, exclude_paths):
        _handle_finish_result(
            state,
            _finish(_collect_test_cmds(harness, state), timeout=verification_timeout),
        )
        return

    failure_history: dict = {}

    while True:
        had_verification_error = False
        still_open = _fixable_deferred(state, exclude_paths)
        if not still_open:
            break

        for issue in still_open:
            if issue.get("attempts", 0) >= harness.config["max_attempts"]:
                pid = _parse_phase_id(issue["id"])
                halt_issue(state, pid, issue["id"])

        by_phase: dict[int, list] = {}
        for issue in still_open:
            pid = _parse_phase_id(issue["id"])
            by_phase.setdefault(pid, []).append(issue)

        remaining_jsonl: list = []
        for pid, phase_issues in by_phase.items():
            profile = harness.profile_for(pid)
            phase_debt_path = Path(f"workspace/tech_debt_phase{pid}.jsonl")
            phase_debt_path.write_text(
                "".join(json.dumps(i) + "\n" for i in phase_issues), encoding="utf-8"
            )
            pre_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip()
            try:
                result = agents.fix_issues(
                    source_file=str(phase_debt_path),
                    profile=profile,
                    config=harness.config,
                    failure_history=failure_history or None,
                    phase_type=harness.phase_type_for(pid),
                    spec_context=_phase_spec_context(state, pid),
                )
            except agents.ExternalDependencyError as e:
                block_cleanup_external_dependency(state, str(e))
                return
            except agents.SubprocessError as e:
                _record_cleanup_subprocess_error(state, phase_issues, str(e))
                return
            finally:
                phase_debt_path.unlink(missing_ok=True)

            fixes = result["signal"].get("fixes", [])
            log_usage(
                task_id="cleanup",
                phase_id=pid,
                mode="CLEANUP",
                usage=result["usage"],
                files_changed=sum(
                    len(f.get("files_changed", []))
                    for f in fixes
                    if f.get("status") == "fixed"
                ),
                call_id=result.get("call_id"),
            )

            verify_result = verify_fix(
                harness, state, fixes, pid, pre_sha, call_id=result.get("call_id")
            )
            if getattr(verify_result, "harness_blocker", False):
                target = next(
                    (fix for fix in verify_result.open_fixes if fix.get("id")), None
                )
                if target:
                    halt_issue(
                        state,
                        _parse_phase_id(target["id"]),
                        target["id"],
                        getattr(verify_result, "blocker_reason", None)
                        or target.get("reason", "cleanup verification blocked"),
                    )
                block_cleanup_external_dependency(
                    state,
                    getattr(verify_result, "blocker_reason", None)
                    or "cleanup verification blocked",
                )
                return
            if not verify_result.tests_ok or not verify_result.commit_ok:
                had_verification_error = True

            open_after_by_id = {fix["id"]: fix for fix in verify_result.open_fixes}
            if any(
                fix.get("status") == "fixed" and fix["id"] in open_after_by_id
                for fix in fixes
            ):
                had_verification_error = True
            verification_reason = (
                verify_result.stdout_tail.strip()
                or verify_result.stderr_tail.strip()
                or "cleanup verification failed"
            )
            if not verify_result.tests_ok or not verify_result.commit_ok:
                for fix in open_after_by_id.values():
                    fix.setdefault("reason", verification_reason)
            for fix in fixes:
                if fix.get("status") == "deferred":
                    open_after_by_id.setdefault(
                        fix["id"], {**fix, "reason": "cleanup fix deferred"}
                    )

            handled_ids: set[str] = {fix["id"] for fix in fixes}
            for fix in open_after_by_id.values():
                fix_phase_id = _parse_phase_id(fix["id"])
                issue = find_issue(state, fix_phase_id, fix["id"])
                if issue:
                    issue["attempts"] = issue.get("attempts", 0) + 1
                    reason = fix.get("reason", "fix attempt failed")
                    issue.setdefault("last_error", []).append(reason)
                    failure_history.setdefault(fix["id"], []).append(reason)
                    update_state(
                        state,
                        phase_id=fix_phase_id,
                        issue_id=fix["id"],
                        attempts=issue["attempts"],
                        last_error=issue["last_error"],
                    )
                remaining_jsonl.append(issue or fix)
            for issue in phase_issues:
                if issue["id"] not in handled_ids:
                    remaining_jsonl.append(issue)

        TECH_DEBT_PATH.write_text(
            "".join(json.dumps(i) + "\n" for i in remaining_jsonl if i),
            encoding="utf-8",
        )
        _rewrite_tech_debt_from_state(state, exclude_paths)
        if had_verification_error:
            break

    _handle_finish_result(
        state,
        _finish(_collect_test_cmds(harness, state), timeout=verification_timeout),
    )


def _handle_finish_result(state: dict, failures: list[dict] | None) -> None:
    failures = failures or []
    if failures:
        state["cleanup"] = {"status": "halted", "last_error": failures}
        save_state(state)
        logger.error("[HALT] Cleanup final verification failed.")
        print("[HALT] Cleanup final verification failed. Fix manually, then --resume.")
        sys.exit(1)
    state["cleanup"] = {"status": "complete", "last_error": []}
    save_state(state)


def _record_cleanup_subprocess_error(
    state: dict, phase_issues: list[dict], reason: str
) -> None:
    for issue in phase_issues:
        issue.setdefault("last_error", []).append(reason)
    state["cleanup"] = {"status": "error", "last_error": [reason]}
    save_state(state)
    logger.error("[ERROR] Cleanup aborted: %s. It will resume at CLEANUP.", reason)
    sys.exit(1)


def _finish(
    test_cmds: list[list] | None = None, timeout: int | None = None
) -> list[dict]:
    print("\n[HARNESS] All phases complete.")
    failures: list[dict] = []
    for cmd in test_cmds or [["pytest"]]:
        run_cmd, result = run_command(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        print(result.stdout[-1000:] if result.stdout else "(no output)")
        if result.returncode != 0:
            print(f"[WARN] {run_cmd[0]} reported failures — review manually.")
            failures.append(
                {
                    "cmd": run_cmd,
                    "returncode": result.returncode,
                    "stdout_tail": result.stdout[-500:],
                    "stderr_tail": result.stderr[-500:],
                }
            )
    print("[HARNESS] COMPLETE.")
    return failures


def _collect_test_cmds(harness: Harness, state: dict) -> list[list]:
    return collect_regression_commands(harness, state)


def _parse_phase_id(issue_id: str) -> int:
    try:
        return int(issue_id.split(".", 1)[0])
    except ValueError:
        raise ValueError(
            f"Cannot parse phase id from {issue_id!r}: expected 'N.M' format"
        )


def _all_deferred_issues(state: dict) -> list:
    return [
        issue
        for phase in state.get("phases", [])
        for issue in phase.get("review", {}).get("issues", [])
        if issue.get("status") == "deferred"
    ]


def _fixable_deferred(state: dict, exclude_paths: list[str]) -> list[dict]:
    return [
        i
        for i in _all_deferred_issues(state)
        if not _is_excluded_path(i.get("file", ""), exclude_paths)
    ]


def _purge_excluded_from_tech_debt(exclude_paths: list[str]) -> None:
    if not exclude_paths or not TECH_DEBT_PATH.exists():
        return
    lines = TECH_DEBT_PATH.read_text(encoding="utf-8").splitlines()
    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            issue = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if _is_excluded_path(issue.get("file", ""), exclude_paths):
            logger.warning(
                "[CLEANUP] Skipping issue %s — %r is in review_exclude_paths.",
                issue.get("id", "?"),
                issue.get("file", ""),
            )
        else:
            kept.append(line)
    TECH_DEBT_PATH.write_text("".join(line + "\n" for line in kept), encoding="utf-8")


def _rewrite_tech_debt_from_state(state: dict, exclude_paths: list[str]) -> None:
    malformed_lines = []
    if TECH_DEBT_PATH.exists():
        for line in TECH_DEBT_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                malformed_lines.append(line)

    issues = [
        issue
        for issue in _all_deferred_issues(state)
        if not _is_excluded_path(issue.get("file", ""), exclude_paths)
    ]
    lines = malformed_lines + [json.dumps(issue) for issue in issues]
    TECH_DEBT_PATH.write_text(
        "".join(line + "\n" for line in lines),
        encoding="utf-8",
    )
