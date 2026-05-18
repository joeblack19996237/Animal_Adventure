from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import agents
from calibrate import log_usage
from git_changes import capture_snapshot
from spec_context import build_phase_spec_context
from state import (
    block_review_external_dependency,
    block_task_external_dependency,
    error_issues,
    error_task,
    find_issue,
    find_phase,
    find_task,
    halt_issue,
    halt_task,
    save_state,
    update_state,
)
from verify import (
    REVIEW_REPORT_PATH,
    _remove_from_review_report,
    verify_execution,
    verify_fix,
)

if TYPE_CHECKING:
    from harness import Harness

logger = logging.getLogger(__name__)

TECH_DEBT_PATH = Path("workspace/tech_debt.jsonl")
REGRESSION_INFRA_FAILURE_KINDS = {"infra_failure", "timeout"}


def _phase_spec_context(state: dict, phase_id: int) -> str:
    phase = find_phase(state, phase_id) or {"id": phase_id}
    spec_file = state.get("spec_file", "")
    if not spec_file:
        return ""
    return build_phase_spec_context(spec_file, phase)


def run_batch_retry_loop(
    harness: Harness, state: dict, failed_tasks: list, phase_id: int
) -> None:
    failed_tasks = sorted(failed_tasks, key=lambda t: t["id"])
    profile = harness.profile_for(phase_id)

    for task_sig in failed_tasks:
        task_id = task_sig["id"]
        task = find_task(state, task_id)
        if task is None:
            continue

        while task["status"] != "complete":
            if _task_retry_exhausted(task, harness.config):
                halt_task(
                    state,
                    task_id,
                    _task_retry_exhausted_reason(task, harness.config),
                )

            failure_history = {task_id: list(task.get("last_error", []))}
            pre_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip()
            pre_snapshot = capture_snapshot()

            try:
                result = agents.execute(
                    [task],
                    phase_id=int(phase_id),
                    profile=profile,
                    config=harness.config,
                    failure_history=failure_history,
                    phase_type=harness.phase_type_for(phase_id),
                    spec_context=_phase_spec_context(state, phase_id),
                )
                signal = result["signal"]
                task_result = signal["tasks"][0] if signal.get("tasks") else {}
                if result.get("call_id"):
                    verify_failures = verify_execution(
                        harness,
                        pre_sha,
                        [task],
                        signal,
                        pre_snapshot=pre_snapshot,
                        call_id=result.get("call_id"),
                    )
                else:
                    verify_failures = verify_execution(
                        harness, pre_sha, [task], signal, pre_snapshot=pre_snapshot
                    )
            except agents.ExternalDependencyError as e:
                block_task_external_dependency(state, task_id, str(e))
                return
            except agents.SubprocessError as e:
                error_task(state, task_id, str(e))
                return

            if task_result.get("status") == "failed":
                task["attempts"] += 1
                task["verify_fails"] = 0
                task.setdefault("last_error", []).append(
                    task_result.get("reason", "unknown")
                )
                update_state(
                    state,
                    task_id=task_id,
                    attempts=task["attempts"],
                    verify_fails=0,
                    last_error=task["last_error"],
                )
                if _task_retry_exhausted(task, harness.config):
                    halt_task(
                        state,
                        task_id,
                        _task_retry_exhausted_reason(task, harness.config),
                    )
                continue

            if verify_failures:
                if getattr(verify_failures, "harness_blocker", False):
                    halt_task(
                        state,
                        task_id,
                        getattr(verify_failures, "blocker_reason", None)
                        or verify_failures[0].get(
                            "reason", "harness verification blocked"
                        ),
                    )
                    return
                task["verify_fails"] = task.get("verify_fails", 0) + 1
                reason = verify_failures[0].get("reason", "harness verification failed")
                task.setdefault("last_error", []).append(reason)
                if task["verify_fails"] >= harness.config["verify_fail_escalation"]:
                    task["attempts"] += 1
                    task["verify_fails"] = 0
                update_state(
                    state,
                    task_id=task_id,
                    attempts=task["attempts"],
                    verify_fails=task["verify_fails"],
                    last_error=task["last_error"],
                )
                if _task_retry_exhausted(task, harness.config):
                    halt_task(
                        state,
                        task_id,
                        _task_retry_exhausted_reason(task, harness.config),
                    )
                continue

            task["verify_fails"] = 0
            task["status"] = "complete"
            update_state(
                state,
                task_id=task_id,
                status="complete",
                verify_fails=0,
                tdd_applied=task_result.get("tdd_applied"),
                tdd_skipped=task_result.get("tdd_skipped"),
                files_changed=task_result.get("files_changed", []),
            )


