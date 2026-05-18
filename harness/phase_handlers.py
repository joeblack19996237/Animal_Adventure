from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import agents
from game_smoke import run_game_smoke
from spec_context import build_phase_spec_context
from calibrate import (
    get_task_planning_limits,
    get_usage_guardrails,
    latest_usage_entry,
    log_usage,
    phase_usage_summary,
)
from fix import handle_verdict, run_batch_retry_loop, run_fix_cycle
from harness_state import HarnessState
from regression import regression_failure_blocks_fix, run_phase_regression_gate
from state import (
    block_phase_external_dependency,
    block_review_external_dependency,
    block_task_external_dependency,
    error_phase,
    error_review,
    error_task,
    find_phase,
    find_task,
    halt_task,
    save_state,
    update_state,
)
from verify import verify_execution
from git_changes import capture_snapshot

if TYPE_CHECKING:
    from harness import Harness

logger = logging.getLogger(__name__)

_TASK_ID_RE = re.compile(r"^\d+\.\d+$")
_ALLOWED_TDD_MODES = {
    None,
    "test_first",
    "implementation",
    "tdd_slice",
    "unit_test",
    "exempt",
}


def _local_unit_test_result(task: dict, phase_id: int) -> dict:
    return {
        "signal": {
            "phase_id": phase_id,
            "tasks": [
                {
                    "id": task["id"],
                    "title": task.get("title", ""),
                    "task_type": task.get("task_type", "default"),
                    "status": "complete",
                    "tdd_applied": False,
                    "tdd_skipped": "unit_test verified locally by harness",
                    "files_changed": [],
                }
            ],
        },
        "usage": {},
        "local": True,
    }


def _phase_spec_context(state: dict, phase: dict | None) -> str:
    spec_file = state.get("spec_file", "")
    if not spec_file or not phase:
        return ""
    return build_phase_spec_context(spec_file, phase)


def _completed_work_context(state: dict, *, max_chars: int = 4000) -> str:
    lines: list[str] = []
    for phase in state.get("phases", []):
        completed = [t for t in phase.get("tasks", []) if t.get("status") == "complete"]
        if not completed:
            continue
        lines.append(f"Phase {phase.get('id')} ({phase.get('title', '')}) completed:")
        for task in completed:
            files = ", ".join(task.get("files_changed", [])[:6])
            if len(task.get("files_changed", [])) > 6:
                files += ", ..."
            lines.append(
                f"- {task.get('id')}: {task.get('title', '')}"
                + (f" | files: {files}" if files else "")
            )
    summary = "\n".join(lines)
    if len(summary) <= max_chars:
        return summary
    return summary[-max_chars:]


def _task_planning_violation(
    config: dict, phase: dict, tasks: list[dict]
) -> str | None:
    limits = get_task_planning_limits(config)
    if not limits["enabled"] or phase.get("phase_type") != "development":
        return None
    max_tasks = limits["max_tasks_per_development_phase"]
    if len(tasks) > max_tasks:
        return (
            f"TASK_BUILD generated {len(tasks)} tasks for development phase "
            f"{phase.get('id')} (limit {max_tasks}); replan with coarser "
            "tdd_slice tasks"
        )
    if not limits["allow_legacy_tdd_triplets"]:
        unit_tasks = [
            t.get("id", "?") for t in tasks if t.get("tdd_mode") == "unit_test"
        ]
        if unit_tasks:
            return (
                "TASK_BUILD generated legacy unit_test Claude tasks "
                f"{unit_tasks}; use harness-local verification instead"
            )
    return None


