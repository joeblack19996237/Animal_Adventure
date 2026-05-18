from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from git_changes import (
    capture_status_snapshot,
    new_untracked_files_since,
    tracked_dirty_files_since,
)
from subprocess_runner import (
    ProcessCleanupResult,
    cleanup_process_tree,
    list_named_processes,
    process_exists,
)

CONTEXT_PATH = Path("workspace/external_dependency_context.json")
QUARANTINE_ROOT = Path("workspace/external_dependency_artifacts")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retry_at(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def load_context() -> dict | None:
    if not CONTEXT_PATH.exists():
        return None
    try:
        return json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"corrupt": True}


def save_context(context: dict) -> None:
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_PATH.write_text(json.dumps(context, indent=2), encoding="utf-8")


def clear_context() -> None:
    CONTEXT_PATH.unlink(missing_ok=True)


def start_context(
    *,
    mode: str,
    root_pid: int | None,
    pre_git_snapshot: dict[str, str],
    retry_delay: float,
) -> dict:
    context = {
        "mode": mode,
        "root_pid": root_pid,
        "started_at": _now_iso(),
        "reset_at": _retry_at(retry_delay),
        "pre_git_snapshot": pre_git_snapshot,
        "cleanup_status": "started",
    }
    save_context(context)
    return context


def cleanup_before_wait(context: dict) -> dict:
    claude_before = _claude_process_snapshot()
    cleanup = _cleanup_context_process(context.get("root_pid"))
    claude_after = _claude_process_snapshot()
    untracked = new_untracked_files_since(
        context.get("pre_git_snapshot", {}), ignore_control_plane=True
    )
    quarantined, quarantine_errors = quarantine_paths(untracked)
    tracked_dirty = tracked_dirty_files_since(
        context.get("pre_git_snapshot", {}), ignore_control_plane=True
    )
    clean_snapshot = capture_status_snapshot()

    context.update(
        {
            "process_cleanup": cleanup.to_dict(),
            "claude_processes_before_cleanup": claude_before,
            "claude_processes_after_cleanup": claude_after,
            "possible_orphan_processes": _possible_orphan_processes(
                claude_after, context.get("root_pid"), cleanup
            ),
            "quarantined_files": quarantined,
            "quarantine_errors": quarantine_errors,
            "tracked_dirty_files": tracked_dirty,
            "clean_snapshot_after_cleanup": clean_snapshot,
            "cleanup_status": "clean"
            if cleanup.ok and not quarantine_errors and not tracked_dirty
            else "failed",
            "updated_at": _now_iso(),
        }
    )
    save_context(context)
    return context


def preflight_context(*, allow_quarantine: bool) -> dict:
    context = load_context()
    if not context:
        return {"ok": True, "context_present": False}
    if context.get("corrupt"):
        return {"ok": False, "reason": "external dependency context is corrupt"}

    cleanup = _cleanup_context_process(context.get("root_pid"))
    claude_after = _claude_process_snapshot()
    baseline = (
        context.get("clean_snapshot_after_cleanup")
        if context.get("cleanup_status") == "clean"
        else context.get("pre_git_snapshot", {})
    )
    baseline = baseline or {}
    untracked = new_untracked_files_since(baseline, ignore_control_plane=True)
    quarantined: list[str] = []
    quarantine_errors: list[str] = []
    if allow_quarantine and untracked:
        quarantined, quarantine_errors = quarantine_paths(untracked)
        untracked = new_untracked_files_since(baseline, ignore_control_plane=True)
    tracked_dirty = tracked_dirty_files_since(baseline, ignore_control_plane=True)

    ok = cleanup.ok and not quarantine_errors and not tracked_dirty and not untracked
    result = {
        "ok": ok,
        "context_present": True,
        "process_cleanup": cleanup.to_dict(),
        "claude_processes_after_cleanup": claude_after,
        "possible_orphan_processes": _possible_orphan_processes(
            claude_after, context.get("root_pid"), cleanup
        ),
        "quarantined_files": quarantined,
        "quarantine_errors": quarantine_errors,
        "untracked_files": untracked,
        "tracked_dirty_files": tracked_dirty,
    }
    if ok:
        clear_context()
    else:
        context.update(
            {
                "cleanup_status": "failed",
                "preflight": result,
                "claude_processes_after_cleanup": claude_after,
                "possible_orphan_processes": result["possible_orphan_processes"],
                "updated_at": _now_iso(),
            }
        )
        save_context(context)
    return result


def _claude_process_snapshot() -> list[dict]:
    return list_named_processes(["claude"])


def _cleanup_context_process(root_pid: int | None) -> ProcessCleanupResult:
    if root_pid and process_exists(root_pid) is False:
        return ProcessCleanupResult(
            True,
            True,
            int(root_pid),
            [],
            f"root pid {root_pid} no longer active",
        )
    return cleanup_process_tree(root_pid)


def _possible_orphan_processes(
    processes: list[dict], root_pid: int | None, cleanup: ProcessCleanupResult
) -> list[dict]:
    known = set(cleanup.terminated_pids)
    if root_pid:
        known.add(int(root_pid))
    return [proc for proc in processes if int(proc.get("pid") or 0) not in known]


def quarantine_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    if not paths:
        return [], []
    root = Path(".").resolve()
    dest_root = QUARANTINE_ROOT / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    quarantined: list[str] = []
    errors: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").strip("/")
        try:
            src = (root / normalized).resolve()
            if not src.is_relative_to(root) or not src.exists():
                continue
            dest = dest_root / normalized
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            quarantined.append(normalized)
        except Exception as exc:  # pragma: no cover - exact OS errors vary
            errors.append(f"{normalized}: {exc}")
    return quarantined, errors
