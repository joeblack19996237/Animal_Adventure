"""
Autonomous Dev Harness — Orchestrator
Usage: python harness/harness.py [<spec_file_or_dir>] [--language python] [--resume] [--max-phase N]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import phase_handlers
import external_dependency
import resume_process_cleanup
import resume_recovery
from calibrate import (
    get_claude_session_pacing,
    latest_usage_entry,
    load_config,
    recent_usage_summary,
    usage_token_totals,
)
from calibrate import get_default_app_type, get_default_language, get_default_spec_path
from cleanup import run_cleanup
from events import emit_event, log_line
from evaluate import run_evaluate_cycle
from harness_state import HarnessState
from lang import apply_profile_overrides, get_profile
from run_lock import (
    RunLockError,
    acquire_lock,
    clear_stale_lock,
    lock_status,
    release_lock,
)
from subprocess_runner import process_exists
from spec import check_spec_completeness, parse_spec, validate_spec
from state import (
    find_phase,
    load_state,
    reconcile_committed_tasks,
    reset_interrupted_tasks,
    save_state,
)

logger = logging.getLogger(__name__)

_STAGE_PATHS = ["harness", ".claude", "docs", "tests", "CLAUDE.md", "README.md"]
EVENTS_PATH = Path("workspace/events.jsonl")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous Dev Harness")
    parser.add_argument(
        "spec_file_or_dir",
        nargs="?",
        help="Spec file or directory (required on first run)",
    )
    parser.add_argument("--language", default=None, help="Target language")
    parser.add_argument(
        "--app-type",
        choices=["cli", "web", "game"],
        default=None,
        help="App type for spec completeness validation",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from existing state.json"
    )
    parser.add_argument(
        "--max-phase", type=int, default=None, help="Stop after this phase number"
    )
    parser.add_argument(
        "--status", action="store_true", help="Print harness run status"
    )
    parser.add_argument(
        "--clear-stale-lock",
        action="store_true",
        help="Clear workspace/run.lock only when its PID is no longer active",
    )
    return parser.parse_args()


def _git_startup(state: dict) -> None:
    result = subprocess.run(["git", "status"], capture_output=True)
    if result.returncode != 0 and b"not a git repository" in result.stderr:
        subprocess.run(["git", "init"], check=True)
        stage = [p for p in _STAGE_PATHS if Path(p).exists()]
        if stage:
            subprocess.run(["git", "add"] + stage, check=True)
        subprocess.run(["git", "commit", "-m", "chore: init harness"], check=True)

    if not state.get("initial_sha"):
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        state["initial_sha"] = sha
        save_state(state)


def _pending_tasks(state: dict) -> list:
    phase = find_phase(state, state.get("current_phase", 1))
    if phase is None:
        return []
    return [t for t in phase.get("tasks", []) if t["status"] == "pending"]


def _has_existing_run(state: dict) -> bool:
    return bool(state.get("spec_file") or state.get("phases") or state.get("evaluate"))


def _summarize_status(state: dict, lock: dict) -> dict:
    phase = find_phase(state, state.get("current_phase", 1)) or {}
    review = phase.get("review", {})
    regression = phase.get("regression", {})
    cleanup = state.get("cleanup", {})
    evaluate = state.get("evaluate", {})
    current_error = _current_error(phase, review, regression, cleanup, evaluate)
    historical_error = _latest_error(phase, review, regression, cleanup, evaluate)
    active_tasks = [
        _task_status_summary(t)
        for t in phase.get("tasks", [])
        if t.get("status") == "building"
    ]
    error_tasks = [
        _task_status_summary(t)
        for t in phase.get("tasks", [])
        if t.get("status") == "error"
    ]
    blocked_tasks = [
        _task_status_summary(t)
        for t in phase.get("tasks", [])
        if t.get("status") == "blocked_external_dependency"
    ]
    halted_tasks = [
        _task_status_summary(t)
        for t in phase.get("tasks", [])
        if t.get("status") == "halted"
    ]
    halted_issues = [
        _issue_status_summary(i)
        for i in review.get("issues", [])
        if i.get("status") == "halted"
    ]
    error_issues = [
        _issue_status_summary(i)
        for i in review.get("issues", [])
        if i.get("status") == "error"
    ]
    recent_claude_events = _recent_claude_event_status()
    current_run_claude_events = _recent_claude_event_status(
        since_ts=lock.get("started_at"),
        include_pid_active=True,
    )
    return {
        **lock,
        "stale_lock": bool(lock.get("pid") and lock.get("active") is False),
        "current_phase": state.get("current_phase"),
        "phase_title": phase.get("title"),
        "phase_status": phase.get("status"),
        "harness_state": _approx_harness_state(state, phase),
        "review_status": review.get("status"),
        "review_blocked_mode": review.get("blocked_mode"),
        "regression_status": regression.get("status"),
        "regression_attempts": regression.get("attempts"),
        "cleanup_status": cleanup.get("status"),
        "evaluate_status": evaluate.get("status"),
        "evaluate_current_iteration": evaluate.get("current_iteration"),
        "evaluate_attempts": evaluate.get("attempts"),
        "last_error": current_error,
        "historical_last_error": historical_error,
        "active_tasks": active_tasks,
        "error_tasks": error_tasks,
        "blocked_tasks": blocked_tasks,
        "halted_tasks": halted_tasks,
        "error_issues": error_issues,
        "halted_issues": halted_issues,
        "recent_claude_events": recent_claude_events,
        "current_run_claude_events": current_run_claude_events,
        "stale_execution": _stale_execution_status(
            state, lock, current_run_claude_events
        ),
        "usage_window": _usage_window_status(),
        "last_claude_usage": _last_claude_usage_status(),
        "session_pacing": _session_pacing_status(),
        "external_dependency_wait": _external_dependency_wait_status(),
        "resume_claude_cleanup": _latest_resume_claude_cleanup_status(),
        "next_command": "python harness/harness.py --resume"
        if _has_existing_run(state)
        else "python harness/harness.py <spec_file_or_dir>",
    }


def _task_status_summary(task: dict) -> dict:
    return {
        "id": task.get("id"),
        "title": task.get("title", ""),
        "status": task.get("status"),
        "last_error": task.get("last_error", []),
    }


def _issue_status_summary(issue: dict) -> dict:
    return {
        "id": issue.get("id"),
        "title": issue.get("title", ""),
        "status": issue.get("status"),
        "attempts": issue.get("attempts", 0),
        "last_error": issue.get("last_error", []),
    }


def _recent_claude_event_status(
    limit: int = 5,
    *,
    since_ts: str | None = None,
    include_pid_active: bool = False,
) -> dict:
    if not EVENTS_PATH.exists():
        return {
            "recent_nonzero_end": [],
            "recent_timeouts": [],
            "recent_failed": [],
            "unmatched_starts": [],
        }
    events = []
    for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    starts = []
    nonzero = []
    timeouts = []
    failed = []
    since = _parse_iso(since_ts) if since_ts else None
    for event in events:
        if since is not None and not _event_at_or_after(event, since):
            continue
        name = event.get("event")
        if name == "claude_subprocess_start":
            starts.append(event)
        elif name == "claude_subprocess_end":
            _remove_matching_claude_start(starts, event)
            if event.get("returncode") not in (None, 0):
                nonzero.append(event)
        elif name == "claude_subprocess_timeout":
            _remove_matching_claude_start(starts, event)
            timeouts.append(event)
        elif name == "claude_subprocess_failed":
            _remove_matching_claude_start(starts, event)
            failed.append(event)
    return {
        "recent_nonzero_end": [
            _claude_event_summary(e, include_pid_active=include_pid_active)
            for e in nonzero[-limit:]
        ],
        "recent_timeouts": [
            _claude_event_summary(e, include_pid_active=include_pid_active)
            for e in timeouts[-limit:]
        ],
        "recent_failed": [
            _claude_event_summary(e, include_pid_active=include_pid_active)
            for e in failed[-limit:]
        ],
        "unmatched_starts": [
            _claude_event_summary(e, include_pid_active=include_pid_active)
            for e in starts[-limit:]
        ],
    }


def _remove_matching_claude_start(starts: list[dict], event: dict) -> None:
    pid = event.get("pid")
    if pid is not None:
        for index in range(len(starts) - 1, -1, -1):
            if starts[index].get("pid") == pid:
                starts.pop(index)
                return
        return
    if starts:
        starts.pop()


def _claude_event_summary(event: dict, *, include_pid_active: bool = False) -> dict:
    summary = {
        "ts": event.get("ts"),
        "event": event.get("event"),
        "mode": event.get("mode"),
        "call_id": event.get("call_id"),
        "pid": event.get("pid"),
        "returncode": event.get("returncode"),
        "timeout": event.get("timeout"),
        "elapsed": event.get("elapsed"),
        "stderr_tail": event.get("stderr_tail", ""),
        "reason": event.get("reason", ""),
    }
    if include_pid_active:
        summary["pid_active"] = process_exists(event.get("pid"))
    return summary


def _event_at_or_after(event: dict, since: datetime) -> bool:
    ts = _parse_iso(event.get("ts", ""))
    return bool(ts and ts >= since)


def _stale_execution_status(
    state: dict, lock: dict, current_run_claude_events: dict
) -> dict:
    phase = find_phase(state, state.get("current_phase", 1)) or {}
    inflight_tasks = [
        _task_status_summary(t)
        for t in phase.get("tasks", [])
        if t.get("status") == "building"
    ]
    unmatched = current_run_claude_events.get("unmatched_starts", [])
    live_unmatched = [e for e in unmatched if e.get("pid_active") is True]
    detected = bool(
        lock.get("pid")
        and lock.get("active") is False
        and (inflight_tasks or unmatched)
    )
    if not detected:
        action = ""
    elif live_unmatched:
        action = "stop old Claude CLI processes before resume"
    else:
        action = "resume can recover interrupted state after stale lock cleanup"
    return {
        "detected": detected,
        "inflight_tasks": inflight_tasks,
        "unmatched_current_run_claude_starts": unmatched,
        "live_unmatched_pids": [e.get("pid") for e in live_unmatched],
        "recommended_action": action,
    }


def _latest_resume_claude_cleanup_status() -> dict | None:
    if not EVENTS_PATH.exists():
        return None
    latest = None
    for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "resume_claude_cleanup_end":
            latest = event
    if not latest:
        return None
    return {
        "ts": latest.get("ts"),
        "attempted": latest.get("attempted"),
        "protection_incomplete": latest.get("protection_incomplete"),
        "protected_pids": latest.get("protected_pids", []),
        "candidate_pids": latest.get("candidate_pids", []),
        "killed_pids": latest.get("killed_pids", []),
        "skipped_pids": latest.get("skipped_pids", []),
        "errors": latest.get("errors", []),
        "unsafe_to_resume": latest.get("unsafe_to_resume"),
        "unsafe_to_resume_reason": latest.get("unsafe_to_resume_reason", ""),
    }


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _usage_window_status() -> dict:
    config = load_config()
    pacing = get_claude_session_pacing(config)
    return recent_usage_summary(window_seconds=pacing["usage_window_seconds"])


def _last_claude_usage_status() -> dict | None:
    entry = latest_usage_entry()
    if not entry:
        return None
    return {
        "ts": entry.get("ts"),
        "phase_id": entry.get("phase_id"),
        "task_id": entry.get("task_id"),
        "mode": entry.get("mode"),
        "call_id": entry.get("call_id"),
        **usage_token_totals(entry),
    }


def _session_pacing_status() -> dict:
    config = load_config()
    pacing = get_claude_session_pacing(config)
    return {
        "enabled": pacing["enabled"],
        "min_seconds_between_calls": pacing["min_seconds_between_calls"],
        "large_output_token_threshold": pacing["large_output_token_threshold"],
        "large_output_cooldown_seconds": pacing["large_output_cooldown_seconds"],
        "usage_window_seconds": pacing["usage_window_seconds"],
    }


def _external_dependency_wait_status() -> dict | None:
    context = external_dependency.load_context()
    if not context:
        return None
    reset_at = _parse_iso(context.get("reset_at", ""))
    remaining_seconds = None
    if reset_at:
        remaining_seconds = max(
            0, int((reset_at - datetime.now(timezone.utc)).total_seconds())
        )
    cleanup = context.get("process_cleanup", {})
    return {
        "mode": context.get("mode"),
        "root_pid": context.get("root_pid"),
        "reset_at": context.get("reset_at"),
        "remaining_seconds": remaining_seconds,
        "cleanup_status": context.get("cleanup_status"),
        "process_cleanup_attempted": cleanup.get("attempted"),
        "process_cleanup_ok": cleanup.get("ok"),
        "process_cleanup_error": cleanup.get("error", ""),
        "claude_processes_after_cleanup": context.get(
            "claude_processes_after_cleanup", []
        ),
        "possible_orphan_processes": context.get("possible_orphan_processes", []),
        "tracked_dirty_files": context.get("tracked_dirty_files", []),
        "quarantined_files": context.get("quarantined_files", []),
    }


def _latest_error(*items: dict) -> str | None:
    for item in reversed(items):
        errors = item.get("last_error") if item else None
        if isinstance(errors, list) and errors:
            return str(errors[-1])
        if isinstance(errors, str):
            return errors
    return None


def _current_error(
    phase: dict, review: dict, regression: dict, cleanup: dict, evaluate: dict
) -> str | None:
    for task in phase.get("tasks", []):
        if task.get("status") == "blocked_external_dependency":
            return _latest_error(task)
    for task in phase.get("tasks", []):
        if task.get("status") == "error":
            return _latest_error(task)
    for task in phase.get("tasks", []):
        if task.get("status") == "halted":
            return _latest_error(task)
    for issue in review.get("issues", []):
        if issue.get("status") == "error":
            return _latest_error(issue)
    for issue in review.get("issues", []):
        if issue.get("status") == "halted":
            return _latest_error(issue)
    if regression.get("status") in ("failed", "blocked", "error", "halted"):
        return _latest_error(regression)
    if evaluate.get("status") in ("blocked_external_dependency", "timeout", "error"):
        return _latest_error(evaluate)
    if cleanup.get("status") in ("blocked_external_dependency", "error", "halted"):
        return _latest_error(cleanup)
    if review.get("status") in ("blocked_external_dependency", "error"):
        return _latest_error(review)
    if phase.get("status") in ("blocked_external_dependency", "error"):
        return _latest_error(phase)
    return None


def _approx_harness_state(state: dict, phase: dict) -> str:
    evaluate_status = state.get("evaluate", {}).get("status")
    if evaluate_status in (
        "evaluating",
        "test_authoring",
        "red_verifying",
        "fixing",
        "targeted_verifying",
        "regression_verifying",
        "blocked_external_dependency",
        "timeout",
        "error",
    ):
        return HarnessState.EVALUATING.name
    if evaluate_status == "complete":
        return HarnessState.COMPLETE.name
    if state.get("cleanup", {}).get("status") in (
        "blocked_external_dependency",
        "error",
        "halted",
    ):
        return HarnessState.CLEANUP.name
    status = phase.get("status")
    review = phase.get("review", {})
    regression = phase.get("regression", {})
    if status in ("error", "pending", "blocked_external_dependency"):
        return HarnessState.TASK_BUILD.name
    if status == "building":
        if any(t.get("status") in ("error", "halted") for t in phase.get("tasks", [])):
            return HarnessState.HALTED.name
        if any(i.get("status") == "halted" for i in review.get("issues", [])):
            return HarnessState.HALTED.name
        if any(
            t.get("status") in ("pending", "building", "blocked_external_dependency")
            for t in phase.get("tasks", [])
        ):
            return HarnessState.EXECUTING.name
        if review.get("status") == "blocked_external_dependency":
            return (
                HarnessState.FIXING.name
                if review.get("blocked_mode") == "FIX"
                else HarnessState.REVIEWING.name
            )
        if review.get("status") in ("pending", "error"):
            return HarnessState.REVIEWING.name
        if review.get("status") == "fixing":
            return HarnessState.FIXING.name
        if regression.get("status") in ("running", "failed", "blocked", "pending"):
            return HarnessState.REGRESSION_TESTING.name
        if review.get("status") in ("complete", "fixed"):
            if regression.get("status") == "passed":
                return HarnessState.NEXT_PHASE.name
            return HarnessState.REGRESSION_TESTING.name
    return HarnessState.CLEANUP.name


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        os.makedirs("workspace", exist_ok=True)
        os.makedirs("workspace/screenshots", exist_ok=True)
        self.config = load_config()
        self.state = load_state()
        self.args = args
        self.profiles: dict[int, dict] = {}
        self._default_language: str = "python"
        self.phases: list = []
        self.context: str = ""
        self._resume_lock_context: dict = {}

    def run(self) -> None:
        args = self.args
        state = self.state
        if getattr(args, "status", False) is True:
            print(_summarize_status(state, lock_status()))
            return
        if getattr(args, "clear_stale_lock", False) is True:
            print(
                "[HARNESS] stale lock cleared"
                if clear_stale_lock()
                else "[HARNESS] no stale lock"
            )
            return

        pre_lock = lock_status()
        self._resume_lock_context = {
            "stale_lock_at_start": bool(
                args.resume and pre_lock.get("pid") and pre_lock.get("active") is False
            ),
            "lock": pre_lock,
        }

        lock_acquired = False
        try:
            arg_spec_file = getattr(args, "spec_file_or_dir", None)
            if not isinstance(arg_spec_file, str):
                arg_spec_file = ""
            arg_app_type = getattr(args, "app_type", None)
            if not isinstance(arg_app_type, str):
                arg_app_type = get_default_app_type(self.config)
            acquire_lock(
                spec_file=arg_spec_file
                or state.get("spec_file", "")
                or get_default_spec_path(self.config),
                app_type=arg_app_type or state.get("app_type", ""),
                current_phase=state.get("current_phase"),
            )
            lock_acquired = True
        except RunLockError as e:
            logger.error("[LOCK] %s", e)
            sys.exit(1)

        emit_event(
            "harness_start", resume=bool(args.resume), cwd=str(Path(".").resolve())
        )
        log_line("[HARNESS] start")

        release_on_exit = False
        try:
            self._run_locked(args, state)
        except SystemExit:
            release_on_exit = True
            raise
        except Exception as e:
            emit_event("harness_crash", error_type=type(e).__name__)
            raise
        else:
            release_on_exit = True
            emit_event("harness_complete")
            log_line("[HARNESS] complete")
        finally:
            if lock_acquired and release_on_exit:
                release_lock()

    def _run_locked(self, args: argparse.Namespace, state: dict) -> None:
        if args.resume:
            self._default_language = (
                args.language if args.language else state.get("language", "python")
            )
            app_type = (
                args.app_type
                if args.app_type
                else state.get("app_type", get_default_app_type(self.config))
            )
            state["app_type"] = app_type
            for sp in state.get("phases", []):
                lang = self._phase_profile_language(sp, app_type)
                self.profiles[sp["id"]] = apply_profile_overrides(
                    get_profile(lang), self.config
                )
            spec_file = state.get("spec_file")
            if not spec_file:
                logger.error("[ERROR] state.json has no spec_file — cannot resume.")
                sys.exit(1)
            _git_startup(state)
            cleanup_result = resume_process_cleanup.cleanup_stale_claude_processes()
            resume_process_cleanup.cleanup_resume_temp_dirs()
            resume_recovery.recover_or_block_stale_execution(
                state,
                lock_context=self._resume_lock_context,
                cleanup_result=cleanup_result,
            )
            current_state = self._derive_state()
        else:
            if _has_existing_run(state):
                logger.error(
                    "[ERROR] Existing harness state found in workspace/state.json. "
                    "Use `python harness/harness.py --resume` to continue, or clear "
                    "workspace/state.json before starting a fresh run."
                )
                sys.exit(1)
            if not args.spec_file_or_dir:
                args.spec_file_or_dir = get_default_spec_path(self.config)
            if not args.spec_file_or_dir:
                logger.error("[ERROR] spec_file_or_dir is required on first run.")
                sys.exit(1)
            if args.language is None:
                args.language = get_default_language(self.config)
            if args.app_type is None:
                args.app_type = get_default_app_type(self.config)
            self._default_language = args.language
            state["spec_file"] = args.spec_file_or_dir
            state["language"] = args.language
            state["app_type"] = args.app_type
            save_state(state)
            _git_startup(state)
            self.phases, self.context = parse_spec(
                args.spec_file_or_dir, state, write_phases=True
            )
            validate_spec(self.phases)
            for p in self.phases:
                lang = self._phase_profile_language(p, state["app_type"])
                self.profiles[p["id"]] = apply_profile_overrides(
                    get_profile(lang), self.config
                )
            for sp in state["phases"]:
                if sp.get("language") is None and sp.get("phase_type") not in (
                    "integration",
                    "e2e",
                ):
                    sp["language"] = self._default_language
            config_path = Path(__file__).parent / "spec_validation.json"
            missing = check_spec_completeness(
                args.spec_file_or_dir, state["app_type"], config_path
            )
            if missing:
                print(
                    f"[ERROR] Spec missing required sections for a '{state['app_type']}' app:"
                )
                for label in missing:
                    print(f"  - {label}")
                print(
                    f"\nFix these in: {args.spec_file_or_dir}\nThen re-run the harness."
                )
                sys.exit(1)
            state["current_phase"] = 1
            save_state(state)
            current_state = HarnessState.TASK_BUILD

        while current_state not in (HarnessState.COMPLETE, HarnessState.HALTED):
            phase_id = state.get("current_phase", 1)
            if not isinstance(current_state, HarnessState):
                raise RuntimeError(f"Unhandled harness state: {current_state!r}")
            emit_event("state_transition", state=current_state.name, phase_id=phase_id)

            if args.max_phase and phase_id > args.max_phase:
                logger.info(
                    "[HARNESS] Reached --max-phase %d. Stopping.", args.max_phase
                )
                sys.exit(0)

            profile = self.profile_for(phase_id)
            if current_state == HarnessState.TASK_BUILD:
                current_state = phase_handlers.handle_task_build(
                    self, state, phase_id, profile
                )
            elif current_state == HarnessState.EXECUTING:
                current_state = phase_handlers.handle_executing(
                    self, state, phase_id, profile
                )
            elif current_state == HarnessState.REVIEWING:
                current_state = phase_handlers.handle_reviewing(
                    self, state, phase_id, profile
                )
            elif current_state == HarnessState.FIXING:
                current_state = phase_handlers.handle_fixing(self, state, phase_id)
            elif current_state == HarnessState.REGRESSION_TESTING:
                current_state = phase_handlers.handle_regression_testing(
                    self, state, phase_id
                )
            elif current_state == HarnessState.NEXT_PHASE:
                current_state = phase_handlers.handle_next_phase(self, state, phase_id)
            elif current_state == HarnessState.CLEANUP:
                run_cleanup(self, state)
                current_state = HarnessState.EVALUATING
            elif current_state == HarnessState.EVALUATING:
                run_evaluate_cycle(self, state)
                current_state = HarnessState.COMPLETE

    def _derive_state(self) -> HarnessState:
        state = self.state

        # Check evaluate block BEFORE the phases loop so that a fully-built project
        # with evaluate in progress does not restart from TASK_BUILD.
        evaluate = state.get("evaluate", {})
        ev_status = evaluate.get("status")

        if ev_status == "complete":
            return HarnessState.COMPLETE

        if ev_status == "halted":
            logger.error(
                "[RESUME] Evaluate is halted. Fix the issues manually, "
                "set state['evaluate']['status'] = 'evaluating', then --resume."
            )
            sys.exit(1)

        preflight = external_dependency.preflight_context(allow_quarantine=False)
        if not preflight.get("ok"):
            logger.error(
                "[RESUME] External dependency preflight failed: %s",
                preflight,
            )
            sys.exit(1)

        if ev_status in (
            "evaluating",
            "test_authoring",
            "red_verifying",
            "fixing",
            "targeted_verifying",
            "regression_verifying",
            "blocked_external_dependency",
            "timeout",
            "error",
        ):
            return HarnessState.EVALUATING

        _reset_happened = False
        if reconcile_committed_tasks(state):
            _reset_happened = True
        if reset_interrupted_tasks(state):
            _reset_happened = True
        for phase in state.get("phases", []):
            for task in phase.get("tasks", []):
                if task["status"] == "halted":
                    logger.error(
                        "[RESUME] Task %s is halted after %d attempts: %s\n"
                        "Increase max_attempts or fix manually, "
                        "set status → 'pending' in state.json, then --resume.",
                        task["id"],
                        task.get("attempts", 0),
                        task.get("last_error", []),
                    )
                    sys.exit(1)
                if task["status"] == "error":
                    logger.warning(
                        "[RESUME] Auto-resetting task %s from 'error' → 'pending' (last error: %s)",
                        task["id"],
                        (task.get("last_error") or ["(none)"])[-1],
                    )
                    task["status"] = "pending"
                    _reset_happened = True
            for issue in phase.get("review", {}).get("issues", []):
                if issue["status"] == "halted":
                    logger.error(
                        "[RESUME] Issue %s is halted after %d attempts: %s\n"
                        "Fix manually, set status → 'open' in state.json, then --resume.",
                        issue["id"],
                        issue.get("attempts", 0),
                        issue.get("last_error", []),
                    )
                    sys.exit(1)
                if issue["status"] == "error":
                    logger.warning(
                        "[RESUME] Auto-resetting issue %s from 'error' → 'open' (last error: %s)",
                        issue["id"],
                        (issue.get("last_error") or ["(none)"])[-1],
                    )
                    issue["status"] = "open"
                    _reset_happened = True
        if _reset_happened:
            save_state(state)

        for phase in state.get("phases", []):
            pid = phase["id"]

            if phase["status"] in ("error", "blocked_external_dependency"):
                state["current_phase"] = pid
                self._load_spec_into_memory()
                return HarnessState.TASK_BUILD

            if phase["status"] == "building":
                review = phase.get("review", {})
                tasks = phase.get("tasks", [])
                if not tasks and review.get("status") in (None, "pending", "error"):
                    state["current_phase"] = pid
                    save_state(state)
                    self._load_spec_into_memory()
                    return HarnessState.TASK_BUILD
                if tasks and all(t.get("status") == "complete" for t in tasks):
                    if review.get("status") in ("pending", "error"):
                        state["current_phase"] = pid
                        save_state(state)
                        return HarnessState.REVIEWING
                    if review.get("status") == "blocked_external_dependency":
                        state["current_phase"] = pid
                        save_state(state)
                        if review.get("blocked_mode") == "FIX":
                            return HarnessState.FIXING
                        return HarnessState.REVIEWING
                if review.get("status") == "fixing":
                    state["current_phase"] = pid
                    save_state(state)
                    return HarnessState.FIXING
                if review.get("status") == "complete" and review.get("verdict") in (
                    "APPROVE",
                    "WARN",
                ):
                    state["current_phase"] = pid
                    save_state(state)
                    if phase.get("regression", {}).get("status") == "passed":
                        return HarnessState.NEXT_PHASE
                    return HarnessState.REGRESSION_TESTING
                if review.get("status") == "fixed":
                    state["current_phase"] = pid
                    save_state(state)
                    if phase.get("regression", {}).get("status") == "passed":
                        return HarnessState.NEXT_PHASE
                    return HarnessState.REGRESSION_TESTING
                if (
                    review.get("status") == "complete"
                    and review.get("verdict") == "BLOCK"
                ):
                    state["current_phase"] = pid
                    save_state(state)
                    return HarnessState.FIXING
                for task in phase.get("tasks", []):
                    if task["status"] == "building":
                        task["status"] = "pending"
                save_state(state)
                state["current_phase"] = pid
                return HarnessState.EXECUTING

            if phase["status"] == "complete":
                continue

            if phase["status"] == "pending":
                state["current_phase"] = pid
                self._load_spec_into_memory()
                return HarnessState.TASK_BUILD

        if state.get("cleanup", {}).get("status") in (
            "blocked_external_dependency",
            "error",
            "halted",
        ):
            return HarnessState.CLEANUP

        return HarnessState.CLEANUP

    def profile_for(self, phase_id: int) -> dict:
        return self.profiles.get(phase_id) or apply_profile_overrides(
            get_profile(self._default_language), self.config
        )

    def _phase_profile_language(self, phase: dict, app_type: str) -> str:
        if (
            app_type == "game"
            and phase.get("phase_type") in ("integration", "e2e")
            and not phase.get("language")
        ):
            return "typescript"
        return phase.get("language") or self._default_language

    def verification_profiles_for(self, phase_id: int) -> list[dict]:
        primary = self.profile_for(phase_id)
        if self.state.get("app_type") != "game" or self.phase_type_for(
            phase_id
        ) not in (
            "integration",
            "e2e",
        ):
            return [primary]
        profiles = [primary]
        for name in ("python", "typescript"):
            profile = apply_profile_overrides(get_profile(name), self.config)
            if profile["name"] not in {p["name"] for p in profiles}:
                profiles.append(profile)
        return profiles

    def phase_type_for(self, phase_id: int) -> str:
        return (find_phase(self.state, phase_id) or {}).get("phase_type", "development")

    def _load_spec_into_memory(self) -> None:
        spec_file = self.state.get("spec_file", "")
        self.phases, self.context = parse_spec(
            spec_file, self.state, write_phases=False
        )

    def _get_phase_data(self, phase_id: int) -> dict:
        return next((p for p in self.phases if p["id"] == phase_id), {})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    harness = Harness(args)
    harness.run()