def _validate_task_plan_signal(phase_id: int, signal: dict) -> str | None:
    tasks = signal.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return "TASK_BUILD generated no tasks; please regenerate a non-empty task list"

    seen_ids: set[str] = set()
    required_fields = ("id", "title", "task_type", "description")
    expected_prefix = f"{phase_id}."
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            return f"TASK_BUILD task #{index} is not an object"
        for field in required_fields:
            value = task.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"TASK_BUILD task #{index} missing non-empty {field!r}"

        task_id = task["id"].strip()
        if not _TASK_ID_RE.match(task_id) or not task_id.startswith(expected_prefix):
            return (
                f"TASK_BUILD task #{index} id {task_id!r} must use phase "
                f"{phase_id} prefix"
            )
        if task_id in seen_ids:
            return f"TASK_BUILD generated duplicate task id {task_id!r}"
        seen_ids.add(task_id)

        tdd_mode = task.get("tdd_mode")
        if tdd_mode not in _ALLOWED_TDD_MODES:
            return f"TASK_BUILD task {task_id} has unknown tdd_mode {tdd_mode!r}"
    return None


def _usage_guardrail_violation(config: dict, phase_id: int) -> str | None:
    guardrails = get_usage_guardrails(config)
    if not guardrails["enabled"]:
        return None
    latest = latest_usage_entry()
    if not latest or latest.get("phase_id") != phase_id:
        return None
    if latest.get("actual_output_tokens", 0) > guardrails["max_single_output_tokens"]:
        return (
            f"usage guardrail tripped: task {latest.get('task_id')} output "
            f"{latest.get('actual_output_tokens')} tokens exceeds "
            f"limit {guardrails['max_single_output_tokens']}"
        )
    summary = phase_usage_summary(phase_id)
    if summary["calls"] > guardrails["max_phase_claude_calls"]:
        return (
            f"usage guardrail tripped: phase {phase_id} has {summary['calls']} Claude "
            f"calls (limit {guardrails['max_phase_claude_calls']})"
        )
    if summary["combined_tokens"] > guardrails["max_phase_combined_tokens"]:
        return (
            f"usage guardrail tripped: phase {phase_id} combined tokens "
            f"{summary['combined_tokens']} exceeds "
            f"limit {guardrails['max_phase_combined_tokens']}"
        )
    return None


def handle_task_build(harness: Harness, state: dict, phase_id: int, profile: dict):
    phase_data = harness._get_phase_data(phase_id)
    if not phase_data:
        harness._load_spec_into_memory()
        phase_data = harness._get_phase_data(phase_id)

    update_state(state, entity_type="phase", phase_id=phase_id, status="building")

    ref_contents: list[str] = []
    seen_refs: set[str] = set()
    for ref_path in phase_data.get("refs", []):
        if ref_path in seen_refs:
            continue
        seen_refs.add(ref_path)
        p = Path(ref_path)
        if p.exists():
            ref_contents.append(p.read_text(encoding="utf-8"))
        else:
            logger.warning(
                "[TASK_BUILD] Phase %s ref not found: %s", phase_id, ref_path
            )

    done_summaries = "\n".join(
        f"Phase {ph['id']} ({ph['title']}): complete"
        for ph in state["phases"]
        if ph["status"] == "complete"
    )
    scoped_context = (
        f"Completed phases:\n{done_summaries}\n\n" if done_summaries else ""
    )
    scoped_context += "\n\n".join(ref_contents)

    try:
        result = agents.build_tasks(
            phase_data,
            scoped_context,
            profile,
            harness.config,
            state,
            spec_context=_phase_spec_context(state, phase_data),
            completed_work_context=_completed_work_context(state),
        )
    except agents.ExternalDependencyError as e:
        block_phase_external_dependency(state, phase_id, str(e))
        return HarnessState.HALTED
    except agents.SubprocessError as e:
        error_phase(state, phase_id, str(e))
        return HarnessState.HALTED

    signal = result["signal"]
    new_tasks = signal.get("tasks", [])
    log_usage(
        task_id=f"phase_{phase_id}_build",
        phase_id=phase_id,
        mode="TASK_BUILD",
        usage=result["usage"],
        files_changed=0,
        call_id=result.get("call_id"),
    )
    usage_error = _usage_guardrail_violation(harness.config, phase_id)
    if usage_error:
        error_phase(state, phase_id, usage_error)
        return HarnessState.HALTED

    validation_error = _validate_task_plan_signal(phase_id, signal)
    if validation_error:
        error_phase(state, phase_id, validation_error)
        return HarnessState.HALTED

    planning_error = _task_planning_violation(harness.config, phase_data, new_tasks)
    if planning_error:
        error_phase(state, phase_id, planning_error)
        return HarnessState.HALTED

    state_phase = find_phase(state, phase_id)
    if state_phase is None:
        error_phase(state, phase_id, "phase not found in state")
        return HarnessState.HALTED
    state_phase["tasks"] = [
        {
            "id": t["id"],
            "title": t["title"],
            "task_type": t["task_type"],
            "description": t.get("description", ""),
            "refs": t.get("refs", []),
            "status": "pending",
            "attempts": 0,
            "verify_fails": 0,
            "tdd_mode": t.get("tdd_mode"),
            "tdd_applied": None,
            "tdd_skipped": None,
            "files_changed": [],
            "last_error": [],
        }
        for t in new_tasks
    ]
    for t in state_phase["tasks"]:
        if not t["description"]:
            logger.warning(
                "[TASK_BUILD] Task %s has no description — EXECUTE agent will have less context.",
                t["id"],
            )
    save_state(state)

    return HarnessState.EXECUTING