def _task_retry_exhausted(task: dict, config: dict) -> bool:
    max_attempts = int(config["max_attempts"])
    return (
        task.get("attempts", 0) >= max_attempts
        or len(task.get("last_error", [])) >= max_attempts
        or task.get("verify_fails", 0) >= max_attempts
    )


def _task_retry_exhausted_reason(task: dict, config: dict) -> str:
    max_attempts = int(config["max_attempts"])
    failures = len(task.get("last_error", []))
    verify_fails = task.get("verify_fails", 0)
    attempts = task.get("attempts", 0)
    if failures >= max_attempts and attempts < max_attempts:
        return (
            f"task recorded {failures} failures "
            f"(max_attempts={max_attempts})"
        )
    if verify_fails >= max_attempts and attempts < max_attempts:
        return (
            f"task recorded {verify_fails} consecutive verify failures "
            f"(max_attempts={max_attempts})"
        )
    return "failed too many times"


def run_fix_cycle(harness: Harness, state: dict, phase_id: int) -> None:
    _reconcile_review_report(state, phase_id)
    _normalize_review_report_ids(state, phase_id)
    profile = harness.profile_for(phase_id)
    failure_history: dict = {}

    while True:
        open_issues = _open_critical_high(state, phase_id)
        if not open_issues:
            break

        if _block_regression_infra_issues(open_issues, state, phase_id):
            return

        open_issues = _skip_excluded_issues(
            open_issues,
            profile.get("review_exclude_paths", []),
            state,
            phase_id,
        )
        if not open_issues:
            break

        for issue in open_issues:
            if issue["attempts"] >= harness.config["max_attempts"]:
                halt_issue(state, phase_id, issue["id"])

        pre_snapshot = capture_snapshot()
        pre_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()

        try:
            result = agents.fix_issues(
                source_file=str(REVIEW_REPORT_PATH),
                profile=profile,
                config=harness.config,
                failure_history=failure_history or None,
                phase_type=harness.phase_type_for(phase_id),
                spec_context=_phase_spec_context(state, phase_id),
            )
            fixes = result["signal"].get("fixes", [])
            log_usage(
                task_id=f"phase_{phase_id}_fix",
                phase_id=phase_id,
                mode="FIX",
                usage=result["usage"],
                files_changed=sum(
                    len(f.get("files_changed", []))
                    for f in fixes
                    if f.get("status") == "fixed"
                ),
                call_id=result.get("call_id"),
            )
        except agents.ExternalDependencyError as e:
            block_review_external_dependency(state, phase_id, str(e), "FIX")
            return
        except agents.SubprocessError as e:
            for issue in open_issues:
                issue["attempts"] = issue.get("attempts", 0) + 1
                update_state(
                    state,
                    phase_id=phase_id,
                    issue_id=issue["id"],
                    attempts=issue["attempts"],
                )
            error_issues(
                state, phase_id, [issue["id"] for issue in open_issues], str(e)
            )
            return

        fixes_for_verify = _fixes_with_attempts(state, phase_id, fixes)
        if result.get("call_id"):
            open_after = verify_fix(
                harness,
                state,
                fixes_for_verify,
                phase_id,
                pre_sha,
                pre_snapshot,
                call_id=result.get("call_id"),
            )
        else:
            open_after = verify_fix(
                harness, state, fixes_for_verify, phase_id, pre_sha, pre_snapshot
            )
        if getattr(open_after, "harness_blocker", False):
            reason = getattr(open_after, "blocker_reason", None) or (
                open_after[0].get("reason") if open_after else "harness fix blocked"
            )
            target_ids = [fix.get("id") for fix in open_after if fix.get("id")]
            if not target_ids:
                target_ids = [issue["id"] for issue in open_issues]
            halt_issue(state, phase_id, target_ids[0], reason)
            return
        if not open_after:
            rereview_open = _targeted_rereview_blocking_fixes(
                harness, state, phase_id, fixes, pre_sha
            )
            open_after.extend(rereview_open)

        for fix in open_after:
            issue = find_issue(state, phase_id, fix["id"])
            if issue is None:
                continue
            if issue.get("severity") in ("MEDIUM", "LOW"):
                update_state(
                    state, phase_id=phase_id, issue_id=fix["id"], status="deferred"
                )
                continue
            issue["attempts"] = issue.get("attempts", 0) + 1
            reason = fix.get("reason", "fix attempt failed")
            last_error = issue.setdefault("last_error", [])
            if not last_error or last_error[-1] != reason:
                last_error.append(reason)
            failure_history.setdefault(fix["id"], []).append(reason)
            update_state(
                state,
                phase_id=phase_id,
                issue_id=fix["id"],
                attempts=issue["attempts"],
                last_error=issue["last_error"],
            )

    update_state(state, entity_type="review", phase_id=phase_id, status="fixed")
    _append_medium_low_to_tech_debt(state, phase_id)
    REVIEW_REPORT_PATH.write_text("", encoding="utf-8")


