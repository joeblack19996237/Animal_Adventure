import json
from datetime import datetime, timedelta, timezone

import pytest

from calibrate import (
    claude_session_pacing_delay,
    get_artifact_limits,
    log_usage,
    get_task_planning_limits,
    get_usage_guardrails,
    recent_usage_summary,
    usage_token_totals,
)


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)


def test_log_usage_fields(tmp_workspace):
    usage = {
        "input_tokens": 5000,
        "output_tokens": 2000,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 50,
    }
    log_usage("1.1", 1, "EXECUTE", usage, 3, "foundation")
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["actual_input_tokens"] == 5000
    assert entry["actual_output_tokens"] == 2000
    assert entry["cache_read_tokens"] == 100
    assert entry["cache_write_tokens"] == 50
    assert entry["task_type"] == "foundation"
    assert entry["files_changed"] == 3
    assert "estimated_input_tokens" not in entry
    assert "overhead_actual" not in entry
    assert "estimation_error" not in entry
    assert "usage_missing" not in entry


def test_log_usage_writes_call_id_when_provided(tmp_workspace):
    log_usage(
        "1.1",
        1,
        "EXECUTE",
        {"input_tokens": 1, "output_tokens": 2},
        3,
        "foundation",
        call_id="execute-abc",
    )
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["call_id"] == "execute-abc"


def test_log_usage_call_id_is_optional(tmp_workspace):
    log_usage("1.1", 1, "EXECUTE", {"input_tokens": 1, "output_tokens": 2}, 3)
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["call_id"] is None


def test_log_usage_missing_input_tokens_does_not_crash(tmp_workspace):
    log_usage("1.1", 1, "EXECUTE", {"output_tokens": 2000}, 3, "foundation")
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["actual_input_tokens"] == 0
    assert entry["actual_output_tokens"] == 2000


def test_log_usage_missing_output_tokens_does_not_crash(tmp_workspace):
    log_usage("1.1", 1, "EXECUTE", {"input_tokens": 5000}, 3, "foundation")
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["actual_input_tokens"] == 5000
    assert entry["actual_output_tokens"] == 0


def test_log_usage_marks_usage_missing_when_core_fields_absent(tmp_workspace):
    log_usage("1.1", 1, "EXECUTE", {}, 3, "foundation")
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["usage_missing"] is True


def test_log_usage_does_not_mark_usage_missing_when_core_fields_present(tmp_workspace):
    log_usage("1.1", 1, "EXECUTE", {"input_tokens": 1, "output_tokens": 2}, 3, "foundation")
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert "usage_missing" not in entry


def test_usage_token_totals_separates_actual_and_cache_tokens():
    totals = usage_token_totals(
        {
            "actual_input_tokens": 10,
            "actual_output_tokens": 20,
            "cache_read_tokens": 100,
            "cache_write_tokens": 200,
        }
    )
    assert totals == {
        "actual_tokens": 30,
        "cache_tokens": 300,
        "combined_tokens": 330,
    }


def test_recent_usage_summary_filters_to_window(tmp_workspace):
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    path = tmp_workspace / "workspace" / "usage.jsonl"
    old = {
        "ts": (now - timedelta(hours=6)).isoformat(),
        "mode": "EXECUTE",
        "actual_input_tokens": 100,
        "actual_output_tokens": 100,
    }
    recent = {
        "ts": (now - timedelta(minutes=5)).isoformat(),
        "mode": "EXECUTE",
        "actual_input_tokens": 10,
        "actual_output_tokens": 20,
    }
    path.write_text(json.dumps(old) + "\n" + json.dumps(recent) + "\n", encoding="utf-8")

    summary = recent_usage_summary(window_seconds=18000, now=now)

    assert summary["calls"] == 1
    assert summary["actual_tokens"] == 30


def test_recent_usage_summary_groups_by_mode(tmp_workspace):
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entries = [
        {
            "ts": now.isoformat(),
            "mode": "EXECUTE",
            "actual_input_tokens": 1,
            "actual_output_tokens": 2,
        },
        {
            "ts": now.isoformat(),
            "mode": "REVIEW",
            "actual_input_tokens": 3,
            "actual_output_tokens": 4,
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    summary = recent_usage_summary(window_seconds=18000, now=now)

    assert summary["by_mode"]["EXECUTE"]["actual_tokens"] == 3
    assert summary["by_mode"]["REVIEW"]["actual_tokens"] == 7


def test_recent_usage_summary_returns_top_recent_calls(tmp_workspace):
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    path = tmp_workspace / "workspace" / "usage.jsonl"
    entries = [
        {
            "ts": now.isoformat(),
            "mode": "EXECUTE",
            "phase_id": 1,
            "task_id": f"1.{i}",
            "actual_input_tokens": i,
            "actual_output_tokens": 0,
        }
        for i in range(4)
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    summary = recent_usage_summary(window_seconds=18000, now=now, top_n=2)

    assert [c["task_id"] for c in summary["top_recent_calls"]] == ["1.2", "1.3"]


def test_recent_usage_summary_handles_missing_usage_file():
    summary = recent_usage_summary()
    assert summary["calls"] == 0
    assert summary["actual_tokens"] == 0


def test_claude_session_pacing_delay_uses_recent_call_interval(tmp_workspace):
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    path = tmp_workspace / "workspace" / "usage.jsonl"
    path.write_text(
        json.dumps(
            {
                "ts": (now - timedelta(seconds=10)).isoformat(),
                "mode": "EXECUTE",
                "actual_input_tokens": 1,
                "actual_output_tokens": 1,
            }
        ),
        encoding="utf-8",
    )
    config = {"claude_session_pacing": {"min_seconds_between_calls": 60}}

    delay = claude_session_pacing_delay(config, now=now)

    assert delay == (50.0, "min_interval")


def test_claude_session_pacing_delay_uses_large_output_cooldown(tmp_workspace):
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    path = tmp_workspace / "workspace" / "usage.jsonl"
    path.write_text(
        json.dumps(
            {
                "ts": (now - timedelta(seconds=30)).isoformat(),
                "mode": "EXECUTE",
                "actual_input_tokens": 1,
                "actual_output_tokens": 20000,
            }
        ),
        encoding="utf-8",
    )
    config = {
        "claude_session_pacing": {
            "min_seconds_between_calls": 60,
            "large_output_token_threshold": 15000,
            "large_output_cooldown_seconds": 180,
        }
    }

    delay = claude_session_pacing_delay(config, now=now)

    assert delay == (150.0, "large_output_cooldown")


def test_task_planning_limits_defaults_are_valid():
    limits = get_task_planning_limits({})
    assert limits["enabled"] is True
    assert limits["max_tasks_per_development_phase"] == 10
    assert limits["allow_legacy_tdd_triplets"] is False


def test_artifact_limits_defaults_are_valid():
    assert get_artifact_limits({})["max_new_test_file_lines"] == 250


def test_usage_guardrails_defaults_are_valid():
    guardrails = get_usage_guardrails({})
    assert guardrails["enabled"] is True
    assert guardrails["max_single_output_tokens"] == 15000
