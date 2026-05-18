"""Unit tests for evaluate.py"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agents
import evaluate as eval_mod
import state as state_mod
from evaluate import (
    _extract_rubric_section,
    _infer_evaluate_app_type,
    _normalize_evaluate_result,
    _run_evaluate_fix,
    _should_early_stop,
    _write_evaluate_fix_md,
    run_evaluate_cycle,
    verify_evaluate_fix,
)
from state import save_state


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))
    monkeypatch.setattr(
        eval_mod, "EVALUATE_FIX_MD", tmp_workspace / "workspace" / "evaluate_fix.md"
    )
    monkeypatch.setattr(
        eval_mod, "RUBRIC_REPORT_MD", tmp_workspace / "workspace" / "rubric-report.md"
    )


def _approve(iteration):
    return {
        "signal": {"iteration": iteration, "verdict": "APPROVE", "issues": []},
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _approve_with_score(iteration, total=50, max_score=50):
    result = _approve(iteration)
    result["signal"]["score"] = {"total": total, "max": max_score}
    return result


def _block(iteration):
    return {
        "signal": {
            "iteration": iteration,
            "verdict": "BLOCK",
            "issues": [
                {
                    "id": f"2.{iteration}",
                    "severity": "HIGH",
                    "title": "Bug",
                    "file": "app.py",
                    "dimension": "Security",
                    "description": "Bad",
                    "suggestion": "Fix",
                    "log_info": "",
                    "refs": "",
                    "non_automatable_reason": "unit test fixture issue",
                }
            ],
        },
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _fix_result():
    return {
        "signal": {"fixes": [{"id": "2.1", "status": "fixed", "files_changed": ["app.py"]}]},
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _make_harness(sample_profile, sample_config):
    h = MagicMock()
    h.config = sample_config
    h.profile_for = MagicMock(return_value=sample_profile)
    h.phase_type_for = MagicMock(return_value="development")
    return h


def _git_ok(*a, **kw):
    cmd = a[0] if a else kw.get("args", [])
    if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
        return MagicMock(returncode=0, stdout="sha123\n")
    return MagicMock(returncode=0, stdout="")


def _evaluate_issue_with_test():
    return {
        "id": "2.1",
        "severity": "HIGH",
        "title": "Bug",
        "file": "app.py",
        "dimension": "Security",
        "description": "Bad",
        "suggestion": "Fix",
        "test_cases": [
            {
                "id": "2.1-t1",
                "description": "Reproduce bug",
                "command": ["pytest", "targeted"],
            }
        ],
    }


# ── _extract_rubric_section ──────────────────────────────────────────────────


def test_extract_rubric_returns_empty_when_file_missing():
    assert _extract_rubric_section(1) == ""


def test_extract_rubric_finds_correct_iteration(tmp_workspace):
    (tmp_workspace / "workspace" / "rubric-report.md").write_text(
        "# Rubric Report — Iteration 1\nContent A.\n\n# Rubric Report — Iteration 2\nContent B.\n",
        encoding="utf-8",
    )
    result = _extract_rubric_section(2)
    assert "Content B." in result
    assert "Content A." not in result


def test_extract_rubric_stops_at_next_h1(tmp_workspace):
    (tmp_workspace / "workspace" / "rubric-report.md").write_text(
        "# Rubric Report — Iteration 1\nBody.\n\n# Other\nShould not appear.\n",
        encoding="utf-8",
    )
    assert "Should not appear." not in _extract_rubric_section(1)


def test_extract_rubric_returns_empty_when_iteration_not_found(tmp_workspace):
    (tmp_workspace / "workspace" / "rubric-report.md").write_text(
        "# Rubric Report — Iteration 1\nBody.\n",
        encoding="utf-8",
    )
    assert _extract_rubric_section(99) == ""


def test_extract_rubric_returns_entire_content_for_last_section(tmp_workspace):
    (tmp_workspace / "workspace" / "rubric-report.md").write_text(
        "# Rubric Report — Iteration 1\nOnly section.\n",
        encoding="utf-8",
    )
    result = _extract_rubric_section(1)
    assert "Only section." in result


def test_infer_evaluate_app_type_keeps_explicit_web(sample_state):
    sample_state["app_type"] = "web"
    assert _infer_evaluate_app_type(sample_state) == "web"


def test_infer_evaluate_app_type_web_for_typescript_phase(sample_state):
    sample_state["app_type"] = "cli"
    sample_state["phases"][0]["language"] = "typescript"
    assert _infer_evaluate_app_type(sample_state) == "web"


def test_infer_evaluate_app_type_web_for_client_index(tmp_workspace, sample_state):
    sample_state["app_type"] = "cli"
    sample_state["phases"][0]["language"] = "python"
    (tmp_workspace / "client").mkdir()
    (tmp_workspace / "client" / "index.html").write_text("<div></div>", encoding="utf-8")
    assert _infer_evaluate_app_type(sample_state) == "web"


def test_infer_evaluate_app_type_web_for_root_frontend(tmp_workspace, sample_state):
    sample_state["app_type"] = "cli"
    sample_state["phases"][0]["language"] = "python"
    (tmp_workspace / "src").mkdir()
    (tmp_workspace / "src" / "main.ts").write_text("export {}", encoding="utf-8")
    assert _infer_evaluate_app_type(sample_state) == "web"


# ── _write_evaluate_fix_md ───────────────────────────────────────────────────


def test_write_evaluate_fix_md_creates_file_with_issue_fields(tmp_workspace, sample_state):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "fix_sha": None,
                "issues": [
                    {
                        "id": "2.1",
                        "severity": "HIGH",
                        "title": "Bad thing",
                        "file": "app.py",
                        "dimension": "Security",
                        "description": "It is bad",
                        "suggestion": "Fix it",
                        "log_info": "stacktrace",
                        "refs": "spec.md",
                    }
                ],
            }
        ],
    }
    _write_evaluate_fix_md(sample_state, 1)
    content = (tmp_workspace / "workspace" / "evaluate_fix.md").read_text(encoding="utf-8")
    assert "Bad thing" in content
    assert "HIGH" in content
    assert "app.py" in content
    assert "It is bad" in content


def test_write_evaluate_fix_md_includes_rubric_section(tmp_workspace, sample_state):
    (tmp_workspace / "workspace" / "rubric-report.md").write_text(
        "# Rubric Report — Iteration 1\nScore: 5/10\n",
        encoding="utf-8",
    )
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "fix_sha": None,
                "issues": [],
            }
        ],
    }
    _write_evaluate_fix_md(sample_state, 1)
    content = (tmp_workspace / "workspace" / "evaluate_fix.md").read_text(encoding="utf-8")
    assert "Score: 5/10" in content


def test_write_evaluate_fix_md_works_with_empty_issues(tmp_workspace, sample_state):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "fix_sha": None, "issues": []}
        ],
    }
    _write_evaluate_fix_md(sample_state, 1)
    assert (tmp_workspace / "workspace" / "evaluate_fix.md").exists()


def test_write_evaluate_fix_md_includes_test_cases(tmp_workspace, sample_state):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "fix_sha": None,
                "issues": [_evaluate_issue_with_test()],
            }
        ],
    }

    _write_evaluate_fix_md(sample_state, 1)

    content = (tmp_workspace / "workspace" / "evaluate_fix.md").read_text(
        encoding="utf-8"
    )
    assert "Test cases" in content
    assert "2.1-t1" in content
    assert "pytest" in content


# ── verify_evaluate_fix ──────────────────────────────────────────────────────


def test_verify_sets_fix_sha_when_tests_pass(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _git_ok)
    harness = _make_harness(sample_profile, sample_config)
    verify_evaluate_fix(harness, sample_state, 2, 1, "oldsha")
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] == "sha123"


def test_verify_clears_evaluate_fix_md_on_success(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    fix_md = tmp_workspace / "workspace" / "evaluate_fix.md"
    fix_md.write_text("content", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _git_ok)
    harness = _make_harness(sample_profile, sample_config)
    verify_evaluate_fix(harness, sample_state, 2, 1, "pre")
    assert fix_md.read_text(encoding="utf-8") == ""


def test_verify_does_not_set_fix_sha_when_tests_fail(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(stdout="sha\n", returncode=0)
        return MagicMock(returncode=1, stdout="FAILED")

    monkeypatch.setattr(subprocess, "run", mock_run)
    harness = _make_harness(sample_profile, sample_config)
    verify_evaluate_fix(harness, sample_state, 2, 1, "pre")
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_verify_does_not_set_fix_sha_when_sha_unchanged(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _git_ok)
    harness = _make_harness(sample_profile, sample_config)

    verify_evaluate_fix(harness, sample_state, 2, 1, "sha123")

    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_verify_does_not_clear_fix_md_when_sha_unchanged(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    fix_md = tmp_workspace / "workspace" / "evaluate_fix.md"
    fix_md.write_text("content", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _git_ok)
    harness = _make_harness(sample_profile, sample_config)

    verify_evaluate_fix(harness, sample_state, 2, 1, "sha123")

    assert fix_md.read_text(encoding="utf-8") == "content"


def test_verify_does_not_set_fix_sha_when_git_rev_parse_fails(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=1, stdout="", stderr="not git")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    harness = _make_harness(sample_profile, sample_config)

    verify_evaluate_fix(harness, sample_state, 2, 1, "pre")

    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_verify_updates_requested_iteration_not_last(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "s1", "issues": [], "fix_sha": None},
            {"iteration": 2, "verdict": "APPROVE", "sha_at_evaluate": "s2", "issues": [], "fix_sha": None},
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _git_ok)
    harness = _make_harness(sample_profile, sample_config)

    verify_evaluate_fix(harness, sample_state, 2, 1, "oldsha")

    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] == "sha123"
    assert sample_state["evaluate"]["iterations"][1]["fix_sha"] is None


def test_verify_deduplicates_test_commands(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["phases"].append(
        {
            "id": 2,
            "title": "Phase Two",
            "language": "python",
            "phase_type": "development",
            "status": "complete",
            "tasks": [],
            "review": {"status": "pending", "verdict": None, "sha_at_review": None, "issues": []},
        }
    )
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 3,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    test_runs: list = []

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(stdout="sha\n", returncode=0)
        test_runs.append(list(cmd))
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    harness = _make_harness(sample_profile, sample_config)
    verify_evaluate_fix(harness, sample_state, 3, 1, "pre")
    assert len(test_runs) == 1


def test_verify_runs_multiple_unique_test_commands(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    ts_profile = dict(sample_profile, name="typescript", test_cmd=["npx", "vitest", "run"])
    sample_state["phases"].append(
        {
            "id": 2,
            "title": "Phase Two",
            "language": "typescript",
            "phase_type": "development",
            "status": "complete",
            "tasks": [],
            "review": {"status": "pending", "verdict": None, "sha_at_review": None, "issues": []},
        }
    )
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 3,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    test_runs: list = []

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(stdout="sha\n", returncode=0)
        test_runs.append(list(cmd))
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    def profile_for(pid):
        return sample_profile if pid == 1 else ts_profile

    harness = _make_harness(sample_profile, sample_config)
    harness.profile_for = profile_for
    verify_evaluate_fix(harness, sample_state, 3, 1, "pre")
    assert len(test_runs) == 2


def test_verify_evaluate_fix_uses_verification_profiles_for_unique_commands(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "abc", "issues": [], "fix_sha": None}
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    ts_profile = dict(
        sample_profile,
        name="typescript",
        integration_test_cmd=["npm", "run", "test:e2e"],
    )
    sample_state["phases"][0]["phase_type"] = "e2e"
    test_runs: list = []

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(stdout="sha\n", returncode=0)
        test_runs.append(list(cmd))
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    harness = _make_harness(sample_profile, sample_config)
    harness.phase_type_for = MagicMock(return_value="e2e")
    harness.verification_profiles_for = MagicMock(return_value=[sample_profile, ts_profile])

    verify_evaluate_fix(harness, sample_state, 2, 1, "pre")

    assert sample_profile["integration_test_cmd"] in test_runs
    assert ts_profile["integration_test_cmd"] in test_runs


def test_low_score_approve_is_normalized_to_block(sample_config):
    result = _approve_with_score(1, total=80, max_score=100)
    sample_config["evaluation_min_score_pct"] = 0.9

    _normalize_evaluate_result(result, 2, sample_config)

    assert result["signal"]["verdict"] == "BLOCK"


def test_low_score_approve_adds_synthetic_score_issue_when_no_issues(sample_config):
    result = _approve_with_score(1, total=80, max_score=100)
    sample_config["evaluation_min_score_pct"] = 0.9

    _normalize_evaluate_result(result, 2, sample_config)

    issue = result["signal"]["issues"][0]
    assert issue["severity"] == "HIGH"
    assert issue["title"] == "Evaluation score below threshold"


def test_early_stop_requires_score_at_or_above_threshold(sample_config):
    state = {
        "evaluate": {
            "iterations": [
                {"iteration": 1, "verdict": "APPROVE", "score": {"total": 80, "max": 100}},
                {"iteration": 2, "verdict": "APPROVE", "score": {"total": 100, "max": 100}},
            ]
        }
    }
    sample_config["evaluate_early_stop_on_full_score"] = True
    sample_config["evaluation_min_score_pct"] = 0.9

    assert _should_early_stop(state, sample_config) is False


def test_run_evaluate_fix_skips_verify_when_all_fixes_open(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [
                    {
                        "id": "2.1",
                        "severity": "HIGH",
                        "title": "Bug",
                        "file": "app.py",
                        "dimension": "Security",
                        "non_automatable_reason": "unit test fixture issue",
                    }
                ],
                "fix_sha": None,
            }
        ],
    }
    (tmp_workspace / "workspace" / "evaluate_fix.md").write_text("content", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(
        agents,
        "fix_evaluate_issues",
        lambda *a, **kw: {"signal": {"fixes": [{"id": "2.1", "status": "open"}]}, "usage": {}},
    )
    harness = _make_harness(sample_profile, sample_config)

    _run_evaluate_fix(harness, sample_state, 2, 1, [sample_profile])

    last_iter = sample_state["evaluate"]["iterations"][0]
    assert last_iter["fix_sha"] is None
    assert last_iter["fix_attempts"] == 1


def test_run_evaluate_fix_records_last_fix_error_on_no_fixed(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [],
                "fix_sha": None,
            }
        ],
    }
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(
        agents,
        "fix_evaluate_issues",
        lambda *a, **kw: {"signal": {"fixes": [{"id": "2.1", "status": "open"}]}, "usage": {}},
    )
    harness = _make_harness(sample_profile, sample_config)

    _run_evaluate_fix(harness, sample_state, 2, 1, [sample_profile])

    assert sample_state["evaluate"]["iterations"][0]["last_fix_error"]


def test_run_evaluate_fix_records_no_fixed_on_requested_iteration(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "s1",
                "issues": [],
                "fix_sha": None,
            },
            {
                "iteration": 2,
                "verdict": "APPROVE",
                "sha_at_evaluate": "s2",
                "issues": [],
                "fix_sha": None,
            },
        ],
    }
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(
        agents,
        "fix_evaluate_issues",
        lambda *a, **kw: {"signal": {"fixes": [{"id": "2.1", "status": "open"}]}, "usage": {}},
    )
    harness = _make_harness(sample_profile, sample_config)

    _run_evaluate_fix(harness, sample_state, 2, 1, [sample_profile])

    assert sample_state["evaluate"]["iterations"][0]["fix_attempts"] == 1
    assert sample_state["evaluate"]["iterations"][0]["last_fix_error"]
    assert "fix_attempts" not in sample_state["evaluate"]["iterations"][1]


def test_run_evaluate_fix_external_dependency_records_block(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [],
                "fix_sha": None,
            }
        ],
    }
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(
        agents,
        "fix_evaluate_issues",
        MagicMock(side_effect=agents.ExternalDependencyError("429")),
    )
    harness = _make_harness(sample_profile, sample_config)

    with pytest.raises(SystemExit):
        _run_evaluate_fix(harness, sample_state, 2, 1, [sample_profile])

    assert sample_state["evaluate"]["status"] == "blocked_external_dependency"
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_run_evaluate_fix_timeout_records_timeout(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [],
                "fix_sha": None,
            }
        ],
    }
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(
        agents,
        "fix_evaluate_issues",
        MagicMock(side_effect=agents.TimeoutError("timeout after 600s")),
    )
    harness = _make_harness(sample_profile, sample_config)

    with pytest.raises(SystemExit):
        _run_evaluate_fix(harness, sample_state, 2, 1, [sample_profile])

    assert sample_state["evaluate"]["status"] == "timeout"
    assert sample_state["evaluate"]["last_error"] == ["timeout after 600s"]
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_run_evaluate_fix_subprocess_error_records_error(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [],
                "fix_sha": None,
            }
        ],
    }
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(
        agents,
        "fix_evaluate_issues",
        MagicMock(side_effect=agents.SubprocessError("could not extract signal")),
    )
    harness = _make_harness(sample_profile, sample_config)

    with pytest.raises(SystemExit):
        _run_evaluate_fix(harness, sample_state, 2, 1, [sample_profile])

    assert sample_state["evaluate"]["status"] == "error"
    assert sample_state["evaluate"]["last_error"] == ["could not extract signal"]
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] is None


def test_run_evaluate_fix_strict_flow_requires_red_green_and_full_regression(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [_evaluate_issue_with_test()],
                "fix_sha": None,
            }
        ],
    }
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(
        agents,
        "author_evaluate_tests",
        lambda *a, **kw: {
            "signal": {
                "tests": [
                    {
                        "id": "2.1-t1",
                        "issue_id": "2.1",
                        "status": "authored",
                        "files_changed": ["tests/test_bug.py"],
                        "command": ["pytest", "targeted"],
                    }
                ]
            },
            "usage": {},
        },
    )
    monkeypatch.setattr(agents, "fix_evaluate_issues", lambda *a, **kw: _fix_result())
    git_shas = iter(["test_sha", "pre_fix", "fixed_sha"])
    targeted_runs = []

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout=f"{next(git_shas)}\n")
        if cmd == ["pytest", "targeted"]:
            targeted_runs.append(cmd)
            return MagicMock(returncode=1 if len(targeted_runs) == 1 else 0, stdout="")
        if cmd == ["pytest"]:
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    _run_evaluate_fix(
        _make_harness(sample_profile, sample_config), sample_state, 2, 1, [sample_profile]
    )

    iteration = sample_state["evaluate"]["iterations"][0]
    assert iteration["test_status"] == "red_verified"
    assert iteration["red_verification"]["commands"][0]["returncode"] == 1
    assert iteration["green_verification"]["commands"][0]["returncode"] == 0
    assert iteration["full_regression"]["commands"][0]["returncode"] == 0
    assert iteration["fix_sha"] == "fixed_sha"


def test_run_evaluate_fix_full_regression_failure_blocks_next_evaluate(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "abc",
                "issues": [_evaluate_issue_with_test()],
                "fix_sha": None,
            }
        ],
    }
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(
        agents,
        "author_evaluate_tests",
        lambda *a, **kw: {
            "signal": {
                "tests": [
                    {
                        "id": "2.1-t1",
                        "issue_id": "2.1",
                        "status": "authored",
                        "files_changed": ["tests/test_bug.py"],
                        "command": ["pytest", "targeted"],
                    }
                ]
            },
            "usage": {},
        },
    )
    monkeypatch.setattr(agents, "fix_evaluate_issues", lambda *a, **kw: _fix_result())
    git_shas = iter(["test_sha", "pre_fix"])
    targeted_runs = []

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout=f"{next(git_shas)}\n")
        if cmd == ["pytest", "targeted"]:
            targeted_runs.append(cmd)
            return MagicMock(returncode=1 if len(targeted_runs) == 1 else 0, stdout="")
        if cmd == ["pytest"]:
            return MagicMock(returncode=1, stdout="FAILED")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    _run_evaluate_fix(
        _make_harness(sample_profile, sample_config), sample_state, 2, 1, [sample_profile]
    )

    iteration = sample_state["evaluate"]["iterations"][0]
    assert iteration["fix_sha"] is None
    assert iteration["last_fix_error"] == "full regression failed after evaluate fix"
    assert sample_state["evaluate"]["status"] == "regression_verifying"


# ── run_evaluate_cycle ───────────────────────────────────────────────────────


def test_run_evaluate_cycle_calls_evaluate_three_times(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    calls: list = []

    def mock_evaluate(model, state, iteration, spec, config):
        calls.append(iteration)
        return _approve(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert calls == [1, 2, 3]


def test_run_evaluate_cycle_respects_configured_max_iterations(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_config["max_evaluate_iterations"] = 2
    calls: list = []

    def mock_evaluate(model, state, iteration, spec, config):
        calls.append(iteration)
        return _approve(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert calls == [1, 2]


def test_run_evaluate_cycle_rejects_iterations_above_hook_cap(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_config["max_evaluate_iterations"] = 4
    monkeypatch.setattr(
        agents,
        "evaluate",
        MagicMock(side_effect=AssertionError("evaluate should not run")),
    )

    with pytest.raises(ValueError, match="max_evaluate_iterations"):
        run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)


def test_run_evaluate_cycle_defaults_to_constant_when_config_missing(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_config.pop("max_evaluate_iterations", None)
    calls: list = []

    def mock_evaluate(model, state, iteration, spec, config):
        calls.append(iteration)
        return _approve(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert calls == [1, 2, 3]


def test_run_evaluate_cycle_status_complete_when_all_approve(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", lambda model, state, iteration, spec, cfg: _approve(iteration))

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert sample_state["evaluate"]["status"] == "complete"


def test_run_evaluate_cycle_persists_evaluate_app_type(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["app_type"] = "cli"
    sample_state["phases"][0]["language"] = "typescript"
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", lambda model, state, iteration, spec, cfg: _approve(iteration))

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert sample_state["evaluate"]["app_type"] == "web"


def test_run_evaluate_cycle_external_dependency_does_not_append_iteration(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(
        agents,
        "evaluate",
        MagicMock(side_effect=agents.ExternalDependencyError("429")),
    )

    with pytest.raises(SystemExit):
        run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert sample_state["evaluate"]["status"] == "blocked_external_dependency"
    assert sample_state["evaluate"]["iterations"] == []


def test_run_evaluate_cycle_subprocess_error_records_error(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(
        agents,
        "evaluate",
        MagicMock(side_effect=agents.SubprocessError("could not extract signal")),
    )

    with pytest.raises(SystemExit):
        run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert sample_state["evaluate"]["status"] == "error"
    assert sample_state["evaluate"]["last_error"] == ["could not extract signal"]
    assert sample_state["evaluate"]["iterations"] == []


def test_run_evaluate_cycle_timeout_records_timeout(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(
        agents,
        "evaluate",
        MagicMock(side_effect=agents.TimeoutError("timeout after 600s")),
    )

    with pytest.raises(SystemExit):
        run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert sample_state["evaluate"]["status"] == "timeout"
    assert sample_state["evaluate"]["last_error"] == ["timeout after 600s"]
    assert sample_state["evaluate"]["iterations"] == []


def test_run_evaluate_cycle_iteration_mismatch_records_error(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    (tmp_workspace / "workspace" / "rubric-report.md").write_text(
        "# Rubric Report — Iteration 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(
        agents,
        "evaluate",
        lambda model, state, iteration, spec, cfg: _approve(iteration + 1),
    )

    with pytest.raises(SystemExit):
        run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert sample_state["evaluate"]["status"] == "error"
    assert "expected 1" in sample_state["evaluate"]["last_error"][-1]
    assert "rubric_report_has_iteration=True" in sample_state["evaluate"]["last_error"][-1]
    assert sample_state["evaluate"]["iterations"] == []


def test_run_evaluate_cycle_early_stop_disabled_by_default_after_full_scores(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    calls: list = []

    def mock_evaluate(model, state, iteration, spec, config):
        calls.append(iteration)
        return _approve_with_score(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert calls == [1, 2, 3]


def test_run_evaluate_cycle_early_stop_enabled_after_two_full_scores(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_config["evaluate_early_stop_on_full_score"] = True
    calls: list = []

    def mock_evaluate(model, state, iteration, spec, config):
        calls.append(iteration)
        return _approve_with_score(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert calls == [1, 2]
    assert sample_state["evaluate"]["status"] == "complete"


def test_run_evaluate_cycle_halts_and_exits_on_final_block(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", lambda model, state, iteration, spec, cfg: _block(iteration))
    monkeypatch.setattr(agents, "fix_evaluate_issues", lambda *a, **kw: _fix_result())
    monkeypatch.setattr(
        eval_mod,
        "verify_evaluate_fix",
        lambda h, state, eid, it, pre: state["evaluate"]["iterations"][it - 1].__setitem__(
            "fix_sha", "fixed"
        ),
    )

    with pytest.raises(SystemExit) as exc:
        run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert exc.value.code == 1
    assert sample_state["evaluate"]["status"] == "halted"


def test_run_evaluate_cycle_calls_fix_on_block(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    fix_calls: list = []

    def mock_fix(source_file, profiles, config, **kw):
        fix_calls.append(True)
        return _fix_result()

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)

    results = [_block(1), _approve(2), _approve(3)]
    call_idx = 0

    def mock_evaluate(model, state, iteration, spec, cfg):
        nonlocal call_idx
        r = results[call_idx]
        call_idx += 1
        return r

    monkeypatch.setattr(agents, "evaluate", mock_evaluate)
    monkeypatch.setattr(agents, "fix_evaluate_issues", mock_fix)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert len(fix_calls) == 1


def test_run_evaluate_cycle_skips_completed_iterations_on_resume(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "APPROVE", "sha_at_evaluate": "s1", "issues": [], "fix_sha": None},
            {"iteration": 2, "verdict": "APPROVE", "sha_at_evaluate": "s2", "issues": [], "fix_sha": None},
        ],
    }
    calls: list = []

    def mock_evaluate(model, state, iteration, spec, cfg):
        calls.append(iteration)
        return _approve(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert calls == [3]


def test_run_evaluate_cycle_reenters_fix_for_block_without_fix_sha_on_resume(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {"iteration": 1, "verdict": "BLOCK", "sha_at_evaluate": "s1", "issues": [], "fix_sha": None},
        ],
    }
    fix_calls: list = []

    def mock_fix(source_file, profiles, config, **kw):
        fix_calls.append(True)
        return _fix_result()

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", lambda model, state, iteration, spec, cfg: _approve(iteration))
    monkeypatch.setattr(agents, "fix_evaluate_issues", mock_fix)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert fix_calls


def test_run_evaluate_cycle_reenters_fix_for_earlier_block_iteration_on_resume(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "s1",
                "issues": [
                    {
                        "id": "2.1",
                        "severity": "HIGH",
                        "title": "First iteration bug",
                        "file": "app.py",
                        "dimension": "Security",
                        "non_automatable_reason": "unit test fixture issue",
                    }
                ],
                "fix_sha": None,
            },
            {
                "iteration": 2,
                "verdict": "APPROVE",
                "sha_at_evaluate": "s2",
                "issues": [
                    {
                        "id": "2.2",
                        "severity": "HIGH",
                        "title": "Second iteration issue",
                        "file": "other.py",
                        "dimension": "Quality",
                    }
                ],
                "fix_sha": None,
            },
        ],
    }
    git_shas = iter(["before_fix", "after_fix", "after_fix"])

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(returncode=0, stdout=f"{next(git_shas)}\n")
        return MagicMock(returncode=0, stdout="")

    fix_docs = []

    def mock_fix(source_file, profiles, config, **kw):
        fix_docs.append(Path(source_file).read_text(encoding="utf-8"))
        return _fix_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", lambda model, state, iteration, spec, cfg: _approve(iteration))
    monkeypatch.setattr(agents, "fix_evaluate_issues", mock_fix)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)

    assert "First iteration bug" in fix_docs[0]
    assert "Second iteration issue" not in fix_docs[0]
    assert sample_state["evaluate"]["iterations"][0]["fix_sha"] == "after_fix"
    assert sample_state["evaluate"]["iterations"][1]["fix_sha"] is None


def test_run_evaluate_cycle_skips_fix_when_block_already_fixed_on_resume(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    sample_state["evaluate"] = {
        "status": "evaluating",
        "phase_id": 2,
        "iterations": [
            {
                "iteration": 1,
                "verdict": "BLOCK",
                "sha_at_evaluate": "s1",
                "issues": [],
                "fix_sha": "fixed_sha",
            },
        ],
    }
    fix_calls: list = []
    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", lambda model, state, iteration, spec, cfg: _approve(iteration))
    monkeypatch.setattr(agents, "fix_evaluate_issues", lambda *a, **kw: fix_calls.append(True) or _fix_result())

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert not fix_calls


def test_run_evaluate_cycle_uses_first_profile_execute_model(
    tmp_workspace, sample_state, sample_profile, sample_config, monkeypatch
):
    save_state(sample_state)
    captured: list = []

    def mock_evaluate(model, state, iteration, spec, cfg):
        captured.append(model)
        return _approve(iteration)

    monkeypatch.setattr(subprocess, "run", _git_ok)
    monkeypatch.setattr(eval_mod, "extract_spec_sections", lambda p: "spec")
    monkeypatch.setattr(eval_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(agents, "evaluate", mock_evaluate)

    run_evaluate_cycle(_make_harness(sample_profile, sample_config), sample_state)
    assert captured[0] == sample_profile["execute_model"]