def handle_executing(harness: Harness, state: dict, phase_id: int, profile: dict):
    from harness import _pending_tasks

    tasks = _pending_tasks(state)
    if not tasks:
        state_phase = find_phase(state, phase_id) or {}
        if not state_phase.get("tasks", []):
            logger.warning(
                "[EXECUTE] Phase %s has no tasks; returning to TASK_BUILD.",
                phase_id,
            )
            harness._load_spec_into_memory()
            return HarnessState.TASK_BUILD
        return HarnessState.REVIEWING

    for task in tasks:
        update_state(state, task_id=task["id"], status="building")

        pre_snapshot = capture_snapshot()
        pre_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()

        if task.get("tdd_mode") == "unit_test":
            result = _local_unit_test_result(task, phase_id)
        else:
            try:
                state_phase = find_phase(state, phase_id) or {}
                result = agents.execute(
                    [task],
                    phase_id=phase_id,
                    profile=profile,
                    config=harness.config,
                    phase_type=harness.phase_type_for(phase_id),
                    spec_context=_phase_spec_context(state, state_phase),
                )
            except agents.ExternalDependencyError as e:
                block_task_external_dependency(state, task["id"], str(e))
                return HarnessState.HALTED
            except agents.SubprocessError as e:
                error_task(state, task["id"], str(e))
                return HarnessState.HALTED

        signal = result["signal"]

        signal_phase_id = signal.get("phase_id")
        if signal_phase_id is None:
            # Builder omitted or nulled phase_id (common on large-output correction turns).
            # Patch from harness context; task-ID checks below still guard correctness.
            logger.warning(
                "[EXECUTE] Signal phase_id is None — patching to %r for task %r.",
                phase_id,
                task["id"],
            )
            signal["phase_id"] = phase_id
            signal_phase_id = phase_id
        if signal_phase_id != phase_id:
            logger.error(
                "[EXECUTE] Signal phase_id=%r does not match active phase %r — "
                "failing task %r.",
                signal_phase_id,
                phase_id,
                task["id"],
            )
            error_task(
                state,
                task["id"],
                f"signal phase_id mismatch: expected {phase_id}, got {signal_phase_id}",
            )
            return HarnessState.HALTED

        signal_task_ids = {t["id"] for t in signal.get("tasks", [])}
        if task["id"] not in signal_task_ids:
            logger.error(
                "[EXECUTE] Active task %r absent from signal task IDs %r — failing task.",
                task["id"],
                sorted(signal_task_ids),
            )
            error_task(
                state,
                task["id"],
                f"active task {task['id']} not found in signal",
            )
            return HarnessState.HALTED

        unexpected = signal_task_ids - {task["id"]}
        if unexpected:
            logger.warning(
                "[EXECUTE] Signal contains unexpected task IDs %r (active: %r) — ignoring.",
                sorted(unexpected),
                task["id"],
            )

        verify_failures = verify_execution(
            harness,
            pre_sha,
            [task],
            signal,
            pre_snapshot=pre_snapshot,
            call_id=result.get("call_id"),
        )
        if getattr(verify_failures, "harness_blocker", False):
            if not result.get("local"):
                task_sig = next(
                    (s for s in signal.get("tasks", []) if s["id"] == task["id"]),
                    {},
                )
                log_usage(
                    task_id=task["id"],
                    phase_id=phase_id,
                    mode="EXECUTE",
                    usage=result["usage"],
                    files_changed=len(task_sig.get("files_changed", [])),
                    task_type=task_sig.get("task_type", "default"),
                    call_id=result.get("call_id"),
                )
            halt_task(
                state,
                task["id"],
                getattr(verify_failures, "blocker_reason", None)
                or verify_failures[0].get("reason", "harness verification blocked"),
            )
            return HarnessState.HALTED
        verify_failed_ids = {t["id"] for t in verify_failures}

        failed_tasks = []
        for task_sig in signal.get("tasks", []):
            if task_sig["id"] != task["id"]:
                continue
            task_id = task_sig["id"]
            if task_sig["status"] == "complete" and task_id not in verify_failed_ids:
                update_state(
                    state,
                    task_id=task_id,
                    status="complete",
                    tdd_applied=task_sig.get("tdd_applied"),
                    tdd_skipped=task_sig.get("tdd_skipped"),
                    files_changed=task_sig.get("files_changed", [])
                    or getattr(verify_failures, "committed_files", []),
                    commit_sha=getattr(verify_failures, "commit_sha", None),
                )
            elif task_sig["status"] == "failed":
                t = find_task(state, task_id)
                if t:
                    t["attempts"] += 1
                    t.setdefault("last_error", []).append(task_sig.get("reason", ""))
                    update_state(
                        state,
                        task_id=task_id,
                        attempts=t["attempts"],
                        last_error=t["last_error"],
                    )
                failed_tasks.append(task_sig)

        failed_tasks.extend(verify_failures)

        if not result.get("local"):
            task_sig = next(
                (s for s in signal.get("tasks", []) if s["id"] == task["id"]), {}
            )
            log_usage(
                task_id=task["id"],
                phase_id=phase_id,
                mode="EXECUTE",
                usage=result["usage"],
                files_changed=len(task_sig.get("files_changed", [])),
                task_type=task_sig.get("task_type", "default"),
                call_id=result.get("call_id"),
            )
            usage_error = _usage_guardrail_violation(harness.config, phase_id)
            if usage_error:
                update_state(
                    state,
                    entity_type="phase",
                    phase_id=phase_id,
                    status="error",
                    last_error=[usage_error],
                )
                return HarnessState.HALTED

        if failed_tasks:
            run_batch_retry_loop(harness, state, failed_tasks, phase_id)

    return HarnessState.REVIEWING


