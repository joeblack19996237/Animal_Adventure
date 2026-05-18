from __future__ import annotations

import ctypes
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOCK_PATH = Path("workspace/run.lock")
PID_PATH = Path("workspace/harness.pid")


class RunLockError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED means the process exists but we lack permission to
        # open it (e.g. it runs at a higher privilege level).  A dead PID returns
        # ERROR_INVALID_PARAMETER instead.  Treat access-denied conservatively as
        # alive to avoid false stale-lock detection across privilege boundaries.
        if kernel32.GetLastError() == error_access_denied:
            return True
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def read_lock() -> dict[str, Any] | None:
    if not LOCK_PATH.exists():
        return None
    try:
        return json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"pid": None, "corrupt": True}


def clear_stale_lock() -> bool:
    lock = read_lock()
    if not lock:
        return False
    pid = int(lock.get("pid") or 0)
    if _pid_alive(pid):
        stored_token = lock.get("lock_token")
        if stored_token:
            try:
                pid_token = PID_PATH.read_text(encoding="utf-8").strip()
                if stored_token == pid_token:
                    return False  # same process — genuinely alive
                # token mismatch: PID reused; fall through to clear
            except FileNotFoundError:
                return False  # harness.pid missing — be conservative
        else:
            return False  # old-format lock without token — trust PID only
    LOCK_PATH.unlink(missing_ok=True)
    PID_PATH.unlink(missing_ok=True)
    return True


def _write_lock_atomic(entry: dict[str, Any]) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = None
    try:
        fd = os.open(LOCK_PATH, flags)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            f.write(json.dumps(entry, indent=2))
    except FileExistsError:
        raise
    except Exception:
        if fd is not None:
            os.close(fd)
        LOCK_PATH.unlink(missing_ok=True)
        raise


def acquire_lock(
    *,
    spec_file: str = "",
    app_type: str = "",
    current_phase: int | None = None,
) -> dict[str, Any]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_token = secrets.token_hex(16)
    entry = {
        "pid": os.getpid(),
        "lock_token": lock_token,
        "cwd": str(Path(".").resolve()),
        "spec_file": spec_file,
        "app_type": app_type,
        "current_phase": current_phase,
        "started_at": _now(),
    }
    acquired = False
    for attempt in range(2):
        lock = read_lock()
        if lock:
            pid = int(lock.get("pid") or 0)
            if _pid_alive(pid):
                raise RunLockError(f"harness run already active with pid {pid}")
            clear_stale_lock()
        try:
            _write_lock_atomic(entry)
            acquired = True
            break
        except FileExistsError:
            if attempt == 1:
                lock = read_lock()
                pid = int((lock or {}).get("pid") or 0)
                if lock and _pid_alive(pid):
                    raise RunLockError(f"harness run already active with pid {pid}")
                raise RunLockError(
                    "could not acquire harness lock after concurrent race"
                )
    if not acquired:
        raise RunLockError("could not acquire harness lock")
    try:
        PID_PATH.write_text(lock_token, encoding="utf-8")
    except Exception:
        release_lock()
        raise
    return entry


def release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)
    PID_PATH.unlink(missing_ok=True)


def lock_status() -> dict[str, Any]:
    lock = read_lock()
    if not lock:
        return {"active": False}
    pid = int(lock.get("pid") or 0)
    return {**lock, "active": _pid_alive(pid)}
