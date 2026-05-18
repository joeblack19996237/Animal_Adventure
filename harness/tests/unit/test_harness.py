import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import calibrate as cal_mod
import harness as harness_mod
import phase_handlers
import pytest
import state as state_mod
from harness import (
    Harness,
    HarnessState,
    _has_existing_run,
    _parse_args,
    _pending_tasks,
    _summarize_status,
)
from lang import get_profile
from run_lock import lock_status, release_lock


# --- profile_for ---


@pytest.fixture
def in_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def test_profile_for_returns_correct_profile(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.profiles = {1: get_profile("python"), 2: get_profile("typescript")}
    harness._default_language = "python"
    assert harness.profile_for(2)["name"] == "typescript"


def test_profile_for_applies_config_profile_overrides(
    in_tmp_workspace, sample_config, monkeypatch
):
    sample_config["profile_overrides"] = {"typescript": {"test_cmd": ["npm", "test"]}}
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "typescript"
    harness = Harness(args)
    harness.profiles = {}
    harness._default_language = "typescript"
    assert harness.profile_for(99)["test_cmd"] == ["npm", "test"]


def test_profile_for_falls_back_to_default(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.profiles = {}
    harness._default_language = "python"
    assert harness.profile_for(99)["name"] == "python"


def test_verification_profiles_for_development_returns_primary_profile(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "app_type": "game",
        "phases": [{"id": 1, "phase_type": "development"}],
    }
    harness.profiles = {1: get_profile("python")}

    assert [p["name"] for p in harness.verification_profiles_for(1)] == ["python"]


def test_verification_profiles_for_game_e2e_returns_python_and_typescript(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {"app_type": "game", "phases": [{"id": 8, "phase_type": "e2e"}]}
    harness.profiles = {8: get_profile("typescript")}

    assert [p["name"] for p in harness.verification_profiles_for(8)] == [
        "typescript",
        "python",
    ]


def test_profile_for_remains_single_profile(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {"app_type": "game", "phases": [{"id": 8, "phase_type": "e2e"}]}
    harness.profiles = {8: get_profile("typescript")}

    assert harness.profile_for(8)["name"] == "typescript"


# --- _pending_tasks ---


def test_pending_tasks_returns_pending_only():
    state = {
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "P1",
                "status": "building",
                "tasks": [
                    {"id": "1.1", "status": "pending"},
                    {"id": "1.2", "status": "complete"},
                    {"id": "1.3", "status": "building"},
                ],
                "review": {},
            }
        ],
    }
    result = _pending_tasks(state)
    assert len(result) == 1
    assert result[0]["id"] == "1.1"


def test_pending_tasks_no_phase():
    state = {"current_phase": 99, "phases": [{"id": 1, "tasks": [], "review": {}}]}
    result = _pending_tasks(state)
    assert result == []


def test_has_existing_run_detects_saved_progress():
    assert _has_existing_run({}) is False
    assert _has_existing_run({"spec_file": "docs/spec.md"}) is True
    assert _has_existing_run({"phases": [{"id": 1}]}) is True


def test_non_resume_refuses_to_overwrite_existing_state(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    existing = {
        "spec_file": "docs/spec.md",
        "language": "python",
        "app_type": "cli",
        "current_phase": 2,
        "phases": [{"id": 1, "status": "complete", "tasks": [], "review": {}}],
    }
    state_mod.save_state(existing)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    args = MagicMock()
    args.resume = False
    args.language = "python"
    args.app_type = "cli"
    args.spec_file_or_dir = "docs/spec.md"
    args.max_phase = None
    args.status = False
    args.clear_stale_lock = False
    harness = Harness(args)

    with pytest.raises(SystemExit) as exc:
        harness.run()

    assert exc.value.code == 1
    assert state_mod.load_state()["current_phase"] == 2
    assert lock_status()["active"] is False


def test_status_includes_phase_review_error_and_next_command():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 3,
        "phases": [
            {
                "id": 3,
                "title": "Frontend",
                "status": "building",
                "tasks": [{"id": "3.1", "status": "complete"}],
                "review": {
                    "status": "error",
                    "last_error": ["review failed"],
                    "issues": [],
                },
            }
        ],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["phase_title"] == "Frontend"
    assert summary["harness_state"] == "REVIEWING"
    assert summary["last_error"] == "review failed"
    assert summary["next_command"] == "python harness/harness.py --resume"


def test_status_reports_external_dependency_block():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 2,
        "phases": [
            {
                "id": 2,
                "title": "Backend",
                "status": "building",
                "tasks": [{"id": "2.1", "status": "complete"}],
                "review": {
                    "status": "blocked_external_dependency",
                    "blocked_mode": "FIX",
                    "last_error": ["claude API error 429"],
                },
            }
        ],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["harness_state"] == "FIXING"
    assert summary["review_blocked_mode"] == "FIX"
    assert summary["last_error"] == "claude API error 429"


def test_status_separates_current_and_historical_errors():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "Done",
                "status": "complete",
                "tasks": [],
                "review": {},
                "last_error": ["old phase error"],
            }
        ],
        "evaluate": {
            "status": "complete",
            "last_error": ["old evaluate 429"],
            "iterations": [{"iteration": 1, "verdict": "APPROVE"}],
        },
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["last_error"] is None
    assert summary["historical_last_error"] == "old evaluate 429"


def test_status_reports_current_evaluate_error_fields():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {"id": 1, "title": "Done", "status": "complete", "tasks": [], "review": {}}
        ],
        "evaluate": {
            "status": "timeout",
            "current_iteration": 2,
            "attempts": 4,
            "last_error": ["timeout after 600s"],
            "iterations": [{"iteration": 1, "verdict": "APPROVE"}],
        },
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["harness_state"] == "EVALUATING"
    assert summary["last_error"] == "timeout after 600s"
    assert summary["historical_last_error"] == "timeout after 600s"
    assert summary["evaluate_current_iteration"] == 2
    assert summary["evaluate_attempts"] == 4


