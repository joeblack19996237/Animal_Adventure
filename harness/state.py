import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_PATH = Path("workspace/state.json")
STATE_TMP = Path("workspace/state.json.tmp")
ID_RE = re.compile(r"^\d+\.\d+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    _validate_ids(state)
    return state


def save_state(state: dict) -> None:
    _validate_ids(state)
    tmp = STATE_TMP.parent / f"{STATE_TMP.stem}.{os.getpid()}{STATE_TMP.suffix}"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def _validate_ids(state: dict) -> None:
    for phase in state.get("phases", []):
        phase_id = phase.get("id", "?")
        for item in phase.get("tasks", []):
            if not ID_RE.match(str(item.get("id", ""))):
                raise ValueError(
                    f"Malformed task id {item.get('id')!r} in phase {phase_id}. "
                    "Expected format '{phase_id}.{seq}'. Fix workspace/state.json manually."
                )
        for item in phase.get("review", {}).get("issues", []):
            if not ID_RE.match(str(item.get("id", ""))):
                raise ValueError(
                    f"Malformed issue id {item.get('id')!r} in phase {phase_id}. "
                    "Expected format '{phase_id}.{seq}'. Fix workspace/state.json manually."
                )


def find_task(state: dict, task_id: str) -> dict | None:
    for phase in state.get("phases", []):
        for task in phase.get("tasks", []):
            if task["id"] == task_id:
                return task
    return None


def find_issue(state: dict, phase_id: int, issue_id: str) -> dict | None:
    phase_id = int(phase_id)
    issue_id = str(issue_id)
    # Normalize bare sequential IDs (e.g. "3") to phase-prefixed form (e.g. "2.3").
    # Reviewers occasionally emit "## Issue 3" instead of "## 2.3"; the FIX agent echoes
    # that bare number back in its signal, causing update_state to crash on lookup.
    if "." not in issue_id:
        issue_id = f"{phase_id}.{issue_id}"
    for phase in state.get("phases", []):
        if phase["id"] == phase_id:
            return next(
                (
                    i
                    for i in phase.get("review", {}).get("issues", [])
                    if i["id"] == issue_id
                ),
                None,
            )
    return None


def find_phase(state: dict, phase_id: int) -> dict | None:
    phase_id = int(phase_id)
    return next((p for p in state.get("phases", []) if p["id"] == phase_id), None)


def update_state(state: dict, **kwargs) -> None:
    entity_type = kwargs.pop("entity_type", None)
    task_id = kwargs.pop("task_id", None)
    phase_id = kwargs.pop("phase_id", None)
    issue_id = kwargs.pop("issue_id", None)

    if task_id is not None:
        entity = find_task(state, task_id)
        if entity is None:
            raise ValueError(f"Task {task_id!r} not found in state")
        _apply_task_fields(entity, kwargs)

    elif issue_id is not None and phase_id is not None:
        entity = find_issue(state, phase_id, issue_id)
        if entity is None:
            raise ValueError(f"Issue {issue_id!r} not found in phase {phase_id}")
        _apply_issue_fields(entity, kwargs)

    elif entity_type == "review" and phase_id is not None:
        phase = find_phase(state, phase_id)
        if phase is None:
            raise ValueError(f"Phase {phase_id} not found")
        review = phase.setdefault("review", {})
        _apply_review_fields(review, kwargs)

    elif entity_type == "phase" and phase_id is not None:
        phase = find_phase(state, phase_id)
        if phase is None:
            raise ValueError(f"Phase {phase_id} not found")
        _apply_phase_fields(phase, kwargs)

    else:
        raise ValueError(
            "update_state requires task_id, issue_id+phase_id, entity_type='review'+phase_id, or entity_type='phase'+phase_id"
        )

    save_state(state)


def _apply_task_fields(task: dict, fields: dict) -> None:
    allowed = {
        "status",
        "attempts",
        "verify_fails",
        "tdd_mode",
        "tdd_applied",
        "tdd_skipped",
        "files_changed",
        "commit_sha",
        "last_error",
    }
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(f"Unknown task field: {k!r}")
        task[k] = v


def _apply_issue_fields(issue: dict, fields: dict) -> None:
    allowed = {"status", "attempts", "files_changed", "fixed_sha", "last_error"}
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(f"Unknown issue field: {k!r}")
        issue[k] = v


def _apply_review_fields(review: dict, fields: dict) -> None:
    allowed = {
        "status",
        "verdict",
        "sha_at_review",
        "issues",
        "last_error",
        "attempts",
        "blocked_mode",
    }
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(f"Unknown review field: {k!r}")
        review[k] = v


def _apply_phase_fields(phase: dict, fields: dict) -> None:
    allowed = {"status", "language", "last_error", "regression"}
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(f"Unknown phase field: {k!r}")
        phase[k] = v


def halt_task(state: dict, task_id: str, reason: str | None = None) -> None:
    task = find_task(state, task_id)
    if task:
        task["status"] = "halted"
        if reason:
            task.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.warning(
        "[HALT] Task %s halted: %s. Fix manually, then run --resume.",
        task_id,
        reason or "failed too many times",
    )
    sys.exit(1)


def error_task(state: dict, task_id: str, reason: str) -> None:
    task = find_task(state, task_id)
    if task:
        task["status"] = "error"
        task.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error("[ERROR] Task %s aborted: %s.", task_id, reason)
    logger.error("It will be auto-reset to 'pending' on next --resume.")
    sys.exit(1)


def halt_issue(
    state: dict, phase_id: int, issue_id: str, reason: str | None = None
) -> None:
    issue = find_issue(state, phase_id, issue_id)
    if issue:
        issue["status"] = "halted"
        if reason:
            issue.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.warning(
        "[HALT] Issue %s halted: %s. Fix manually, then run --resume.",
        issue_id,
        reason or "failed too many times",
    )
    sys.exit(1)


def error_issue(state: dict, phase_id: int, issue_id: str, reason: str) -> None:
    issue = find_issue(state, phase_id, issue_id)
    if issue:
        issue["status"] = "error"
        issue.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error(
        "[ERROR] Issue %s aborted: %s. It will be auto-reset to 'open' on next --resume.",
        issue_id,
        reason,
    )
    sys.exit(1)


def error_issues(state: dict, phase_id: int, issue_ids: list[str], reason: str) -> None:
    for issue_id in issue_ids:
        issue = find_issue(state, phase_id, issue_id)
        if issue:
            issue["status"] = "error"
            issue.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error(
        "[ERROR] Phase %d issues aborted: %s. They will auto-reset to 'open' on next --resume.",
        phase_id,
        reason,
    )
    sys.exit(1)


def error_review(state: dict, phase_id: int, reason: str) -> None:
    phase = find_phase(state, phase_id)
    if phase:
        review = phase.setdefault("review", {})
        review["status"] = "error"
        review["attempts"] = review.get("attempts", 0) + 1
        review.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error(
        "[ERROR] Phase %d REVIEW aborted: %s. It will resume at REVIEWING.",
        phase_id,
        reason,
    )
    sys.exit(1)


def block_phase_external_dependency(state: dict, phase_id: int, reason: str) -> None:
    phase = find_phase(state, phase_id)
    if phase:
        phase["status"] = "blocked_external_dependency"
        phase.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error("[BLOCKED] Phase %d TASK_BUILD blocked: %s.", phase_id, reason)
    sys.exit(1)


def block_task_external_dependency(state: dict, task_id: str, reason: str) -> None:
    task = find_task(state, task_id)
    if task:
        task["status"] = "blocked_external_dependency"
        task.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error("[BLOCKED] Task %s blocked: %s.", task_id, reason)
    sys.exit(1)


def block_review_external_dependency(
    state: dict, phase_id: int, reason: str, blocked_mode: str
) -> None:
    phase = find_phase(state, phase_id)
    if phase:
        review = phase.setdefault("review", {})
        review["status"] = "blocked_external_dependency"
        review["blocked_mode"] = blocked_mode
        review.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error("[BLOCKED] Phase %d %s blocked: %s.", phase_id, blocked_mode, reason)
    sys.exit(1)


def block_cleanup_external_dependency(state: dict, reason: str) -> None:
    state["cleanup"] = {
        "status": "blocked_external_dependency",
        "last_error": [reason],
    }
    save_state(state)
    logger.error("[BLOCKED] Cleanup blocked: %s.", reason)
    sys.exit(1)


def block_evaluate_external_dependency(state: dict, reason: str) -> None:
    evaluate = state.setdefault("evaluate", {})
    evaluate["status"] = "blocked_external_dependency"
    evaluate["last_finished_at"] = _now_iso()
    evaluate.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error("[BLOCKED] Evaluate blocked: %s.", reason)
    sys.exit(1)


def reset_interrupted_tasks(state: dict) -> bool:
    changed = False
    for phase in state.get("phases", []):
        for task in phase.get("tasks", []):
            if task.get("status") in ("building", "blocked_external_dependency"):
                if task.get("status") == "blocked_external_dependency":
                    existing = task.get("last_error", [])
                    if isinstance(existing, list):
                        task.setdefault("last_blocked_error", []).extend(existing)
                    elif existing:
                        task.setdefault("last_blocked_error", []).append(existing)
                task["status"] = "pending"
                changed = True
    if changed:
        save_state(state)
    return changed


def reconcile_committed_tasks(state: dict) -> bool:
    changed = False
    initial_sha = state.get("initial_sha")
    for phase in state.get("phases", []):
        phase_id = phase.get("id")
        for task in phase.get("tasks", []):
            if task.get("status") == "complete":
                continue
            commit = _find_task_commit(
                initial_sha,
                phase_id,
                task.get("title", ""),
                task.get("tdd_mode"),
            )
            if not commit:
                continue
            task["status"] = "complete"
            task["verify_fails"] = 0
            task["files_changed"] = commit.get("files_changed", [])
            task["commit_sha"] = commit.get("sha")
            if task.get("tdd_mode") in ("test_first", "implementation", "tdd_slice"):
                task["tdd_applied"] = True
            elif task.get("tdd_mode") == "unit_test":
                task["tdd_skipped"] = (
                    task.get("tdd_skipped")
                    or "unit_test verification only — no code written"
                )
            elif task.get("tdd_mode") == "exempt":
                task["tdd_skipped"] = task.get("tdd_skipped") or "committed exempt task"
            changed = True
            logger.warning(
                "[RESUME] Reconciled task %s as complete from commit %s.",
                task.get("id"),
                commit.get("sha"),
            )
    if changed:
        save_state(state)
    return changed


def _find_task_commit(
    initial_sha: str | None, phase_id: int, title: str, tdd_mode: str | None = None
) -> dict | None:
    if not phase_id or not title:
        return None
    subjects = {
        f"feat(phase-{phase_id}): {title}",
        f"test(phase-{phase_id}): {title}",
    }
    if tdd_mode == "unit_test":
        subjects.add(f"chore(phase-{phase_id}): update test verification support")
    rev_range = f"{initial_sha}..HEAD" if initial_sha else "HEAD"
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H%x00%s", rev_range],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        try:
            sha, commit_subject = line.split("\0", 1)
        except ValueError:
            continue
        if commit_subject not in subjects:
            continue
        files = _commit_files(sha)
        return {"sha": sha, "files_changed": files}
    return None


def _commit_files(sha: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def init_evaluate_state(state: dict, phase_id: int) -> None:
    if "evaluate" not in state:
        state["evaluate"] = {
            "status": "evaluating",
            "phase_id": phase_id,
            "iterations": [],
        }
    else:
        state["evaluate"]["status"] = "evaluating"
    save_state(state)


def start_evaluate_iteration(state: dict, iteration: int) -> None:
    evaluate = state.setdefault("evaluate", {})
    evaluate["status"] = "evaluating"
    evaluate["current_iteration"] = iteration
    evaluate["attempts"] = evaluate.get("attempts", 0) + 1
    evaluate["last_started_at"] = _now_iso()
    save_state(state)


def update_evaluate_iteration(state: dict, result: dict) -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    signal = result["signal"]
    entry = {
        "iteration": signal["iteration"],
        "verdict": signal["verdict"],
        "sha_at_evaluate": sha,
        "issues": signal.get("issues", []),
        "fix_sha": None,
    }
    if "score" in signal:
        entry["score"] = signal["score"]
    state["evaluate"]["current_iteration"] = None
    state["evaluate"]["last_finished_at"] = _now_iso()
    state["evaluate"]["iterations"].append(entry)
    save_state(state)


def update_evaluate_status(state: dict, status: str) -> None:
    state["evaluate"]["status"] = status
    save_state(state)


def error_evaluate(state: dict, status: str, reason: str) -> None:
    evaluate = state.setdefault("evaluate", {})
    evaluate["status"] = status
    evaluate["last_finished_at"] = _now_iso()
    evaluate.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error(
        "[ERROR] Evaluate %s: %s. It will resume at EVALUATING.", status, reason
    )
    sys.exit(1)


def find_evaluate_issue(state: dict, issue_id: str) -> dict | None:
    for iteration in state.get("evaluate", {}).get("iterations", []):
        for issue in iteration.get("issues", []):
            if issue["id"] == issue_id:
                return issue
    return None


def error_phase(state: dict, phase_id: int, reason: str) -> None:
    phase = find_phase(state, phase_id)
    if phase:
        phase["status"] = "error"
        phase.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error(
        "[ERROR] Phase %d TASK_BUILD failed: %s. Fix the spec, then run --resume.",
        phase_id,
        reason,
    )
    sys.exit(1)
