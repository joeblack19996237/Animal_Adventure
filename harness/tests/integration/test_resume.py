"""
Integration test: --resume re-entry from each interruptible state.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import calibrate as cal_mod
import state as state_mod
from harness import Harness, HarnessState
from phase_handlers import handle_next_phase


SPEC_CONTENT = (
    "## Phase 1: Bootstrap\nSet up the project.\n\n## Phase 2: Build\nBuild it.\n"
)


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def _write_spec(tmp_workspace, content=SPEC_CONTENT):
    spec = tmp_workspace / "spec.md"
    spec.write_text(content, encoding="utf-8")
    return str(spec)


def _make_resume_args(tmp_workspace, sample_config, monkeypatch):
    args = MagicMock()
    args.resume = True
    args.language = "python"
    args.spec_file_or_dir = None
    args.max_phase = None
    args.token_budget = 1_000_000
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    return args


def _git_result(sha="abc123"):
    r = MagicMock()
    r.returncode = 0
    r.stdout = sha + "\n"
    r.stderr = ""
    return r


def _base_state(spec_file, phase_status="building", task_status="pending", attempts=0):
    return {
        "spec_file": spec_file,
        "language": "python",
        "initial_sha": "abc123",
        "task_types": ["foundation"],
        "current_phase": 1,
        "total_phases": 2,
        "phases": [
            {
                "id": 1,
                "title": "Bootstrap",
                "language": "python",
                "status": phase_status,
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Task 1",
                        "task_type": "foundation",
                        "status": task_status,
                        "attempts": attempts,
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
                "title": "Build",
                "language": "python",
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
    }


def test_resume_from_executing_picks_up_building_task(
    tmp_workspace, monkeypatch, sample_config
):
    """Resume from EXECUTING (task status='building'): correct task picked up."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, task_status="building")
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    derived = harness._derive_state()
    # A task with status="building" in phase status="building" → EXECUTING
    assert derived == HarnessState.EXECUTING


def test_resume_from_fixing(tmp_workspace, monkeypatch, sample_config):
    """Resume from FIXING (review status='fixing'): resolves to FIXING state."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file)
    state["phases"][0]["review"]["status"] = "fixing"
    state["phases"][0]["review"]["verdict"] = "BLOCK"
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    derived = harness._derive_state()
    assert derived == HarnessState.FIXING


def test_resume_from_cleanup(tmp_workspace, monkeypatch, sample_config):
    """Resume from CLEANUP: all phases complete + deferred issues → CLEANUP state."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="complete", task_status="complete")
    # Set both phases to complete so the deferred-issue check runs
    state["phases"][1]["status"] = "complete"
    state["phases"][0]["review"] = {
        "status": "fixed",
        "verdict": "BLOCK",
        "sha_at_review": "abc",
        "issues": [
            {
                "id": "1.1",
                "severity": "MEDIUM",
                "status": "deferred",
                "dimension": "Performance",
                "file": "app.py",
                "title": "Slow query",
                "attempts": 0,
                "files_changed": [],
                "fixed_sha": None,
                "last_error": [],
            }
        ],
    }
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    derived = harness._derive_state()
    assert derived == HarnessState.CLEANUP


def test_resume_task_error_auto_resets(tmp_workspace, monkeypatch, sample_config):
    """Resume from task status='error': auto-resets to 'pending' and continues."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, task_status="error")
    state["phases"][0]["tasks"][0]["last_error"] = ["subprocess timed out"]
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    derived = harness._derive_state()
    assert derived == HarnessState.EXECUTING
    assert harness.state["phases"][0]["tasks"][0]["status"] == "pending"


def test_resume_issue_error_auto_resets(tmp_workspace, monkeypatch, sample_config):
    """Resume from issue status='error': auto-resets to 'open' and re-enters FIXING."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="building", task_status="complete")
    state["phases"][0]["review"] = {
        "status": "fixing",
        "verdict": "BLOCK",
        "sha_at_review": "abc123",
        "issues": [
            {
                "id": "1.1",
                "severity": "HIGH",
                "status": "error",
                "dimension": "Security",
                "file": "app.py:10",
                "title": "SQL injection",
                "attempts": 1,
                "files_changed": [],
                "fixed_sha": None,
                "last_error": ["claude exited with code 1"],
            }
        ],
    }
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    derived = harness._derive_state()
    assert derived == HarnessState.FIXING
    assert harness.state["phases"][0]["review"]["issues"][0]["status"] == "open"


