import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import agents
from subprocess_runner import ProcessResult


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)


def _make_subprocess_result(returncode=0, stdout="", stderr="", pid=None):
    return ProcessResult(
        stdout=stdout, stderr=stderr, returncode=returncode, elapsed=0.0, pid=pid
    )


def _make_envelope(signal: dict, usage: dict | None = None) -> str:
    return json.dumps(
        {
            "result": json.dumps(signal),
            "usage": usage or {"input_tokens": 100, "output_tokens": 50},
        }
    )


# --- extract_signal ---


def test_extract_signal_clean_json():
    raw = '{"mode": "EXECUTE", "phase_id": 1}'
    result = agents.extract_signal(raw)
    assert result == {"mode": "EXECUTE", "phase_id": 1}


def test_extract_signal_fenced():
    raw = '```json\n{"mode": "EXECUTE", "phase_id": 1}\n```'
    result = agents.extract_signal(raw)
    assert result == {"mode": "EXECUTE", "phase_id": 1}


def test_extract_signal_prose_wrapped():
    raw = 'Here is the result: {"mode": "EXECUTE", "phase_id": 1} done.'
    result = agents.extract_signal(raw)
    assert result == {"mode": "EXECUTE", "phase_id": 1}


def test_extract_signal_no_json():
    with pytest.raises(ValueError):
        agents.extract_signal("no json here at all")


# --- build_file_lists / file_preamble ---


def test_build_file_lists(sample_profile):
    builder, reviewer = agents.build_file_lists(sample_profile)
    assert sample_profile["builder_agent"] in builder
    assert sample_profile["reviewer_agent"] in reviewer
    assert sample_profile["common_rules"] in builder
    assert sample_profile["rules_file"] in builder


def test_file_preamble_format(sample_profile):
    builder, _ = agents.build_file_lists(sample_profile)
    preamble = agents.file_preamble(builder)
    for path in builder:
        assert path in preamble
    assert preamble.index(builder[0]) < preamble.index(builder[-1])


# --- call_claude ---


def test_call_claude_timeout(sample_config, monkeypatch):
    def mock_run(*args, **kwargs):
        raise agents.RunnerTimeout("timeout after 0s")

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    with pytest.raises(agents.SubprocessError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)
    assert "timeout" in str(exc.value)
    assert str(sample_config["subprocess_timeout"]["EXECUTE"]) in str(exc.value)


def test_call_claude_double_timeout_raises_timeout_error(sample_config, monkeypatch):
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        MagicMock(side_effect=agents.RunnerTimeout("timeout")),
    )

    with pytest.raises(agents.TimeoutError) as exc:
        agents.call_claude("prompt", "model", "EVALUATE", sample_config)

    assert "timeout" in str(exc.value)


def test_call_claude_nonzero_exit(sample_config, monkeypatch):
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(returncode=1, stderr="err"),
    )
    with pytest.raises(agents.SubprocessError):
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)


def test_call_claude_nonzero_unparseable_error_includes_pid_and_empty_output_marker(
    sample_config, monkeypatch
):
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(returncode=1, pid=987),
    )
    monkeypatch.setattr(agents, "emit_event", lambda *a, **kw: None)

    with pytest.raises(agents.SubprocessError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    message = str(exc.value)
    assert "pid 987" in message
    assert "code 1" in message
    assert "stdout_tail=<empty>" in message
    assert "stderr_tail=<empty>" in message


def test_call_claude_nonzero_unparseable_emits_failed_event(sample_config, monkeypatch):
    events = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout="not json", stderr="boom", pid=987
        ),
    )
    monkeypatch.setattr(
        agents, "emit_event", lambda event, **kw: events.append((event, kw))
    )

    with pytest.raises(agents.SubprocessError):
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert events[0][0] == "claude_subprocess_failed"
    event = events[0][1]
    assert event["mode"] == "EXECUTE"
    assert event["call_id"].startswith("execute-")
    assert event["pid"] == 987
    assert event["returncode"] == 1
    assert event["stdout_tail"] == "not json"
    assert event["stderr_tail"] == "boom"
    assert event["reason"] == "nonzero exit with unparseable CLI envelope"


def test_call_claude_raises_external_dependency_error_for_429(
    sample_config, monkeypatch
):
    envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit",
    }

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(envelope)
        ),
    )

    with pytest.raises(agents.ExternalDependencyError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert "claude API error 429" in str(exc.value)
    assert "You've hit your limit" in str(exc.value)


def test_call_claude_waits_and_retries_parseable_429(sample_config, monkeypatch):
    first = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit · resets 3:20pm (Pacific/Auckland)",
    }
    signal = {"mode": "EXECUTE", "phase_id": 1, "tasks": []}
    calls = []
    sleeps = []
    events = []

    def mock_run(*args, **kwargs):
        calls.append(kwargs.get("mode"))
        if len(calls) == 1:
            return _make_subprocess_result(returncode=1, stdout=json.dumps(first))
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    monkeypatch.setattr(agents, "_external_dependency_retry_delay", lambda detail: 0.01)
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        agents, "emit_event", lambda event, **kw: events.append((event, kw))
    )

    result = agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert result["signal"] == signal
    assert len(calls) == 2
    assert sleeps == [0.01]
    assert [event for event, _ in events] == [
        "external_dependency_wait_start",
        "external_dependency_wait_end",
    ]
    wait_event = events[0][1]
    assert "process_cleanup_attempted" in wait_event
    assert "quarantined_files_count" in wait_event


