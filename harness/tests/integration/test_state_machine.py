"""
Integration test: full single-phase cycle with mocked call_claude.
Verifies state transitions: INIT → TASK_BUILD → EXECUTING → REVIEWING → COMPLETE.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agents
import calibrate as cal_mod
import state as state_mod
from harness import Harness, HarnessState
from phase_handlers import handle_executing, handle_reviewing, handle_task_build


SPEC_CONTENT = "## Phase 1: Bootstrap\nSet up the project foundation.\n"


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def _make_args(tmp_workspace, resume=False):
    spec = tmp_workspace / "spec.md"
    spec.write_text(SPEC_CONTENT, encoding="utf-8")
    args = MagicMock()
    args.resume = resume
    args.language = "python"
    args.spec_file_or_dir = str(spec)
    args.max_phase = None
    return args


def _git_result(sha="abc1234"):
    r = MagicMock()
    r.returncode = 0
    r.stdout = sha + "\n"
    r.stderr = ""
    return r


def _run_result(returncode=0, stdout="", stderr=""):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _build_signal(phase_id=1, task_types=None):
    task_types = task_types or ["foundation"]
    return {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": phase_id,
        "tasks": [
            {
                "id": f"{phase_id}.{i + 1}",
                "title": f"Task {i + 1}",
                "task_type": t,
                "description": f"Implement task {i + 1} for phase {phase_id}.",
                "refs": [],
            }
            for i, t in enumerate(task_types)
        ],
    }


def _execute_signal(phase_id=1, n=1, status="complete"):
    return {
        "mode": "EXECUTE",
        "phase_id": phase_id,
        "tasks": [
            {
                "id": f"{phase_id}.{i + 1}",
                "title": f"Task {i + 1}",
                "task_type": "foundation",
                "status": status,
                "tdd_applied": True,
                "tdd_skipped": None,
                "files_changed": [f"src/task{i + 1}.py"],
            }
            for i in range(n)
        ],
    }


def _review_signal(phase_id=1, verdict="APPROVE"):
    return {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": phase_id,
        "verdict": verdict,
        "sha_at_review": "def456",
        "issues": [],
    }


def _envelope(signal, usage=None):
    return json.dumps(
        {
            "result": json.dumps(signal),
            "usage": usage
            or {
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }
    )


def _mock_claude_process(monkeypatch, next_signal):
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda *a, **kw: _run_result(stdout=_envelope(next_signal())),
    )


def test_init_to_parsing_to_task_build(tmp_workspace, monkeypatch, sample_config):
    """TASK_BUILD: tasks written to state.json with correct task_types."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)

    call_index = [0]
    signals = [_build_signal()]

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result()
        if cmd[0] == "claude":
            sig = signals[call_index[0] % len(signals)]
            call_index[0] += 1
            return _run_result(stdout=_envelope(sig))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    _mock_claude_process(
        monkeypatch,
        lambda: signals[call_index[0] % len(signals)],
    )

    # Only run TASK_BUILD phase (stop after)
    args = _make_args(tmp_workspace)
    args.max_phase = 0  # stop before any phase executes

    harness = Harness(args)
    from lang import get_profile

    harness.profiles = {1: get_profile("python")}
    harness._default_language = "python"
    harness.phases, harness.context = __import__("spec").parse_spec(
        str(tmp_workspace / "spec.md"), harness.state, write_phases=True
    )
    state_mod.save_state(harness.state)
    harness.state["current_phase"] = 1

    result_state = handle_task_build(harness, harness.state, 1, get_profile("python"))
    assert result_state == HarnessState.EXECUTING

    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert len(loaded["phases"][0]["tasks"]) == 1
    task = loaded["phases"][0]["tasks"][0]
    assert task["task_type"] == "foundation"
    assert task["description"] == "Implement task 1 for phase 1."
    assert task["refs"] == []
    assert "task_types" not in loaded


