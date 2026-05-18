import json
import subprocess
import sys
from pathlib import Path

import eval_services


def test_register_pid_writes_registry(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    eval_services.register_pid("api", 12345)
    data = json.loads(Path("workspace/eval_services.json").read_text(encoding="utf-8"))
    assert data == [{"name": "api", "pid": 12345}]


def test_stop_registered_ignores_missing_process(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    eval_services.register_pid("missing", 99999999)
    eval_services.stop_registered()
    assert not Path("workspace/eval_services.json").exists()


def test_stop_registered_terminates_running_process(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        eval_services.register_pid("sleep", proc.pid)
        eval_services.stop_registered()
        proc.wait(timeout=10)
        assert proc.returncode is not None
        assert not Path("workspace/eval_services.json").exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_stop_registered_cleans_process_tree(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    eval_services.register_pid("sleep", 123)
    cleanup_calls = []

    monkeypatch.setattr(eval_services, "is_pid_running", lambda pid: True)
    monkeypatch.setattr(
        eval_services,
        "cleanup_process_tree",
        lambda pid, include_root=False: cleanup_calls.append((pid, include_root)),
    )

    eval_services.stop_registered()

    assert cleanup_calls == [(123, True)]
    assert not Path("workspace/eval_services.json").exists()


def test_cleanup_cli_removes_registry(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    eval_services.register_pid("missing", 99999999)
    script = Path(__file__).resolve().parents[3] / "harness" / "eval_services.py"
    result = subprocess.run(
        [sys.executable, str(script), "cleanup"],
        cwd=tmp_workspace,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert not Path("workspace/eval_services.json").exists()


def test_start_api_registers_pid(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)

    class Proc:
        pid = 123

    monkeypatch.setattr(eval_services.subprocess, "Popen", lambda *a, **kw: Proc())
    monkeypatch.setattr(eval_services, "is_pid_running", lambda pid: False)

    assert eval_services.start_service("api", ["python", "-m", "uvicorn"]) == 0
    data = json.loads(Path("workspace/eval_services.json").read_text(encoding="utf-8"))
    assert data == [{"name": "api", "pid": 123}]


def test_start_service_posix_starts_new_session(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    captured = {}

    class Proc:
        pid = 123

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return Proc()

    monkeypatch.setattr(eval_services.os, "name", "posix")
    monkeypatch.setattr(eval_services.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(eval_services, "is_pid_running", lambda pid: False)

    assert eval_services.start_service("api", ["python"]) == 0
    assert captured.get("start_new_session") is True
    assert "creationflags" not in captured


def test_start_service_windows_uses_new_process_group(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    captured = {}

    class Proc:
        pid = 123

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return Proc()

    monkeypatch.setattr(eval_services.os, "name", "nt")
    monkeypatch.setattr(
        eval_services.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False
    )
    monkeypatch.setattr(eval_services.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(eval_services, "is_pid_running", lambda pid: False)

    assert eval_services.start_service("api", ["python"]) == 0
    assert captured.get("creationflags") == 512
    assert "start_new_session" not in captured


def test_start_vite_registers_pid(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)

    class Proc:
        pid = 456

    monkeypatch.setattr(eval_services.subprocess, "Popen", lambda *a, **kw: Proc())
    monkeypatch.setattr(eval_services, "is_pid_running", lambda pid: False)

    assert eval_services.start_service("vite", ["npm", "run", "dev"]) == 0
    data = json.loads(Path("workspace/eval_services.json").read_text(encoding="utf-8"))
    assert data == [{"name": "vite", "pid": 456}]


def test_start_command_reuses_running_pid(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    eval_services.register_pid("api", 123)
    popen = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not start"))
    monkeypatch.setattr(eval_services.subprocess, "Popen", popen)
    monkeypatch.setattr(eval_services, "is_pid_running", lambda pid: pid == 123)

    assert eval_services.start_service("api", ["python"]) == 0


def test_check_nginx_reports_missing_executable(monkeypatch, capsys):
    def mock_run(*a, **kw):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(eval_services.subprocess, "run", mock_run)

    assert eval_services.check_nginx() == 1
    assert "nginx is not available" in capsys.readouterr().err
