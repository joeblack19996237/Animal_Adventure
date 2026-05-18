import json
import subprocess
from pathlib import Path

import pytest

import subprocess_runner as runner


class _FakePopen:
    """Minimal Popen stand-in for success cases."""

    pid = 12345
    returncode = 0

    def __init__(self, stdout="", stderr=""):
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, input=None, timeout=None):
        return self._stdout, self._stderr

    def wait(self):
        pass


class _TimeoutPopen:
    """Popen stand-in that raises TimeoutExpired on communicate()."""

    pid = 12345

    def communicate(self, input=None, timeout=None):
        raise subprocess.TimeoutExpired(["claude"], timeout, output="out", stderr="err")

    def wait(self):
        pass


def test_runner_success_returns_stdout_metadata(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **kw: _FakePopen('{"ok": true}', "")
    )
    result = runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)
    assert result.stdout == '{"ok": true}'
    assert result.returncode == 0
    assert result.timed_out is False


def test_run_claude_process_emits_pid_on_start_and_end(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **kw: _FakePopen('{"ok": true}', "")
    )

    runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)

    events = [
        json.loads(line)
        for line in Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["event"] == "claude_subprocess_start"
    assert events[0]["pid"] == 12345
    assert events[1]["event"] == "claude_subprocess_end"
    assert events[1]["pid"] == 12345


def test_run_claude_process_events_include_call_id(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **kw: _FakePopen('{"ok": true}', "")
    )

    runner.run_claude_process(
        ["claude"], "prompt", "EXECUTE", 10, call_id="execute-test"
    )

    events = [
        json.loads(line)
        for line in Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["call_id"] == "execute-test"
    assert events[1]["call_id"] == "execute-test"


def test_run_claude_process_end_includes_stdout_and_stderr_tail(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **kw: _FakePopen("x" * 600, "y" * 600),
    )

    runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)

    event = json.loads(
        Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert event["stdout_tail"] == "x" * 500
    assert event["stderr_tail"] == "y" * 500


def test_runner_timeout_raises_and_records_timeout(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: _TimeoutPopen())
    # _kill_process_tree calls subprocess.run (taskkill on Windows / killpg on POSIX)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: None)
    with pytest.raises(runner.RunnerTimeout):
        runner.run_claude_process(["claude"], "prompt", "REVIEW", 1)


def test_run_claude_process_timeout_emits_pid_and_cleanup_result(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: _TimeoutPopen())
    monkeypatch.setattr(
        runner,
        "cleanup_process_tree",
        lambda pid, include_root=False: runner.ProcessCleanupResult(
            True, True, pid, [pid]
        ),
    )

    with pytest.raises(runner.RunnerTimeout):
        runner.run_claude_process(["claude"], "prompt", "REVIEW", 1)

    event = json.loads(
        Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert event["event"] == "claude_subprocess_timeout"
    assert event["pid"] == 12345
    assert event["process_cleanup_ok"] is True
    assert event["processes_terminated"] == 1


def test_runner_nonzero_return_is_reported(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)

    class _BadPopen(_FakePopen):
        returncode = 2

        def communicate(self, input=None, timeout=None):
            return "", "bad"

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: _BadPopen())
    result = runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)
    assert result.returncode == 2
    assert result.stderr == "bad"


def test_runner_does_not_swallow_stdout_stderr_tails(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **kw: _FakePopen("out", "err")
    )
    result = runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)
    assert result.stdout == "out"
    assert result.stderr == "err"


def test_runner_windows_uses_process_group_cleanup(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    captured = {}

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _FakePopen("{}", "")

    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(
        runner.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False
    )
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)
    assert captured["creationflags"] == 512


def test_runner_timeout_kills_process_tree_before_retry(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(
        runner.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False
    )
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: _TimeoutPopen())
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222])

    kill_calls = []

    def fake_run(cmd, **kw):
        kill_calls.append(cmd)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.RunnerTimeout):
        runner.run_claude_process(["claude"], "prompt", "EXECUTE", 1)

    assert any("/T" in cmd and "/F" in cmd and "/PID" in cmd for cmd in kill_calls)


def test_runner_posix_uses_start_new_session(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    captured = {}

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _FakePopen("{}", "")

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    runner.run_claude_process(["claude"], "prompt", "EXECUTE", 10)
    assert captured.get("start_new_session") is True
    assert "creationflags" not in captured


def test_runner_timeout_waits_for_process_after_kill(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    wait_calls = []

    class _TrackWaitPopen(_TimeoutPopen):
        def wait(self):
            wait_calls.append(True)

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: _TrackWaitPopen())
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: None)

    with pytest.raises(runner.RunnerTimeout):
        runner.run_claude_process(["claude"], "prompt", "EXECUTE", 1)

    assert wait_calls, "proc.wait() must be called after _kill_process_tree()"