def test_call_claude_defers_long_parseable_429_wait(sample_config, monkeypatch):
    sample_config["external_dependency"] = {"max_in_process_wait_seconds": 900}
    envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit · resets 3:20pm (Pacific/Auckland)",
    }
    events = []
    sleeps = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(envelope), pid=123
        ),
    )
    monkeypatch.setattr(agents, "_external_dependency_retry_delay", lambda detail: 901)
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        agents.external_dependency,
        "start_context",
        lambda **kw: {**kw, "reset_at": "later"},
    )
    monkeypatch.setattr(
        agents.external_dependency,
        "cleanup_before_wait",
        lambda context: {
            **context,
            "cleanup_status": "clean",
            "process_cleanup": {"attempted": True, "terminated_pids": [], "error": ""},
            "quarantined_files": [],
        },
    )
    monkeypatch.setattr(
        agents, "emit_event", lambda event, **kw: events.append((event, kw))
    )

    with pytest.raises(agents.ExternalDependencyError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert "exceeds in-process wait limit" in str(exc.value)
    assert sleeps == []
    assert events[0][0] == "external_dependency_wait_deferred"
    assert events[0][1]["seconds"] == 901
    assert events[0][1]["max_in_process_wait_seconds"] == 900
    assert events[0][1]["call_id"].startswith("execute-")


def test_call_claude_cleans_process_tree_before_429_wait_retry(
    sample_config, monkeypatch
):
    first = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit · resets 3:20pm (Pacific/Auckland)",
    }
    signal = {"mode": "EXECUTE", "phase_id": 1, "tasks": []}
    cleanup_calls = []

    def mock_run(*args, **kwargs):
        if not cleanup_calls:
            return _make_subprocess_result(
                returncode=1, stdout=json.dumps(first), pid=123
            )
        return _make_subprocess_result(stdout=_make_envelope(signal))

    def cleanup_before_wait(context):
        cleanup_calls.append(context["root_pid"])
        context.update(
            {
                "cleanup_status": "clean",
                "process_cleanup": {
                    "attempted": True,
                    "terminated_pids": [456],
                    "error": "",
                },
                "quarantined_files": [],
            }
        )
        return context

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    monkeypatch.setattr(agents, "_external_dependency_retry_delay", lambda detail: 0.01)
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        agents.external_dependency,
        "start_context",
        lambda **kw: {**kw, "reset_at": "soon"},
    )
    monkeypatch.setattr(
        agents.external_dependency, "cleanup_before_wait", cleanup_before_wait
    )
    monkeypatch.setattr(
        agents.external_dependency,
        "preflight_context",
        lambda allow_quarantine: {"ok": True},
    )
    monkeypatch.setattr(agents, "emit_event", lambda *a, **kw: None)

    agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert cleanup_calls == [123]


def test_call_claude_does_not_retry_when_process_cleanup_fails(
    sample_config, monkeypatch
):
    envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit · resets 3:20pm (Pacific/Auckland)",
    }
    calls = []

    def mock_run(*args, **kwargs):
        calls.append(1)
        return _make_subprocess_result(returncode=1, stdout=json.dumps(envelope))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    monkeypatch.setattr(agents, "_external_dependency_retry_delay", lambda detail: 0.01)
    monkeypatch.setattr(
        agents.external_dependency,
        "start_context",
        lambda **kw: {**kw, "reset_at": "soon"},
    )
    monkeypatch.setattr(
        agents.external_dependency,
        "cleanup_before_wait",
        lambda context: {
            **context,
            "cleanup_status": "failed",
            "process_cleanup": {"error": "still running"},
            "tracked_dirty_files": [],
            "quarantine_errors": [],
        },
    )

    with pytest.raises(agents.ExternalDependencyError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert len(calls) == 1
    assert "environment cleanup before retry failed" in str(exc.value)


def test_call_claude_blocks_when_post_wait_preflight_fails(sample_config, monkeypatch):
    first = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit · resets 3:20pm (Pacific/Auckland)",
    }

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(first)
        ),
    )
    monkeypatch.setattr(agents, "_external_dependency_retry_delay", lambda detail: 0.01)
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        agents.external_dependency,
        "start_context",
        lambda **kw: {**kw, "reset_at": "soon"},
    )
    monkeypatch.setattr(
        agents.external_dependency,
        "cleanup_before_wait",
        lambda context: {
            **context,
            "cleanup_status": "clean",
            "process_cleanup": {"attempted": True, "terminated_pids": [], "error": ""},
            "quarantined_files": [],
        },
    )
    monkeypatch.setattr(
        agents.external_dependency,
        "preflight_context",
        lambda allow_quarantine: {
            "ok": False,
            "tracked_dirty_files": ["app/db.py"],
            "untracked_files": [],
            "process_cleanup": {"error": ""},
        },
    )
    monkeypatch.setattr(agents, "emit_event", lambda *a, **kw: None)

    with pytest.raises(agents.ExternalDependencyError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert "environment preflight after wait failed" in str(exc.value)


def test_call_claude_parseable_429_retries_only_once(sample_config, monkeypatch):
    envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit · resets 3:20pm (Pacific/Auckland)",
    }
    calls = []

    def mock_run(*args, **kwargs):
        calls.append(1)
        return _make_subprocess_result(returncode=1, stdout=json.dumps(envelope))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    monkeypatch.setattr(agents, "_external_dependency_retry_delay", lambda detail: 0.01)
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: None)

    with pytest.raises(agents.ExternalDependencyError):
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert len(calls) == 2