def test_status_reports_cleanup_error():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "Done",
                "status": "complete",
                "tasks": [],
                "review": {},
            }
        ],
        "cleanup": {"status": "error", "last_error": ["cleanup parser failed"]},
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["harness_state"] == "CLEANUP"
    assert summary["last_error"] == "cleanup parser failed"


def test_status_does_not_mutate_state():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }
    before = repr(state)
    _summarize_status(state, {"active": False})
    assert repr(state) == before


def test_summarize_status_includes_blocked_task():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "Backend",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Implement auth",
                        "status": "blocked_external_dependency",
                        "last_error": ["claude auth 429"],
                    }
                ],
                "review": {},
            }
        ],
    }
    summary = _summarize_status(state, {"active": False})
    assert len(summary["blocked_tasks"]) == 1
    assert summary["blocked_tasks"][0]["id"] == "1.1"
    assert summary["blocked_tasks"][0]["last_error"] == ["claude auth 429"]


def test_summarize_status_blocked_task_appears_in_last_error():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "Backend",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Implement auth",
                        "status": "blocked_external_dependency",
                        "last_error": ["rate limit hit"],
                    }
                ],
                "review": {},
            }
        ],
    }
    summary = _summarize_status(state, {"active": False})
    assert summary["last_error"] == "rate limit hit"


def test_summarize_status_error_task_appears_in_last_error():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 5,
        "phases": [
            {
                "id": 5,
                "title": "Frontend Foundation",
                "status": "building",
                "tasks": [
                    {"id": "5.4", "status": "complete", "last_error": []},
                    {
                        "id": "5.5",
                        "status": "error",
                        "last_error": [
                            "claude exited with code 1: API Error: Unable to connect to API (ConnectionRefused)"
                        ],
                    },
                    {"id": "5.6", "status": "pending", "last_error": []},
                ],
                "review": {},
            }
        ],
    }
    summary = _summarize_status(state, {"active": False})
    assert "ConnectionRefused" in summary["last_error"]


def test_summarize_status_includes_active_and_error_tasks():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 7,
        "phases": [
            {
                "id": 7,
                "title": "Login",
                "status": "building",
                "tasks": [
                    {"id": "7.1", "title": "API client", "status": "building"},
                    {
                        "id": "7.2",
                        "title": "Session state",
                        "status": "error",
                        "last_error": ["tests failed"],
                    },
                ],
                "review": {},
            }
        ],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["active_tasks"][0]["id"] == "7.1"
    assert summary["error_tasks"][0]["id"] == "7.2"
    assert summary["error_tasks"][0]["last_error"] == ["tests failed"]


