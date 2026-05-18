from __future__ import annotations

import os
import signal as _signal
import subprocess
import time
import json
from dataclasses import dataclass
from pathlib import Path
import shutil

from events import emit_event


@dataclass
class ProcessResult:
    stdout: str
    stderr: str
    returncode: int
    elapsed: float
    timed_out: bool = False
    attempts: int = 1
    pid: int | None = None


@dataclass
class ProcessCleanupResult:
    attempted: bool
    ok: bool
    root_pid: int | None
    terminated_pids: list[int]
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "ok": self.ok,
            "root_pid": self.root_pid,
            "terminated_pids": self.terminated_pids,
            "error": self.error,
        }


class RunnerTimeout(RuntimeError):
    pass


class ProcessEnumerationError(RuntimeError):
    pass


def resolve_missing_executable(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    exe = cmd[0]
    candidates = [exe]
    if os.name == "nt" and not Path(exe).suffix:
        candidates.extend([f"{exe}.cmd", f"{exe}.exe", f"{exe}.bat"])
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return [resolved, *cmd[1:]]
    return cmd


def run_command(
    cmd: list[str], **kwargs
) -> tuple[list[str], subprocess.CompletedProcess]:
    timeout = kwargs.pop("timeout", None)
    if timeout is not None:
        return _run_command_with_timeout(cmd, timeout, **kwargs)
    try:
        return cmd, subprocess.run(cmd, **kwargs)
    except FileNotFoundError:
        resolved = resolve_missing_executable(cmd)
        if resolved == cmd:
            raise
        return resolved, subprocess.run(resolved, **kwargs)


def _kill_process_tree(proc: subprocess.Popen) -> ProcessCleanupResult:
    return cleanup_process_tree(proc.pid, include_root=True)


def cleanup_process_tree(
    pid: int | None, *, include_root: bool = False
) -> ProcessCleanupResult:
    if not pid:
        return ProcessCleanupResult(False, True, None, [])
    if os.name == "nt":
        return _cleanup_windows_process_tree(pid, include_root=include_root)
    return _cleanup_posix_process_tree(pid, include_root=include_root)


def process_exists(pid: int | None) -> bool | None:
    if not pid:
        return False
    if os.name == "nt":
        return _windows_process_exists(pid)
    return _posix_process_exists(pid)


def process_parent_pid(pid: int | None) -> int | None:
    if not pid:
        return None
    if os.name == "nt":
        return _windows_process_parent_pid(pid)
    return _posix_process_parent_pid(pid)


def current_process_ancestor_pids(pid: int | None = None, *, max_depth: int = 50) -> list[int]:
    current = int(pid or os.getpid())
    ancestors: list[int] = []
    seen = {current}
    for _ in range(max_depth):
        parent = process_parent_pid(current)
        if not parent or parent in seen:
            break
        ancestors.append(parent)
        seen.add(parent)
        current = parent
    return ancestors


def is_claude_desktop_process(process: dict) -> bool:
    path = _normalized_process_path(process)
    return "windowsapps/claude_" in path and path.endswith("/app/claude.exe")


def is_claude_cli_process(process: dict) -> bool:
    path = _normalized_process_path(process)
    if not path or is_claude_desktop_process(process):
        return False
    return (
        path.endswith("/.local/bin/claude.exe")
        or "/appdata/roaming/claude/claude-code/" in path
        or path.endswith("/bin/claude")
    )


def _normalized_process_path(process: dict) -> str:
    return str(process.get("path") or "").replace("\\", "/").lower()


def _windows_process_exists(pid: int) -> bool | None:
    script = (
        f"$process = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        "if ($process) { exit 0 } else { exit 3 }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result is None:
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 3:
        return False
    return None


def _windows_process_parent_pid(pid: int) -> int | None:
    script = (
        "$parent = $null; "
        f"try {{ $p = Get-CimInstance Win32_Process -Filter \"ProcessId = {int(pid)}\"; "
        "if ($p) { $parent = $p.ParentProcessId } }} catch { $parent = $null }; "
        "if ($null -eq $parent) { exit 3 }; "
        "Write-Output $parent"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result is None or result.returncode != 0:
        return None
    try:
        parent = int((result.stdout or "").strip())
    except ValueError:
        return None
    return parent or None


def _posix_process_exists(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _posix_process_parent_pid(pid: int) -> int | None:
    result = subprocess.run(
        ["ps", "-o", "ppid=", "-p", str(int(pid))],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        parent = int((result.stdout or "").strip())
    except ValueError:
        return None
    return parent or None


def _cleanup_windows_process_tree(
    pid: int, *, include_root: bool
) -> ProcessCleanupResult:
    enumeration_error = ""
    try:
        descendants = list(dict.fromkeys(list_descendant_pids(pid)))
    except ProcessEnumerationError as exc:
        if not include_root:
            return ProcessCleanupResult(True, False, pid, [], str(exc))
        descendants = []
        enumeration_error = str(exc)
    targets = [pid] if include_root else descendants
    if not targets:
        return ProcessCleanupResult(True, True, pid, [])
    terminated: list[int] = []
    errors: list[str] = [enumeration_error] if enumeration_error else []
    for target in targets:
        result = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(target)],
            capture_output=True,
            text=True,
        )
        if result is None or result.returncode == 0:
            if include_root and target == pid:
                terminated.extend([pid, *descendants])
            else:
                terminated.append(target)
        else:
            fallback_error = _terminate_windows_pid(target)
            if fallback_error:
                errors.append(
                    "; ".join(
                        p
                        for p in [
                            (result.stderr or result.stdout or "").strip(),
                            fallback_error,
                        ]
                        if p
                    )
                )
            else:
                terminated.append(target)
    return ProcessCleanupResult(True, not errors, pid, terminated, "; ".join(errors))


def _terminate_windows_pid(pid: int) -> str:
    try:
        import ctypes
    except ImportError:
        return "ctypes unavailable for TerminateProcess fallback"

    process_terminate = 0x0001
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_terminate, False, pid)
    if not handle:
        return f"TerminateProcess fallback could not open pid {pid}"
    try:
        if kernel32.TerminateProcess(handle, 1):
            return ""
        return f"TerminateProcess fallback failed for pid {pid}"
    finally:
        kernel32.CloseHandle(handle)


def _cleanup_posix_process_tree(
    pid: int, *, include_root: bool
) -> ProcessCleanupResult:
    descendants = list_descendant_pids(pid)
    if not include_root:
        terminated: list[int] = []
        errors: list[str] = []
        for target in reversed(descendants):
            try:
                os.kill(target, _signal.SIGKILL)
                terminated.append(target)
            except ProcessLookupError:
                terminated.append(target)
            except OSError as exc:
                errors.append(str(exc))
        return ProcessCleanupResult(
            True, not errors, pid, terminated, "; ".join(errors)
        )
    try:
        os.killpg(pid, _signal.SIGKILL)
        return ProcessCleanupResult(True, True, pid, [pid, *descendants])
    except ProcessLookupError:
        return ProcessCleanupResult(True, True, pid, [pid, *descendants])
    except OSError as exc:
        return ProcessCleanupResult(True, False, pid, [pid, *descendants], str(exc))


def list_descendant_pids(pid: int | None) -> list[int]:
    if not pid:
        return []
    if os.name == "nt":
        return _windows_descendant_pids(pid)
    return _posix_descendant_pids(pid)


def list_named_processes(names: list[str]) -> list[dict]:
    wanted = {name.lower() for name in names if name}
    if not wanted:
        return []
    if os.name == "nt":
        return _windows_named_processes(wanted)
    return _posix_named_processes(wanted)


def _windows_named_processes(wanted: set[str]) -> list[dict]:
    quoted = ",".join(repr(name) for name in sorted(wanted))
    script = (
        f"$names = @({quoted}); "
        "Get-Process | Where-Object { $names -contains $_.ProcessName.ToLowerInvariant() } | "
        "ForEach-Object { "
        "$path = ''; try { $path = $_.Path } catch { $path = '' }; "
        "$start = ''; try { $start = $_.StartTime.ToUniversalTime().ToString('o') } catch { $start = '' }; "
        "$parent = $null; "
        "try { $wmi = Get-CimInstance Win32_Process -Filter \"ProcessId = $($_.Id)\"; "
        "if ($wmi) { $parent = $wmi.ParentProcessId } } catch { $parent = $null }; "
        "[pscustomobject]@{ Id = $_.Id; ProcessName = $_.ProcessName; Path = $path; StartTime = $start; ParentProcessId = $parent } "
        "} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result is None or result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    processes = []
    for row in rows:
        try:
            pid = int(row.get("Id") or 0)
        except (TypeError, ValueError):
            continue
        if not pid:
            continue
        processes.append(
            {
                "pid": pid,
                "name": row.get("ProcessName") or "",
                "path": row.get("Path") or "",
                "start_time": row.get("StartTime") or "",
                "parent_pid": _coerce_optional_int(row.get("ParentProcessId")),
            }
        )
    return processes


def _posix_named_processes(wanted: set[str]) -> list[dict]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,comm="],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    processes = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        name = Path(parts[1]).name
        if name.lower() in wanted:
            processes.append(
                {
                    "pid": pid,
                    "name": name,
                    "path": "",
                    "start_time": "",
                    "parent_pid": process_parent_pid(pid),
                }
            )
    return processes


def _coerce_optional_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed or None


def _windows_descendant_pids(pid: int) -> list[int]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result is None:
        raise ProcessEnumerationError("Windows process enumeration did not run")
    detail = (result.stderr or result.stdout or "").strip()
    if result.returncode != 0:
        raise ProcessEnumerationError(
            f"Windows process enumeration failed: {detail[:500]}"
        )
    if not result.stdout.strip():
        raise ProcessEnumerationError(
            f"Windows process enumeration returned no output: {detail[:500]}"
        )

    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProcessEnumerationError(
            f"Windows process enumeration returned invalid JSON: {exc}"
        ) from exc
    if isinstance(rows, dict):
        rows = [rows]
    children: dict[int, list[int]] = {}
    for row in rows:
        ppid = int(row.get("ParentProcessId") or 0)
        child = int(row.get("ProcessId") or 0)
        children.setdefault(ppid, []).append(child)
    return _walk_descendants(pid, children)


def _posix_descendant_pids(pid: int) -> list[int]:
    result = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        child, ppid = int(parts[0]), int(parts[1])
        children.setdefault(ppid, []).append(child)
    return _walk_descendants(pid, children)


def _walk_descendants(pid: int, children: dict[int, list[int]]) -> list[int]:
    descendants: list[int] = []
    stack = list(children.get(pid, []))
    while stack:
        child = stack.pop()
        descendants.append(child)
        stack.extend(children.get(child, []))
    return descendants


def _run_command_with_timeout(
    cmd: list[str], timeout: int | float, **kwargs
) -> tuple[list[str], subprocess.CompletedProcess]:
    resolved = resolve_missing_executable(cmd)
    popen_kwargs = dict(kwargs)
    capture_output = popen_kwargs.pop("capture_output", False)
    if capture_output:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
    if os.name != "nt" and "start_new_session" not in popen_kwargs:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(resolved, **popen_kwargs)  # type: ignore[call-overload]
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return resolved, subprocess.CompletedProcess(
            resolved, proc.returncode, stdout=stdout, stderr=stderr
        )
    except subprocess.TimeoutExpired as exc:
        cleanup_process_tree(proc.pid, include_root=True)
        proc.wait()
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        timeout_msg = f"\ncommand timed out after {timeout}s"
        return resolved, subprocess.CompletedProcess(
            resolved, 124, stdout=stdout, stderr=f"{stderr}{timeout_msg}"
        )


def run_claude_process(
    cmd: list[str],
    input_text: str,
    mode: str,
    timeout: int,
    env: dict | None = None,
    cwd: str | None = None,
    call_id: str | None = None,
) -> ProcessResult:
    start = time.monotonic()
    kwargs: dict = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": env,
        "cwd": cwd,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)  # type: ignore[call-overload]
    emit_event(
        "claude_subprocess_start",
        mode=mode,
        call_id=call_id,
        timeout=timeout,
        cmd=cmd[:3],
        pid=proc.pid,
    )
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        cleanup = _kill_process_tree(proc)
        proc.wait()
        emit_event(
            "claude_subprocess_timeout",
            mode=mode,
            call_id=call_id,
            timeout=timeout,
            elapsed=elapsed,
            pid=proc.pid,
            stdout_tail=(exc.stdout or "")[-500:]
            if isinstance(exc.stdout, str)
            else "",
            stderr_tail=(exc.stderr or "")[-500:]
            if isinstance(exc.stderr, str)
            else "",
            process_cleanup_attempted=cleanup.attempted,
            process_cleanup_ok=cleanup.ok,
            process_cleanup_error=cleanup.error,
            processes_terminated=len(cleanup.terminated_pids),
        )
        raise RunnerTimeout(f"timeout after {timeout}s ({mode} mode)") from exc

    elapsed = time.monotonic() - start
    emit_event(
        "claude_subprocess_end",
        mode=mode,
        call_id=call_id,
        timeout=timeout,
        elapsed=elapsed,
        pid=proc.pid,
        returncode=proc.returncode,
        stdout_tail=stdout[-500:],
        stderr_tail=stderr[-500:],
    )
    return ProcessResult(
        stdout=stdout,
        stderr=stderr,
        returncode=proc.returncode,
        elapsed=elapsed,
        pid=proc.pid,
    )
