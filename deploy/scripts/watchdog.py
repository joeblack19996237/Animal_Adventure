from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from typing import Any

_DEFAULT_CMD: list[str] = [
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
]


def find_uvicorn_pid(
    process_iter: Callable[[list[str]], Any] | None = None,
) -> int | None:
    """Return the PID of a running uvicorn process, or None if not found.

    When *process_iter* is provided (e.g. in tests) it is called with a list
    of attribute names and must yield objects with a ``pid`` int attribute and
    an ``info`` dict containing ``"cmdline"``.  When it is None the real psutil
    iterator is used.
    """
    if process_iter is not None:
        for proc in process_iter(["name", "cmdline"]):
            cmdline: list[str] = proc.info.get("cmdline") or []
            if any("uvicorn" in part for part in cmdline):
                return proc.pid
        return None

    try:
        import psutil
    except ImportError:
        return None

    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if any("uvicorn" in part for part in cmdline):
                return proc.pid
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None


def start_uvicorn(cmd: list[str]) -> subprocess.Popen[bytes]:
    """Launch uvicorn with *cmd* and return the Popen handle."""
    return subprocess.Popen(cmd)


def run_watchdog(
    cmd: list[str] | None = None,
    find_pid_fn: Callable[[], int | None] | None = None,
    start_fn: Callable[[list[str]], Any] | None = None,
) -> bool:
    """Check whether uvicorn is running and start it if missing.

    Returns True if uvicorn was started, False if it was already running.
    Both *find_pid_fn* and *start_fn* are injectable for testing.
    """
    _cmd = cmd if cmd is not None else _DEFAULT_CMD
    _find = find_pid_fn if find_pid_fn is not None else find_uvicorn_pid
    _start = start_fn if start_fn is not None else start_uvicorn

    if _find() is not None:
        return False
    _start(_cmd)
    return True


if __name__ == "__main__":
    started = run_watchdog()
    if started:
        sys.stdout.write("uvicorn started\n")
    else:
        sys.stdout.write("uvicorn already running — no action taken\n")
    sys.exit(0)
