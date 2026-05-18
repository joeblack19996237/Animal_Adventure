from __future__ import annotations

import shutil
from pathlib import Path

from events import emit_event
from subprocess_runner import (
    cleanup_process_tree,
    current_process_ancestor_pids,
    is_claude_cli_process,
    is_claude_desktop_process,
    list_named_processes,
)

RESUME_TEMP_PATTERNS = ["pytest-*", "verification-tmp"]


def cleanup_resume_temp_dirs() -> dict:
    workspace = Path("workspace")
    removed: list[str] = []
    errors: list[dict] = []

    emit_event("resume_temp_cleanup_start", patterns=RESUME_TEMP_PATTERNS)

    for pattern in RESUME_TEMP_PATTERNS:
        for path in workspace.glob(pattern):
            if not path.is_dir():
                continue
            try:
                shutil.rmtree(path, ignore_errors=False)
                removed.append(str(path))
            except Exception as e:
                errors.append({"path": str(path), "error": str(e)})

    emit_event("resume_temp_cleanup_end", removed=removed, errors=errors)
    return {"removed": removed, "errors": errors}


def cleanup_stale_claude_processes() -> dict:
    processes = list_named_processes(["claude"])
    ancestor_pids = set(current_process_ancestor_pids())
    protection_incomplete = not ancestor_pids
    result = {
        "attempted": True,
        "protection_incomplete": protection_incomplete,
        "protected_pids": sorted(ancestor_pids),
        "killed_pids": [],
        "skipped_pids": [],
        "candidate_pids": [],
        "errors": [],
        "unsafe_to_resume": False,
        "unsafe_to_resume_reason": "",
    }

    emit_event(
        "resume_claude_cleanup_start",
        process_count=len(processes),
        protected_pids=result["protected_pids"],
        protection_incomplete=protection_incomplete,
    )

    for process in processes:
        pid = _process_pid(process)
        if not pid:
            continue
        if pid in ancestor_pids:
            _skip(result, pid, "protected_current_session")
            continue
        if is_claude_desktop_process(process):
            _skip(result, pid, "claude_desktop")
            continue
        if not is_claude_cli_process(process):
            _skip(result, pid, "unknown_or_non_cli")
            continue

        result["candidate_pids"].append(pid)
        if protection_incomplete:
            _skip(result, pid, "protection_incomplete")
            continue

        cleanup = cleanup_process_tree(pid, include_root=True)
        if cleanup.ok:
            result["killed_pids"].extend(cleanup.terminated_pids or [pid])
        else:
            result["errors"].append(
                {
                    "pid": pid,
                    "error": cleanup.error or "process cleanup failed",
                }
            )

    result["killed_pids"] = sorted(set(result["killed_pids"]))
    result["skipped_pids"] = sorted(set(result["skipped_pids"]))
    result["candidate_pids"] = sorted(set(result["candidate_pids"]))
    _mark_resume_safety(result)
    emit_event(
        "resume_claude_cleanup_end",
        attempted=result["attempted"],
        protection_incomplete=result["protection_incomplete"],
        protected_pids=result["protected_pids"],
        candidate_pids=result["candidate_pids"],
        killed_pids=result["killed_pids"],
        skipped_pids=result["skipped_pids"],
        errors=result["errors"],
        unsafe_to_resume=result["unsafe_to_resume"],
        unsafe_to_resume_reason=result["unsafe_to_resume_reason"],
    )
    return result


def _skip(result: dict, pid: int, reason: str) -> None:
    result["skipped_pids"].append(pid)
    emit_event("resume_claude_cleanup_skip", pid=pid, reason=reason)


def _process_pid(process: dict) -> int | None:
    try:
        pid = int(process.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    return pid or None


def _mark_resume_safety(result: dict) -> None:
    if result["errors"]:
        result["unsafe_to_resume"] = True
        result["unsafe_to_resume_reason"] = "Claude cleanup reported errors"
        return
    remaining_candidates = [
        pid for pid in result["candidate_pids"] if pid not in result["killed_pids"]
    ]
    if result["protection_incomplete"] and remaining_candidates:
        result["unsafe_to_resume"] = True
        result["unsafe_to_resume_reason"] = (
            "Claude process protection was incomplete and CLI candidates remain"
        )
