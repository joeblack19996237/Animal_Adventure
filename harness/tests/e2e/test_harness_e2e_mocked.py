import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import agents
import git_changes
import harness as harness_mod
import phase_handlers
import state as state_mod
from fix import _targeted_rereview_blocking_fixes
from harness import Harness, HarnessState
from run_lock import acquire_lock, release_lock
from state import error_review, save_state

from . import fake_claude

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_workspace, monkeypatch, sample_config, sample_profile):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))
    monkeypatch.setattr(harness_mod, "load_config", lambda: sample_config)
    monkeypatch.setattr(harness_mod, "get_profile", lambda language: sample_profile)
    monkeypatch.setattr(harness_mod, "_git_startup", lambda state: state.setdefault("initial_sha", "sha0"))
    monkeypatch.setattr(harness_mod, "check_spec_completeness", lambda *a, **kw: [])
    monkeypatch.setattr(
        phase_handlers.subprocess,
        "run",
        lambda *a, **kw: MagicMock(stdout="sha1\n", stderr="", returncode=0),
    )
    monkeypatch.setattr(
        "fix.subprocess.run",
        lambda *a, **kw: MagicMock(stdout="sha1\n", stderr="", returncode=0),
    )
    release_lock()
    yield
    release_lock()


def _args(spec_name="python_cli_spec.md", resume=False):
    return SimpleNamespace(
        spec_file_or_dir=str(FIXTURES / spec_name),
        language="python",
        app_type="cli",
        resume=resume,
        max_phase=None,
        status=False,
        clear_stale_lock=False,
    )


def _usage():
    return {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


@pytest.mark.e2e
def test_mocked_e2e_happy_path_complete(monkeypatch):
    monkeypatch.setattr(
        agents,
        "build_tasks",
        lambda phase, *a, **kw: {"signal": fake_claude.task_build_signal(phase["id"]), "usage": _usage()},
    )
    monkeypatch.setattr(
        agents,
        "execute",
        lambda batch, phase_id, **kw: {"signal": fake_claude.execute_signal(phase_id), "usage": _usage()},
    )
    monkeypatch.setattr(
        agents,
        "review_phase",
        lambda phase_id, *a, **kw: {"signal": fake_claude.review_signal(phase_id), "usage": _usage()},
    )
    monkeypatch.setattr(phase_handlers, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(harness_mod, "run_cleanup", lambda *a, **kw: None)
    monkeypatch.setattr(
        harness_mod,
        "run_evaluate_cycle",
        lambda h, state: state.setdefault("evaluate", {"status": "complete"}),
    )

    Harness(_args()).run()

    state = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert all(phase["status"] == "complete" for phase in state["phases"])
    assert Path("workspace/events.jsonl").exists()
    assert Path("workspace/harness.log").exists()
    assert not Path("workspace/run.lock").exists()


@pytest.mark.e2e
def test_mocked_e2e_review_timeout_resume_to_reviewing():
    state = {
        "spec_file": str(FIXTURES / "review_timeout_spec.md"),
        "language": "python",
        "current_phase": 2,
        "phases": [
            {
                "id": 2,
                "title": "Review Timeout Path [python]",
                "status": "building",
                "tasks": [{"id": "2.1", "status": "complete"}],
                "review": {"status": "pending", "issues": []},
            }
        ],
    }
    save_state(state)
    with pytest.raises(SystemExit) as exc:
        error_review(state, 2, "timeout after 1s")
    assert exc.value.code == 1
    harness = Harness(_args("review_timeout_spec.md", resume=True))
    harness.state = state
    assert harness._derive_state() is HarnessState.REVIEWING
    assert state["phases"][0]["tasks"][0]["status"] == "complete"


@pytest.mark.e2e
def test_mocked_e2e_fix_cycle_then_targeted_rereview(monkeypatch, sample_config):
    harness = MagicMock()
    harness.config = sample_config
    harness.profile_for = MagicMock(return_value={})
    state = {
        "spec_file": str(FIXTURES / "fix_cycle_spec.md"),
        "phases": [
            {
                "id": 1,
                "review": {
                    "issues": [
                        {
                            "id": "1.1",
                            "severity": "HIGH",
                            "status": "open",
                            "last_error": [],
                        }
                    ]
                },
            }
        ],
    }
    monkeypatch.setattr(
        agents,
        "review_fix",
        lambda **kw: {"signal": fake_claude.review_signal(1, "APPROVE"), "usage": _usage()},
    )

    result = _targeted_rereview_blocking_fixes(
        harness, state, 1, fake_claude.fix_signal("1.1")["fixes"], "sha0"
    )
    assert result == []


@pytest.mark.e2e
def test_mocked_e2e_run_lock_prevents_parallel_run():
    acquire_lock(spec_file="spec.md", app_type="cli")
    with pytest.raises(SystemExit) as exc:
        Harness(_args()).run()
    assert exc.value.code == 1


@pytest.mark.e2e
def test_mocked_e2e_events_jsonl_contains_required_events(monkeypatch):
    monkeypatch.setattr(
        agents,
        "build_tasks",
        lambda phase, *a, **kw: {"signal": fake_claude.task_build_signal(phase["id"]), "usage": _usage()},
    )
    monkeypatch.setattr(
        agents,
        "execute",
        lambda batch, phase_id, **kw: {"signal": fake_claude.execute_signal(phase_id), "usage": _usage()},
    )
    monkeypatch.setattr(
        agents,
        "review_phase",
        lambda phase_id, *a, **kw: {"signal": fake_claude.review_signal(phase_id), "usage": _usage()},
    )
    monkeypatch.setattr(phase_handlers, "verify_execution", lambda *a, **kw: [])
    monkeypatch.setattr(harness_mod, "run_cleanup", lambda *a, **kw: None)
    monkeypatch.setattr(harness_mod, "run_evaluate_cycle", lambda *a, **kw: None)

    Harness(_args()).run()

    events = [
        json.loads(line)["event"]
        for line in Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "harness_start" in events
    assert "state_transition" in events
    assert "harness_complete" in events


@pytest.mark.e2e
def test_mocked_e2e_commit_gate_ignores_unrelated_dirty_file(monkeypatch):
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"app.py", "unrelated.txt"})
    result = git_changes.safe_changed_signal_files({"unrelated.txt"}, ["app.py", "unrelated.txt"])
    assert result == ["app.py"]

