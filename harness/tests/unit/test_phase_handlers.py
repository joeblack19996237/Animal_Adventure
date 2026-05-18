"""Regression tests for phase_handlers.py"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agents
import phase_handlers as ph_mod
import state as state_mod
import verify as verify_mod
from phase_handlers import (
    handle_executing,
    handle_fixing,
    handle_next_phase,
    handle_regression_testing,
    handle_reviewing,
    handle_task_build,
)
from state import save_state


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def _make_harness(sample_config):
    h = MagicMock()
    h.config = sample_config
    return h


def _mark_regression_passed(state, phase_id=1):
    for phase in state["phases"]:
        if phase["id"] == phase_id:
            phase["regression"] = {"status": "passed"}
            return


# ── handle_next_phase ────────────────────────────────────────────────────────


def test_handle_next_phase_returns_cleanup_when_beyond_total_phases(
    sample_state, sample_config
):
    from harness import HarnessState

    save_state(sample_state)
    _mark_regression_passed(sample_state)
    result = handle_next_phase(_make_harness(sample_config), sample_state, phase_id=1)
    assert result == HarnessState.CLEANUP


def test_phase_handlers_return_canonical_harness_state(sample_state, sample_config):
    from harness import HarnessState as ExportedState
    from harness_state import HarnessState as CanonicalState

    save_state(sample_state)
    _mark_regression_passed(sample_state)
    result = handle_next_phase(_make_harness(sample_config), sample_state, phase_id=1)

    assert result is CanonicalState.CLEANUP
    assert result is ExportedState.CLEANUP


def test_handle_next_phase_returns_task_build_and_increments_phase(
    tmp_workspace, sample_config, monkeypatch
):
    from harness import HarnessState

    state = {
        "spec_file": "spec.md",
        "current_phase": 1,
        "total_phases": 2,
        "language": "python",
        "phases": [
            {
                "id": 1,
                "title": "P1",
                "language": "python",
                "phase_type": "setup",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "T",
                        "task_type": "foundation",
                        "description": "",
                        "refs": [],
                        "status": "complete",
                        "attempts": 0,
                        "verify_fails": 0,
                        "tdd_mode": None,
                        "tdd_applied": None,
                        "tdd_skipped": None,
                        "files_changed": [],
                        "last_error": [],
                    }
                ],
                "review": {
                    "status": "pending",
                    "verdict": None,
                    "sha_at_review": None,
                    "issues": [],
                },
            },
            {
                "id": 2,
                "title": "P2",
                "language": "python",
                "phase_type": "development",
                "status": "pending",
                "tasks": [],
                "review": {
                    "status": "pending",
                    "verdict": None,
                    "sha_at_review": None,
                    "issues": [],
                },
            },
        ],
        "last_updated": "2026-01-01T00:00:00+00:00",
    }
    _mark_regression_passed(state)
    save_state(state)
    result = handle_next_phase(_make_harness(sample_config), state, phase_id=1)
    assert result == HarnessState.TASK_BUILD
    assert state["current_phase"] == 2


def test_handle_next_phase_runs_smoke_before_marking_complete(
    sample_state, sample_config, monkeypatch
):
    save_state(sample_state)
    _mark_regression_passed(sample_state)
    sample_state["app_type"] = "game"
    sample_config["game_quick_smoke_phase_ids"] = [1]
    calls = []

    def mock_smoke(state, phase_id, config):
        calls.append(state["phases"][0]["status"])
        return type("Smoke", (), {"ok": True})()

    monkeypatch.setattr(ph_mod, "run_game_smoke", mock_smoke)

    handle_next_phase(_make_harness(sample_config), sample_state, phase_id=1)

    assert calls == ["building"]
    assert sample_state["phases"][0]["status"] == "complete"


def test_handle_next_phase_marks_phase_error_when_smoke_fails(
    sample_state, sample_config, monkeypatch
):
    from harness import HarnessState

    save_state(sample_state)
    _mark_regression_passed(sample_state)
    sample_state["app_type"] = "game"

    monkeypatch.setattr(
        ph_mod,
        "run_game_smoke",
        lambda *a, **kw: type(
            "Smoke",
            (),
            {
                "ok": False,
                "cmd": ["npm"],
                "stdout_tail": "stdout",
                "stderr_tail": "stderr",
            },
        )(),
    )

    result = handle_next_phase(_make_harness(sample_config), sample_state, phase_id=1)

    assert result == HarnessState.HALTED
    assert sample_state["phases"][0]["status"] == "error"
    assert sample_state["phases"][0]["last_error"][0]["stderr_tail"] == "stderr"


def test_handle_next_phase_does_not_run_smoke_for_unlisted_phase(
    sample_state, sample_config, monkeypatch
):
    save_state(sample_state)
    _mark_regression_passed(sample_state)
    sample_state["app_type"] = "game"
    sample_config["game_quick_smoke_phase_ids"] = [5]
    smoke_mock = MagicMock(return_value=type("Smoke", (), {"ok": True})())
    monkeypatch.setattr(ph_mod, "run_game_smoke", smoke_mock)

    handle_next_phase(_make_harness(sample_config), sample_state, phase_id=1)

    smoke_mock.assert_called_once()
    assert sample_state["phases"][0]["status"] == "complete"


# ── handle_task_build ────────────────────────────────────────────────────────


def test_handle_task_build_returns_executing_on_success(
    sample_state, sample_profile, sample_config, monkeypatch
):
    from harness import HarnessState

    save_state(sample_state)
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "task_type": "foundation",
                    "description": "Setup",
                    "refs": [],
                    "tdd_mode": None,
                }
            ]
        },
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)

    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    result = handle_task_build(
        harness, sample_state, phase_id=1, profile=sample_profile
    )
    assert result == HarnessState.EXECUTING


def test_handle_task_build_passes_spec_context(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    captured = {}
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "task_type": "foundation",
                    "description": "Setup.",
                    "tdd_mode": None,
                }
            ]
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    def mock_build(*args, **kwargs):
        captured["spec_context"] = kwargs.get("spec_context")
        return build_result

    monkeypatch.setattr(agents, "build_tasks", mock_build)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "Spec manifest" in captured["spec_context"]


def test_handle_task_build_includes_phase_ref_contents(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    ref = tmp_workspace / "docs" / "requirements.md"
    ref.parent.mkdir()
    ref.write_text("Referenced requirement detail.", encoding="utf-8")
    captured = {}
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "task_type": "foundation",
                    "description": "Setup.",
                    "tdd_mode": None,
                }
            ]
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    def mock_build(*args, **kwargs):
        captured["context"] = args[1]
        return build_result

    monkeypatch.setattr(agents, "build_tasks", mock_build)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": ["docs/requirements.md"],
        "language": "python",
        "phase_type": "setup",
    }

    handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "Referenced requirement detail." in captured["context"]


def test_handle_task_build_halts_on_subprocess_error(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    monkeypatch.setattr(
        agents,
        "build_tasks",
        MagicMock(side_effect=agents.SubprocessError("timeout")),
    )

    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    with pytest.raises(SystemExit) as exc:
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)
    assert exc.value.code == 1


def test_handle_task_build_blocks_when_task_count_exceeds_limit(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["phase_type"] = "development"
    save_state(sample_state)
    sample_config["task_planning_limits"] = {
        "enabled": True,
        "max_tasks_per_development_phase": 2,
        "allow_legacy_tdd_triplets": False,
    }
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": f"1.{i}",
                    "title": f"Task {i}",
                    "task_type": "foundation",
                    "description": "Do work.",
                    "refs": [],
                    "tdd_mode": "tdd_slice",
                }
                for i in range(1, 4)
            ]
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Development.",
        "refs": [],
        "language": "python",
        "phase_type": "development",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert sample_state["phases"][0]["status"] == "error"
    assert "generated 3 tasks" in sample_state["phases"][0]["last_error"][0]


def test_handle_task_build_rejects_legacy_unit_test_tasks_by_default(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["phase_type"] = "development"
    save_state(sample_state)
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Run tests",
                    "task_type": "testing",
                    "description": "Run tests.",
                    "refs": [],
                    "tdd_mode": "unit_test",
                }
            ]
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Development.",
        "refs": [],
        "language": "python",
        "phase_type": "development",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "legacy unit_test" in sample_state["phases"][0]["last_error"][0]


def test_handle_task_build_rejects_empty_task_list(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    build_result = {
        "signal": {"tasks": []},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "generated no tasks" in sample_state["phases"][0]["last_error"][-1]


def test_handle_task_build_rejects_task_missing_required_field(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "description": "Setup.",
                    "tdd_mode": None,
                }
            ]
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "missing non-empty 'task_type'" in sample_state["phases"][0]["last_error"][-1]


def test_handle_task_build_rejects_wrong_phase_task_id(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "2.1",
                    "title": "Task One",
                    "task_type": "foundation",
                    "description": "Setup.",
                    "tdd_mode": None,
                }
            ]
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "must use phase 1 prefix" in sample_state["phases"][0]["last_error"][-1]


def test_handle_task_build_rejects_duplicate_task_ids(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    task = {
        "id": "1.1",
        "title": "Task One",
        "task_type": "foundation",
        "description": "Setup.",
        "tdd_mode": None,
    }
    build_result = {
        "signal": {"tasks": [task, {**task, "title": "Task Two"}]},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "duplicate task id" in sample_state["phases"][0]["last_error"][-1]


def test_handle_task_build_rejects_unknown_tdd_mode(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "task_type": "foundation",
                    "description": "Setup.",
                    "tdd_mode": "mystery",
                }
            ]
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    monkeypatch.setattr(agents, "build_tasks", lambda *a, **kw: build_result)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    with pytest.raises(SystemExit):
        handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "unknown tdd_mode" in sample_state["phases"][0]["last_error"][-1]


def test_handle_task_build_passes_completed_work_context(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["tasks"][0]["status"] = "complete"
    sample_state["phases"][0]["tasks"][0]["files_changed"] = ["app/settings.py"]
    save_state(sample_state)
    captured = {}
    build_result = {
        "signal": {
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "task_type": "foundation",
                    "description": "Setup.",
                    "tdd_mode": None,
                }
            ]
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    def mock_build(*args, **kwargs):
        captured["completed_work_context"] = kwargs.get("completed_work_context")
        return build_result

    monkeypatch.setattr(agents, "build_tasks", mock_build)
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness._get_phase_data.return_value = {
        "id": 1,
        "title": "Phase One",
        "description": "Setup.",
        "refs": [],
        "language": "python",
        "phase_type": "setup",
    }

    handle_task_build(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "Task One" in captured["completed_work_context"]
    assert "app/settings.py" in captured["completed_work_context"]


# ── handle_executing ─────────────────────────────────────────────────────────


def test_handle_executing_returns_reviewing_when_no_pending_tasks(
    sample_state, sample_profile, sample_config
):
    from harness import HarnessState

    sample_state["phases"][0]["tasks"][0]["status"] = "complete"
    save_state(sample_state)

    result = handle_executing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )
    assert result == HarnessState.REVIEWING


def test_handle_executing_empty_phase_tasks_returns_task_build(
    sample_state, sample_profile, sample_config
):
    from harness import HarnessState

    sample_state["phases"][0]["tasks"] = []
    save_state(sample_state)
    harness = _make_harness(sample_config)

    result = handle_executing(
        harness, sample_state, phase_id=1, profile=sample_profile
    )

    assert result == HarnessState.TASK_BUILD
    harness._load_spec_into_memory.assert_called_once()


def test_handle_executing_unit_test_does_not_call_agents_execute(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["tasks"][0]["tdd_mode"] = "unit_test"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    execute_mock = MagicMock()
    monkeypatch.setattr(agents, "execute", execute_mock)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(ph_mod, "log_usage", MagicMock())
    harness = _make_harness(sample_config)

    handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    execute_mock.assert_not_called()
    ph_mod.log_usage.assert_not_called()


def test_handle_executing_unit_test_marks_complete_on_verify_success(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["tasks"][0]["tdd_mode"] = "unit_test"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    harness = _make_harness(sample_config)

    handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    task = sample_state["phases"][0]["tasks"][0]
    assert task["status"] == "complete"
    assert task["tdd_applied"] is False
    assert task["tdd_skipped"] == "unit_test verified locally by harness"


def test_handle_executing_unit_test_verify_failure_enters_retry_path(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["tasks"][0]["tdd_mode"] = "unit_test"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    retry_mock = MagicMock()
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(
        ph_mod,
        "verify_execution",
        lambda *a, **kw: [
            {"id": "1.1", "status": "failed", "reason": "tests failed"}
        ],
    )
    monkeypatch.setattr(ph_mod, "run_batch_retry_loop", retry_mock)
    harness = _make_harness(sample_config)

    handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    retry_mock.assert_called_once()


def test_handle_executing_non_unit_test_still_calls_agents_execute(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["tasks"][0]["tdd_mode"] = "implementation"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    execute_mock = MagicMock(return_value=_make_execute_result(phase_id=1))
    monkeypatch.setattr(agents, "execute", execute_mock)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "development"

    handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    execute_mock.assert_called_once()


def test_handle_executing_external_dependency_from_retry_blocks_task(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["status"] = "building"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    execute_result = {
        "signal": {
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
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    execute_calls = [0]

    def mock_execute(*args, **kwargs):
        execute_calls[0] += 1
        if execute_calls[0] == 1:
            return execute_result
        raise agents.ExternalDependencyError("429")

    harness = _make_harness(sample_config)
    harness.profile_for.return_value = sample_profile
    harness.phase_type_for.return_value = "development"
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="same_sha\n", stderr=""),
    )
    monkeypatch.setattr(agents, "execute", mock_execute)
    monkeypatch.setattr(
        ph_mod,
        "verify_execution",
        lambda *a, **kw: [
            {
                "id": "1.1",
                "status": "failed",
                "reason": "agent completed task but created no commit",
            }
        ],
    )

    with pytest.raises(SystemExit):
        handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    task = sample_state["phases"][0]["tasks"][0]
    assert task["status"] == "blocked_external_dependency"
    assert task["attempts"] == 0


def test_handle_executing_passes_spec_context(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["status"] = "building"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    captured = {}
    execute_result = {
        "signal": {
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
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    def mock_execute(*args, **kwargs):
        captured["spec_context"] = kwargs.get("spec_context")
        return execute_result

    harness = _make_harness(sample_config)
    harness.profile_for.return_value = sample_profile
    harness.phase_type_for.return_value = "development"
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(agents, "execute", mock_execute)
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)

    handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    assert "Spec manifest" in captured["spec_context"]


def test_handle_executing_halts_on_harness_verification_blocker(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["status"] = "building"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    execute_result = {
        "signal": {
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
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "call_id": "execute-test",
    }
    harness = _make_harness(sample_config)
    harness.profile_for.return_value = sample_profile
    harness.phase_type_for.return_value = "development"
    blocker = verify_mod.VerificationResult(
        failed_tasks=[
            {
                "id": "1.1",
                "status": "failed",
                "reason": "agent completed task but created no commit",
            }
        ],
        harness_blocker=True,
        blocker_reason="agent completed task but created no commit",
        failure_kind="no_commit",
    )
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="same_sha\n", stderr=""),
    )
    monkeypatch.setattr(agents, "execute", lambda *a, **kw: execute_result)
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: blocker)

    with pytest.raises(SystemExit):
        handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    task = sample_state["phases"][0]["tasks"][0]
    assert task["status"] == "halted"
    assert task["attempts"] == 0
    assert task["last_error"][-1] == "agent completed task but created no commit"


def test_handle_executing_uses_verify_committed_files_when_signal_files_empty(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["status"] = "building"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    execute_result = {
        "signal": {
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
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    harness = _make_harness(sample_config)
    harness.profile_for.return_value = sample_profile
    harness.phase_type_for.return_value = "development"
    monkeypatch.setattr(agents, "execute", lambda *a, **kw: execute_result)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(
        ph_mod,
        "verify_execution",
        lambda *a, **kw: verify_mod.VerificationResult(
            commit_sha="new_sha",
            committed_files=["src/config/clientConfig.ts"],
        ),
    )
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)

    handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    task = sample_state["phases"][0]["tasks"][0]
    assert task["files_changed"] == ["src/config/clientConfig.ts"]
    assert task["commit_sha"] == "new_sha"


def _make_execute_result(phase_id: int, task_id: str = "1.1") -> dict:
    return {
        "signal": {
            "phase_id": phase_id,
            "tasks": [
                {
                    "id": task_id,
                    "title": "T",
                    "task_type": "foundation",
                    "status": "complete",
                    "files_changed": [],
                }
            ],
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def test_handle_executing_rejects_wrong_phase_id(
    sample_state, sample_profile, sample_config, monkeypatch
):

    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    # Signal reports phase_id=2 but active phase is 1
    monkeypatch.setattr(
        agents, "execute", lambda *a, **kw: _make_execute_result(phase_id=2)
    )
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "development"

    with pytest.raises(SystemExit):
        handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    task = sample_state["phases"][0]["tasks"][0]
    assert task["status"] == "error"


def test_handle_executing_rejects_missing_active_task_in_signal(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)
    # Signal contains only task "1.2" while active task is "1.1"
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **kw: _make_execute_result(phase_id=1, task_id="1.2"),
    )
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "development"

    with pytest.raises(SystemExit):
        handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    task = sample_state["phases"][0]["tasks"][0]
    assert task["status"] == "error"


def test_handle_executing_ignores_extra_task_ids_in_signal(
    sample_state, sample_profile, sample_config, monkeypatch
):
    from harness import HarnessState

    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)

    execute_result = {
        "signal": {
            "phase_id": 1,
            "tasks": [
                {
                    "id": "1.1",
                    "title": "T",
                    "task_type": "foundation",
                    "status": "complete",
                    "files_changed": [],
                },
                {
                    "id": "1.2",
                    "title": "Extra",
                    "task_type": "foundation",
                    "status": "complete",
                    "files_changed": [],
                },
            ],
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    monkeypatch.setattr(agents, "execute", lambda *a, **kw: execute_result)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "development"

    result = handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    assert result == HarnessState.REVIEWING
    # Only the active task "1.1" is updated; "1.2" was ignored
    task_11 = sample_state["phases"][0]["tasks"][0]
    assert task_11["status"] == "complete"


def test_handle_executing_no_warning_when_signal_matches_active_task(
    sample_state, sample_profile, sample_config, monkeypatch, caplog
):
    import logging

    from harness import HarnessState

    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    save_state(sample_state)

    monkeypatch.setattr(
        agents, "execute", lambda *a, **kw: _make_execute_result(phase_id=1)
    )
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(ph_mod, "log_usage", lambda **kw: None)
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "development"

    with caplog.at_level(logging.WARNING):
        result = handle_executing(
            harness, sample_state, phase_id=1, profile=sample_profile
        )

    assert result == HarnessState.REVIEWING
    assert "unexpected task IDs" not in caplog.text


def test_handle_executing_halts_after_large_output_usage_guardrail(
    sample_state, sample_profile, sample_config, monkeypatch
):
    from harness import HarnessState

    sample_state["phases"][0]["phase_type"] = "development"
    sample_state["phases"][0]["tasks"][0]["status"] = "pending"
    sample_state["phases"][0]["tasks"][0]["tdd_mode"] = "tdd_slice"
    save_state(sample_state)
    sample_config["usage_guardrails"] = {
        "enabled": True,
        "max_single_output_tokens": 10,
        "max_phase_claude_calls": 10,
        "max_phase_combined_tokens": 1000000,
    }
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **kw: {
            **_make_execute_result(phase_id=1),
            "usage": {"input_tokens": 1, "output_tokens": 11},
        },
    )
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="sha\n"),
    )
    monkeypatch.setattr(ph_mod, "verify_execution", lambda *a, **kw: [])
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "development"

    result = handle_executing(harness, sample_state, phase_id=1, profile=sample_profile)

    assert result == HarnessState.HALTED
    assert sample_state["phases"][0]["status"] == "error"
    assert "usage guardrail tripped" in sample_state["phases"][0]["last_error"][0]


# ── handle_reviewing ─────────────────────────────────────────────────────────


def test_handle_reviewing_returns_regression_testing(
    sample_state, sample_profile, sample_config, monkeypatch
):
    from harness import HarnessState

    save_state(sample_state)
    review_result = {
        "signal": {"verdict": "APPROVE", "sha_at_review": "sha123", "issues": []},
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    monkeypatch.setattr(agents, "review_phase", lambda *a, **kw: review_result)
    monkeypatch.setattr(ph_mod, "handle_verdict", lambda *a, **kw: None)

    sample_state["initial_sha"] = "abc"
    result = handle_reviewing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )
    assert result == HarnessState.REGRESSION_TESTING


def test_handle_reviewing_does_not_auto_approve_game_setup_phase(
    sample_state, sample_profile, sample_config, monkeypatch
):
    from harness import HarnessState

    sample_state["app_type"] = "game"
    sample_state["phases"][0]["status"] = "building"
    sample_state["phases"][0]["tasks"][0]["status"] = "complete"
    save_state(sample_state)
    captured = {}
    review_result = {
        "signal": {"verdict": "APPROVE", "sha_at_review": "sha123", "issues": []},
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    def mock_review(*args, **kwargs):
        captured["spec_context"] = kwargs.get("spec_context")
        return review_result

    monkeypatch.setattr(agents, "review_phase", mock_review)
    monkeypatch.setattr(ph_mod, "handle_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=1, stdout="", stderr="not git"),
    )

    result = handle_reviewing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )

    assert result == HarnessState.REGRESSION_TESTING
    assert "Spec manifest" in captured["spec_context"]


def test_handle_reviewing_still_auto_approves_non_game_setup_phase(
    sample_state, sample_profile, sample_config, monkeypatch
):
    sample_state["app_type"] = "cli"
    save_state(sample_state)
    review_mock = MagicMock()
    monkeypatch.setattr(agents, "review_phase", review_mock)
    harness = _make_harness(sample_config)
    harness.phase_type_for.return_value = "setup"

    handle_reviewing(harness, sample_state, phase_id=1, profile=sample_profile)

    review_mock.assert_not_called()


def test_handle_reviewing_subprocess_error_sets_review_error(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["phases"][0]["status"] = "building"
    sample_state["phases"][0]["phase_type"] = "development"
    sample_state["phases"][0]["tasks"][0]["status"] = "complete"
    monkeypatch.setattr(
        agents,
        "review_phase",
        MagicMock(side_effect=agents.SubprocessError("timeout")),
    )
    sample_state["initial_sha"] = "abc"

    with pytest.raises(SystemExit) as exc:
        handle_reviewing(
            _make_harness(sample_config),
            sample_state,
            phase_id=1,
            profile=sample_profile,
        )

    assert exc.value.code == 1
    assert sample_state["phases"][0]["status"] == "building"
    assert sample_state["phases"][0]["review"]["status"] == "error"
    assert "timeout" in sample_state["phases"][0]["review"]["last_error"][0]


def test_handle_reviewing_stores_actual_head_as_sha_at_review(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    review_result = {
        "signal": {"verdict": "APPROVE", "sha_at_review": "agent_sha", "issues": []},
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    monkeypatch.setattr(agents, "review_phase", lambda *a, **kw: review_result)
    monkeypatch.setattr(ph_mod, "handle_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="actual_sha\n", stderr=""),
    )
    sample_state["initial_sha"] = "abc"

    handle_reviewing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )

    assert sample_state["phases"][0]["review"]["sha_at_review"] == "actual_sha"


def test_handle_reviewing_logs_warning_when_sha_mismatch(
    sample_state, sample_profile, sample_config, monkeypatch, caplog
):
    save_state(sample_state)
    review_result = {
        "signal": {"verdict": "APPROVE", "sha_at_review": "agent_sha", "issues": []},
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    monkeypatch.setattr(agents, "review_phase", lambda *a, **kw: review_result)
    monkeypatch.setattr(ph_mod, "handle_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="actual_sha\n", stderr=""),
    )
    sample_state["initial_sha"] = "abc"

    handle_reviewing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )

    assert "overriding" in caplog.text


def test_handle_reviewing_uses_agent_sha_when_git_fails(
    sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    review_result = {
        "signal": {"verdict": "APPROVE", "sha_at_review": "sha123", "issues": []},
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    monkeypatch.setattr(agents, "review_phase", lambda *a, **kw: review_result)
    monkeypatch.setattr(ph_mod, "handle_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=1, stdout="", stderr="not git"),
    )
    sample_state["initial_sha"] = "abc"

    handle_reviewing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )

    assert sample_state["phases"][0]["review"]["sha_at_review"] == "sha123"


def test_handle_reviewing_no_warning_when_shas_match(
    sample_state, sample_profile, sample_config, monkeypatch, caplog
):
    save_state(sample_state)
    review_result = {
        "signal": {"verdict": "APPROVE", "sha_at_review": "same_sha", "issues": []},
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    monkeypatch.setattr(agents, "review_phase", lambda *a, **kw: review_result)
    monkeypatch.setattr(ph_mod, "handle_verdict", lambda *a, **kw: None)
    monkeypatch.setattr(
        ph_mod.subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="same_sha\n", stderr=""),
    )
    sample_state["initial_sha"] = "abc"

    handle_reviewing(
        _make_harness(sample_config), sample_state, phase_id=1, profile=sample_profile
    )

    assert "overriding" not in caplog.text


# ── handle_fixing ────────────────────────────────────────────────────────────


def test_handle_fixing_returns_regression_testing(sample_state, sample_config, monkeypatch):
    from harness import HarnessState

    save_state(sample_state)
    monkeypatch.setattr(ph_mod, "run_fix_cycle", lambda *a, **kw: None)

    result = handle_fixing(_make_harness(sample_config), sample_state, phase_id=1)
    assert result == HarnessState.REGRESSION_TESTING


def test_handle_regression_testing_pass_returns_next_phase(
    sample_state, sample_config, monkeypatch
):
    from harness import HarnessState

    save_state(sample_state)
    monkeypatch.setattr(ph_mod, "run_phase_regression_gate", lambda *a, **kw: True)

    result = handle_regression_testing(
        _make_harness(sample_config), sample_state, phase_id=1
    )

    assert result == HarnessState.NEXT_PHASE


def test_handle_regression_testing_fail_returns_fixing(
    sample_state, sample_config, monkeypatch
):
    from harness import HarnessState

    save_state(sample_state)
    monkeypatch.setattr(ph_mod, "run_phase_regression_gate", lambda *a, **kw: False)

    result = handle_regression_testing(
        _make_harness(sample_config), sample_state, phase_id=1
    )

    assert result == HarnessState.FIXING