def test_summarize_status_includes_error_issues_and_prefers_issue_error():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 8,
        "phases": [
            {
                "id": 8,
                "title": "Player Session Integration",
                "status": "building",
                "tasks": [{"id": "8.1", "title": "Session", "status": "complete"}],
                "review": {
                    "status": "blocked_external_dependency",
                    "blocked_mode": "FIX",
                    "last_error": ["stale 429 preflight error"],
                    "issues": [
                        {
                            "id": "8.1",
                            "title": "Fix session login",
                            "status": "error",
                            "attempts": 2,
                            "last_error": [
                                "claude exited with code 1: API Error: Unable to connect to API (ConnectionRefused)"
                            ],
                        }
                    ],
                },
            }
        ],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["error_issues"][0]["id"] == "8.1"
    assert "ConnectionRefused" in summary["last_error"]
    assert summary["last_error"] != "stale 429 preflight error"


def test_summarize_status_marks_stale_lock():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"pid": 123, "active": False})

    assert summary["stale_lock"] is True


def test_approx_harness_state_halted_when_task_has_error():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 5,
        "phases": [
            {
                "id": 5,
                "title": "Frontend Foundation",
                "status": "building",
                "tasks": [
                    {"id": "5.4", "status": "complete", "last_error": []},
                    {
                        "id": "5.5",
                        "status": "error",
                        "last_error": ["claude exited with code 1: ConnectionRefused"],
                    },
                    {"id": "5.6", "status": "pending", "last_error": []},
                ],
                "review": {},
            }
        ],
    }
    summary = _summarize_status(state, {"active": False})
    assert summary["harness_state"] == "HALTED"


def test_summarize_status_includes_halted_task_and_issue_reason():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 5,
        "phases": [
            {
                "id": 5,
                "title": "Frontend Foundation",
                "status": "building",
                "tasks": [
                    {
                        "id": "5.5",
                        "title": "Build UI",
                        "status": "halted",
                        "last_error": ["agent completed task but created no commit"],
                    }
                ],
                "review": {
                    "status": "fixing",
                    "issues": [
                        {
                            "id": "5.1",
                            "title": "Review issue",
                            "status": "halted",
                            "attempts": 0,
                            "last_error": ["claimed fixed but no commit was created"],
                        }
                    ],
                },
            }
        ],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["harness_state"] == "HALTED"
    assert summary["halted_tasks"][0]["last_error"] == [
        "agent completed task but created no commit"
    ]
    assert summary["halted_issues"][0]["last_error"] == [
        "claimed fixed but no commit was created"
    ]
    assert summary["last_error"] == "agent completed task but created no commit"


def test_summarize_status_no_blocked_tasks_when_all_pending():
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "Backend",
                "status": "building",
                "tasks": [{"id": "1.1", "status": "pending"}],
                "review": {},
            }
        ],
    }
    summary = _summarize_status(state, {"active": False})
    assert summary["blocked_tasks"] == []


def test_status_reports_recent_claude_event_anomalies(
    in_tmp_workspace, sample_config, monkeypatch
):
    events_path = Path("workspace/events.jsonl")
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "claude_subprocess_start",
                        "mode": "EXECUTE",
                        "ts": "2026-05-16T01:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "event": "claude_subprocess_end",
                        "mode": "EXECUTE",
                        "returncode": 1,
                        "ts": "2026-05-16T01:01:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "event": "claude_subprocess_start",
                        "mode": "EXECUTE",
                        "ts": "2026-05-16T01:02:00+00:00",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(harness_mod, "EVENTS_PATH", events_path)
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"active": False})

    recent = summary["recent_claude_events"]
    assert recent["recent_nonzero_end"][0]["returncode"] == 1
    assert recent["unmatched_starts"][0]["ts"] == "2026-05-16T01:02:00+00:00"


def test_recent_claude_events_matches_start_end_by_pid(
    in_tmp_workspace, sample_config, monkeypatch
):
    events_path = Path("workspace/events.jsonl")
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "claude_subprocess_start",
                        "mode": "EXECUTE",
                        "pid": 111,
                        "ts": "2026-05-16T01:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "event": "claude_subprocess_start",
                        "mode": "EXECUTE",
                        "pid": 222,
                        "ts": "2026-05-16T01:01:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "event": "claude_subprocess_end",
                        "mode": "EXECUTE",
                        "pid": 111,
                        "returncode": 0,
                        "ts": "2026-05-16T01:02:00+00:00",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(harness_mod, "EVENTS_PATH", events_path)

    status = harness_mod._recent_claude_event_status()

    assert status["unmatched_starts"] == [
        {
            "ts": "2026-05-16T01:01:00+00:00",
            "event": "claude_subprocess_start",
            "mode": "EXECUTE",
            "call_id": None,
            "pid": 222,
            "returncode": None,
            "timeout": None,
            "elapsed": None,
            "stderr_tail": "",
            "reason": "",
        }
    ]