def _targeted_rereview_blocking_fixes(
    harness: Harness,
    state: dict,
    phase_id: int,
    fixes: list,
    pre_sha: str,
) -> list:
    fixed_blocking = []
    for fix in fixes:
        if fix.get("status") != "fixed":
            continue
        issue = find_issue(state, phase_id, fix["id"])
        severity = (issue or {}).get("severity") or fix.get("severity")
        if severity in ("CRITICAL", "HIGH"):
            fixed_blocking.append({**fix, "severity": severity})
    if not fixed_blocking:
        return []
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if not pre_sha or not head or pre_sha == head:
        return []
    try:
        result = agents.review_fix(
            phase_id=phase_id,
            issue_ids=[f["id"] for f in fixed_blocking],
            base_sha=pre_sha,
            head_sha=head,
            spec_paths=[state.get("spec_file", "")],
            profile=harness.profile_for(phase_id),
            config=harness.config,
            spec_context=_phase_spec_context(state, phase_id),
        )
    except agents.ExternalDependencyError as e:
        reason = f"targeted re-review blocked: {e}"
        for fix in fixed_blocking:
            state_issue = find_issue(state, phase_id, fix["id"])
            if state_issue:
                last_error = state_issue.setdefault("last_error", [])
                if not last_error or last_error[-1] != reason:
                    last_error.append(reason)
                update_state(
                    state,
                    phase_id=phase_id,
                    issue_id=fix["id"],
                    status="open",
                    last_error=last_error,
                )
        block_review_external_dependency(state, phase_id, str(e), "FIX")
        return []
    except agents.SubprocessError as e:
        reopened = []
        reason = f"targeted re-review failed: {e}"
        for fix in fixed_blocking:
            state_issue = find_issue(state, phase_id, fix["id"])
            if state_issue:
                last_error = state_issue.setdefault("last_error", [])
                if not last_error or last_error[-1] != reason:
                    last_error.append(reason)
                update_state(
                    state,
                    phase_id=phase_id,
                    issue_id=fix["id"],
                    status="open",
                    last_error=last_error,
                )
            reopened.append({**fix, "status": "open", "reason": reason})
        return reopened
    signal = result["signal"]
    if signal.get("verdict") != "BLOCK":
        return []
    reopened = []
    for issue in signal.get("issues", []):
        fix = next((f for f in fixed_blocking if f["id"] == issue.get("id")), None)
        if not fix:
            continue
        state_issue = find_issue(state, phase_id, fix["id"])
        if state_issue:
            last_error = state_issue.setdefault("last_error", [])
            last_error.append(
                f"targeted re-review still blocks: {issue.get('title', '')}"
            )
            update_state(
                state,
                phase_id=phase_id,
                issue_id=fix["id"],
                status="open",
                last_error=last_error,
            )
        reopened.append(
            {
                **fix,
                "status": "open",
                "reason": f"targeted re-review still blocks: {issue.get('title', '')}",
            }
        )
    return reopened


def _fixes_with_attempts(state: dict, phase_id: int, fixes: list) -> list:
    enriched = []
    for fix in fixes:
        issue = find_issue(state, phase_id, fix.get("id", ""))
        if issue and "attempts" not in fix:
            enriched.append({**fix, "attempts": issue.get("attempts", 0)})
        else:
            enriched.append(fix)
    return enriched


def handle_verdict(
    harness: Harness,
    state: dict,
    phase_id: int,
    review_result: dict,
) -> None:
    signal = review_result["signal"]
    log_usage(
        task_id=f"phase_{phase_id}_review",
        phase_id=phase_id,
        mode="REVIEW",
        usage=review_result["usage"],
        files_changed=0,
        call_id=review_result.get("call_id"),
    )

    verdict = signal.get("verdict")

    if verdict == "WARN":
        phase = find_phase(state, phase_id) or {}
        for issue in phase.get("review", {}).get("issues", []):
            update_state(
                state, phase_id=phase_id, issue_id=issue["id"], status="deferred"
            )
            _append_issue_to_tech_debt(issue)

    elif verdict == "BLOCK":
        update_state(state, entity_type="review", phase_id=phase_id, status="fixing")
        run_fix_cycle(harness, state, phase_id)


def _reconcile_review_report(state: dict, phase_id: int) -> None:
    phase = find_phase(state, phase_id)
    if phase is None:
        return
    for issue in phase.get("review", {}).get("issues", []):
        if issue.get("status") == "fixed":
            _remove_from_review_report(issue["id"])


