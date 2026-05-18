"""Regression tests for cleanup.py utility functions."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import cleanup as cleanup_mod
import state as state_mod
from cleanup import (
    _all_deferred_issues,
    _collect_test_cmds,
    _finish,
    _fixable_deferred,
    _parse_phase_id,
    _purge_excluded_from_tech_debt,
    _rewrite_tech_debt_from_state,
    run_cleanup,
)
from state import save_state


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))
    monkeypatch.setattr(
        cleanup_mod, "TECH_DEBT_PATH", tmp_workspace / "workspace" / "tech_debt.jsonl"
    )


# ── _parse_phase_id ──────────────────────────────────────────────────────────


def test_parse_phase_id_extracts_integer():
    assert _parse_phase_id("3.7") == 3


def test_parse_phase_id_raises_on_non_numeric_prefix():
    with pytest.raises(ValueError, match="Cannot parse phase id"):
        _parse_phase_id("bad")


def test_parse_phase_id_raises_on_no_dot():
    with pytest.raises(ValueError, match="Cannot parse phase id"):
        _parse_phase_id("nodot")


# ── _all_deferred_issues ─────────────────────────────────────────────────────


def test_all_deferred_issues_collects_across_phases():
    state = {
        "phases": [
            {
                "id": 1,
                "review": {
                    "issues": [
                        {"id": "1.1", "status": "deferred"},
                        {"id": "1.2", "status": "fixed"},
                    ]
                },
            },
            {
                "id": 2,
                "review": {
                    "issues": [
                        {"id": "2.1", "status": "deferred"},
                    ]
                },
            },
        ]
    }
    result = _all_deferred_issues(state)
    ids = {i["id"] for i in result}
    assert ids == {"1.1", "2.1"}


def test_all_deferred_issues_returns_empty_when_none():
    state = {
        "phases": [{"id": 1, "review": {"issues": [{"id": "1.1", "status": "fixed"}]}}]
    }
    assert _all_deferred_issues(state) == []


def test_all_deferred_issues_handles_empty_phases():
    assert _all_deferred_issues({"phases": []}) == []


# ── _fixable_deferred ────────────────────────────────────────────────────────


def test_fixable_deferred_excludes_paths_in_exclude_list():
    state = {
        "phases": [
            {
                "id": 1,
                "review": {
                    "issues": [
                        {"id": "1.1", "status": "deferred", "file": "harness/main.py"},
                        {"id": "1.2", "status": "deferred", "file": "src/app.py"},
                    ]
                },
            }
        ]
    }
    result = _fixable_deferred(state, exclude_paths=["harness"])
    ids = [i["id"] for i in result]
    assert "1.2" in ids
    assert "1.1" not in ids


def test_fixable_deferred_returns_all_when_no_exclusions():
    state = {
        "phases": [
            {
                "id": 1,
                "review": {
                    "issues": [
                        {"id": "1.1", "status": "deferred", "file": "src/a.py"},
                        {"id": "1.2", "status": "deferred", "file": "src/b.py"},
                    ]
                },
            }
        ]
    }
    result = _fixable_deferred(state, exclude_paths=[])
    assert len(result) == 2


def test_fixable_deferred_respects_trailing_slash_exclude():
    state = {
        "phases": [
            {
                "id": 1,
                "review": {
                    "issues": [
                        {"id": "1.1", "status": "deferred", "file": "dist/app.js"},
                        {"id": "1.2", "status": "deferred", "file": "src/app.py"},
                    ]
                },
            }
        ]
    }
    result = _fixable_deferred(state, exclude_paths=["dist/"])
    assert [i["id"] for i in result] == ["1.2"]


# ── _purge_excluded_from_tech_debt ───────────────────────────────────────────


def test_purge_excluded_removes_matching_lines(tmp_workspace):
    debt = tmp_workspace / "workspace" / "tech_debt.jsonl"
    debt.write_text(
        json.dumps({"id": "1.1", "file": "harness/main.py"})
        + "\n"
        + json.dumps({"id": "2.1", "file": "src/app.py"})
        + "\n",
        encoding="utf-8",
    )
    _purge_excluded_from_tech_debt(["harness"])
    remaining = [
        json.loads(line)
        for line in debt.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(remaining) == 1
    assert remaining[0]["id"] == "2.1"


def test_purge_excluded_noop_when_file_missing():
    _purge_excluded_from_tech_debt(["harness"])


def test_purge_excluded_noop_when_no_exclude_paths(tmp_workspace):
    debt = tmp_workspace / "workspace" / "tech_debt.jsonl"
    debt.write_text(
        json.dumps({"id": "1.1", "file": "harness/main.py"}) + "\n",
        encoding="utf-8",
    )
    _purge_excluded_from_tech_debt([])
    remaining = [
        json.loads(line)
        for line in debt.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(remaining) == 1


def test_cleanup_rewrites_tech_debt_to_skip_fixed_issues(tmp_workspace):
    state = _cleanup_state_with_deferred_issue()
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"

    _rewrite_tech_debt_from_state(state, [])

    assert cleanup_mod.TECH_DEBT_PATH.read_text(encoding="utf-8") == ""


def test_cleanup_keeps_only_deferred_issues(tmp_workspace):
    state = _cleanup_state_with_deferred_issue()
    state["phases"][0]["review"]["issues"].append(
        {
            "id": "1.2",
            "severity": "LOW",
            "file": "src/other.py",
            "title": "Fixed",
            "status": "fixed",
        }
    )

    _rewrite_tech_debt_from_state(state, [])
    lines = cleanup_mod.TECH_DEBT_PATH.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "1.1"


def test_cleanup_preserves_malformed_manual_lines(tmp_workspace):
    cleanup_mod.TECH_DEBT_PATH.write_text("not-json\n", encoding="utf-8")
    state = _cleanup_state_with_deferred_issue()

    _rewrite_tech_debt_from_state(state, [])
    text = cleanup_mod.TECH_DEBT_PATH.read_text(encoding="utf-8")

    assert "not-json" in text
    assert "1.1" in text


# ── _collect_test_cmds ───────────────────────────────────────────────────────


def test_collect_test_cmds_deduplicates_same_command(sample_config, sample_profile):
    state = {
        "phases": [
            {"id": 1, "phase_type": "development"},
            {"id": 2, "phase_type": "development"},
        ]
    }
    harness = MagicMock()
    harness.profile_for = MagicMock(return_value=sample_profile)
    harness.phase_type_for = MagicMock(return_value="development")

    cmds = _collect_test_cmds(harness, state)
    assert len(cmds) == 1
    assert cmds[0] == sample_profile["test_cmd"]


def test_collect_test_cmds_includes_distinct_commands(sample_config, sample_profile):
    ts_profile = dict(
        sample_profile, name="typescript", test_cmd=["npx", "vitest", "run"]
    )
    state = {
        "phases": [
            {"id": 1, "phase_type": "development"},
            {"id": 2, "phase_type": "development"},
        ]
    }
    harness = MagicMock()
    harness.profile_for = MagicMock(
        side_effect=lambda pid: sample_profile if pid == 1 else ts_profile
    )
    harness.phase_type_for = MagicMock(return_value="development")

    cmds = _collect_test_cmds(harness, state)
    assert len(cmds) == 2


def test_collect_test_cmds_uses_verification_profiles_for_game_e2e(
    sample_config, sample_profile
):
    ts_profile = dict(
        sample_profile,
        name="typescript",
        integration_test_cmd=["npm", "run", "test:e2e"],
    )
    state = {"phases": [{"id": 8, "phase_type": "e2e"}]}
    harness = MagicMock()
    harness.phase_type_for = MagicMock(return_value="e2e")
    harness.verification_profiles_for = MagicMock(
        return_value=[sample_profile, ts_profile]
    )

    cmds = _collect_test_cmds(harness, state)

    assert sample_profile["integration_test_cmd"] in cmds
    assert ts_profile["integration_test_cmd"] in cmds


def test_finish_returns_empty_when_all_commands_pass(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr=""),
    )

    assert _finish([["pytest"]]) == []


def test_finish_returns_failures_for_nonzero_command(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 2, stdout="FAILED stdout", stderr="FAILED stderr"
        ),
    )

    failures = _finish([["pytest"]])

    assert failures == [
        {
            "cmd": ["pytest"],
            "returncode": 2,
            "stdout_tail": "FAILED stdout",
            "stderr_tail": "FAILED stderr",
        }
    ]


def _cleanup_state_with_deferred_issue():
    return {
        "phases": [
            {
                "id": 1,
                "phase_type": "development",
                "review": {
                    "issues": [
                        {
                            "id": "1.1",
                            "severity": "LOW",
                            "file": "src/app.py",
                            "title": "Issue",
                            "status": "deferred",
                            "attempts": 0,
                            "files_changed": [],
                            "fixed_sha": None,
                            "last_error": [],
                        }
                    ]
                },
            }
        ]
    }


def _cleanup_harness(sample_profile, sample_config):
    harness = MagicMock()
    harness.config = sample_config
    harness.profile_for = MagicMock(return_value=sample_profile)
    harness.phase_type_for = MagicMock(return_value="development")
    return harness


def _cleanup_verify_run(test_returncode=0, test_stdout="", diff_stdout="src/app.py\n"):
    shas = iter(["oldsha\n", "newsha\n"])

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=next(shas, "newsha\n"), stderr=""
            )
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=diff_stdout, stderr="")
        return subprocess.CompletedProcess(
            cmd, test_returncode, stdout=test_stdout, stderr=""
        )

    return mock_run


def test_cleanup_accepts_fixed_issue_only_when_tests_pass(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)

    monkeypatch.setattr(subprocess, "run", _cleanup_verify_run())

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "fixed"
    assert issue["fixed_sha"] == "newsha"


def test_cleanup_record_only_skips_fix_issues_when_config_false(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    sample_config["cleanup_fix_deferred_issues"] = False
    fix_mock = MagicMock()
    monkeypatch.setattr(cleanup_mod.agents, "fix_issues", fix_mock)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: [])

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    fix_mock.assert_not_called()
    assert "1.1" in cleanup_mod.TECH_DEBT_PATH.read_text(encoding="utf-8")


def test_cleanup_record_only_still_runs_final_verification(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    sample_config["cleanup_fix_deferred_issues"] = False
    finish_mock = MagicMock(return_value=[])
    monkeypatch.setattr(cleanup_mod, "_finish", finish_mock)

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    finish_mock.assert_called_once()


def test_cleanup_passes_phase_spec_context(sample_profile, sample_config, monkeypatch):
    state = _cleanup_state_with_deferred_issue()
    state["spec_file"] = "spec.md"
    save_state(state)
    captured = {}
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)

    def mock_fix(*args, **kwargs):
        captured["spec_context"] = kwargs.get("spec_context")
        return {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(cleanup_mod.agents, "fix_issues", mock_fix)
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(subprocess, "run", _cleanup_verify_run())

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    assert "Spec manifest" in captured["spec_context"]


def test_cleanup_rejects_fixed_issue_when_sha_unchanged(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout="same-sha\n", stderr=""
        ),
    )

    with pytest.raises(SystemExit):
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "halted"
    assert "no commit" in issue["last_error"][0]


def test_cleanup_rejects_fixed_issue_when_claimed_files_not_in_diff(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        _cleanup_verify_run(diff_stdout="other.py\n"),
    )

    with pytest.raises(SystemExit):
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "halted"
    assert "not found in git diff" in issue["last_error"][0]


def test_run_cleanup_halts_when_final_tests_fail_with_no_deferred_issues(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"
    save_state(state)
    monkeypatch.setattr(
        cleanup_mod,
        "_finish",
        lambda *a, **kw: [
            {
                "cmd": ["pytest"],
                "returncode": 1,
                "stdout_tail": "FAILED",
                "stderr_tail": "",
            }
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    assert exc.value.code == 1
    assert state["cleanup"]["status"] == "halted"
    assert state["cleanup"]["last_error"][0]["cmd"] == ["pytest"]


def test_run_cleanup_halts_when_final_tests_fail_after_deferred_fix(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)

    monkeypatch.setattr(subprocess, "run", _cleanup_verify_run())
    monkeypatch.setattr(
        cleanup_mod,
        "_finish",
        lambda *a, **kw: [
            {
                "cmd": ["pytest"],
                "returncode": 1,
                "stdout_tail": "FAILED",
                "stderr_tail": "",
            }
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    assert exc.value.code == 1
    assert state["phases"][0]["review"]["issues"][0]["status"] == "fixed"
    assert state["cleanup"]["status"] == "halted"


def test_run_cleanup_records_cleanup_complete_when_final_tests_pass(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: [])

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    assert state["cleanup"] == {"status": "complete", "last_error": []}


def test_cleanup_keeps_issue_deferred_when_tests_fail(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)

    monkeypatch.setattr(
        subprocess,
        "run",
        _cleanup_verify_run(test_returncode=1, test_stdout="FAILED"),
    )

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "deferred"
    assert issue["attempts"] == 1
    debt = cleanup_mod.TECH_DEBT_PATH.read_text(encoding="utf-8")
    assert "1.1" in debt


def test_cleanup_records_last_error_when_verification_fails(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": ["src/app.py"]}
                ]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(cleanup_mod, "log_usage", lambda **kw: None)

    monkeypatch.setattr(
        subprocess,
        "run",
        _cleanup_verify_run(test_returncode=1, test_stdout="FAILED test"),
    )

    run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    last_error = state["phases"][0]["review"]["issues"][0]["last_error"][0]
    assert "fix tests failed" in last_error
    assert "workspace" in last_error
    log_text = Path("workspace/fix_test_failure.log").read_text(encoding="utf-8")
    assert "FAILED test" in log_text


def test_cleanup_subprocess_error_records_all_phase_issues_without_status_change(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    state["phases"][0]["review"]["issues"].append(
        {
            "id": "1.2",
            "severity": "MEDIUM",
            "file": "src/other.py",
            "title": "Other",
            "status": "deferred",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
    )
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        MagicMock(side_effect=cleanup_mod.agents.SubprocessError("bad json")),
    )
    monkeypatch.setattr(subprocess, "run", _cleanup_verify_run())

    with pytest.raises(SystemExit):
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    issues = state["phases"][0]["review"]["issues"]
    assert [issue["status"] for issue in issues] == ["deferred", "deferred"]
    assert [issue["last_error"] for issue in issues] == [["bad json"], ["bad json"]]
    assert state["cleanup"] == {"status": "error", "last_error": ["bad json"]}


def test_cleanup_error_status_is_reported_and_retryable(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        MagicMock(side_effect=cleanup_mod.agents.SubprocessError("bad json")),
    )
    monkeypatch.setattr(subprocess, "run", _cleanup_verify_run())

    with pytest.raises(SystemExit):
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    assert state["cleanup"]["status"] == "error"
    assert [i["id"] for i in _fixable_deferred(state, [])] == ["1.1"]


def test_cleanup_external_dependency_does_not_increment_attempts(
    sample_profile, sample_config, monkeypatch
):
    state = _cleanup_state_with_deferred_issue()
    save_state(state)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *a, **kw: None)
    monkeypatch.setattr(
        cleanup_mod.agents,
        "fix_issues",
        MagicMock(side_effect=cleanup_mod.agents.ExternalDependencyError("429")),
    )
    monkeypatch.setattr(subprocess, "run", _cleanup_verify_run())

    with pytest.raises(SystemExit):
        run_cleanup(_cleanup_harness(sample_profile, sample_config), state)

    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "deferred"
    assert issue["attempts"] == 0
    assert state["cleanup"]["status"] == "blocked_external_dependency"