def test_status_reports_external_dependency_context(monkeypatch):
    monkeypatch.setattr(
        harness_mod.external_dependency,
        "load_context",
        lambda: {
            "mode": "EXECUTE",
            "root_pid": 999,
            "reset_at": "2026-05-16T01:20:00+00:00",
            "cleanup_status": "clean",
            "quarantined_files": ["app/db.py"],
        },
    )
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"active": True})

    assert summary["external_dependency_wait"]["mode"] == "EXECUTE"
    assert summary["external_dependency_wait"]["root_pid"] == 999
    assert summary["external_dependency_wait"]["cleanup_status"] == "clean"


def test_status_reports_external_dependency_orphan_processes(monkeypatch):
    monkeypatch.setattr(
        harness_mod.external_dependency,
        "load_context",
        lambda: {
            "mode": "FIX",
            "root_pid": 123,
            "reset_at": "2026-05-16T01:20:00+00:00",
            "cleanup_status": "clean",
            "process_cleanup": {"attempted": True, "ok": True, "error": ""},
            "claude_processes_after_cleanup": [
                {"pid": 789, "name": "claude", "path": "", "start_time": ""}
            ],
            "possible_orphan_processes": [
                {"pid": 789, "name": "claude", "path": "", "start_time": ""}
            ],
        },
    )
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"active": True})

    wait = summary["external_dependency_wait"]
    assert wait["root_pid"] == 123
    assert wait["claude_processes_after_cleanup"][0]["pid"] == 789
    assert wait["possible_orphan_processes"][0]["pid"] == 789


def test_status_reports_usage_window_summary(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    usage = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase_id": 5,
        "task_id": "5.4",
        "mode": "EXECUTE",
        "actual_input_tokens": 10,
        "actual_output_tokens": 20,
        "cache_read_tokens": 100,
        "cache_write_tokens": 200,
    }
    Path("workspace/usage.jsonl").write_text(json.dumps(usage), encoding="utf-8")
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["usage_window"]["calls"] == 1
    assert summary["usage_window"]["actual_tokens"] == 30
    assert summary["usage_window"]["cache_tokens"] == 300


def test_status_reports_last_claude_usage(in_tmp_workspace, sample_config, monkeypatch):
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    usage = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase_id": 5,
        "task_id": "5.4",
        "mode": "EXECUTE",
        "actual_input_tokens": 10,
        "actual_output_tokens": 20,
    }
    Path("workspace/usage.jsonl").write_text(json.dumps(usage), encoding="utf-8")
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["last_claude_usage"]["task_id"] == "5.4"
    assert summary["last_claude_usage"]["actual_tokens"] == 30


def test_status_reports_external_dependency_remaining_seconds(monkeypatch):
    reset_at = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
    monkeypatch.setattr(
        harness_mod.external_dependency,
        "load_context",
        lambda: {
            "mode": "EXECUTE",
            "reset_at": reset_at,
            "cleanup_status": "clean",
            "process_cleanup": {"attempted": True, "ok": True, "error": ""},
        },
    )

    status = harness_mod._external_dependency_wait_status()

    assert 0 <= status["remaining_seconds"] <= 90
    assert status["process_cleanup_attempted"] is True
    assert status["process_cleanup_ok"] is True