def test_call_claude_unparseable_429_does_not_wait(sample_config, monkeypatch):
    envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 429,
        "result": "You've hit your limit",
    }
    sleep = MagicMock()
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(envelope)
        ),
    )
    monkeypatch.setattr(agents.time, "sleep", sleep)

    with pytest.raises(agents.ExternalDependencyError):
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    sleep.assert_not_called()


def test_external_dependency_retry_delay_parses_reset_time():
    tz = ZoneInfo("Pacific/Auckland")
    now = datetime(2026, 5, 15, 14, 30, tzinfo=tz)

    delay = agents._external_dependency_retry_delay(
        "You've hit your limit · resets 3:20pm (Pacific/Auckland)", now=now
    )

    assert delay == pytest.approx(50 * 60)


def test_external_dependency_retry_delay_rejects_expired_or_too_long_reset():
    tz = ZoneInfo("Pacific/Auckland")
    expired_now = datetime(2026, 5, 15, 15, 30, tzinfo=tz)
    long_now = datetime(2026, 5, 15, 8, 0, tzinfo=tz)

    assert (
        agents._external_dependency_retry_delay(
            "resets 3:20pm (Pacific/Auckland)", now=expired_now
        )
        is None
    )
    assert (
        agents._external_dependency_retry_delay(
            "resets 3:20pm (Pacific/Auckland)",
            now=long_now,
            max_wait_seconds=int(timedelta(hours=6).total_seconds()),
        )
        is None
    )


def test_external_dependency_retry_delay_accepts_next_day_reset_under_limit():
    tz = ZoneInfo("Pacific/Auckland")
    now = datetime(2026, 5, 15, 21, 0, tzinfo=tz)

    delay = agents._external_dependency_retry_delay(
        "You've hit your limit · resets 1:20am (Pacific/Auckland)",
        now=now,
        max_wait_seconds=int(timedelta(hours=6).total_seconds()),
    )

    assert delay == pytest.approx(4 * 60 * 60 + 20 * 60)


def test_external_dependency_retry_delay_rejects_next_day_reset_over_limit():
    tz = ZoneInfo("Pacific/Auckland")
    now = datetime(2026, 5, 15, 18, 0, tzinfo=tz)

    delay = agents._external_dependency_retry_delay(
        "You've hit your limit · resets 1:20am (Pacific/Auckland)",
        now=now,
        max_wait_seconds=int(timedelta(hours=6).total_seconds()),
    )

    assert delay is None


def test_call_claude_non_429_remains_subprocess_error(sample_config, monkeypatch):
    envelope = {
        "type": "result",
        "is_error": True,
        "api_error_status": 500,
        "result": "server error",
    }

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(envelope)
        ),
    )

    with pytest.raises(agents.SubprocessError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert not isinstance(exc.value, agents.ExternalDependencyError)
    assert "claude API error 500" in str(exc.value)


def test_call_claude_connection_refused_is_subprocess_error(sample_config, monkeypatch):
    envelope = {
        "type": "result",
        "is_error": True,
        "result": "API Error: Unable to connect to API (ConnectionRefused)",
    }

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(envelope)
        ),
    )

    with pytest.raises(agents.SubprocessError) as exc:
        agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert not isinstance(exc.value, agents.ExternalDependencyError)
    assert "ConnectionRefused" in str(exc.value)


def test_call_claude_unable_to_connect_is_subprocess_error(sample_config, monkeypatch):
    envelope = {
        "type": "result",
        "is_error": True,
        "result": "API Error: Unable to connect to API",
    }

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1, stdout=json.dumps(envelope)
        ),
    )

    with pytest.raises(agents.SubprocessError) as exc:
        agents.call_claude("prompt", "model", "REVIEW", sample_config)

    assert not isinstance(exc.value, agents.ExternalDependencyError)
    assert "Unable to connect to API" in str(exc.value)


def test_call_claude_unparseable_connection_refused_is_subprocess_error(
    sample_config, monkeypatch
):
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            returncode=1,
            stdout="not json",
            stderr="API Error: Unable to connect to API (ConnectionRefused)",
            pid=987,
        ),
    )
    monkeypatch.setattr(agents, "emit_event", lambda *a, **kw: None)

    with pytest.raises(agents.SubprocessError) as exc:
        agents.call_claude("prompt", "model", "FIX", sample_config)

    assert not isinstance(exc.value, agents.ExternalDependencyError)
    assert "ConnectionRefused" in str(exc.value)


def test_call_claude_success(sample_config, monkeypatch):
    signal = {"mode": "EXECUTE", "phase_id": 1, "tasks": []}
    usage = {"input_tokens": 200, "output_tokens": 80}
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(stdout=_make_envelope(signal, usage)),
    )
    result = agents.call_claude("prompt", "model", "EXECUTE", sample_config)
    assert result["signal"] == signal
    assert result["usage"]["input_tokens"] == 200


def test_call_claude_applies_min_interval_pacing_before_subprocess(
    sample_config, tmp_workspace, monkeypatch
):
    usage_path = tmp_workspace / "workspace" / "usage.jsonl"
    usage_path.write_text(
        json.dumps(
            {
                "ts": datetime.now(ZoneInfo("UTC")).isoformat(),
                "mode": "EXECUTE",
                "actual_input_tokens": 1,
                "actual_output_tokens": 1,
            }
        ),
        encoding="utf-8",
    )
    order = []

    def mock_run(*args, **kwargs):
        order.append("run")
        return _make_subprocess_result(
            stdout=_make_envelope({"mode": "EXECUTE", "phase_id": 1, "tasks": []})
        )

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: order.append("sleep"))
    monkeypatch.setattr(agents, "emit_event", lambda *a, **kw: None)

    agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert order == ["sleep", "run"]


