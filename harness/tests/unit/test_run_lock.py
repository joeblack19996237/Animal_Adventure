import os
from pathlib import Path

import pytest

import run_lock
from run_lock import RunLockError


def test_acquire_lock_writes_pid_and_metadata(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    entry = run_lock.acquire_lock(spec_file="spec.md", app_type="cli", current_phase=2)
    assert entry["spec_file"] == "spec.md"
    assert Path("workspace/run.lock").exists()
    assert Path("workspace/harness.pid").exists()


def test_acquire_lock_rejects_active_lock(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    run_lock.acquire_lock()
    with pytest.raises(RunLockError):
        run_lock.acquire_lock()


def test_stale_lock_is_cleared_when_pid_missing(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    Path("workspace/run.lock").write_text('{"pid": 999999999}', encoding="utf-8")
    assert run_lock.clear_stale_lock() is True
    assert not Path("workspace/run.lock").exists()


def test_release_lock_removes_lock_and_pid(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    run_lock.acquire_lock()
    run_lock.release_lock()
    assert not Path("workspace/run.lock").exists()
    assert not Path("workspace/harness.pid").exists()


def test_status_reads_lock_without_mutating_state(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    run_lock.acquire_lock(spec_file="spec.md")
    status = run_lock.lock_status()
    assert status["spec_file"] == "spec.md"
    assert Path("workspace/run.lock").exists()


def test_acquire_lock_uses_exclusive_create(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    real_open = os.open
    seen_flags = []

    def capture_open(path, flags, *args, **kwargs):
        seen_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(run_lock.os, "open", capture_open)

    run_lock.acquire_lock()

    assert seen_flags
    assert seen_flags[0] & os.O_EXCL


def test_acquire_lock_raises_when_atomic_create_races_with_active_lock(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    locks = iter([None, {"pid": 12345}])
    monkeypatch.setattr(run_lock, "read_lock", lambda: next(locks))
    monkeypatch.setattr(run_lock, "_pid_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(
        run_lock,
        "_write_lock_atomic",
        lambda entry: (_ for _ in ()).throw(FileExistsError()),
    )

    with pytest.raises(RunLockError):
        run_lock.acquire_lock()


def test_acquire_lock_retries_after_stale_lock_race(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    locks = iter([None, {"pid": 999999999}])
    calls = []
    cleared = []
    monkeypatch.setattr(run_lock, "read_lock", lambda: next(locks, None))
    monkeypatch.setattr(run_lock, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(
        run_lock, "clear_stale_lock", lambda: cleared.append(True) or True
    )

    def mock_write(entry):
        calls.append(entry)
        if len(calls) == 1:
            raise FileExistsError()

    monkeypatch.setattr(run_lock, "_write_lock_atomic", mock_write)

    entry = run_lock.acquire_lock(spec_file="spec.md")

    assert entry["spec_file"] == "spec.md"
    assert len(calls) == 2
    assert cleared


def test_acquire_lock_releases_lock_if_pid_write_fails(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)

    class BadPidPath:
        def write_text(self, *args, **kwargs):
            raise OSError("pid write failed")

        def unlink(self, *args, **kwargs):
            return None

    monkeypatch.setattr(run_lock, "PID_PATH", BadPidPath())

    with pytest.raises(OSError, match="pid write failed"):
        run_lock.acquire_lock()

    assert not Path("workspace/run.lock").exists()


def test_acquire_lock_includes_lock_token_in_lock_file(tmp_workspace, monkeypatch):
    import json
    import re

    monkeypatch.chdir(tmp_workspace)
    run_lock.acquire_lock()
    lock_data = json.loads(Path("workspace/run.lock").read_text(encoding="utf-8"))
    assert "lock_token" in lock_data
    assert re.fullmatch(r"[0-9a-f]{32}", lock_data["lock_token"])


def test_acquire_lock_writes_token_to_pid_file(tmp_workspace, monkeypatch):
    import json

    monkeypatch.chdir(tmp_workspace)
    run_lock.acquire_lock()
    lock_data = json.loads(Path("workspace/run.lock").read_text(encoding="utf-8"))
    pid_content = Path("workspace/harness.pid").read_text(encoding="utf-8").strip()
    assert pid_content == lock_data["lock_token"]


def test_clear_stale_lock_does_not_clear_when_token_matches(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(run_lock, "_pid_alive", lambda pid: True)
    Path("workspace/run.lock").write_text(
        '{"pid": 12345, "lock_token": "abc123"}', encoding="utf-8"
    )
    Path("workspace/harness.pid").write_text("abc123", encoding="utf-8")
    assert run_lock.clear_stale_lock() is False
    assert Path("workspace/run.lock").exists()


def test_clear_stale_lock_clears_when_token_mismatches(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(run_lock, "_pid_alive", lambda pid: True)
    Path("workspace/run.lock").write_text(
        '{"pid": 12345, "lock_token": "abc123"}', encoding="utf-8"
    )
    Path("workspace/harness.pid").write_text("different_token", encoding="utf-8")
    assert run_lock.clear_stale_lock() is True
    assert not Path("workspace/run.lock").exists()


def test_windows_pid_alive_returns_true_on_access_denied(monkeypatch):
    """OpenProcess returning NULL with ERROR_ACCESS_DENIED means the process
    exists but is inaccessible — it must not be treated as dead."""
    if os.name != "nt":
        pytest.skip("Windows-only")

    import ctypes

    mock_kernel32 = type(
        "K32",
        (),
        {
            "OpenProcess": staticmethod(lambda access, inherit, pid: 0),
            "GetLastError": staticmethod(lambda: 5),  # ERROR_ACCESS_DENIED
            "CloseHandle": staticmethod(lambda h: None),
        },
    )()

    monkeypatch.setattr(
        ctypes, "windll", type("WDL", (), {"kernel32": mock_kernel32})()
    )
    assert run_lock._windows_pid_alive(928) is True


def test_windows_pid_alive_returns_false_on_invalid_pid(monkeypatch):
    """OpenProcess returning NULL with any error other than ERROR_ACCESS_DENIED
    means the process does not exist."""
    if os.name != "nt":
        pytest.skip("Windows-only")

    import ctypes

    mock_kernel32 = type(
        "K32",
        (),
        {
            "OpenProcess": staticmethod(lambda access, inherit, pid: 0),
            "GetLastError": staticmethod(lambda: 87),  # ERROR_INVALID_PARAMETER
            "CloseHandle": staticmethod(lambda h: None),
        },
    )()

    monkeypatch.setattr(
        ctypes, "windll", type("WDL", (), {"kernel32": mock_kernel32})()
    )
    assert run_lock._windows_pid_alive(999999) is False


def test_clear_stale_lock_conservative_when_pid_file_missing(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(run_lock, "_pid_alive", lambda pid: True)
    Path("workspace/run.lock").write_text(
        '{"pid": 12345, "lock_token": "abc123"}', encoding="utf-8"
    )
    # harness.pid is absent
    assert run_lock.clear_stale_lock() is False
    assert Path("workspace/run.lock").exists()