def test_run_command_resolves_windows_shim_after_file_not_found(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "npx":
            raise FileNotFoundError("missing npx")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda exe: "C:/node/npx.cmd" if exe == "npx.cmd" else None,
    )
    monkeypatch.setattr(runner.os, "name", "nt")

    run_cmd, result = runner.run_command(["npx", "vitest", "run"], capture_output=True)

    assert run_cmd == ["C:/node/npx.cmd", "vitest", "run"]
    assert result.returncode == 0
    assert calls == [["npx", "vitest", "run"], ["C:/node/npx.cmd", "vitest", "run"]]


def test_cleanup_process_tree_noops_without_pid():
    result = runner.cleanup_process_tree(None)
    assert result.ok is True
    assert result.attempted is False


def test_process_exists_noops_without_pid():
    assert runner.process_exists(None) is False


def test_process_exists_windows_true_false_and_unknown(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")

    def fake_run(cmd, **kwargs):
        pid_script = cmd[-1]
        if "111" in pid_script:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "222" in pid_script:
            return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="denied")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.process_exists(111) is True
    assert runner.process_exists(222) is False
    assert runner.process_exists(333) is None


def test_process_exists_posix_true_false_permission_and_unknown(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")

    def fake_kill(pid, sig):
        if pid == 222:
            raise ProcessLookupError()
        if pid == 333:
            raise PermissionError()
        if pid == 444:
            raise OSError("unexpected")

    monkeypatch.setattr(runner.os, "kill", fake_kill)

    assert runner.process_exists(111) is True
    assert runner.process_exists(222) is False
    assert runner.process_exists(333) is True
    assert runner.process_exists(444) is None


def test_list_named_processes_windows_tolerates_access_denied_fields(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                [
                    {
                        "Id": 111,
                        "ProcessName": "claude",
                        "Path": None,
                        "StartTime": None,
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.list_named_processes(["claude"]) == [
        {
            "pid": 111,
            "name": "claude",
            "path": "",
            "start_time": "",
            "parent_pid": None,
        }
    ]


def test_list_named_processes_windows_includes_parent_pid(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "Id": 111,
                    "ProcessName": "claude",
                    "Path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2/claude.exe",
                    "StartTime": "2026-05-17T00:00:00Z",
                    "ParentProcessId": 222,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.list_named_processes(["claude"]) == [
        {
            "pid": 111,
            "name": "claude",
            "path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2/claude.exe",
            "start_time": "2026-05-17T00:00:00Z",
            "parent_pid": 222,
        }
    ]


def test_current_process_ancestor_pids_stops_on_missing_parent(monkeypatch):
    parents = {100: 90, 90: 80, 80: None}
    monkeypatch.setattr(runner, "process_parent_pid", lambda pid: parents[pid])

    assert runner.current_process_ancestor_pids(100) == [90, 80]


def test_is_claude_cli_process_matches_claude_code_paths():
    assert runner.is_claude_cli_process(
        {
            "path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2.1.138/claude.exe"
        }
    )
    assert runner.is_claude_cli_process(
        {"path": "C:/Users/OEM/.local/bin/claude.exe"}
    )


def test_is_claude_cli_process_excludes_windowsapps_claude_desktop():
    process = {
        "path": "C:/Program Files/WindowsApps/Claude_1.0.0.0_x64__id/app/Claude.exe"
    }

    assert runner.is_claude_desktop_process(process)
    assert not runner.is_claude_cli_process(process)


def test_cleanup_process_tree_reports_windows_failure(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222])

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="denied")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_terminate_windows_pid", lambda pid: "fallback denied")

    result = runner.cleanup_process_tree(111)

    assert result.ok is False
    assert result.terminated_pids == []
    assert "denied" in result.error
    assert "fallback denied" in result.error


def test_cleanup_process_tree_windows_falls_back_to_terminate_process(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222])

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="denied")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_terminate_windows_pid", lambda pid: "")

    result = runner.cleanup_process_tree(111)

    assert result.ok is True
    assert result.terminated_pids == [222]
    assert result.error == ""


def test_cleanup_process_tree_reports_windows_descendant_enumeration_failure(
    monkeypatch,
):
    monkeypatch.setattr(runner.os, "name", "nt")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Access denied")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.cleanup_process_tree(111)

    assert result.ok is False
    assert result.terminated_pids == []
    assert "Access denied" in result.error


def test_cleanup_process_tree_windows_include_root_taskkills_after_enumeration_failure(
    monkeypatch,
):
    monkeypatch.setattr(runner.os, "name", "nt")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "powershell":
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="Access denied"
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.cleanup_process_tree(111, include_root=True)

    assert calls[-1] == ["taskkill", "/T", "/F", "/PID", "111"]
    assert result.ok is False
    assert result.terminated_pids == [111]
    assert "Access denied" in result.error


def test_cleanup_process_tree_reports_windows_descendant_json_parse_failure(
    monkeypatch,
):
    monkeypatch.setattr(runner.os, "name", "nt")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="{not json", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.cleanup_process_tree(111)

    assert result.ok is False
    assert result.terminated_pids == []
    assert "invalid JSON" in result.error


def test_cleanup_process_tree_windows_include_root_taskkills_root_once(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222, 333])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.cleanup_process_tree(111, include_root=True)

    assert calls == [["taskkill", "/T", "/F", "/PID", "111"]]
    assert result.ok is True
    assert result.terminated_pids == [111, 222, 333]


