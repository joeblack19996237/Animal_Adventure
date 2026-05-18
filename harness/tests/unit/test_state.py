import json
from pathlib import Path

import pytest

import state as state_mod
from state import (
    error_issue,
    error_issues,
    error_phase,
    error_review,
    error_task,
    halt_issue,
    halt_task,
    reconcile_committed_tasks,
    save_state,
    reset_interrupted_tasks,
    update_state,
)


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def test_save_state_atomic(sample_state):
    save_state(sample_state)
    assert Path("workspace/state.json").exists()
    assert not Path("workspace/state.json.tmp").exists()
    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert loaded["spec_file"] == "spec.md"


def test_error_review_records_error_without_phase_error(sample_state):
    save_state(sample_state)
    with pytest.raises(SystemExit) as exc:
        error_review(sample_state, 1, "review timeout")
    assert exc.value.code == 1
    phase = sample_state["phases"][0]
    assert phase["status"] == "building"
    assert phase["review"]["status"] == "error"
    assert phase["review"]["last_error"] == ["review timeout"]


def test_error_review_appends_last_error_and_attempts(sample_state):
    sample_state["phases"][0]["review"]["status"] = "error"
    sample_state["phases"][0]["review"]["last_error"] = ["first"]
    sample_state["phases"][0]["review"]["attempts"] = 1
    save_state(sample_state)
    with pytest.raises(SystemExit):
        error_review(sample_state, 1, "second")
    review = sample_state["phases"][0]["review"]
    assert review["attempts"] == 2
    assert review["last_error"] == ["first", "second"]


def test_error_issues_records_all_issue_errors(sample_state):
    sample_state["phases"][0]["review"]["issues"] = [
        {
            "id": "1.1",
            "severity": "HIGH",
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        },
        {
            "id": "1.2",
            "severity": "CRITICAL",
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        },
    ]
    save_state(sample_state)

    with pytest.raises(SystemExit) as exc:
        error_issues(sample_state, 1, ["1.1", "1.2"], "fix parser failed")

    assert exc.value.code == 1
    issues = sample_state["phases"][0]["review"]["issues"]
    assert [issue["status"] for issue in issues] == ["error", "error"]
    assert [issue["last_error"] for issue in issues] == [
        ["fix parser failed"],
        ["fix parser failed"],
    ]


def test_reset_interrupted_tasks_resets_building_only(sample_state):
    sample_state["phases"][0]["tasks"].append(
        {
            **sample_state["phases"][0]["tasks"][0],
            "id": "1.2",
            "status": "building",
        }
    )
    sample_state["phases"][0]["tasks"][0]["status"] = "complete"
    save_state(sample_state)
    assert reset_interrupted_tasks(sample_state) is True
    assert sample_state["phases"][0]["tasks"][0]["status"] == "complete"
    assert sample_state["phases"][0]["tasks"][1]["status"] == "pending"


def test_reset_interrupted_preserves_blocked_error_in_last_blocked_error(sample_state):
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "blocked_external_dependency"
    task["last_error"] = ["auth 429"]
    save_state(sample_state)
    reset_interrupted_tasks(sample_state)
    assert task["status"] == "pending"
    assert task["last_blocked_error"] == ["auth 429"]


def test_reset_interrupted_does_not_set_last_blocked_error_for_building(sample_state):
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "building"
    task["last_error"] = ["some error"]
    save_state(sample_state)
    reset_interrupted_tasks(sample_state)
    assert task["status"] == "pending"
    assert "last_blocked_error" not in task


def test_reconcile_committed_tasks_marks_matching_task_complete(
    sample_state, monkeypatch
):
    from unittest.mock import MagicMock

    sample_state["initial_sha"] = "base"
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "error"
    task["title"] = "Task One"
    task["tdd_mode"] = "test_first"
    save_state(sample_state)

    def mock_run(cmd, **kwargs):
        result = MagicMock(returncode=0, stderr="")
        if cmd[:2] == ["git", "log"]:
            result.stdout = "abc123\0feat(phase-1): Task One\n"
        elif cmd[:2] == ["git", "show"]:
            result.stdout = "server/tests/test_notes.py\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(state_mod.subprocess, "run", mock_run)

    assert reconcile_committed_tasks(sample_state) is True
    assert task["status"] == "complete"
    assert task["files_changed"] == ["server/tests/test_notes.py"]
    assert task["tdd_applied"] is True


