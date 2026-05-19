from __future__ import annotations

from unittest.mock import MagicMock

from watchdog import find_uvicorn_pid, run_watchdog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(cmdline: list[str], pid: int = 1000) -> MagicMock:
    proc = MagicMock()
    proc.pid = pid
    proc.info = {"name": "python", "cmdline": cmdline}
    return proc


def _noop_start(cmd: list[str]) -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# run_watchdog — starts uvicorn when process is missing
# ---------------------------------------------------------------------------


def test_watchdog_starts_uvicorn_when_missing() -> None:
    started: list[list[str]] = []

    def collecting_start(cmd: list[str]) -> MagicMock:
        started.append(cmd)
        return MagicMock()

    result = run_watchdog(find_pid_fn=lambda: None, start_fn=collecting_start)

    assert result is True
    assert len(started) == 1


def test_watchdog_start_receives_default_cmd() -> None:
    received: list[list[str]] = []

    def collecting_start(cmd: list[str]) -> MagicMock:
        received.append(cmd)
        return MagicMock()

    run_watchdog(find_pid_fn=lambda: None, start_fn=collecting_start)

    assert received[0][0] == "uvicorn"


def test_watchdog_start_receives_custom_cmd() -> None:
    custom_cmd = ["uvicorn", "myapp:app", "--port", "9000"]
    received: list[list[str]] = []

    def collecting_start(cmd: list[str]) -> MagicMock:
        received.append(cmd)
        return MagicMock()

    run_watchdog(cmd=custom_cmd, find_pid_fn=lambda: None, start_fn=collecting_start)

    assert received[0] == custom_cmd


def test_watchdog_returns_true_when_started() -> None:
    result = run_watchdog(find_pid_fn=lambda: None, start_fn=_noop_start)
    assert result is True


# ---------------------------------------------------------------------------
# run_watchdog — avoids duplicates when process is already running
# ---------------------------------------------------------------------------


def test_watchdog_skips_start_when_already_running() -> None:
    call_count = 0

    def counting_start(cmd: list[str]) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return MagicMock()

    result = run_watchdog(find_pid_fn=lambda: 12345, start_fn=counting_start)

    assert result is False
    assert call_count == 0


def test_watchdog_returns_false_when_already_running() -> None:
    result = run_watchdog(find_pid_fn=lambda: 99, start_fn=_noop_start)
    assert result is False


def test_watchdog_does_not_start_for_any_nonzero_pid() -> None:
    for pid in (1, 100, 99999):
        started: list[list[str]] = []

        def collecting_start(cmd: list[str]) -> MagicMock:
            started.append(cmd)
            return MagicMock()

        run_watchdog(find_pid_fn=lambda p=pid: p, start_fn=collecting_start)
        assert started == [], f"should not start when pid={pid}"


# ---------------------------------------------------------------------------
# find_uvicorn_pid — process detection via injected iterator
# ---------------------------------------------------------------------------


def test_find_pid_returns_pid_when_uvicorn_in_cmdline() -> None:
    proc = _make_proc(["python", "-m", "uvicorn", "app.main:app"], pid=1234)

    pid = find_uvicorn_pid(process_iter=lambda attrs: [proc])

    assert pid == 1234


def test_find_pid_returns_none_when_no_uvicorn_process() -> None:
    proc = _make_proc(["python", "other_script.py"])

    pid = find_uvicorn_pid(process_iter=lambda attrs: [proc])

    assert pid is None


def test_find_pid_returns_none_when_process_list_empty() -> None:
    pid = find_uvicorn_pid(process_iter=lambda attrs: [])

    assert pid is None


def test_find_pid_matches_uvicorn_as_direct_executable() -> None:
    proc = _make_proc(["uvicorn", "app.main:app", "--host", "127.0.0.1"], pid=5678)

    pid = find_uvicorn_pid(process_iter=lambda attrs: [proc])

    assert pid == 5678


def test_find_pid_ignores_non_uvicorn_processes() -> None:
    procs = [
        _make_proc(["nginx", "-g", "daemon off;"], pid=100),
        _make_proc(["python", "manage.py", "runserver"], pid=200),
        _make_proc(["postgres"], pid=300),
    ]

    pid = find_uvicorn_pid(process_iter=lambda attrs: procs)

    assert pid is None


def test_find_pid_returns_first_matching_pid() -> None:
    procs = [
        _make_proc(["uvicorn", "app.main:app"], pid=111),
        _make_proc(["uvicorn", "other:app"], pid=222),
    ]

    pid = find_uvicorn_pid(process_iter=lambda attrs: procs)

    assert pid == 111


def test_find_pid_handles_none_cmdline() -> None:
    proc = MagicMock()
    proc.pid = 500
    proc.info = {"name": "python", "cmdline": None}

    pid = find_uvicorn_pid(process_iter=lambda attrs: [proc])

    assert pid is None


def test_find_pid_handles_empty_cmdline() -> None:
    proc = _make_proc([], pid=600)

    pid = find_uvicorn_pid(process_iter=lambda attrs: [proc])

    assert pid is None


def test_find_pid_skips_processes_without_uvicorn_substring() -> None:
    procs = [
        _make_proc(["python", "-c", "print('hello')"], pid=10),
        _make_proc(["uvicorn", "app.main:app"], pid=20),
    ]

    pid = find_uvicorn_pid(process_iter=lambda attrs: procs)

    assert pid == 20