def test_status_reports_latest_resume_claude_cleanup(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    Path("workspace/events.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-05-17T00:00:00Z",
                "event": "resume_claude_cleanup_end",
                "attempted": True,
                "protection_incomplete": False,
                "protected_pids": [10],
                "candidate_pids": [20],
                "killed_pids": [20],
                "skipped_pids": [10],
                "errors": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state = {
        "spec_file": "docs/spec.md",
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    summary = _summarize_status(state, {"active": False})

    assert summary["resume_claude_cleanup"]["attempted"] is True
    assert summary["resume_claude_cleanup"]["protected_pids"] == [10]
    assert summary["resume_claude_cleanup"]["killed_pids"] == [20]


def test_status_reports_stale_execution_with_live_unmatched_pid(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "process_exists", lambda pid: pid == 222)
    Path("workspace/events.jsonl").write_text(
        json.dumps(
            {
                "event": "claude_subprocess_start",
                "mode": "EXECUTE",
                "pid": 222,
                "call_id": "execute-live",
                "ts": "2026-05-17T08:31:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 9,
        "phases": [
            {
                "id": 9,
                "title": "WebSocket",
                "status": "building",
                "tasks": [{"id": "9.1", "status": "building", "last_error": []}],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }

    summary = _summarize_status(
        state,
        {
            "pid": 999999,
            "active": False,
            "started_at": "2026-05-17T08:30:00+00:00",
        },
    )

    assert summary["stale_execution"]["detected"] is True
    assert summary["stale_execution"]["live_unmatched_pids"] == [222]
    assert summary["current_run_claude_events"]["unmatched_starts"][0][
        "pid_active"
    ] is True


def test_status_filters_current_run_unmatched_starts_by_lock_started_at(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "process_exists", lambda pid: False)
    Path("workspace/events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "claude_subprocess_start",
                        "mode": "EXECUTE",
                        "pid": 111,
                        "ts": "2026-05-17T08:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "event": "claude_subprocess_start",
                        "mode": "EXECUTE",
                        "pid": 222,
                        "ts": "2026-05-17T08:31:00+00:00",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    state = {
        "spec_file": "docs/spec.md",
        "current_phase": 9,
        "phases": [
            {
                "id": 9,
                "status": "building",
                "tasks": [{"id": "9.1", "status": "building"}],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }

    summary = _summarize_status(
        state,
        {
            "pid": 999999,
            "active": False,
            "started_at": "2026-05-17T08:30:00+00:00",
        },
    )

    assert [e["pid"] for e in summary["recent_claude_events"]["unmatched_starts"]] == [
        111,
        222,
    ]
    assert [
        e["pid"]
        for e in summary["current_run_claude_events"]["unmatched_starts"]
    ] == [222]


def test_derive_state_runs_resume_preflight(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    preflight = MagicMock(return_value={"ok": True, "context_present": True})
    monkeypatch.setattr(harness_mod.external_dependency, "preflight_context", preflight)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness._load_spec_into_memory = MagicMock()
    harness.state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    assert harness._derive_state() == HarnessState.TASK_BUILD
    preflight.assert_called_once_with(allow_quarantine=False)


def test_derive_state_blocks_when_resume_preflight_fails(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(
        harness_mod.external_dependency,
        "preflight_context",
        lambda allow_quarantine: {
            "ok": False,
            "tracked_dirty_files": ["app/db.py"],
        },
    )
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }

    with pytest.raises(SystemExit):
        harness._derive_state()


# --- EVALUATING: _derive_state ---


def _all_complete_state() -> dict:
    return {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "app_type": "cli",
        "phases": [{"id": 1, "status": "complete", "tasks": [], "review": {}}],
    }


def test_derive_state_returns_evaluating_when_status_evaluating(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        **_all_complete_state(),
        "evaluate": {"status": "evaluating", "phase_id": 2, "iterations": []},
    }
    assert harness._derive_state() == HarnessState.EVALUATING


def test_derive_state_returns_evaluating_when_status_timeout(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        **_all_complete_state(),
        "evaluate": {"status": "timeout", "phase_id": 2, "iterations": []},
    }
    assert harness._derive_state() == HarnessState.EVALUATING


def test_derive_state_exits_when_status_halted(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        **_all_complete_state(),
        "evaluate": {"status": "halted", "phase_id": 2, "iterations": []},
    }
    with pytest.raises(SystemExit) as exc:
        harness._derive_state()
    assert exc.value.code == 1


def test_derive_state_evaluating_check_before_phases_loop(
    in_tmp_workspace, sample_config, monkeypatch
):
    """All phases complete AND evaluate=evaluating → EVALUATING, not CLEANUP."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        **_all_complete_state(),
        "evaluate": {"status": "evaluating", "phase_id": 2, "iterations": []},
    }
    assert harness._derive_state() == HarnessState.EVALUATING


def test_derive_state_returns_cleanup_when_cleanup_status_error(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        **_all_complete_state(),
        "cleanup": {"status": "error", "last_error": ["cleanup parser failed"]},
    }
    assert harness._derive_state() == HarnessState.CLEANUP


def test_derive_state_review_error_with_complete_tasks_returns_reviewing(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {"status": "error", "last_error": ["timeout"], "issues": []},
            }
        ],
    }
    assert harness._derive_state() == HarnessState.REVIEWING


def test_derive_state_empty_building_tasks_returns_task_build(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }
    monkeypatch.setattr(harness, "_load_spec_into_memory", MagicMock())

    assert harness._derive_state() == HarnessState.TASK_BUILD
    harness._load_spec_into_memory.assert_called_once()


def test_derive_state_phase_error_still_returns_task_build_for_task_build_failure(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [{"id": 1, "status": "error", "tasks": [], "review": {}}],
    }
    monkeypatch.setattr(harness, "_load_spec_into_memory", lambda: None)
    assert harness._derive_state() == HarnessState.TASK_BUILD


def test_phase_external_block_resumes_task_build(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "blocked_external_dependency",
                "tasks": [],
                "review": {},
            }
        ],
    }
    monkeypatch.setattr(harness, "_load_spec_into_memory", lambda: None)
    assert harness._derive_state() == HarnessState.TASK_BUILD


def test_task_external_block_resets_to_pending_on_resume(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    task = {"id": "1.1", "status": "blocked_external_dependency"}
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [task],
                "review": {"status": "pending"},
            }
        ],
    }
    assert harness._derive_state() == HarnessState.EXECUTING
    assert task["status"] == "pending"


def test_review_external_block_review_mode_resumes_reviewing(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {
                    "status": "blocked_external_dependency",
                    "blocked_mode": "REVIEW",
                },
            }
        ],
    }
    assert harness._derive_state() == HarnessState.REVIEWING


def test_review_external_block_fix_mode_resumes_fixing(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {
                    "status": "blocked_external_dependency",
                    "blocked_mode": "FIX",
                },
            }
        ],
    }
    assert harness._derive_state() == HarnessState.FIXING


def test_derive_state_resets_building_task_to_pending(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    task = {"id": "1.1", "status": "building"}
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [task],
                "review": {"status": "pending"},
            }
        ],
    }
    assert harness._derive_state() == HarnessState.EXECUTING
    assert task["status"] == "pending"


def test_completed_tasks_are_not_reset(in_tmp_workspace, sample_config, monkeypatch):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [
                    {"id": "1.1", "status": "complete"},
                    {"id": "1.2", "status": "building"},
                ],
                "review": {"status": "pending"},
            }
        ],
    }
    harness._derive_state()
    statuses = [t["status"] for t in harness.state["phases"][0]["tasks"]]
    assert statuses == ["complete", "pending"]


def test_resume_approved_phase_completes_via_next_phase(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 2,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {
                    "status": "complete",
                    "verdict": "APPROVE",
                    "sha_at_review": "def456",
                    "issues": [],
                },
                "regression": {"status": "passed"},
            },
            {
                "id": 2,
                "status": "pending",
                "tasks": [],
                "review": {"status": "pending"},
            },
        ],
    }

    assert harness._derive_state() == HarnessState.NEXT_PHASE

    from phase_handlers import handle_next_phase

    assert handle_next_phase(harness, harness.state, 1) == HarnessState.TASK_BUILD
    assert harness.state["phases"][0]["status"] == "complete"
    assert harness.state["current_phase"] == 2


def test_resume_fixed_phase_completes_via_next_phase(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 2,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {
                    "status": "fixed",
                    "verdict": "BLOCK",
                    "sha_at_review": "def456",
                    "issues": [{"id": "1.1", "status": "fixed"}],
                },
                "regression": {"status": "passed"},
            },
            {
                "id": 2,
                "status": "pending",
                "tasks": [],
                "review": {"status": "pending"},
            },
        ],
    }

    assert harness._derive_state() == HarnessState.NEXT_PHASE

    from phase_handlers import handle_next_phase

    assert handle_next_phase(harness, harness.state, 1) == HarnessState.TASK_BUILD
    assert harness.state["phases"][0]["status"] == "complete"
    assert harness.state["current_phase"] == 2


def test_resume_final_approved_phase_returns_next_phase_then_cleanup(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {
                    "status": "complete",
                    "verdict": "APPROVE",
                    "sha_at_review": "def456",
                    "issues": [],
                },
                "regression": {"status": "passed"},
            }
        ],
    }

    assert harness._derive_state() == HarnessState.NEXT_PHASE

    from phase_handlers import handle_next_phase

    assert handle_next_phase(harness, harness.state, 1) == HarnessState.CLEANUP
    assert harness.state["phases"][0]["status"] == "complete"


def test_resume_approved_phase_without_regression_enters_regression_testing(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness.state = {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "complete"}],
                "review": {
                    "status": "complete",
                    "verdict": "APPROVE",
                    "sha_at_review": "def456",
                    "issues": [],
                },
            }
        ],
    }

    assert harness._derive_state() == HarnessState.REGRESSION_TESTING


# --- EVALUATING: run() transitions ---


def _make_resume_harness(
    in_tmp_workspace_fixture, sample_config, monkeypatch, state: dict
) -> Harness:
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: {"attempted": True},
    )
    state_mod.save_state(state)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = None
    args.app_type = "cli"
    return Harness(args)


def test_resume_calls_process_cleanup_after_lock_before_derive_state(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    calls = []
    state = {
        "spec_file": "docs/spec.md",
        "language": "python",
        "app_type": "cli",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }
    state_mod.save_state(state)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: calls.append("git"))
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: calls.append("cleanup") or {"attempted": True},
    )
    monkeypatch.setattr(
        Harness, "_derive_state", lambda self: calls.append("derive") or HarnessState.COMPLETE
    )
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = None
    args.app_type = "cli"
    args.status = False
    args.clear_stale_lock = False

    Harness(args).run()

    assert calls == ["git", "cleanup", "derive"]
    assert lock_status()["active"] is False


def test_resume_records_stale_lock_context_before_acquire(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    Path("workspace/run.lock").write_text(
        json.dumps({"pid": 999999999, "started_at": "2026-05-17T08:00:00+00:00"}),
        encoding="utf-8",
    )
    captured = {}
    state = {
        "spec_file": "docs/spec.md",
        "language": "python",
        "app_type": "cli",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "pending", "tasks": [], "review": {}}],
    }
    state_mod.save_state(state)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: {"attempted": True, "unsafe_to_resume": False},
    )

    def capture_recovery(state, *, lock_context, cleanup_result):
        captured["lock_context"] = lock_context
        return {"action": "noop"}

    monkeypatch.setattr(
        harness_mod.resume_recovery,
        "recover_or_block_stale_execution",
        capture_recovery,
    )
    monkeypatch.setattr(Harness, "_derive_state", lambda self: HarnessState.COMPLETE)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = None
    args.app_type = "cli"
    args.status = False
    args.clear_stale_lock = False

    Harness(args).run()

    assert captured["lock_context"]["stale_lock_at_start"] is True
    assert captured["lock_context"]["lock"]["pid"] == 999999999
    assert lock_status()["active"] is False


def test_resume_blocks_stale_execution_when_cleanup_unsafe(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    Path("workspace/run.lock").write_text(
        json.dumps({"pid": 999999999, "started_at": "2026-05-17T08:00:00+00:00"}),
        encoding="utf-8",
    )
    state = {
        "spec_file": "docs/spec.md",
        "language": "python",
        "app_type": "cli",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "building", "last_error": []}],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }
    state_mod.save_state(state)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: {
            "attempted": True,
            "protection_incomplete": True,
            "candidate_pids": [123],
            "unsafe_to_resume": True,
        },
    )
    monkeypatch.setattr(
        Harness,
        "_derive_state",
        lambda self: (_ for _ in ()).throw(
            AssertionError("_derive_state must not run when recovery blocks")
        ),
    )
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = None
    args.app_type = "cli"
    args.status = False
    args.clear_stale_lock = False

    with pytest.raises(SystemExit) as exc:
        Harness(args).run()

    assert exc.value.code == 1
    assert state_mod.load_state()["phases"][0]["tasks"][0]["status"] == "building"
    assert lock_status()["active"] is False


def test_resume_recovers_stale_execution_when_cleanup_safe(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    Path("workspace/run.lock").write_text(
        json.dumps({"pid": 999999999, "started_at": "2026-05-17T08:00:00+00:00"}),
        encoding="utf-8",
    )
    state = {
        "spec_file": "docs/spec.md",
        "language": "python",
        "app_type": "cli",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "status": "building",
                "tasks": [{"id": "1.1", "status": "building", "last_error": []}],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }
    state_mod.save_state(state)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: {
            "attempted": True,
            "protection_incomplete": False,
            "candidate_pids": [],
            "unsafe_to_resume": False,
            "errors": [],
        },
    )
    monkeypatch.setattr(Harness, "_derive_state", lambda self: HarnessState.COMPLETE)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = None
    args.app_type = "cli"
    args.status = False
    args.clear_stale_lock = False

    Harness(args).run()

    assert state_mod.load_state()["phases"][0]["tasks"][0]["status"] == "pending"
    assert lock_status()["active"] is False


def test_fresh_run_does_not_call_resume_process_cleanup(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: (_ for _ in ()).throw(
            AssertionError("fresh run must not cleanup stale Claude processes")
        ),
    )
    args = MagicMock()
    args.resume = False
    args.language = "python"
    args.app_type = "cli"
    args.spec_file_or_dir = ""
    args.max_phase = None
    args.status = False
    args.clear_stale_lock = False
    harness = Harness(args)

    with pytest.raises(SystemExit):
        harness.run()


def test_cleanup_transitions_to_evaluating(
    in_tmp_workspace, sample_config, monkeypatch
):
    evaluate_called = []
    monkeypatch.setattr(harness_mod, "run_cleanup", lambda h, s: None)
    monkeypatch.setattr(
        harness_mod, "run_evaluate_cycle", lambda h, s: evaluate_called.append(True)
    )
    harness = _make_resume_harness(
        in_tmp_workspace, sample_config, monkeypatch, _all_complete_state()
    )
    harness.run()
    assert evaluate_called


def test_evaluating_transitions_to_complete_on_approve(
    in_tmp_workspace, sample_config, monkeypatch
):
    evaluate_called = []
    monkeypatch.setattr(
        harness_mod, "run_evaluate_cycle", lambda h, s: evaluate_called.append(True)
    )
    state = {
        **_all_complete_state(),
        "evaluate": {"status": "evaluating", "phase_id": 2, "iterations": []},
    }
    harness = _make_resume_harness(in_tmp_workspace, sample_config, monkeypatch, state)
    harness.run()
    assert evaluate_called


def test_run_preserves_lock_on_unexpected_exception(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    state = {
        "spec_file": "spec.md",
        "language": "python",
        "app_type": "cli",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
                {
                    "id": 1,
                    "title": "Phase One",
                    "language": "python",
                    "phase_type": "setup",
                    "status": "building",
                    "tasks": [{"id": "1.1", "status": "pending"}],
                    "review": {"status": "pending", "issues": []},
                }
            ],
    }
    state_mod.save_state(state)
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: {"attempted": True},
    )
    monkeypatch.setattr(phase_handlers, "handle_executing", lambda *a, **kw: object())
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = None
    args.app_type = "cli"
    args.status = False
    args.clear_stale_lock = False
    harness = Harness(args)

    try:
        with pytest.raises(RuntimeError, match="Unhandled harness state"):
            harness.run()

        assert lock_status()["active"] is True
    finally:
        release_lock()


def test_run_releases_lock_on_controlled_system_exit(
    in_tmp_workspace, sample_config, monkeypatch
):
    release_lock()
    existing = {
        "spec_file": "docs/spec.md",
        "language": "python",
        "app_type": "cli",
        "current_phase": 1,
        "phases": [{"id": 1, "status": "complete", "tasks": [], "review": {}}],
    }
    state_mod.save_state(existing)
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    args = MagicMock()
    args.resume = False
    args.language = "python"
    args.app_type = "cli"
    args.spec_file_or_dir = "docs/spec.md"
    args.max_phase = None
    args.status = False
    args.clear_stale_lock = False
    harness = Harness(args)

    with pytest.raises(SystemExit):
        harness.run()

    assert lock_status()["active"] is False


# --- EVALUATING: __init__ and argparse ---


def test_workspace_screenshots_created_on_init(
    in_tmp_workspace, sample_config, monkeypatch
):
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    args = MagicMock()
    args.resume = True
    args.language = "python"
    Harness(args)
    assert Path("workspace/screenshots").exists()


def test_app_type_game_accepted():
    old_argv = sys.argv
    sys.argv = ["harness.py", "--resume", "--app-type", "game"]
    try:
        args = _parse_args()
        assert args.app_type == "game"
    finally:
        sys.argv = old_argv


def test_max_phase_does_not_block_evaluating(
    in_tmp_workspace, sample_config, monkeypatch
):
    """max_phase == total_phases should not prevent EVALUATING from running."""
    evaluate_called = []
    monkeypatch.setattr(
        harness_mod, "run_evaluate_cycle", lambda h, s: evaluate_called.append(True)
    )
    state = {
        **_all_complete_state(),
        "evaluate": {"status": "evaluating", "phase_id": 2, "iterations": []},
    }
    state_mod.save_state(state)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda s: None)
    monkeypatch.setattr(
        harness_mod.resume_process_cleanup,
        "cleanup_stale_claude_processes",
        lambda: {"attempted": True},
    )
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.max_phase = 1  # equals total_phases — guard must not fire
    args.app_type = "cli"
    harness = Harness(args)
    harness.run()
    assert evaluate_called