def test_cleanup_process_tree_windows_deduplicates_descendants(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222, 333, 222])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.cleanup_process_tree(111, include_root=False)

    assert calls == [
        ["taskkill", "/T", "/F", "/PID", "222"],
        ["taskkill", "/T", "/F", "/PID", "333"],
    ]
    assert result.ok is True
    assert result.terminated_pids == [222, 333]


def test_cleanup_process_tree_posix_include_root_true_kills_process_group(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222, 333])
    monkeypatch.setattr(runner._signal, "SIGKILL", 9, raising=False)
    killpg_calls = []
    kill_calls = []

    monkeypatch.setattr(
        runner.os,
        "killpg",
        lambda pid, sig: killpg_calls.append((pid, sig)),
        raising=False,
    )
    monkeypatch.setattr(
        runner.os, "kill", lambda pid, sig: kill_calls.append((pid, sig))
    )

    result = runner.cleanup_process_tree(111, include_root=True)

    assert result.ok is True
    assert result.terminated_pids == [111, 222, 333]
    assert killpg_calls == [(111, runner._signal.SIGKILL)]
    assert kill_calls == []


def test_cleanup_process_tree_posix_include_root_false_kills_descendants_only(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222, 333])
    monkeypatch.setattr(runner._signal, "SIGKILL", 9, raising=False)
    kill_calls = []
    killpg_calls = []

    monkeypatch.setattr(
        runner.os, "kill", lambda pid, sig: kill_calls.append((pid, sig))
    )
    monkeypatch.setattr(
        runner.os,
        "killpg",
        lambda pid, sig: killpg_calls.append((pid, sig)),
        raising=False,
    )

    result = runner.cleanup_process_tree(111, include_root=False)

    assert result.ok is True
    assert result.terminated_pids == [333, 222]
    assert kill_calls == [(333, runner._signal.SIGKILL), (222, runner._signal.SIGKILL)]
    assert killpg_calls == []


def test_cleanup_process_tree_posix_include_root_false_reports_child_errors(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner, "list_descendant_pids", lambda pid: [222])
    monkeypatch.setattr(runner._signal, "SIGKILL", 9, raising=False)

    def fail_kill(pid, sig):
        raise OSError("denied")

    monkeypatch.setattr(runner.os, "kill", fail_kill)

    result = runner.cleanup_process_tree(111, include_root=False)

    assert result.ok is False
    assert result.terminated_pids == []
    assert "denied" in result.error


def test_run_command_timeout_returns_timeout_result(monkeypatch):
    class TimeoutProc:
        pid = 333

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(["pytest"], timeout, output="", stderr="")

        def wait(self):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: TimeoutProc())
    monkeypatch.setattr(
        runner,
        "cleanup_process_tree",
        lambda pid, include_root=False: runner.ProcessCleanupResult(
            True, True, pid, [pid]
        ),
    )

    run_cmd, result = runner.run_command(
        ["pytest"], capture_output=True, text=True, timeout=1
    )

    assert Path(run_cmd[0]).name.lower().startswith("pytest")
    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_run_command_timeout_posix_starts_new_session(monkeypatch):
    class TimeoutProc:
        pid = 333

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(["pytest"], timeout, output="", stderr="")

        def wait(self):
            return 0

    captured = {}

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return TimeoutProc()

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner,
        "cleanup_process_tree",
        lambda pid, include_root=False: runner.ProcessCleanupResult(
            True, True, pid, [pid]
        ),
    )

    runner.run_command(["pytest"], capture_output=True, text=True, timeout=1)

    assert captured["start_new_session"] is True


def test_run_command_timeout_preserves_explicit_start_new_session(monkeypatch):
    captured = {}

    class TimeoutProc:
        pid = 333

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(["pytest"], timeout, output="", stderr="")

        def wait(self):
            return 0

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return TimeoutProc()

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner,
        "cleanup_process_tree",
        lambda pid, include_root=False: runner.ProcessCleanupResult(
            True, True, pid, [pid]
        ),
    )

    runner.run_command(
        ["pytest"], capture_output=True, text=True, timeout=1, start_new_session=False
    )

    assert captured["start_new_session"] is False


def test_run_command_timeout_windows_does_not_set_start_new_session(monkeypatch):
    captured = {}

    class TimeoutProc:
        pid = 333

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(["pytest"], timeout, output="", stderr="")

        def wait(self):
            return 0

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return TimeoutProc()

    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner,
        "cleanup_process_tree",
        lambda pid, include_root=False: runner.ProcessCleanupResult(
            True, True, pid, [pid]
        ),
    )

    runner.run_command(["pytest"], capture_output=True, text=True, timeout=1)

    assert "start_new_session" not in captured