def _normalize_review_report_ids(state: dict, phase_id: int) -> None:
    """Replace bare sequential IDs in review_report.md headings with state.json issue IDs."""
    if not REVIEW_REPORT_PATH.exists():
        return
    phase = find_phase(state, phase_id)
    if not phase:
        return
    content = REVIEW_REPORT_PATH.read_text(encoding="utf-8")
    heading_re = re.compile(r"^(#{1,3}\s+)Issue\s+(\d+)(\b.*)?$", re.MULTILINE)
    matches = list(heading_re.finditer(content))
    if not matches:
        return
    all_issues = phase.get("review", {}).get("issues", [])
    for match in matches:
        seq = int(match.group(2))
        if 1 <= seq <= len(all_issues):
            issue = all_issues[seq - 1]
            old = match.group(0)
            new = match.group(1) + issue["id"] + (match.group(3) or "")
            content = content.replace(old, new, 1)
    REVIEW_REPORT_PATH.write_text(content, encoding="utf-8")


def _open_critical_high(state: dict, phase_id: int) -> list:
    phase = find_phase(state, phase_id)
    if not phase:
        return []
    return [
        i
        for i in phase.get("review", {}).get("issues", [])
        if i.get("status") == "open" and i.get("severity") in ("CRITICAL", "HIGH")
    ]


def _block_regression_infra_issues(
    issues: list[dict], state: dict, phase_id: int
) -> bool:
    blocked = False
    for issue in issues:
        if issue.get("source") != "regression":
            continue
        if issue.get("failure_kind") not in REGRESSION_INFRA_FAILURE_KINDS:
            continue
        reason = (
            "regression issue is a harness/environment blocker, not a product "
            "FIX task"
        )
        issue["status"] = "halted"
        last_error = issue.setdefault("last_error", [])
        if not last_error or last_error[-1] != reason:
            last_error.append(reason)
        blocked = True
    if blocked:
        phase = find_phase(state, phase_id)
        if phase:
            phase.setdefault("review", {})["status"] = "error"
        save_state(state)
        logger.error(
            "[FIX] Phase %d has regression infra issue(s); not invoking builder.",
            phase_id,
        )
    return blocked


def _tech_debt_existing_ids() -> set[str]:
    if not TECH_DEBT_PATH.exists():
        return set()
    ids: set[str] = set()
    for line in TECH_DEBT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ids.add(json.loads(line).get("id", ""))
        except json.JSONDecodeError:
            pass
    return ids


def _append_medium_low_to_tech_debt(state: dict, phase_id: int) -> None:
    phase = find_phase(state, phase_id)
    if not phase:
        return
    existing_ids = _tech_debt_existing_ids()
    with open(TECH_DEBT_PATH, "a", encoding="utf-8") as f:
        for issue in phase.get("review", {}).get("issues", []):
            if issue.get("severity") in ("MEDIUM", "LOW") and issue.get("status") in (
                "open",
                "deferred",
            ):
                if issue["id"] not in existing_ids:
                    f.write(json.dumps(issue) + "\n")
                    existing_ids.add(issue["id"])
                update_state(
                    state, phase_id=phase_id, issue_id=issue["id"], status="deferred"
                )


def _append_issue_to_tech_debt(issue: dict) -> None:
    TECH_DEBT_PATH.parent.mkdir(exist_ok=True)
    if issue.get("id") in _tech_debt_existing_ids():
        return
    with open(TECH_DEBT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(issue) + "\n")


def _is_excluded_path(file_field: str, exclude_paths: list[str]) -> bool:
    path = file_field.split(":", 1)[0].replace("\\", "/").strip("/")
    for raw in exclude_paths:
        excluded = raw.replace("\\", "/").strip("/")
        if excluded and (path == excluded or path.startswith(excluded + "/")):
            return True
    return False


def _skip_excluded_issues(
    issues: list[dict],
    exclude_paths: list[str],
    state: dict,
    phase_id: int,
) -> list[dict]:
    if not exclude_paths:
        return issues
    fixable = []
    for issue in issues:
        if _is_excluded_path(issue.get("file", ""), exclude_paths):
            reason = (
                f"file {issue.get('file', '')!r} is in review_exclude_paths"
                " — fix before harness run, not by the FIX agent"
            )
            logger.warning(
                "[FIX] Issue %s skipped — %r outside deliverable scope. Deferring.",
                issue["id"],
                issue.get("file", ""),
            )
            issue.setdefault("last_error", []).append(reason)
            update_state(
                state, phase_id=phase_id, issue_id=issue["id"], status="deferred"
            )
        else:
            fixable.append(issue)
    return fixable
