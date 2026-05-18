from __future__ import annotations

import logging
import sys
from typing import Any

from events import emit_event
from state import reset_interrupted_tasks

logger = logging.getLogger(__name__)


def recover_or_block_stale_execution(
    state: dict,
    *,
    lock_context: dict[str, Any] | None,
    cleanup_result: dict[str, Any] | None,
) -> dict[str, Any]:
    lock_context = lock_context or {}
    cleanup_result = cleanup_result or {}
    if not lock_context.get("stale_lock_at_start"):
        return {"action": "not_stale"}

    inflight = _inflight_state_summary(state)
    if not inflight["detected"]:
        emit_event(
            "stale_execution_recovery_noop",
            stale_lock_at_start=True,
            reason="no_inflight_state",
        )
        return {"action": "noop", "inflight": inflight}

    if _cleanup_unsafe_to_resume(cleanup_result):
        reason = _unsafe_cleanup_reason(cleanup_result)
        emit_event(
            "stale_execution_recovery_blocked",
            stale_lock_at_start=True,
            reason=reason,
            inflight_tasks=inflight["tasks"],
            cleanup=cleanup_result,
        )
        logger.error(
            "[RESUME] Stale harness execution detected, but stale Claude CLI "
            "processes could not be proven clean: %s",
            reason,
        )
        logger.error(
            "[RESUME] Stop old Claude CLI processes manually, then run "
            "`python harness/harness.py --resume`."
        )
        sys.exit(1)

    reset_happened = reset_interrupted_tasks(state)
    emit_event(
        "stale_execution_recovered",
        stale_lock_at_start=True,
        reset_interrupted_tasks=reset_happened,
        inflight_tasks=inflight["tasks"],
        cleanup=cleanup_result,
    )
    return {
        "action": "recovered",
        "reset_interrupted_tasks": reset_happened,
        "inflight": inflight,
    }


def _inflight_state_summary(state: dict) -> dict[str, Any]:
    tasks = []
    for phase in state.get("phases", []):
        for task in phase.get("tasks", []):
            if task.get("status") == "building":
                tasks.append(
                    {
                        "phase_id": phase.get("id"),
                        "id": task.get("id"),
                        "title": task.get("title", ""),
                        "status": task.get("status"),
                    }
                )
    cleanup_status = state.get("cleanup", {}).get("status")
    evaluate_status = state.get("evaluate", {}).get("status")
    return {
        "detected": bool(
            tasks
            or cleanup_status in ("cleaning", "fixing")
            or evaluate_status == "evaluating"
        ),
        "tasks": tasks,
        "cleanup_status": cleanup_status,
        "evaluate_status": evaluate_status,
    }


def _cleanup_unsafe_to_resume(cleanup_result: dict[str, Any]) -> bool:
    if cleanup_result.get("unsafe_to_resume"):
        return True
    if cleanup_result.get("errors"):
        return True
    return bool(
        cleanup_result.get("protection_incomplete")
        and cleanup_result.get("candidate_pids")
    )


def _unsafe_cleanup_reason(cleanup_result: dict[str, Any]) -> str:
    if cleanup_result.get("unsafe_to_resume_reason"):
        return str(cleanup_result["unsafe_to_resume_reason"])
    errors = cleanup_result.get("errors") or []
    if errors:
        return f"Claude cleanup errors: {errors}"
    candidates = cleanup_result.get("candidate_pids") or []
    if cleanup_result.get("protection_incomplete") and candidates:
        return (
            "Claude process protection was incomplete and CLI candidates remain: "
            f"{candidates}"
        )
    return "Claude cleanup unsafe to resume"