def handle_reviewing(harness: Harness, state: dict, phase_id: int, profile: dict):
    # Setup phases contain only scaffolding (files, dirs, dependency installs) — no
    # application logic to review. Auto-approve to skip the reviewer agent.
    if harness.phase_type_for(phase_id) == "setup" and state.get("app_type") != "game":
        logger.info(
            "[REVIEW] Phase %d is a setup phase — auto-approving (no code to review).",
            phase_id,
        )
        sha_run = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        )
        sha_at_review = sha_run.stdout.strip() if sha_run.returncode == 0 else None
        update_state(
            state,
            entity_type="review",
            phase_id=phase_id,
            status="complete",
            verdict="APPROVE",
            sha_at_review=sha_at_review,
            issues=[],
        )
        return HarnessState.REGRESSION_TESTING

    if phase_id == 1:
        base_sha = state.get("initial_sha", "HEAD")
    else:
        prev_phase = find_phase(state, phase_id - 1)
        base_sha = (
            (prev_phase or {})
            .get("review", {})
            .get("sha_at_review", state.get("initial_sha", "HEAD"))
        )

    spec_paths = [state.get("spec_file", "")]
    state_phase = find_phase(state, phase_id) or {}

    try:
        result = agents.review_phase(
            phase_id,
            base_sha,
            spec_paths,
            profile,
            harness.config,
            phase_task_count=len((find_phase(state, phase_id) or {}).get("tasks", [])),
            spec_context=_phase_spec_context(state, state_phase),
        )
    except agents.ExternalDependencyError as e:
        block_review_external_dependency(state, phase_id, str(e), "REVIEW")
        return HarnessState.HALTED
    except agents.SubprocessError as e:
        error_review(state, phase_id, str(e))
        return HarnessState.HALTED

    signal = result["signal"]
    sha_run = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    actual_sha = sha_run.stdout.strip() if sha_run.returncode == 0 else None
    agent_sha = signal.get("sha_at_review")
    if actual_sha and agent_sha and agent_sha != actual_sha:
        logger.warning(
            "[REVIEW] Agent sha_at_review=%r differs from actual HEAD %r — overriding.",
            agent_sha,
            actual_sha,
        )
    sha_at_review = actual_sha or agent_sha
    issues = [
        {
            "id": iss["id"],
            "severity": iss["severity"],
            "dimension": iss["dimension"],
            "file": iss["file"],
            "title": iss["title"],
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
        for iss in signal.get("issues", [])
    ]
    update_state(
        state,
        entity_type="review",
        phase_id=phase_id,
        status="complete",
        verdict=signal.get("verdict"),
        sha_at_review=sha_at_review,
        issues=issues,
    )

    handle_verdict(harness, state, phase_id, result)
    return HarnessState.REGRESSION_TESTING


def handle_fixing(harness: Harness, state: dict, phase_id: int):
    run_fix_cycle(harness, state, phase_id)
    return HarnessState.REGRESSION_TESTING


def handle_regression_testing(harness: Harness, state: dict, phase_id: int):
    if run_phase_regression_gate(harness, state, phase_id):
        return HarnessState.NEXT_PHASE
    phase = find_phase(state, phase_id)
    if regression_failure_blocks_fix(phase):
        return HarnessState.HALTED
    return HarnessState.FIXING


def handle_next_phase(harness: Harness, state: dict, phase_id: int):
    phase = find_phase(state, phase_id) or {}
    if phase.get("regression", {}).get("status") != "passed":
        logger.warning(
            "[REGRESSION] Phase %d attempted NEXT_PHASE before full regression passed.",
            phase_id,
        )
        return HarnessState.REGRESSION_TESTING
    smoke = run_game_smoke(state, phase_id, harness.config)
    if not smoke.ok:
        update_state(
            state,
            entity_type="phase",
            phase_id=phase_id,
            status="error",
            last_error=[
                {
                    "reason": "game smoke failed",
                    "cmd": smoke.cmd,
                    "stdout_tail": smoke.stdout_tail,
                    "stderr_tail": smoke.stderr_tail,
                }
            ],
        )
        return HarnessState.HALTED
    update_state(state, entity_type="phase", phase_id=phase_id, status="complete")
    next_id = phase_id + 1
    if next_id > state.get("total_phases", 0):
        return HarnessState.CLEANUP
    state["current_phase"] = next_id
    save_state(state)
    return HarnessState.TASK_BUILD