def test_reconcile_committed_tasks_sets_commit_sha(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    sample_state["initial_sha"] = "base"
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "pending"
    task["title"] = "Task One"

    def mock_run(cmd, **kwargs):
        result = MagicMock(returncode=0, stderr="")
        if cmd[:2] == ["git", "log"]:
            result.stdout = "abc123\0feat(phase-1): Task One\n"
        elif cmd[:2] == ["git", "show"]:
            result.stdout = "app.py\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(state_mod.subprocess, "run", mock_run)

    assert reconcile_committed_tasks(sample_state) is True
    assert task["commit_sha"] == "abc123"


def test_reconcile_committed_tasks_matches_test_prefix(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    sample_state["initial_sha"] = "base"
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "pending"
    task["title"] = "Task One"

    def mock_run(cmd, **kwargs):
        result = MagicMock(returncode=0, stderr="")
        if cmd[:2] == ["git", "log"]:
            result.stdout = "abc123\0test(phase-1): Task One\n"
        elif cmd[:2] == ["git", "show"]:
            result.stdout = "tests/test_task_one.py\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(state_mod.subprocess, "run", mock_run)

    assert reconcile_committed_tasks(sample_state) is True
    assert task["commit_sha"] == "abc123"
    assert task["files_changed"] == ["tests/test_task_one.py"]


def test_reconcile_committed_tasks_matches_unit_test_support_commit(
    sample_state, monkeypatch
):
    from unittest.mock import MagicMock

    sample_state["initial_sha"] = "base"
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "pending"
    task["title"] = "Verify client config"
    task["tdd_mode"] = "unit_test"

    def mock_run(cmd, **kwargs):
        result = MagicMock(returncode=0, stderr="")
        if cmd[:2] == ["git", "log"]:
            result.stdout = (
                "abc123\0chore(phase-1): update test verification support\n"
            )
        elif cmd[:2] == ["git", "show"]:
            result.stdout = "package.json\npackage-lock.json\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(state_mod.subprocess, "run", mock_run)

    assert reconcile_committed_tasks(sample_state) is True
    assert task["commit_sha"] == "abc123"
    assert task["tdd_skipped"] == "unit_test verification only — no code written"


def test_reconcile_committed_tasks_does_not_match_unrelated_subject(
    sample_state, monkeypatch
):
    from unittest.mock import MagicMock

    sample_state["initial_sha"] = "base"
    task = sample_state["phases"][0]["tasks"][0]
    task["status"] = "pending"
    task["title"] = "Task One"

    def mock_run(cmd, **kwargs):
        result = MagicMock(returncode=0, stderr="")
        if cmd[:2] == ["git", "log"]:
            result.stdout = "abc123\0chore: unrelated\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(state_mod.subprocess, "run", mock_run)

    assert reconcile_committed_tasks(sample_state) is False
    assert task["status"] == "pending"


def test_save_state_rejects_malformed_task_id(sample_state):
    sample_state["phases"][0]["tasks"][0]["id"] = "bad-id"
    with pytest.raises(ValueError, match="Malformed task id"):
        save_state(sample_state)


def test_update_state_task(sample_state):
    save_state(sample_state)
    update_state(sample_state, task_id="1.1", status="complete")
    assert sample_state["phases"][0]["tasks"][0]["status"] == "complete"


def test_update_state_accepts_task_commit_sha(sample_state):
    save_state(sample_state)
    update_state(sample_state, task_id="1.1", commit_sha="abc123")
    assert sample_state["phases"][0]["tasks"][0]["commit_sha"] == "abc123"


def test_update_state_issue(sample_state):
    sample_state["phases"][0]["review"]["issues"] = [
        {
            "id": "1.1",
            "severity": "HIGH",
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
    ]
    save_state(sample_state)
    update_state(sample_state, phase_id=1, issue_id="1.1", status="fixed")
    assert sample_state["phases"][0]["review"]["issues"][0]["status"] == "fixed"


def test_halt_task(sample_state):
    save_state(sample_state)
    with pytest.raises(SystemExit) as exc:
        halt_task(sample_state, "1.1")
    assert exc.value.code == 1
    assert sample_state["phases"][0]["tasks"][0]["status"] == "halted"


def test_error_task(sample_state):
    save_state(sample_state)
    with pytest.raises(SystemExit) as exc:
        error_task(sample_state, "1.1", "something broke")
    assert exc.value.code == 1
    assert sample_state["phases"][0]["tasks"][0]["status"] == "error"
    assert "something broke" in sample_state["phases"][0]["tasks"][0]["last_error"]


def test_halt_issue(sample_state):
    sample_state["phases"][0]["review"]["issues"] = [
        {
            "id": "1.1",
            "severity": "HIGH",
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
    ]
    save_state(sample_state)
    with pytest.raises(SystemExit) as exc:
        halt_issue(sample_state, 1, "1.1")
    assert exc.value.code == 1
    assert sample_state["phases"][0]["review"]["issues"][0]["status"] == "halted"


def test_error_issue(sample_state):
    sample_state["phases"][0]["review"]["issues"] = [
        {
            "id": "1.1",
            "severity": "HIGH",
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
    ]
    save_state(sample_state)
    with pytest.raises(SystemExit) as exc:
        error_issue(sample_state, 1, "1.1", "issue broke")
    assert exc.value.code == 1
    assert sample_state["phases"][0]["review"]["issues"][0]["status"] == "error"
    assert (
        "issue broke" in sample_state["phases"][0]["review"]["issues"][0]["last_error"]
    )


def test_apply_phase_fields_allows_language(sample_state):
    save_state(sample_state)
    update_state(sample_state, entity_type="phase", phase_id=1, language="typescript")
    assert sample_state["phases"][0]["language"] == "typescript"


def test_error_phase(sample_state):
    save_state(sample_state)
    with pytest.raises(SystemExit) as exc:
        error_phase(sample_state, 1, "spec broke")
    assert exc.value.code == 1
    assert sample_state["phases"][0]["status"] == "error"


# --- init_evaluate_state ---


def test_creates_evaluate_block_when_absent(sample_state):
    from state import init_evaluate_state

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    ev = sample_state["evaluate"]
    assert ev["status"] == "evaluating"
    assert ev["phase_id"] == 7
    assert ev["iterations"] == []


def test_resets_status_to_evaluating_when_present(sample_state):
    from state import init_evaluate_state

    sample_state["evaluate"] = {
        "status": "halted",
        "phase_id": 7,
        "iterations": [{"iteration": 1, "verdict": "BLOCK", "fix_sha": None}],
    }
    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    assert sample_state["evaluate"]["status"] == "evaluating"
    assert len(sample_state["evaluate"]["iterations"]) == 1  # not wiped


def test_saves_state_after_init(sample_state, tmp_path):
    from state import init_evaluate_state

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert loaded["evaluate"]["phase_id"] == 7


# --- update_evaluate_iteration ---


def test_appends_iteration_entry(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    import subprocess

    from state import init_evaluate_state, update_evaluate_iteration

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)

    mock_proc = MagicMock()
    mock_proc.stdout = "abc123\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_proc)

    result1 = {
        "signal": {"iteration": 1, "verdict": "APPROVE", "issues": []},
        "usage": {},
    }
    result2 = {
        "signal": {"iteration": 2, "verdict": "BLOCK", "issues": []},
        "usage": {},
    }
    update_evaluate_iteration(sample_state, result1)
    update_evaluate_iteration(sample_state, result2)
    assert len(sample_state["evaluate"]["iterations"]) == 2


def test_entry_has_correct_fields(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    import subprocess

    from state import init_evaluate_state, update_evaluate_iteration

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)

    mock_proc = MagicMock()
    mock_proc.stdout = "deadbeef\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_proc)

    issue = {"id": "7.1", "severity": "HIGH", "title": "bug"}
    result = {
        "signal": {"iteration": 1, "verdict": "BLOCK", "issues": [issue]},
        "usage": {},
    }
    update_evaluate_iteration(sample_state, result)

    entry = sample_state["evaluate"]["iterations"][0]
    assert entry["iteration"] == 1
    assert entry["verdict"] == "BLOCK"
    assert entry["sha_at_evaluate"] == "deadbeef"
    assert entry["issues"] == [issue]
    assert entry["fix_sha"] is None


def test_fix_sha_initialises_to_none(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    import subprocess

    from state import init_evaluate_state, update_evaluate_iteration

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)

    mock_proc = MagicMock()
    mock_proc.stdout = "sha\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_proc)

    result = {
        "signal": {"iteration": 1, "verdict": "APPROVE", "issues": []},
        "usage": {},
    }
    update_evaluate_iteration(sample_state, result)
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_start_evaluate_iteration_records_attempt_and_current_iteration(sample_state):
    from state import init_evaluate_state, start_evaluate_iteration

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    start_evaluate_iteration(sample_state, 2)

    ev = sample_state["evaluate"]
    assert ev["status"] == "evaluating"
    assert ev["current_iteration"] == 2
    assert ev["attempts"] == 1
    assert ev["last_started_at"]


def test_update_evaluate_iteration_saves_score(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    import subprocess

    from state import init_evaluate_state, update_evaluate_iteration

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha\n"))

    result = {
        "signal": {
            "iteration": 1,
            "verdict": "APPROVE",
            "issues": [],
            "score": {"total": 50, "max": 50},
        },
        "usage": {},
    }
    update_evaluate_iteration(sample_state, result)

    assert sample_state["evaluate"]["iterations"][0]["score"] == {
        "total": 50,
        "max": 50,
    }


def test_update_evaluate_iteration_records_finished_at(sample_state, monkeypatch):
    from unittest.mock import MagicMock

    import subprocess

    from state import (
        init_evaluate_state,
        start_evaluate_iteration,
        update_evaluate_iteration,
    )

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    start_evaluate_iteration(sample_state, 1)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha\n"))

    update_evaluate_iteration(
        sample_state,
        {"signal": {"iteration": 1, "verdict": "APPROVE", "issues": []}, "usage": {}},
    )

    assert sample_state["evaluate"]["current_iteration"] is None
    assert sample_state["evaluate"]["last_finished_at"]


def test_error_evaluate_records_status_and_error(sample_state):
    from state import error_evaluate, init_evaluate_state

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)

    with pytest.raises(SystemExit) as exc:
        error_evaluate(sample_state, "timeout", "slow evaluator")

    assert exc.value.code == 1
    assert sample_state["evaluate"]["status"] == "timeout"
    assert sample_state["evaluate"]["last_error"] == ["slow evaluator"]


# --- update_evaluate_status ---


def test_sets_status_and_saves(sample_state):
    from state import init_evaluate_state, update_evaluate_status

    save_state(sample_state)
    init_evaluate_state(sample_state, 7)
    update_evaluate_status(sample_state, "complete")
    assert sample_state["evaluate"]["status"] == "complete"
    loaded = json.loads(Path("workspace/state.json").read_text(encoding="utf-8"))
    assert loaded["evaluate"]["status"] == "complete"


# --- find_evaluate_issue ---


def test_finds_issue_across_iterations(sample_state):
    from state import find_evaluate_issue

    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 7,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "issues": [{"id": "7.1", "title": "bug1"}],
            },
            {
                "iteration": 2,
                "verdict": "BLOCK",
                "issues": [{"id": "7.2", "title": "bug2"}],
            },
        ],
    }
    save_state(sample_state)
    found = find_evaluate_issue(sample_state, "7.2")
    assert found is not None
    assert found["title"] == "bug2"


def test_returns_none_when_not_found(sample_state):
    from state import find_evaluate_issue

    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 7,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "issues": [{"id": "7.1", "title": "bug1"}],
            },
        ],
    }
    save_state(sample_state)
    assert find_evaluate_issue(sample_state, "7.99") is None


def test_returns_none_when_evaluate_absent(sample_state):
    from state import find_evaluate_issue

    save_state(sample_state)
    assert find_evaluate_issue(sample_state, "7.1") is None
