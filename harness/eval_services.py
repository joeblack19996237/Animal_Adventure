from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from subprocess_runner import cleanup_process_tree, resolve_missing_executable

REGISTRY_PATH = Path("workspace/eval_services.json")


def register_pid(name: str, pid: int) -> None:
    REGISTRY_PATH.parent.mkdir(exist_ok=True)
    entries = _read_registry()
    entries = [entry for entry in entries if entry.get("pid") != pid]
    entries.append({"name": name, "pid": int(pid)})
    REGISTRY_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def start_service(name: str, cmd: list[str]) -> int:
    existing = _running_entry(name)
    if existing:
        print(f"{name} already running with pid {existing['pid']}")
        return 0
    resolved = resolve_missing_executable(cmd)
    popen_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(resolved, **popen_kwargs)
    except FileNotFoundError:
        print(f"{resolved[0]} is not available", file=sys.stderr)
        return 1
    register_pid(name, proc.pid)
    print(f"{name} started with pid {proc.pid}")
    return 0


def check_nginx() -> int:
    cmd = resolve_missing_executable(["nginx", "-t"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("nginx is not available", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print((result.stderr or result.stdout).strip(), file=sys.stderr)
    return result.returncode


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_pid_running_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_registered() -> None:
    entries = _read_registry()
    for entry in entries:
        pid = int(entry.get("pid", 0) or 0)
        if not is_pid_running(pid):
            continue
        cleanup_process_tree(pid, include_root=True)
    if REGISTRY_PATH.exists():
        REGISTRY_PATH.unlink()


def _running_entry(name: str) -> dict | None:
    for entry in _read_registry():
        if entry.get("name") == name and is_pid_running(int(entry.get("pid", 0) or 0)):
            return entry
    return None


def _read_registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _is_pid_running_windows(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = wintypes.DWORD()
    try:
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: python harness/eval_services.py "
            "cleanup|start-api|start-vite|check-nginx",
            file=sys.stderr,
        )
        sys.exit(2)
    command = sys.argv[1]
    if command == "cleanup":
        stop_registered()
    elif command == "start-api":
        sys.exit(
            start_service(
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
            )
        )
    elif command == "start-vite":
        sys.exit(
            start_service(
                "vite",
                ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
            )
        )
    elif command == "check-nginx":
        sys.exit(check_nginx())
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(2)