def test_call_claude_applies_large_output_cooldown_after_large_call(
    sample_config, tmp_workspace, monkeypatch
):
    usage_path = tmp_workspace / "workspace" / "usage.jsonl"
    usage_path.write_text(
        json.dumps(
            {
                "ts": datetime.now(ZoneInfo("UTC")).isoformat(),
                "mode": "EXECUTE",
                "actual_input_tokens": 1,
                "actual_output_tokens": 20000,
            }
        ),
        encoding="utf-8",
    )
    sleeps = []
    events = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            stdout=_make_envelope({"mode": "EXECUTE", "phase_id": 1, "tasks": []})
        ),
    )
    monkeypatch.setattr(agents.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        agents, "emit_event", lambda event, **kw: events.append((event, kw))
    )

    agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    assert sleeps and sleeps[0] > sample_config.get("claude_session_pacing", {}).get(
        "min_seconds_between_calls", 60
    )
    assert events[0][0] == "session_pacing_wait_start"
    assert events[0][1]["reason"] == "large_output_cooldown"


def test_call_claude_skips_pacing_when_disabled(
    sample_config, tmp_workspace, monkeypatch
):
    sample_config["claude_session_pacing"] = {"enabled": False}
    usage_path = tmp_workspace / "workspace" / "usage.jsonl"
    usage_path.write_text(
        json.dumps(
            {
                "ts": datetime.now(ZoneInfo("UTC")).isoformat(),
                "mode": "EXECUTE",
                "actual_input_tokens": 1,
                "actual_output_tokens": 20000,
            }
        ),
        encoding="utf-8",
    )
    sleep = MagicMock()
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(
            stdout=_make_envelope({"mode": "EXECUTE", "phase_id": 1, "tasks": []})
        ),
    )
    monkeypatch.setattr(agents.time, "sleep", sleep)

    agents.call_claude("prompt", "model", "EXECUTE", sample_config)

    sleep.assert_not_called()


