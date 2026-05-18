from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import regression as regression_mod
import state as state_mod
from regression import (
    REGRESSION_INFRA_FAILURE,
    REGRESSION_PRODUCT_FAILURE,
    REGRESSION_TIMEOUT,
    collect_regression_commands,
    run_phase_regression_gate,
)
from state import save_state


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def _make_harness(sample_config, sample_profile):
    harness = MagicMock()
    harness.config = sample_config
    harness.phase_type_for.side_effect = lambda phase_id: (
        "integration" if int(phase_id) == 2 else "development"
    )
    harness.profile_for.return_value = sample_profile
    return harness


def _completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_collect_regression_commands_deduplicates_and_stops_at_current_phase(
    sample_state, sample_config, sample_profile
):
    sample_state["total_phases"] = 3
    sample_state["phases"].extend(
        [
            {
                "id": 2,
                "status": "building",
                "phase_type": "integration",
                "tasks": [],
                "review": {"status": "pending", "issues": []},
            },
            {
                "id": 3,
                "status": "pending",
                "phase_type": "development",
                "tasks": [],
                "review": {"status": "pending", "issues": []},
            },
        ]
    )
    harness = _make_harness(sample_config, sample_profile)

    commands = collect_regression_commands(harness, sample_state, through_phase_id=2)

    assert commands == [["pytest"], ["pytest", "-m", "integration"]]


def test_run_phase_regression_gate_pass_marks_status_passed(
    sample_state, sample_config, sample_profile, monkeypatch
):
    save_state(sample_state)
    harness = _make_harness(sample_config, sample_profile)
    monkeypatch.setattr(
        regression_mod,
        "run_command",
        lambda cmd, **kwargs: (cmd, _completed(returncode=0, stdout="ok")),
    )
    monkeypatch.setattr(regression_mod, "_current_head", lambda: "sha123")

    assert run_phase_regression_gate(harness, sample_state, 1) is True

    regression = sample_state["phases"][0]["regression"]
    assert regression["status"] == "passed"
    assert regression["passed_sha"] == "sha123"


def test_run_phase_regression_gate_fail_creates_high_issue_with_next_phase_id(
    sample_state, sample_config, sample_profile, monkeypatch
):
    sample_state["phases"][0]["review"]["issues"] = [
        {
            "id": "1.10",
            "severity": "HIGH",
            "dimension": "Review",
            "file": "app.py",
            "title": "Existing issue",
            "status": "fixed",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": "old",
            "last_error": [],
        }
    ]
    save_state(sample_state)
    harness = _make_harness(sample_config, sample_profile)
    monkeypatch.setattr(
        regression_mod,
        "run_command",
        lambda cmd, **kwargs: (
            cmd,
            _completed(returncode=1, stdout="failed", stderr="boom"),
        ),
    )

    assert run_phase_regression_gate(harness, sample_state, 1) is False

    phase = sample_state["phases"][0]
    issue = phase["review"]["issues"][-1]
    assert phase["regression"]["status"] == "failed"
    assert phase["review"]["status"] == "fixing"
    assert issue["id"] == "1.11"
    assert issue["severity"] == "HIGH"
    assert issue["dimension"] == "Regression"
    assert issue["source"] == "regression"
    assert "pytest" in Path("workspace/review_report.md").read_text(encoding="utf-8")


def test_run_phase_regression_gate_reopens_existing_regression_issue(
    sample_state, sample_config, sample_profile, monkeypatch
):
    failure = {
        "cmd": ["pytest", "--ignore=.pytest_cache", "--ignore=.tmp"],
        "returncode": 1,
        "stdout_tail": "failed",
        "stderr_tail": "boom",
    }
    key = regression_mod._failure_key(failure)
    sample_state["phases"][0]["review"]["issues"] = [
        {
            "id": "1.1",
            "severity": "HIGH",
            "dimension": "Regression",
            "file": "FULL_REGRESSION",
            "title": "Full regression failed before phase advancement",
            "status": "fixed",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": "old",
            "last_error": [],
            "source": "regression",
            "regression_key": key,
            "regression_evidence": failure,
        }
    ]
    save_state(sample_state)
    harness = _make_harness(sample_config, sample_profile)
    monkeypatch.setattr(
        regression_mod,
        "run_command",
        lambda cmd, **kwargs: (
            cmd,
            _completed(returncode=1, stdout="failed", stderr="boom"),
        ),
    )

    assert run_phase_regression_gate(harness, sample_state, 1) is False

    issues = sample_state["phases"][0]["review"]["issues"]
    assert len(issues) == 1
    assert issues[0]["status"] == "open"
    assert issues[0]["attempts"] == 1


def test_run_phase_regression_gate_tmp_permission_error_blocks_without_issue(
    sample_state, sample_config, sample_profile, monkeypatch
):
    save_state(sample_state)
    harness = _make_harness(sample_config, sample_profile)
    stdout = (
        "E   PermissionError: [WinError 5] Access is denied: "
        "'D:\\Animal_Adventure\\.tmp\\pytest\\pytest-of-OEM'\n"
        "ERROR .tmp/pytest/pytest-of-OEM - PermissionError\n"
        "Interrupted: 2 errors during collection"
    )
    monkeypatch.setattr(
        regression_mod,
        "run_command",
        lambda cmd, **kwargs: (cmd, _completed(returncode=2, stdout=stdout)),
    )

    assert run_phase_regression_gate(harness, sample_state, 1) is False

    phase = sample_state["phases"][0]
    regression = phase["regression"]
    assert regression["status"] == "blocked"
    assert regression["failure_kind"] == REGRESSION_INFRA_FAILURE
    assert regression["issues"] == []
    assert phase["review"]["issues"] == []
    assert Path(regression["artifact_path"]).exists()


def test_run_phase_regression_gate_timeout_blocks_without_issue(
    sample_state, sample_config, sample_profile, monkeypatch
):
    save_state(sample_state)
    harness = _make_harness(sample_config, sample_profile)
    monkeypatch.setattr(
        regression_mod,
        "run_command",
        lambda cmd, **kwargs: (
            cmd,
            _completed(returncode=124, stderr="command timed out after 600s"),
        ),
    )

    assert run_phase_regression_gate(harness, sample_state, 1) is False

    phase = sample_state["phases"][0]
    regression = phase["regression"]
    assert regression["status"] == "blocked"
    assert regression["failure_kind"] == REGRESSION_TIMEOUT
    assert phase["review"]["issues"] == []


def test_run_phase_regression_gate_product_failure_keeps_high_issue_flow(
    sample_state, sample_config, sample_profile, monkeypatch
):
    save_state(sample_state)
    harness = _make_harness(sample_config, sample_profile)
    monkeypatch.setattr(
        regression_mod,
        "run_command",
        lambda cmd, **kwargs: (
            cmd,
            _completed(returncode=1, stdout="FAILED tests/test_game.py::test_score"),
        ),
    )

    assert run_phase_regression_gate(harness, sample_state, 1) is False

    phase = sample_state["phases"][0]
    regression = phase["regression"]
    issue = phase["review"]["issues"][-1]
    assert regression["status"] == "failed"
    assert regression["failure_kind"] == REGRESSION_PRODUCT_FAILURE
    assert phase["review"]["status"] == "fixing"
    assert issue["severity"] == "HIGH"
    assert issue["failure_kind"] == REGRESSION_PRODUCT_FAILURE