def test_executing_task_status_transitions(tmp_workspace, monkeypatch, sample_config):
    """EXECUTING: task status transitions pending → building → complete; usage.jsonl written."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)

    exec_signal = _execute_signal(n=1)
    git_call_count = [0]

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[0] == "git" and "rev-parse" in cmd:
            git_call_count[0] += 1
            # First call: pre_sha. Second+ call (inside verify_execution): new SHA → commit happened
            return _git_result("sha_before" if git_call_count[0] == 1 else "sha_after")
        if cmd[0] == "pytest":
            return _run_result()
        if cmd[0] == "claude":
            return _run_result(stdout=_envelope(exec_signal))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    _mock_claude_process(monkeypatch, lambda: exec_signal)

    state = {
        "spec_file": str(tmp_workspace / "spec.md"),
        "language": "python",
        "initial_sha": "abc1234",
        "task_types": ["foundation"],
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "title": "Bootstrap",
                "language": "python",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Task 1",
                        "task_type": "foundation",
                        "status": "pending",
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
            }
        ],
    }
    state_mod.save_state(state)

    args = _make_args(tmp_workspace)
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)

    harness = Harness(args)
    harness.state = state
    from lang import get_profile

    harness.profiles = {1: get_profile("python")}
    harness._default_language = "python"

    result_state = handle_executing(harness, state, 1, get_profile("python"))
    assert result_state == HarnessState.REVIEWING

    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert loaded["phases"][0]["tasks"][0]["status"] == "complete"

    usage_path = tmp_workspace / "workspace" / "usage.jsonl"
    assert usage_path.exists()
    entry = json.loads(usage_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["mode"] == "EXECUTE"


def test_reviewing_approve_advances_phase(tmp_workspace, monkeypatch, sample_config):
    """REVIEWING (APPROVE): phase advances to COMPLETE via NEXT_PHASE."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)

    review_signal = _review_signal(verdict="APPROVE")

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result()
        if cmd[0] == "claude":
            return _run_result(stdout=_envelope(review_signal))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    _mock_claude_process(monkeypatch, lambda: review_signal)

    state = {
        "spec_file": str(tmp_workspace / "spec.md"),
        "language": "python",
        "initial_sha": "abc1234",
        "task_types": ["foundation"],
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "title": "Bootstrap",
                "language": "python",
                "status": "building",
                "tasks": [],
                "review": {
                    "status": "pending",
                    "verdict": None,
                    "sha_at_review": None,
                    "issues": [],
                },
            }
        ],
    }
    state_mod.save_state(state)

    args = _make_args(tmp_workspace)
    harness = Harness(args)
    harness.state = state
    from lang import get_profile

    harness.profiles = {1: get_profile("python")}
    harness._default_language = "python"

    result_state = handle_reviewing(harness, state, 1, get_profile("python"))
    assert result_state == HarnessState.REGRESSION_TESTING

    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert loaded["phases"][0]["review"]["verdict"] == "APPROVE"


def test_reviewing_block_enters_fix_cycle(tmp_workspace, monkeypatch, sample_config):
    """REVIEWING (BLOCK): fix cycle entered; CRITICAL/HIGH resolved; MEDIUM/LOW deferred."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)

    review_signal = {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 1,
        "verdict": "BLOCK",
        "sha_at_review": "def456",
        "issues": [
            {
                "id": "1.1",
                "severity": "HIGH",
                "dimension": "Security",
                "file": "app.py",
                "title": "SQL injection",
            },
            {
                "id": "1.2",
                "severity": "MEDIUM",
                "dimension": "Performance",
                "file": "app.py",
                "title": "N+1 query",
            },
        ],
    }
    fix_signal = {
        "mode": "FIX",
        "fixes": [
            {
                "id": "1.1",
                "severity": "HIGH",
                "title": "SQL injection",
                "status": "fixed",
                "files_changed": ["app.py"],
            },
            {
                "id": "1.2",
                "severity": "MEDIUM",
                "title": "N+1 query",
                "status": "deferred",
                "files_changed": [],
            },
        ],
    }

    call_index = [0]
    responses = [review_signal, fix_signal]

    git_shas = iter(["abc1234", "abc1234", "def4567", "def4567"])

    def mock_subprocess_run(cmd, **kwargs):
        if cmd[0] == "git":
            if cmd[:2] == ["git", "diff"]:
                return _run_result(stdout="app.py\n")
            if cmd[:2] == ["git", "rev-parse"]:
                return _git_result(next(git_shas, "def4567"))
            return _git_result()
        if cmd[0] == "pytest":
            return _run_result()
        if cmd[0] == "claude":
            sig = responses[call_index[0] % len(responses)]
            call_index[0] += 1
            return _run_result(stdout=_envelope(sig))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    _mock_claude_process(
        monkeypatch,
        lambda: responses[call_index[0] % len(responses)],
    )

    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda **kw: {"signal": fix_signal, "usage": {}},
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        lambda **kw: {
            "signal": {
                "status": "complete",
                "mode": "REVIEW",
                "phase_id": 1,
                "verdict": "APPROVE",
                "sha_at_review": "def4567",
                "issues": [],
            },
            "usage": {},
        },
    )

    state = {
        "spec_file": str(tmp_workspace / "spec.md"),
        "language": "python",
        "initial_sha": "abc1234",
        "task_types": ["foundation"],
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "title": "Bootstrap",
                "language": "python",
                "status": "building",
                "tasks": [],
                "review": {
                    "status": "pending",
                    "verdict": None,
                    "sha_at_review": None,
                    "issues": [],
                },
            }
        ],
    }
    state_mod.save_state(state)

    (tmp_workspace / "workspace" / "review_report.md").write_text(
        "### 1.1 SQL injection\nFix it.\n", encoding="utf-8"
    )

    args = _make_args(tmp_workspace)
    harness = Harness(args)
    harness.state = state
    from lang import get_profile

    harness.profiles = {1: get_profile("python")}
    harness._default_language = "python"

    handle_reviewing(harness, state, 1, get_profile("python"))

    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    issues = loaded["phases"][0]["review"]["issues"]
    high = next(i for i in issues if i["id"] == "1.1")
    medium = next(i for i in issues if i["id"] == "1.2")
    assert high["status"] == "fixed"
    assert medium["status"] == "deferred"