def test_call_claude_injects_autocompact_env(sample_config, monkeypatch):
    captured_env = {}

    def mock_run(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return _make_subprocess_result(
            stdout=_make_envelope({"mode": "EXECUTE", "phase_id": 1, "tasks": []})
        )

    sample_config["autocompact_pct"] = 75
    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.call_claude("prompt", "model", "EXECUTE", sample_config)
    assert captured_env.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE") == "75"


def test_call_claude_autocompact_default_is_80(sample_config, monkeypatch):
    captured_env = {}

    def mock_run(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return _make_subprocess_result(
            stdout=_make_envelope({"mode": "EXECUTE", "phase_id": 1, "tasks": []})
        )

    sample_config.pop("autocompact_pct", None)
    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.call_claude("prompt", "model", "EXECUTE", sample_config)
    assert captured_env.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE") == "80"


# --- execute ---


def test_execute_prompt_single_with_history(sample_profile, sample_config, monkeypatch):
    signal = {
        "mode": "EXECUTE",
        "phase_id": 1,
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    tasks = [{"id": "1.1", "title": "Task One", "task_type": "foundation"}]
    failure_history = {"1.1": ["attempt 1 failed"]}
    agents.execute(
        tasks, 1, sample_profile, sample_config, failure_history=failure_history
    )

    assert "Prior attempts" in captured[0]
    assert "attempt 1 failed" in captured[0]


def test_execute_prompt_includes_description(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "mode": "EXECUTE",
        "phase_id": 1,
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    tasks = [
        {
            "id": "1.1",
            "title": "Task One",
            "task_type": "foundation",
            "description": "Create app/models.py with User model.",
            "refs": [],
        }
    ]
    agents.execute(tasks, 1, sample_profile, sample_config)

    assert "Create app/models.py with User model." in captured[0]


def test_execute_prompt_requires_utf8_without_bom(
    sample_profile, sample_config, monkeypatch
):
    tasks = [{"id": "1.1", "title": "Create requirements", "description": ""}]
    captured = []

    def fake_call(input_text, *args, **kwargs):
        captured.append(input_text)
        return {"signal": {"tasks": []}, "usage": {}}

    monkeypatch.setattr(agents, "call_claude", fake_call)

    agents.execute(tasks, 1, sample_profile, sample_config)

    assert "UTF-8 without BOM" in captured[0]
    assert "UTF-16" in captured[0]
    assert "NUL-byte" in captured[0]


def test_execute_prompt_explains_existing_tracked_noop_signal(
    sample_profile, sample_config, monkeypatch
):
    tasks = [{"id": "3.2", "title": "Create asset manifest", "description": ""}]
    captured = []

    def fake_call(input_text, *args, **kwargs):
        captured.append(input_text)
        return {"signal": {"tasks": []}, "usage": {}}

    monkeypatch.setattr(agents, "call_claude", fake_call)

    agents.execute(tasks, 3, sample_profile, sample_config)

    prompt = captured[0]
    assert "already satisfied by existing tracked files" in prompt
    assert "empty no-op signal" in prompt
    assert "files_changed" in prompt
    assert "tdd_skipped" in prompt


def test_execute_prompt_includes_refs(sample_profile, sample_config, monkeypatch):
    signal = {
        "mode": "EXECUTE",
        "phase_id": 1,
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    tasks = [
        {
            "id": "1.1",
            "title": "Task One",
            "task_type": "foundation",
            "description": "Some detail.",
            "refs": ["docs/08-state-schema.md", "docs/02-spec-format.md"],
        }
    ]
    agents.execute(tasks, 1, sample_profile, sample_config)

    assert "Also read before starting:" in captured[0]
    assert "docs/08-state-schema.md" in captured[0]
    assert "docs/02-spec-format.md" in captured[0]


def test_execute_prompt_no_description_no_refs(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "mode": "EXECUTE",
        "phase_id": 1,
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    tasks = [{"id": "1.1", "title": "Task One", "task_type": "foundation"}]
    agents.execute(tasks, 1, sample_profile, sample_config)

    assert "Also read before starting:" not in captured[0]


# --- build_tasks ---


def test_build_tasks_prompt_contains_phase_data(
    sample_profile, sample_config, sample_state, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": 1,
        "tasks": [{"id": "1.1", "title": "T1", "task_type": "foundation"}],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    phase = {"id": 1, "title": "Bootstrap", "description": "Set up the project"}
    agents.build_tasks(phase, "", sample_profile, sample_config, sample_state)

    prompt = captured[0]
    assert "Bootstrap" in prompt
    assert "TASK_BUILD" in prompt


def test_build_tasks_normalises_task_list_created_status(
    sample_profile, sample_config, sample_state, monkeypatch, caplog
):
    """status='task_list_created' is a known correction-turn alias; normalise to 'complete'."""
    import logging

    signal = {
        "status": "task_list_created",
        "mode": "TASK_BUILD",
        "phase_id": 1,
        "tasks": [
            {"id": "1.1", "title": "T1", "task_type": "foundation", "description": "d"}
        ],
    }
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(stdout=_make_envelope(signal)),
    )
    phase = {"id": 1, "title": "Bootstrap", "description": "Set up the project"}
    with caplog.at_level(logging.WARNING, logger="agents"):
        agents.build_tasks(phase, "", sample_profile, sample_config, sample_state)
    assert "normalised to 'complete'" in caplog.text


def test_build_tasks_rejects_missing_status_when_tasks_present(
    sample_profile, sample_config, sample_state, monkeypatch
):
    signal = {
        "tasks": [{"id": "1.1", "title": "T1", "task_type": "foundation"}],
    }
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(stdout=_make_envelope(signal)),
    )
    phase = {"id": 1, "title": "Bootstrap", "description": "Set up the project"}
    with pytest.raises(SystemExit):
        agents.build_tasks(phase, "", sample_profile, sample_config, sample_state)
    assert (
        "TASK_BUILD signal invalid: status=None"
        in sample_state["phases"][0]["last_error"][-1]
    )


def test_build_tasks_errors_when_tasks_empty(
    sample_profile, sample_config, sample_state, monkeypatch, tmp_workspace
):
    signal = {"status": "complete", "tasks": []}
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(stdout=_make_envelope(signal)),
    )
    phase = {"id": 1, "title": "Bootstrap", "description": "Set up the project"}
    with pytest.raises(SystemExit):
        agents.build_tasks(phase, "", sample_profile, sample_config, sample_state)
    assert "tasks=list[0]" in sample_state["phases"][0]["last_error"][-1]


def test_build_tasks_rejects_missing_tasks(
    sample_profile, sample_config, sample_state, monkeypatch
):
    signal = {"status": "complete"}
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _make_subprocess_result(stdout=_make_envelope(signal)),
    )
    phase = {"id": 1, "title": "Bootstrap", "description": "Set up the project"}
    with pytest.raises(SystemExit):
        agents.build_tasks(phase, "", sample_profile, sample_config, sample_state)
    assert "tasks=missing" in sample_state["phases"][0]["last_error"][-1]


# --- review_phase ---


def test_review_phase_prompt_contains_base_sha(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 1,
        "verdict": "APPROVE",
        "sha_at_review": "def456",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    agents.review_phase(1, "abc1234", ["spec.md"], sample_profile, sample_config)
    assert "abc1234" in captured[0]


def test_review_phase_prompt_includes_exclude_pathspecs(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 1,
        "verdict": "APPROVE",
        "sha_at_review": "def456",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    profile = {**sample_profile, "review_exclude_paths": [".claude", "harness"]}
    agents.review_phase(1, "abc1234", ["spec.md"], profile, sample_config)

    prompt = captured[0]
    assert ":(exclude).claude" in prompt
    assert ":(exclude)harness" in prompt


def test_review_phase_prompt_plain_diff_when_no_excludes(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 1,
        "verdict": "APPROVE",
        "sha_at_review": "def456",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    profile = {k: v for k, v in sample_profile.items() if k != "review_exclude_paths"}
    agents.review_phase(1, "abc1234", ["spec.md"], profile, sample_config)

    prompt = captured[0]
    assert "abc1234..HEAD" in prompt
    assert ":(exclude)" not in prompt
    assert "git status --short" in prompt
    assert "untracked" in prompt


def test_review_phase_rejects_unsafe_base_sha(sample_profile, sample_config):
    with pytest.raises(ValueError, match="Unsafe git ref"):
        agents.review_phase(
            1, "abc; rm -rf /", ["spec.md"], sample_profile, sample_config
        )


def test_review_phase_quotes_safe_diff_command_with_excludes(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 1,
        "verdict": "APPROVE",
        "sha_at_review": "def4567",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    profile = {
        **sample_profile,
        "review_exclude_paths": ["dist/", "playwright-report/"],
    }

    agents.review_phase(1, "abcdef1", ["spec.md"], profile, sample_config)

    prompt = captured[0]
    assert "git diff abcdef1..HEAD -- . ':(exclude)dist'" in prompt


def test_review_fix_prompt_scopes_to_issue_ids_and_diff(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 2,
        "verdict": "APPROVE",
        "sha_at_review": "def4567",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.review_fix(
        2,
        ["2.1", "2.2"],
        "abcdef1",
        "def4567",
        ["spec.md"],
        sample_profile,
        sample_config,
    )
    prompt = captured[0]
    assert "Issue IDs: 2.1, 2.2" in prompt
    assert "abcdef1..def4567" in prompt
    assert "':(exclude)harness'" in prompt


# --- fix_issues ---


def test_fix_issues_prompt_uses_source_file(sample_profile, sample_config, monkeypatch):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    agents.fix_issues("workspace/review_report.md", sample_profile, sample_config)
    assert "workspace/review_report.md" in captured[0]


def test_fix_issues_prompt_requires_utf8_without_bom(
    sample_profile, sample_config, monkeypatch
):
    captured = []

    def fake_call(input_text, *args, **kwargs):
        captured.append(input_text)
        return {"signal": {"fixes": []}, "usage": {}}

    monkeypatch.setattr(agents, "call_claude", fake_call)

    agents.fix_issues("workspace/review_report.md", sample_profile, sample_config)

    assert "UTF-8 without BOM" in captured[0]
    assert "UTF-16" in captured[0]
    assert "NUL-byte" in captured[0]


# ---------------------------------------------------------------------------
# Gate 2: merged agents + integration guide injection
# ---------------------------------------------------------------------------


def test_build_file_lists_includes_builder_guide(sample_profile):
    builder, _ = agents.build_file_lists(sample_profile)
    assert sample_profile["builder_guide"] in builder


def test_build_file_lists_includes_reviewer_guide(sample_profile):
    _, reviewer = agents.build_file_lists(sample_profile)
    assert sample_profile["reviewer_guide"] in reviewer


def test_build_tasks_integration_guide_appended_for_integration_phase(
    sample_profile, sample_config, sample_state, monkeypatch
):
    """build_tasks() with phase_type='integration' injects the integration guide."""
    signal = {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": 2,
        "tasks": [{"id": "2.1", "title": "T", "task_type": "foundation"}],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    phase = {
        "id": 2,
        "title": "Integration Testing",
        "description": "Write integration tests.",
        "phase_type": "integration",
    }
    agents.build_tasks(phase, "", sample_profile, sample_config, sample_state)
    assert ".claude/rules/common/integration-testing-guide.md" in captured[0]


def test_execute_integration_guide_appended_for_integration_phase(
    sample_profile, sample_config, monkeypatch
):
    """execute() with phase_type='integration' injects the integration guide."""
    signal = {
        "mode": "EXECUTE",
        "phase_id": 2,
        "tasks": [
            {
                "id": "2.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    tasks = [{"id": "2.1", "title": "Write integration test", "task_type": "testing"}]
    agents.execute(tasks, 2, sample_profile, sample_config, phase_type="integration")
    assert ".claude/rules/common/integration-testing-guide.md" in captured[0]


def test_execute_prompt_mentions_cross_stack_for_game_e2e(
    sample_profile, sample_config, monkeypatch
):
    captured = []

    def mock_call(prompt, *args, **kwargs):
        captured.append(prompt)
        return {
            "signal": {"mode": "EXECUTE", "phase_id": 8, "tasks": []},
            "usage": {},
        }

    monkeypatch.setattr(agents, "call_claude", mock_call)
    agents.execute(
        [{"id": "8.1", "title": "Smoke", "task_type": "e2e"}],
        phase_id=8,
        profile=sample_profile,
        config=sample_config,
        phase_type="e2e",
    )

    assert "frontend, backend, and browser acceptance" in captured[0]


def test_integration_guide_not_appended_for_development_phase(
    sample_profile, sample_config, monkeypatch
):
    """execute() with default phase_type='development' does NOT inject the integration guide."""
    signal = {
        "mode": "EXECUTE",
        "phase_id": 2,
        "tasks": [
            {
                "id": "2.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    tasks = [{"id": "2.1", "title": "Build model", "task_type": "database"}]
    agents.execute(tasks, 2, sample_profile, sample_config)
    assert ".claude/rules/common/integration-testing-guide.md" not in captured[0]


def test_fix_issues_uses_integration_test_cmd_for_integration_phase(
    sample_profile, sample_config, monkeypatch
):
    """fix_issues() with phase_type='integration' uses integration_test_cmd in prompt."""
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    agents.fix_issues(
        "workspace/review_report.md",
        sample_profile,
        sample_config,
        phase_type="integration",
    )
    integration_cmd = " ".join(sample_profile["integration_test_cmd"])
    assert integration_cmd in captured[0]


def test_fix_issues_uses_test_cmd_for_development_phase(
    sample_profile, sample_config, monkeypatch
):
    """fix_issues() with default phase_type uses test_cmd (not integration_test_cmd) in prompt."""
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    agents.fix_issues("workspace/review_report.md", sample_profile, sample_config)
    test_cmd = " ".join(sample_profile["test_cmd"])
    assert test_cmd in captured[0]
    integration_cmd = " ".join(sample_profile["integration_test_cmd"])
    assert integration_cmd not in captured[0]


# --- evaluate ---


def _eval_state(app_type="cli"):
    return {
        "app_type": app_type,
        "total_phases": 6,
        "evaluate": {"phase_id": 7, "status": "evaluating", "iterations": []},
        "phases": [],
    }


def test_evaluate_uses_evaluator_settings_file(sample_config, monkeypatch):
    signal = {
        "status": "complete",
        "mode": "EVALUATE",
        "iteration": 1,
        "phase_id": 7,
        "verdict": "APPROVE",
        "issues": [],
    }
    captured_cmd = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured_cmd.append(cmd)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.evaluate("claude-sonnet-4-6", _eval_state(), 1, "spec text", sample_config)
    assert "--settings" in captured_cmd[0]
    idx = captured_cmd[0].index("--settings")
    assert captured_cmd[0][idx + 1] == ".claude/settings.evaluator.json"


def test_evaluate_tools_exclude_edit(sample_config, monkeypatch):
    signal = {
        "status": "complete",
        "mode": "EVALUATE",
        "iteration": 1,
        "phase_id": 7,
        "verdict": "APPROVE",
        "issues": [],
    }
    captured_cmd = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured_cmd.append(cmd)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.evaluate("claude-sonnet-4-6", _eval_state(), 1, "spec text", sample_config)
    tools_idx = captured_cmd[0].index("--allowedTools")
    tools_value = captured_cmd[0][tools_idx + 1]
    assert "Edit" not in tools_value


def test_evaluate_uses_evaluate_timeout(sample_config, monkeypatch):
    sample_config["subprocess_timeout"]["EVALUATE"] = 999
    calls = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        calls.append(timeout)
        return _make_subprocess_result(
            stdout=_make_envelope(
                {
                    "status": "complete",
                    "mode": "EVALUATE",
                    "iteration": 1,
                    "phase_id": 7,
                    "verdict": "APPROVE",
                    "issues": [],
                }
            )
        )

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.evaluate("claude-sonnet-4-6", _eval_state(), 1, "spec", sample_config)
    assert calls[0] == 999


def test_evaluate_injects_spec_sections_string(sample_config, monkeypatch):
    signal = {
        "status": "complete",
        "mode": "EVALUATE",
        "iteration": 1,
        "phase_id": 7,
        "verdict": "APPROVE",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.evaluate(
        "claude-sonnet-4-6", _eval_state(), 1, "## Requirements\nDo X.", sample_config
    )
    assert "## Requirements" in captured[0]
    assert "Do X." in captured[0]


def test_evaluate_prompt_includes_score_threshold(sample_config, monkeypatch):
    captured = []

    def mock_call(prompt, *args, **kwargs):
        captured.append(prompt)
        return {
            "signal": {"iteration": 1, "verdict": "APPROVE", "issues": []},
            "usage": {},
        }

    sample_config["evaluation_min_score_pct"] = 0.9
    monkeypatch.setattr(agents, "call_claude", mock_call)

    agents.evaluate(
        "model",
        {"evaluate": {"app_type": "game"}, "total_phases": 1},
        1,
        "spec",
        sample_config,
    )

    assert "Minimum score threshold: 90%" in captured[0]


def test_evaluate_prompt_requires_game_evidence_sections(sample_config, monkeypatch):
    captured = []

    def mock_call(prompt, *args, **kwargs):
        captured.append(prompt)
        return {
            "signal": {"iteration": 1, "verdict": "APPROVE", "issues": []},
            "usage": {},
        }

    monkeypatch.setattr(agents, "call_claude", mock_call)

    agents.evaluate(
        "model",
        {"evaluate": {"app_type": "game"}, "total_phases": 1},
        1,
        "spec",
        sample_config,
    )

    assert "Spec Acceptance Checklist" in captured[0]
    assert "Command Evidence" in captured[0]
    assert "Code Quality Audit" in captured[0]
    assert "webkit-ipad" in captured[0]
    assert "skipped WebKit-iPad checks do not count as verified" in captured[0]


def test_evaluate_injects_spec_sections_paths(sample_config, monkeypatch):
    signal = {
        "status": "complete",
        "mode": "EVALUATE",
        "iteration": 1,
        "phase_id": 7,
        "verdict": "APPROVE",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.evaluate(
        "claude-sonnet-4-6",
        _eval_state(),
        1,
        "@docs/spec/requirements.md\n@docs/spec/architecture.md",
        sample_config,
    )
    assert "@docs/spec/requirements.md" in captured[0]
    assert "@docs/spec/architecture.md" in captured[0]


def test_agents_evaluate_uses_evaluate_app_type(sample_config, monkeypatch):
    signal = {
        "status": "complete",
        "mode": "EVALUATE",
        "iteration": 1,
        "phase_id": 7,
        "verdict": "APPROVE",
        "issues": [],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    state = _eval_state(app_type="cli")
    state["evaluate"]["app_type"] = "web"
    agents.evaluate("claude-sonnet-4-6", state, 1, "spec", sample_config)
    assert "App type: web" in captured[0]


# --- fix_evaluate_issues ---


def _make_ts_profile(sample_profile):
    return {
        **sample_profile,
        "name": "typescript",
        "test_cmd": ["npx", "vitest", "run"],
        "builder_agent": ".claude/agents/builder-ts.md",
        "rules_file": ".claude/rules/typescript/typescript-standards.md",
    }


def test_author_evaluate_tests_prompt_is_test_only(
    sample_profile, sample_config, monkeypatch
):
    signal = {
        "mode": "EVALUATE_TESTS",
        "phase_id": 2,
        "iteration": 1,
        "tests": [
            {
                "id": "2.1-t1",
                "issue_id": "2.1",
                "status": "authored",
                "files_changed": ["tests/test_bug.py"],
                "command": ["pytest", "tests/test_bug.py", "-q"],
            }
        ],
    }
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append((cmd, input_text, mode))
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    agents.author_evaluate_tests(
        "workspace/evaluate_fix.md",
        [sample_profile],
        sample_config,
        iteration=1,
        eval_phase_id=2,
        spec_context="Spec context marker",
    )

    cmd, prompt, mode = captured[0]
    assert mode == "EVALUATE_TESTS"
    assert "MODE=EVALUATE_TESTS" in prompt
    assert "Write only tests" in prompt
    assert "do not modify application" in prompt
    assert "full regression is run by the harness later" in prompt
    assert "--settings" in cmd


def test_fix_evaluate_issues_prompt_mentions_full_regression_gate(
    sample_profile, sample_config, monkeypatch
):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)

    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md",
        [sample_profile],
        sample_config,
        red_evidence={"commands": [{"cmd": ["pytest", "targeted"], "returncode": 1}]},
    )

    prompt = captured[0]
    assert "Targeted test red-verification evidence" in prompt
    assert "preserve every test authored" in prompt
    assert "full regression" in prompt


def test_merges_builder_files_from_all_profiles(
    sample_profile, sample_config, monkeypatch
):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    ts_profile = _make_ts_profile(sample_profile)
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md", [sample_profile, ts_profile], sample_config
    )
    prompt = captured[0]
    assert sample_profile["builder_agent"] in prompt
    assert ts_profile["builder_agent"] in prompt


def test_deduplicates_shared_builder_files(sample_profile, sample_config, monkeypatch):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md", [sample_profile, sample_profile], sample_config
    )
    prompt = captured[0]
    common = sample_profile["common_rules"]
    assert prompt.count(common) == 1


def test_includes_all_unique_test_commands_in_prompt(
    sample_profile, sample_config, monkeypatch
):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    ts_profile = _make_ts_profile(sample_profile)
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md", [sample_profile, ts_profile], sample_config
    )
    prompt = captured[0]
    assert "pytest" in prompt
    assert "npx vitest run" in prompt


def test_deduplicates_identical_test_commands(
    sample_profile, sample_config, monkeypatch
):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md", [sample_profile, sample_profile], sample_config
    )
    prompt = captured[0]
    assert prompt.count("`pytest`") == 1


def test_fix_evaluate_issues_uses_builder_settings_file(
    sample_profile, sample_config, monkeypatch
):
    signal = {"mode": "FIX", "fixes": []}
    captured_cmd = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured_cmd.append(cmd)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md", [sample_profile], sample_config
    )
    assert "--settings" in captured_cmd[0]
    idx = captured_cmd[0].index("--settings")
    assert captured_cmd[0][idx + 1] == ".claude/settings.builder.json"


def test_fix_evaluate_issues_mode_is_fix(sample_profile, sample_config, monkeypatch):
    signal = {"mode": "FIX", "fixes": []}
    captured = []

    def mock_run(cmd, input_text="", mode="", timeout=None, **kwargs):
        captured.append(input_text)
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md", [sample_profile], sample_config
    )
    assert "MODE=FIX" in captured[0]


def test_agent_prompts_include_spec_context(
    sample_profile, sample_config, sample_state, monkeypatch
):
    captured = []

    def mock_run(cmd, input_text="", mode_arg="", timeout=None, **kwargs):
        captured.append(input_text)
        mode = "FIX" if "MODE=FIX" in captured[-1] else "EXECUTE"
        signal = {
            "status": "complete",
            "mode": mode,
            "phase_id": 1,
            "verdict": "APPROVE",
            "sha_at_review": "abc1234",
            "issues": [],
            "tasks": [
                {
                    "id": "1.1",
                    "title": "T",
                    "task_type": "foundation",
                    "status": "complete",
                    "files_changed": [],
                }
            ],
            "fixes": [],
        }
        return _make_subprocess_result(stdout=_make_envelope(signal))

    monkeypatch.setattr(agents, "run_claude_process", mock_run)
    context = "Spec context marker"
    phase = {"id": 1, "title": "Bootstrap", "description": "Set up."}
    task = {"id": "1.1", "title": "Task", "task_type": "foundation"}

    agents.build_tasks(
        phase, "", sample_profile, sample_config, sample_state, spec_context=context
    )
    agents.execute([task], 1, sample_profile, sample_config, spec_context=context)
    agents.review_phase(
        1, "abc1234", ["spec.md"], sample_profile, sample_config, spec_context=context
    )
    agents.review_fix(
        1,
        ["1.1"],
        "abc1234",
        "def4567",
        ["spec.md"],
        sample_profile,
        sample_config,
        spec_context=context,
    )
    agents.fix_issues(
        "workspace/review_report.md",
        sample_profile,
        sample_config,
        spec_context=context,
    )
    agents.fix_evaluate_issues(
        "workspace/evaluate_fix.md",
        [sample_profile],
        sample_config,
        spec_context=context,
    )

    assert len(captured) == 6
    assert all(context in prompt for prompt in captured)