def test_resume_task_halted_exits(tmp_workspace, monkeypatch, sample_config):
    """Resume from task status='halted': prints halt message and exits."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, task_status="halted")
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    with pytest.raises(SystemExit) as exc:
        harness._derive_state()
    assert exc.value.code == 1


def test_resume_approved_phase_advances_to_next(
    tmp_workspace, monkeypatch, sample_config
):
    """Resume after APPROVE review enters regression before advancing."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="building", task_status="complete")
    state["phases"][0]["review"] = {
        "status": "complete",
        "verdict": "APPROVE",
        "sha_at_review": "def456",
        "issues": [],
    }
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    derived = harness._derive_state()
    assert derived == HarnessState.REGRESSION_TESTING
    assert harness.state["current_phase"] == 1


def test_resume_approved_phase_completes_via_next_phase(
    tmp_workspace, monkeypatch, sample_config
):
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="building", task_status="complete")
    state["phases"][0]["review"] = {
        "status": "complete",
        "verdict": "APPROVE",
        "sha_at_review": "def456",
        "issues": [],
    }
    state["phases"][0]["regression"] = {"status": "passed"}
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    assert harness._derive_state() == HarnessState.NEXT_PHASE
    assert handle_next_phase(harness, state, 1) == HarnessState.TASK_BUILD
    assert state["phases"][0]["status"] == "complete"
    assert state["current_phase"] == 2


def test_resume_fixed_phase_completes_via_next_phase(
    tmp_workspace, monkeypatch, sample_config
):
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="building", task_status="complete")
    state["phases"][0]["review"] = {
        "status": "fixed",
        "verdict": "BLOCK",
        "sha_at_review": "def456",
        "issues": [
            {
                "id": "1.1",
                "severity": "HIGH",
                "status": "fixed",
                "dimension": "Security",
                "file": "app.py",
                "title": "Issue",
                "attempts": 0,
                "files_changed": [],
                "fixed_sha": "def456",
                "last_error": [],
            }
        ],
    }
    state["phases"][0]["regression"] = {"status": "passed"}
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    assert harness._derive_state() == HarnessState.NEXT_PHASE
    assert handle_next_phase(harness, state, 1) == HarnessState.TASK_BUILD
    assert state["phases"][0]["status"] == "complete"
    assert state["current_phase"] == 2


def test_resume_final_approved_phase_returns_next_phase_then_cleanup(
    tmp_workspace, monkeypatch, sample_config
):
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="building", task_status="complete")
    state["total_phases"] = 1
    state["phases"] = state["phases"][:1]
    state["phases"][0]["review"] = {
        "status": "complete",
        "verdict": "APPROVE",
        "sha_at_review": "def456",
        "issues": [],
    }
    state["phases"][0]["regression"] = {"status": "passed"}
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state
    harness.state["spec_file"] = spec_file

    assert harness._derive_state() == HarnessState.NEXT_PHASE
    assert handle_next_phase(harness, state, 1) == HarnessState.CLEANUP
    assert state["phases"][0]["status"] == "complete"


def test_resume_mixed_language_state(tmp_workspace, monkeypatch, sample_config):
    """Resume with mixed-language state: profiles built per-phase from state language fields."""
    spec_file = _write_spec(tmp_workspace)
    state = _base_state(spec_file, phase_status="complete", task_status="complete")
    state["phases"][0]["language"] = "python"
    state["phases"][1]["language"] = "typescript"
    state["phases"][1]["status"] = "pending"
    state_mod.save_state(state)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result())

    args = _make_resume_args(tmp_workspace, sample_config, monkeypatch)
    harness = Harness(args)
    harness.state = state

    # Simulate the resume branch: build profiles from state phases
    from lang import get_profile

    harness._default_language = "python"
    for sp in state.get("phases", []):
        lang = sp.get("language") or harness._default_language
        harness.profiles[sp["id"]] = get_profile(lang)

    assert harness.profile_for(1)["name"] == "python"
    assert harness.profile_for(2)["name"] == "typescript"
