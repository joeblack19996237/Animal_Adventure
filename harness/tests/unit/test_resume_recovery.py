import json
from pathlib import Path

import pytest

import state as state_mod
from resume_recovery import recover_or_block_stale_execution


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def _state_with_building_task():
    return {
        "spec_file": "docs/spec.md",
        "current_phase": 1,
        "phases": [
            {
                "id": 1,
                "title": "Phase One",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Task One",
                        "status": "building",
                        "last_error": [],
                    }
                ],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }


def _events():
    path = Path("workspace/events.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_stale_lock_building_task_blocks_when_cleanup_unsafe():
    state = _state_with_building_task()
    state_mod.save_state(state)

    with pytest.raises(SystemExit) as exc:
        recover_or_block_stale_execution(
            state,
            lock_context={"stale_lock_at_start": True},
            cleanup_result={
                "protection_incomplete": True,
                "candidate_pids": [123],
                "unsafe_to_resume": True,
            },
        )

    assert exc.value.code == 1
    assert state["phases"][0]["tasks"][0]["status"] == "building"
    assert any(e["event"] == "stale_execution_recovery_blocked" for e in _events())


def test_stale_lock_building_task_resets_to_pending_when_cleanup_safe():
    state = _state_with_building_task()
    state_mod.save_state(state)

    result = recover_or_block_stale_execution(
        state,
        lock_context={"stale_lock_at_start": True},
        cleanup_result={
            "protection_incomplete": False,
            "candidate_pids": [],
            "unsafe_to_resume": False,
            "errors": [],
        },
    )

    assert result["action"] == "recovered"
    assert state["phases"][0]["tasks"][0]["status"] == "pending"
    saved = state_mod.load_state()
    assert saved["phases"][0]["tasks"][0]["status"] == "pending"
    assert any(e["event"] == "stale_execution_recovered" for e in _events())


def test_non_stale_resume_does_not_reset_building_task():
    state = _state_with_building_task()
    state_mod.save_state(state)

    result = recover_or_block_stale_execution(
        state,
        lock_context={"stale_lock_at_start": False},
        cleanup_result={"unsafe_to_resume": False},
    )

    assert result["action"] == "not_stale"
    assert state["phases"][0]["tasks"][0]["status"] == "building"


def test_stale_recovery_noops_when_no_inflight_state():
    state = _state_with_building_task()
    state["phases"][0]["tasks"][0]["status"] = "pending"
    state_mod.save_state(state)

    result = recover_or_block_stale_execution(
        state,
        lock_context={"stale_lock_at_start": True},
        cleanup_result={"unsafe_to_resume": False},
    )

    assert result["action"] == "noop"
    assert any(e["event"] == "stale_execution_recovery_noop" for e in _events())


def test_halted_task_is_not_reset_by_stale_recovery():
    state = _state_with_building_task()
    task = state["phases"][0]["tasks"][0]
    task["status"] = "halted"
    state_mod.save_state(state)

    result = recover_or_block_stale_execution(
        state,
        lock_context={"stale_lock_at_start": True},
        cleanup_result={"unsafe_to_resume": False},
    )

    assert result["action"] == "noop"
    assert task["status"] == "halted"
