import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import state as state_mod
import subprocess_runner
import verify as verify_mod
from verify import (
    _remove_from_review_report,
    _prepare_verification_cmd,
    _run_command,
    _select_test_cmd,
    _verification_cmd_kwargs,
    verify_execution,
    verify_fix,
)


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))
    monkeypatch.setattr(
        verify_mod, "REVIEW_REPORT_PATH", Path("workspace/review_report.md")
    )
    monkeypatch.setattr(
        verify_mod, "FIX_TEST_FAILURE_LOG_PATH", Path("workspace/fix_test_failure.log")
    )


def _make_harness(profile, config, phase_type="development"):
    h = MagicMock()
    h.profile = profile
    h.profile_for = MagicMock(return_value=profile)
    h.phase_type_for = MagicMock(return_value=phase_type)
    h.config = config
    return h


def _git_result(sha="abc123"):
    r = MagicMock()
    r.stdout = sha
    r.returncode = 0
    return r


def _run_result(returncode=0, stdout="", stderr=""):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _expected_pytest_cmd(cmd):
    return [
        *cmd,
        "--ignore=.pytest_cache",
        "--ignore=.tmp",
    ]


# --- _select_test_cmd ---


def test_select_test_cmd_returns_integration_cmd_for_integration_phase():
    profile = {
        "test_cmd": ["pytest"],
        "integration_test_cmd": ["pytest", "-m", "integration"],
    }
    assert _select_test_cmd(profile, "integration") == ["pytest", "-m", "integration"]


def test_select_test_cmd_returns_integration_cmd_for_e2e_phase():
    profile = {
        "test_cmd": ["pytest"],
        "integration_test_cmd": ["pytest", "-m", "integration"],
    }
    assert _select_test_cmd(profile, "e2e") == ["pytest", "-m", "integration"]


def test_select_test_cmd_returns_test_cmd_for_development_phase():
    profile = {
        "test_cmd": ["pytest"],
        "integration_test_cmd": ["pytest", "-m", "integration"],
    }
    assert _select_test_cmd(profile, "development") == ["pytest"]


def test_select_test_cmd_returns_test_cmd_for_setup_phase():
    profile = {
        "test_cmd": ["pytest"],
        "integration_test_cmd": ["pytest", "-m", "integration"],
    }
    assert _select_test_cmd(profile, "setup") == ["pytest"]


def test_select_test_cmd_falls_back_to_test_cmd_when_no_integration_cmd():
    profile = {"test_cmd": ["pytest"]}
    assert _select_test_cmd(profile, "integration") == ["pytest"]


def test_run_command_resolves_windows_shim_after_file_not_found(monkeypatch):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "npx":
            raise FileNotFoundError("missing npx")
        return _run_result(returncode=0, stdout="ok")

    monkeypatch.setattr(subprocess_runner.subprocess, "run", mock_run)
    monkeypatch.setattr(
        subprocess_runner.shutil,
        "which",
        lambda exe: "C:/node/npx.cmd" if exe == "npx.cmd" else None,
    )
    monkeypatch.setattr(subprocess_runner.os, "name", "nt")

    run_cmd, result = _run_command(["npx", "vitest", "run"], capture_output=True)

    assert run_cmd == ["C:/node/npx.cmd", "vitest", "run"]
    assert result.returncode == 0
    assert calls == [["npx", "vitest", "run"], ["C:/node/npx.cmd", "vitest", "run"]]


def test_prepare_verification_cmd_adds_pytest_cache_ignore():
    cmd = _prepare_verification_cmd(["pytest", "--ignore=harness"])

    assert cmd == _expected_pytest_cmd(["pytest", "--ignore=harness"])


def test_prepare_verification_cmd_adds_tmp_ignore_for_absolute_pytest():
    cmd = _prepare_verification_cmd(
        [
            "C:\\Users\\OEM\\AppData\\Local\\Python\\pythoncore-3.14-64\\Scripts\\pytest.EXE",
            "--ignore=harness",
        ]
    )

    assert cmd[-2:] == ["--ignore=.pytest_cache", "--ignore=.tmp"]


def test_prepare_verification_cmd_leaves_non_pytest_commands_unchanged():
    assert _prepare_verification_cmd(["npm", "test"]) == ["npm", "test"]


def test_prepare_verification_cmd_does_not_duplicate_pytest_options():
    cmd = _prepare_verification_cmd(
        [
            "pytest",
            "--ignore=.pytest_cache",
            "--ignore=.tmp",
            "--basetemp=workspace/custom-tmp",
        ]
    )

    assert cmd == [
        "pytest",
        "--ignore=.pytest_cache",
        "--ignore=.tmp",
        "--basetemp=workspace/custom-tmp",
    ]


def test_verification_cmd_kwargs_sets_temp_env_to_workspace(sample_config):
    harness = _make_harness({"test_cmd": ["pytest"]}, sample_config)

    kwargs = _verification_cmd_kwargs(harness)

    assert kwargs["env"]["TMP"].endswith(str(Path("workspace") / "verification-tmp"))
    assert kwargs["env"]["TEMP"].endswith(str(Path("workspace") / "verification-tmp"))
    assert Path("workspace/verification-tmp").exists()


# --- verify_execution ---


def test_verify_execution_case1_retry_succeeds(
    sample_profile, sample_config, monkeypatch
):
    """SHA changed (commit happened) → no retry triggered, compile passes → empty failures."""
    harness = _make_harness(sample_profile, sample_config)
    signal = {
        "tasks": [
            {"id": "1.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")  # different from pre_sha="old_sha"
        return _run_result()  # pytest passes

    monkeypatch.setattr(subprocess, "run", mock_run)
    result = verify_execution(harness, "old_sha", [], signal)
    assert result == []


def test_verify_execution_returns_commit_sha_when_head_changed(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    signal = {
        "tasks": [
            {"id": "1.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "old_sha", [{"id": "1.1"}], signal)

    assert result.commit_sha == "new_sha"


def test_verify_execution_case1_double_fail(sample_profile, sample_config, monkeypatch):
    """SHA never changes → retry also fails to commit → task returned as failed."""
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T", "task_type": "foundation"}]
    signal = {
        "tasks": [
            {"id": "1.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("same_sha")
        return _run_result(returncode=1, stdout="FAILED test_x")  # tests fail

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "same_sha", batch, signal)
    assert len(result) == 1
    assert result.commit_ok is False
    assert result[0]["status"] == "failed"
    assert "no commit" in result[0]["reason"]


def test_verify_execution_sha_unchanged_tests_pass(
    sample_profile, sample_config, monkeypatch
):
    """SHA unchanged even when tests pass → task is not accepted without a commit."""
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T", "task_type": "foundation"}]
    signal = {
        "tasks": [
            {"id": "1.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("same_sha")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "same_sha", batch, signal)
    assert len(result) == 1
    assert "no commit" in result[0]["reason"]


def test_verify_execution_sha_unchanged_returns_failure_without_retry(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T", "task_type": "foundation"}]
    signal = {
        "tasks": [
            {"id": "1.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("same_sha")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "same_sha", batch, signal)

    assert len(result) == 1
    assert result.commit_ok is False
    assert result.harness_blocker is True
    assert result.failure_kind == "no_commit"
    assert result[0]["reason"] == "agent completed task but created no commit"


def test_verify_execution_sha_unchanged_retry_no_commit_fails(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T", "task_type": "foundation"}]
    signal = {
        "tasks": [
            {"id": "1.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )

    result = verify_execution(harness, "same_sha", batch, signal)
    assert len(result) == 1
    assert "no commit" in result[0]["reason"]


def test_verify_execution_commits_setup_signal_files_when_head_unchanged(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config, phase_type="setup")
    batch = [{"id": "1.1", "title": "T", "task_type": "foundation"}]
    signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "status": "complete",
                "files_changed": ["requirements.txt"],
            }
        ]
    }
    revs = iter(["same_sha", "new_sha"])
    committed = []

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _git_result(next(revs))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        verify_mod, "safe_changed_signal_files", lambda *a, **kw: ["requirements.txt"]
    )
    monkeypatch.setattr(
        verify_mod,
        "commit_files",
        lambda files, message: committed.append((files, message)) or True,
    )
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: True
    )

    result = verify_execution(harness, "same_sha", batch, signal)
    assert result == []
    assert result.commit_sha == "new_sha"
    assert committed == [(["requirements.txt"], "feat(phase-1): T")]


def test_verify_execution_rejects_utf16_requirements_artifact(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="setup")
    (tmp_workspace / "requirements.txt").write_bytes(
        "# deps\npytest>=8\n".encode("utf-16")
    )
    batch = [{"id": "1.1", "title": "T", "tdd_mode": "exempt"}]
    signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "status": "complete",
                "files_changed": ["requirements.txt"],
            }
        ]
    }

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result("new_sha"))

    result = verify_execution(harness, "old_sha", batch, signal)

    assert len(result) == 1
    assert result.compile_ok is False
    assert "artifact quality failed" in result[0]["reason"]
    assert "UTF-16" in result[0]["reason"]


def test_verify_execution_rejects_utf8_bom_text_artifact(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="setup")
    (tmp_workspace / "deploy").mkdir()
    (tmp_workspace / "deploy" / "app.conf").write_bytes(b"\xef\xbb\xbfserver {}\n")
    batch = [{"id": "1.1", "title": "T", "tdd_mode": "exempt"}]
    signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "status": "complete",
                "files_changed": ["deploy/app.conf"],
            }
        ]
    }

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result("new_sha"))

    result = verify_execution(harness, "old_sha", batch, signal)

    assert len(result) == 1
    assert "UTF-8 BOM" in result[0]["reason"]


def test_verify_execution_rejects_oversized_changed_test_file(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    sample_config["artifact_limits"] = {"max_new_test_file_lines": 3}
    harness = _make_harness(sample_profile, sample_config)
    test_file = tmp_workspace / "tests" / "huge.test.ts"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text("1\n2\n3\n4\n", encoding="utf-8")
    batch = [{"id": "5.1", "title": "T", "tdd_mode": "tdd_slice"}]
    signal = {
        "tasks": [
            {
                "id": "5.1",
                "title": "T",
                "status": "complete",
                "files_changed": ["tests/huge.test.ts"],
            }
        ]
    }

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result("new_sha"))

    result = verify_execution(harness, "old_sha", batch, signal)

    assert len(result) == 1
    assert "limit is 3" in result[0]["reason"]


def test_verify_execution_allows_test_file_under_line_limit(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    sample_config["artifact_limits"] = {"max_new_test_file_lines": 4}
    harness = _make_harness(sample_profile, sample_config)
    test_file = tmp_workspace / "tests" / "small.test.ts"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text("1\n2\n3\n4\n", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "5.1",
                "title": "T",
                "status": "complete",
                "files_changed": ["tests/small.test.ts"],
            }
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "old_sha", [{"id": "5.1"}], signal)

    assert result == []


def test_verify_execution_rejects_fallback_when_signal_files_remain_untracked(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config, phase_type="setup")
    batch = [{"id": "1.1", "title": "T", "task_type": "foundation"}]
    signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "status": "complete",
                "files_changed": ["app/.gitkeep", "logs/.gitkeep"],
            }
        ]
    }
    revs = iter(["same_sha", "new_sha"])

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _git_result(next(revs))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        verify_mod, "safe_changed_signal_files", lambda *a, **kw: ["app/.gitkeep"]
    )
    monkeypatch.setattr(verify_mod, "commit_files", lambda files, message: True)
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: False
    )

    result = verify_execution(harness, "same_sha", batch, signal)

    assert len(result) == 1
    assert result.commit_ok is False
    assert "not all signal files" in result[0]["reason"]


def test_verify_execution_rejects_exempt_signal_files_when_fallback_commit_fails(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [
        {
            "id": "3.1",
            "title": "Config",
            "task_type": "foundation",
            "tdd_mode": "exempt",
        }
    ]
    (tmp_workspace / "client").mkdir()
    (tmp_workspace / "client" / "tsconfig.json").write_text("{}", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "3.1",
                "title": "Config",
                "status": "complete",
                "files_changed": ["client/tsconfig.json"],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(
        verify_mod,
        "safe_changed_signal_files",
        lambda *a, **kw: ["client/tsconfig.json"],
    )
    monkeypatch.setattr(verify_mod, "commit_files", lambda files, message: False)

    result = verify_execution(harness, "same_sha", batch, signal)
    assert len(result) == 1
    assert result.commit_ok is False
    assert "no commit" in result[0]["reason"]


def test_verify_execution_accepts_exempt_noop_only_when_no_signal_changes(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [
        {
            "id": "3.1",
            "title": "Config",
            "task_type": "foundation",
            "tdd_mode": "exempt",
        }
    ]
    (tmp_workspace / "client").mkdir()
    (tmp_workspace / "client" / "tsconfig.json").write_text("{}", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "3.1",
                "title": "Config",
                "status": "complete",
                "files_changed": ["client/tsconfig.json"],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: True
    )

    result = verify_execution(harness, "same_sha", batch, signal)
    assert result == []
    assert result.skipped_reason == "exempt_noop"


def test_verify_execution_accepts_already_satisfied_implementation_noop(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "3.2", "title": "Asset manifest", "tdd_mode": "implementation"}]
    (tmp_workspace / "config").mkdir()
    (tmp_workspace / "config" / "assets.json").write_text("{}", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "3.2",
                "title": "Asset manifest",
                "status": "complete",
                "tdd_skipped": "already satisfied by existing tracked files",
                "files_changed": ["config/assets.json"],
            }
        ]
    }
    test_runs = []

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: True
    )
    monkeypatch.setattr(
        verify_mod,
        "_run_command",
        lambda cmd, **kw: test_runs.append(cmd) or (cmd, _run_result()),
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert result == []
    assert result.skipped_reason == "already_satisfied_noop"
    assert result.committed_files == ["config/assets.json"]
    assert test_runs == [_expected_pytest_cmd(sample_profile["test_cmd"])]


def test_verify_execution_rejects_already_satisfied_noop_without_files(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "3.2", "title": "Asset manifest", "tdd_mode": "implementation"}]
    signal = {
        "tasks": [
            {
                "id": "3.2",
                "status": "complete",
                "tdd_skipped": "already satisfied by existing tracked files",
                "files_changed": [],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.commit_ok is False
    assert "no commit" in result[0]["reason"]


def test_verify_execution_rejects_already_satisfied_noop_without_note(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "3.2", "title": "Asset manifest", "tdd_mode": "implementation"}]
    (tmp_workspace / "config").mkdir()
    (tmp_workspace / "config" / "assets.json").write_text("{}", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "3.2",
                "status": "complete",
                "tdd_skipped": None,
                "files_changed": ["config/assets.json"],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: True
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.commit_ok is False
    assert "no commit" in result[0]["reason"]


def test_verify_execution_rejects_already_satisfied_noop_when_files_dirty(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "3.2", "title": "Asset manifest", "tdd_mode": "implementation"}]
    (tmp_workspace / "config").mkdir()
    (tmp_workspace / "config" / "assets.json").write_text("{}", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "3.2",
                "status": "complete",
                "tdd_skipped": "already satisfied by existing tracked files",
                "files_changed": ["config/assets.json"],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: False
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.commit_ok is False
    assert "no commit" in result[0]["reason"]


def test_verify_execution_rejects_already_satisfied_noop_when_tests_fail(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "3.2", "title": "Asset manifest", "tdd_mode": "implementation"}]
    (tmp_workspace / "config").mkdir()
    (tmp_workspace / "config" / "assets.json").write_text("{}", encoding="utf-8")
    signal = {
        "tasks": [
            {
                "id": "3.2",
                "status": "complete",
                "tdd_skipped": "already satisfied by existing tracked files",
                "files_changed": ["config/assets.json"],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: True
    )
    monkeypatch.setattr(
        verify_mod,
        "_run_command",
        lambda cmd, **kw: (cmd, _run_result(returncode=1, stdout="FAILED asset paths")),
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.tests_ok is False
    assert "FAILED asset paths" in result.stdout_tail


def test_verify_execution_accepts_tdd_slice_with_prior_commit(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    """tdd_slice task with signal files already tracked/clean is accepted without a new commit."""
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "6.2", "title": "PlayerService tests", "tdd_mode": "tdd_slice"}]
    (tmp_workspace / "tests").mkdir()
    (tmp_workspace / "tests" / "test_player_service.py").write_text(
        "# tests", encoding="utf-8"
    )
    signal = {
        "tasks": [
            {
                "id": "6.2",
                "title": "PlayerService tests",
                "status": "complete",
                "files_changed": ["tests/test_player_service.py"],
            }
        ]
    }
    test_runs: list = []

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: True
    )
    monkeypatch.setattr(
        verify_mod,
        "_run_command",
        lambda cmd, **kw: test_runs.append(cmd) or (cmd, _run_result()),
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert result == []
    assert result.committed_files == ["tests/test_player_service.py"]
    assert _expected_pytest_cmd(sample_profile["test_cmd"]) in test_runs


def test_verify_execution_tdd_slice_no_prior_commit_still_fails(
    sample_profile, sample_config, monkeypatch
):
    """tdd_slice task with no prior commit and files not tracked/clean still fails."""
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "6.2", "title": "PlayerService tests", "tdd_mode": "tdd_slice"}]
    signal = {
        "tasks": [
            {
                "id": "6.2",
                "title": "PlayerService tests",
                "status": "complete",
                "files_changed": ["tests/test_player_service.py"],
            }
        ]
    }

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "safe_changed_signal_files", lambda *a, **kw: [])
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod, "_signal_files_tracked_and_clean", lambda files: False
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.commit_ok is False
    assert "no commit" in result[0]["reason"]


def test_verify_execution_skips_project_tests_for_exempt_task(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config, phase_type="development")
    batch = [{"id": "3.1", "title": "Config", "tdd_mode": "exempt"}]
    signal = {"tasks": [{"id": "3.1", "status": "complete", "files_changed": []}]}
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result(returncode=1, stdout="tests should not run")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "old_sha", batch, signal)
    assert result == []
    assert result.skipped_reason == "exempt_task"
    assert all(cmd[0] == "git" for cmd in called_cmds)


def test_verify_execution_skips_project_tests_for_setup_commit(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config, phase_type="setup")
    signal = {"tasks": [{"id": "1.1", "status": "complete", "files_changed": []}]}
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result(returncode=1, stdout="tests should not run")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "old_sha", [], signal)
    assert result == []
    assert result.skipped_reason == "setup_phase"
    assert all(cmd[0] == "git" for cmd in called_cmds)


def test_verify_execution_case2_compile_fail(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    """Compile error → failed task returned."""
    harness = _make_harness(sample_profile, sample_config)
    py_file = tmp_workspace / "bad.py"
    py_file.write_text("def f(:", encoding="utf-8")

    signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "status": "complete",
                "files_changed": [str(py_file)],
            }
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")  # SHA changed
        if "py_compile" in cmd:
            return _run_result(returncode=1, stderr="SyntaxError")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    result = verify_execution(harness, "old_sha", [], signal)
    assert len(result) == 1
    assert result.compile_ok is False
    assert result[0]["status"] == "failed"
    assert "compile" in result[0]["reason"]


def test_verify_execution_returns_commit_failure_detail(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T"}]
    signal = {"tasks": [{"id": "1.1", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _run_result(returncode=1, stderr="no git")
    )

    result = verify_execution(harness, "old_sha", batch, signal)
    assert result.commit_ok is False
    assert result.failed_tasks[0]["reason"] == "git rev-parse HEAD failed"


def test_verify_execution_records_test_first_skip_reason(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T", "tdd_mode": "test_first"}]
    signal = {"tasks": [{"id": "1.1", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result("new_sha"))

    result = verify_execution(harness, "old_sha", batch, signal)
    assert result == []
    assert result.skipped_reason == "test_first"


def test_verify_execution_skips_compile_for_test_first(
    sample_profile, sample_config, monkeypatch
):
    profile = {
        **sample_profile,
        "compile_cmd": ["npx", "tsc", "--noEmit"],
        "compile_extensions": ["*.ts"],
        "test_cmd": ["npx", "vitest", "run"],
    }
    harness = _make_harness(profile, sample_config)
    batch = [{"id": "3.3", "title": "Tests", "tdd_mode": "test_first"}]
    signal = {
        "tasks": [
            {
                "id": "3.3",
                "status": "complete",
                "files_changed": ["client/tests/api.test.ts"],
            }
        ]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")
        raise AssertionError("test_first should skip compile and test commands")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_execution(harness, "old_sha", batch, signal)
    assert result == []
    assert result.skipped_reason == "test_first"


def test_verify_execution_commits_test_first_signal_files_when_head_unchanged(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "3.3", "title": "Tests", "tdd_mode": "test_first"}]
    (tmp_workspace / "client" / "tests").mkdir(parents=True)
    (tmp_workspace / "client" / "tests" / "api.test.ts").write_text(
        "import { describe } from 'vitest';\n",
        encoding="utf-8",
    )
    signal = {
        "tasks": [
            {
                "id": "3.3",
                "status": "complete",
                "files_changed": ["client/tests/api.test.ts"],
            }
        ]
    }
    revs = iter(["same_sha", "new_sha"])

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _git_result(next(revs))
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        verify_mod,
        "safe_changed_signal_files",
        lambda *a, **kw: ["client/tests/api.test.ts"],
    )
    monkeypatch.setattr(verify_mod, "commit_files", lambda files, message: True)

    result = verify_execution(harness, "same_sha", batch, signal)
    assert result == []
    assert result.skipped_reason == "test_first"
    assert result.commit_sha == "new_sha"


def test_verify_execution_fallback_commits_snapshot_delta_when_signal_files_empty(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "2.6", "title": "Client config", "tdd_mode": "implementation"}]
    signal = {"tasks": [{"id": "2.6", "status": "complete", "files_changed": []}]}
    revs = iter(["same_sha", "new_sha"])
    committed = []

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _git_result(next(revs))
        if cmd[:2] == ["git", "diff"]:
            return _run_result(stdout="src/config/clientConfig.ts\n")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        verify_mod,
        "changed_files_since_snapshot",
        lambda snapshot: ["src/config/clientConfig.ts"],
    )
    monkeypatch.setattr(
        verify_mod,
        "commit_files",
        lambda files, message: committed.append((files, message)) or True,
    )
    monkeypatch.setattr(
        verify_mod, "_run_command", lambda *a, **kw: (["pytest"], _run_result())
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert result == []
    assert result.commit_sha == "new_sha"
    assert result.committed_files == ["src/config/clientConfig.ts"]
    assert committed == [
        (["src/config/clientConfig.ts"], "feat(phase-2): Client config")
    ]


def test_verify_execution_does_not_commit_preexisting_dirty_file(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "2.6", "title": "Client config", "tdd_mode": "implementation"}]
    signal = {"tasks": [{"id": "2.6", "status": "complete", "files_changed": []}]}
    committed = []

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod,
        "commit_files",
        lambda files, message: committed.append((files, message)) or True,
    )

    result = verify_execution(
        harness, "same_sha", batch, signal, pre_snapshot={"user.txt"}
    )

    assert len(result) == 1
    assert "no commit" in result[0]["reason"]
    assert committed == []


def test_verify_execution_unit_test_commits_allowed_support_files(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "2.7", "title": "Verify client config", "tdd_mode": "unit_test"}]
    signal = {"tasks": [{"id": "2.7", "status": "complete", "files_changed": []}]}
    revs = iter(["same_sha", "new_sha"])
    committed = []

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _git_result(next(revs))
        if cmd[:2] == ["git", "diff"]:
            return _run_result(stdout="package.json\npackage-lock.json\n")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        verify_mod,
        "changed_files_since_snapshot",
        lambda snapshot: ["package.json", "package-lock.json"],
    )
    monkeypatch.setattr(
        verify_mod,
        "commit_files",
        lambda files, message: committed.append((files, message)) or True,
    )
    monkeypatch.setattr(
        verify_mod, "_run_command", lambda *a, **kw: (["pytest"], _run_result())
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert result == []
    assert result.commit_sha == "new_sha"
    assert result.committed_files == ["package.json", "package-lock.json"]
    assert committed == [
        (
            ["package.json", "package-lock.json"],
            "chore(phase-2): update test verification support",
        )
    ]


def test_verify_execution_unit_test_rejects_source_file_changes(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "2.7", "title": "Verify client config", "tdd_mode": "unit_test"}]
    signal = {"tasks": [{"id": "2.7", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(
        verify_mod,
        "changed_files_since_snapshot",
        lambda snapshot: ["src/config/clientConfig.ts"],
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert "non-support files" in result[0]["reason"]


def test_verify_execution_accepts_browser_preflight_missing_webkit_report(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [
        {
            "id": "2.9",
            "title": "Run and verify Playwright browser launch tests",
            "description": "Verify browser launch preflight failures for missing browsers.",
            "tdd_mode": "unit_test",
        }
    ]
    signal = {"tasks": [{"id": "2.9", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod,
        "_run_command",
        lambda *a, **kw: (
            ["npx", "playwright", "test"],
            _run_result(
                returncode=1,
                stdout="PREFLIGHT FAILURE: WebKit not installed",
            ),
        ),
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert result == []
    assert result.skipped_reason == "preflight_external_dependency_reported"


def test_verify_execution_does_not_accept_preflight_failure_for_non_preflight_task(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "2.9", "title": "Run E2E tests", "tdd_mode": "unit_test"}]
    signal = {"tasks": [{"id": "2.9", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod,
        "_run_command",
        lambda *a, **kw: (
            ["npx", "playwright", "test"],
            _run_result(returncode=1, stdout="PREFLIGHT FAILURE: WebKit not installed"),
        ),
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.tests_ok is False


def test_verify_execution_does_not_accept_generic_playwright_failure_as_preflight(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [
        {
            "id": "2.9",
            "title": "Run and verify Playwright browser launch tests",
            "description": "Verify browser launch preflight failures for missing browsers.",
            "tdd_mode": "unit_test",
        }
    ]
    signal = {"tasks": [{"id": "2.9", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _git_result("same_sha")
    )
    monkeypatch.setattr(verify_mod, "changed_files_since_snapshot", lambda snapshot: [])
    monkeypatch.setattr(
        verify_mod,
        "_run_command",
        lambda *a, **kw: (
            ["npx", "playwright", "test"],
            _run_result(returncode=1, stdout="ReferenceError: page is not defined"),
        ),
    )

    result = verify_execution(harness, "same_sha", batch, signal, pre_snapshot=set())

    assert len(result) == 1
    assert result.tests_ok is False


def test_cleanup_verification_artifacts_removes_coverage(tmp_workspace):
    coverage = tmp_workspace / "coverage"
    coverage.mkdir()
    (coverage / "index.html").write_text("report", encoding="utf-8")

    verify_mod._cleanup_verification_artifacts(tmp_workspace)

    assert not coverage.exists()


def test_cleanup_verification_artifacts_removes_playwright_outputs(tmp_workspace):
    for name in ("test-results", "playwright-report"):
        output = tmp_workspace / name
        output.mkdir()
        (output / "index.html").write_text("report", encoding="utf-8")

    verify_mod._cleanup_verification_artifacts(tmp_workspace)

    assert not (tmp_workspace / "test-results").exists()
    assert not (tmp_workspace / "playwright-report").exists()


def test_cleanup_verification_artifacts_restores_clean_tracked_coverage(
    tmp_workspace, monkeypatch
):
    coverage = tmp_workspace / ".coverage"
    coverage.write_text("dirty", encoding="utf-8")
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "status"]:
            return _run_result(returncode=0, stdout=" M .coverage\n")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    verify_mod._cleanup_verification_artifacts(tmp_workspace, pre_snapshot=set())

    assert ["git", "restore", "--", ".coverage"] in calls


def test_cleanup_verification_artifacts_preserves_preexisting_dirty_coverage(
    tmp_workspace, monkeypatch
):
    coverage = tmp_workspace / ".coverage"
    coverage.write_text("user", encoding="utf-8")
    run = MagicMock()
    monkeypatch.setattr(subprocess, "run", run)

    verify_mod._cleanup_verification_artifacts(
        tmp_workspace, pre_snapshot={".coverage"}
    )

    run.assert_not_called()
    assert coverage.exists()


def test_cleanup_verification_artifacts_removes_untracked_coverage_file(
    tmp_workspace, monkeypatch
):
    coverage = tmp_workspace / ".coverage"
    coverage.write_text("generated", encoding="utf-8")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _run_result(returncode=0, stdout="?? .coverage\n"),
    )

    verify_mod._cleanup_verification_artifacts(tmp_workspace, pre_snapshot=set())

    assert not coverage.exists()


def test_verify_execution_records_unit_test_no_commit_skip_reason(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    batch = [{"id": "1.1", "title": "T", "tdd_mode": "unit_test"}]
    signal = {"tasks": [{"id": "1.1", "status": "complete", "files_changed": []}]}

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _git_result("same_sha"))

    result = verify_execution(harness, "same_sha", batch, signal)
    assert result == []
    assert result.skipped_reason == "unit_test_no_commit"


def test_verify_execution_returns_compile_failure_detail(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config)
    py_file = tmp_workspace / "bad_detail.py"
    py_file.write_text("def f(:", encoding="utf-8")
    signal = {
        "tasks": [{"id": "1.1", "status": "complete", "files_changed": [str(py_file)]}]
    }

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")
        if "py_compile" in cmd:
            return _run_result(returncode=1, stderr="SyntaxError detail")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    result = verify_execution(harness, "old_sha", [], signal)
    assert result.compile_ok is False
    assert "SyntaxError detail" in result.failed_tasks[0]["reason"]


def test_verify_execution_returns_test_failure_detail(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    signal = {"tasks": [{"id": "1.1", "status": "complete", "files_changed": []}]}

    def mock_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result(returncode=1, stdout="unit failure", stderr="stderr tail")

    monkeypatch.setattr(subprocess, "run", mock_run)
    result = verify_execution(harness, "old_sha", [], signal)
    assert result.tests_ok is False
    assert result.commands == [_expected_pytest_cmd(sample_profile["test_cmd"])]
    assert "unit failure" in result.stdout_tail
    assert "stderr tail" in result.stderr_tail


def test_verify_fix_returns_test_failure_detail(
    sample_profile, sample_config, monkeypatch, sample_state
):
    harness = _make_harness(sample_profile, sample_config)
    fix = {"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _git_result("new_sha")
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return _run_result(stdout="app.py\n")
        return _run_result(returncode=1, stdout="tests failed")

    monkeypatch.setattr(subprocess, "run", mock_run)
    result = verify_fix(harness, sample_state, [fix], 1, pre_sha="old_sha")
    assert result.tests_ok is False
    assert result.open_fixes[0]["id"] == fix["id"]
    assert "fix tests failed" in result.open_fixes[0]["reason"]
    assert result.commands == [_expected_pytest_cmd(sample_profile["test_cmd"])]
    assert "tests failed" in result.stdout_tail


def test_verify_execution_uses_integration_test_cmd(
    sample_profile, sample_config, monkeypatch
):
    """Integration phase → verify_execution calls integration_test_cmd, not test_cmd."""
    harness = _make_harness(sample_profile, sample_config, phase_type="integration")
    signal = {
        "tasks": [
            {"id": "2.1", "title": "T", "status": "complete", "files_changed": []}
        ]
    }
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    verify_execution(harness, "old_sha", [], signal)
    non_git = [c for c in called_cmds if c[0] != "git"]
    assert any(
        c == _expected_pytest_cmd(sample_profile["integration_test_cmd"])
        for c in non_git
    )


def test_verify_execution_runs_all_game_e2e_test_commands(
    sample_profile, sample_config, monkeypatch
):
    ts_profile = {
        **sample_profile,
        "name": "typescript",
        "integration_test_cmd": ["npm", "run", "test:e2e"],
    }
    harness = _make_harness(sample_profile, sample_config, phase_type="e2e")
    harness.verification_profiles_for = MagicMock(
        return_value=[sample_profile, ts_profile]
    )
    signal = {"tasks": [{"id": "8.1", "status": "complete", "files_changed": []}]}
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    verify_execution(harness, "old_sha", [{"id": "8.1"}], signal)

    non_git = [c for c in called_cmds if c[0] != "git"]
    assert _expected_pytest_cmd(sample_profile["integration_test_cmd"]) in non_git
    assert ts_profile["integration_test_cmd"] in non_git


def test_verify_execution_uses_matching_compile_profile_per_changed_file(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    ts_profile = {
        **sample_profile,
        "name": "typescript",
        "compile_cmd": ["npm", "run", "typecheck"],
        "compile_extensions": ["*.ts", "*.tsx"],
    }
    harness = _make_harness(sample_profile, sample_config)
    harness.verification_profiles_for = MagicMock(
        return_value=[sample_profile, ts_profile]
    )
    ts_file = tmp_workspace / "src" / "main.ts"
    ts_file.parent.mkdir()
    ts_file.write_text("export const ok = true;\n", encoding="utf-8")
    signal = {
        "tasks": [{"id": "5.1", "status": "complete", "files_changed": [str(ts_file)]}]
    }
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        if cmd[0] == "git":
            return _git_result("new_sha")
        return _run_result()

    monkeypatch.setattr(subprocess, "run", mock_run)
    verify_execution(harness, "old_sha", [{"id": "5.1"}], signal)

    assert ["npm", "run", "typecheck"] in called_cmds


# --- verify_fix ---


def _sample_state_with_issue():
    return {
        "spec_file": "spec.md",
        "language": "python",
        "phases": [
            {
                "id": 1,
                "title": "Phase One",
                "status": "building",
                "tasks": [],
                "review": {
                    "status": "fixing",
                    "verdict": "BLOCK",
                    "sha_at_review": None,
                    "issues": [
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
                            "severity": "MEDIUM",
                            "status": "open",
                            "attempts": 0,
                            "files_changed": [],
                            "fixed_sha": None,
                            "last_error": [],
                        },
                    ],
                },
            }
        ],
    }


def test_verify_fix_all_passed(sample_profile, sample_config, monkeypatch):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)

    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _run_result(stdout="abc123")
    )

    open_fixes = verify_fix(harness, state, fixes, 1)
    assert open_fixes == []
    assert state["phases"][0]["review"]["issues"][0]["status"] == "fixed"


def test_verify_fix_remaining_open(sample_profile, sample_config, monkeypatch):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)

    fixes = [{"id": "1.1", "status": "open", "files_changed": []}]

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _run_result(returncode=0, stdout="abc")
    )

    open_fixes = verify_fix(harness, state, fixes, 1)
    assert len(open_fixes) == 1
    assert open_fixes[0]["id"] == "1.1"


def test_verify_fix_deferred_medium_low(sample_profile, sample_config, monkeypatch):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)

    fixes = [{"id": "1.2", "status": "deferred", "files_changed": []}]

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _run_result(returncode=0, stdout="abc")
    )

    open_fixes = verify_fix(harness, state, fixes, 1)
    assert open_fixes == []
    assert state["phases"][0]["review"]["issues"][1]["status"] == "deferred"


def test_verify_fix_uses_integration_test_cmd(
    sample_profile, sample_config, monkeypatch
):
    """Integration phase → verify_fix calls integration_test_cmd."""
    harness = _make_harness(sample_profile, sample_config, phase_type="integration")
    state = _sample_state_with_issue()
    state_mod.save_state(state)

    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        return _run_result(returncode=0, stdout="abc123")

    monkeypatch.setattr(subprocess, "run", mock_run)
    verify_fix(harness, state, fixes, 1)
    non_git = [c for c in called_cmds if c[0] != "git"]
    assert any(
        c == _expected_pytest_cmd(sample_profile["integration_test_cmd"])
        for c in non_git
    )


def test_verify_fix_runs_all_game_e2e_test_commands(
    sample_profile, sample_config, monkeypatch
):
    ts_profile = {
        **sample_profile,
        "name": "typescript",
        "integration_test_cmd": ["npm", "run", "test:e2e"],
    }
    harness = _make_harness(sample_profile, sample_config, phase_type="e2e")
    harness.verification_profiles_for = MagicMock(
        return_value=[sample_profile, ts_profile]
    )
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(list(cmd))
        return _run_result(returncode=0, stdout="abc123")

    monkeypatch.setattr(subprocess, "run", mock_run)
    verify_fix(harness, state, fixes, 1)

    non_git = [c for c in called_cmds if c[0] != "git"]
    assert _expected_pytest_cmd(sample_profile["integration_test_cmd"]) in non_git
    assert ts_profile["integration_test_cmd"] in non_git


def test_verify_fix_skips_pytest_no_tests_selected_when_another_profile_passes(
    sample_profile, sample_config, monkeypatch
):
    ts_profile = {
        **sample_profile,
        "name": "typescript",
        "integration_test_cmd": ["npm", "run", "test:e2e"],
    }
    harness = _make_harness(sample_profile, sample_config, phase_type="e2e")
    harness.verification_profiles_for = MagicMock(
        return_value=[sample_profile, ts_profile]
    )
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        if cmd[:2] == ["git", "diff"]:
            return _run_result(returncode=0, stdout="f.py\n")
        if cmd and cmd[0] == "pytest":
            return _run_result(
                returncode=5,
                stdout="collected 415 items / 415 deselected / 0 selected",
            )
        return _run_result(returncode=0, stdout="ok")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_fix(harness, state, fixes, 1, pre_sha="oldsha")

    assert result == []
    assert result.harness_blocker is False
    assert state["phases"][0]["review"]["issues"][0]["status"] == "fixed"


def test_verify_fix_all_no_tests_selected_is_harness_blocker(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config, phase_type="integration")
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        return _run_result(
            returncode=5,
            stdout="collected 415 items / 415 deselected / 0 selected",
        )

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = verify_fix(harness, state, fixes, 1, pre_sha="oldsha")

    assert result.harness_blocker is True
    assert result.failure_kind == "no_applicable_verification"
    assert "no applicable verification command" in result.blocker_reason
    assert result.open_fixes[0]["id"] == "1.1"


def test_verify_fix_rejects_fix_when_claimed_files_not_in_diff(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        if cmd[:2] == ["git", "diff"]:
            return _run_result(returncode=0, stdout="other.py\n")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    open_fixes = verify_fix(harness, state, fixes, 1, pre_sha="oldsha")
    assert len(open_fixes) == 1
    assert open_fixes.harness_blocker is True
    assert open_fixes.failure_kind == "fixed_files_not_in_diff"
    assert "not found in git diff" in open_fixes[0]["reason"]
    assert state["phases"][0]["review"]["issues"][0]["status"] == "open"


def test_verify_fix_accepts_fix_when_claimed_files_overlap_diff(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        if cmd[:2] == ["git", "diff"]:
            return _run_result(returncode=0, stdout="f.py\n")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    open_fixes = verify_fix(harness, state, fixes, 1, pre_sha="oldsha")
    assert open_fixes == []
    assert state["phases"][0]["review"]["issues"][0]["fixed_sha"] == "newsha"


def test_verify_fix_skips_intersection_check_when_no_pre_sha(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _run_result(returncode=0, stdout="sha")
    )

    assert verify_fix(harness, state, fixes, 1, pre_sha="") == []


def test_verify_fix_skips_intersection_check_when_fix_files_empty(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": []}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        if cmd[:2] == ["git", "diff"]:
            return _run_result(returncode=0, stdout="other.py\n")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert verify_fix(harness, state, fixes, 1, pre_sha="oldsha") == []


def test_verify_fix_fallback_commits_dirty_fix_files(
    sample_profile, sample_config, monkeypatch
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["requirements.txt"]}]
    revs = iter(["oldsha", "newsha"])
    committed = []

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout=next(revs))
        if cmd[:2] == ["git", "diff"]:
            return _run_result(returncode=0, stdout="requirements.txt\n")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        verify_mod,
        "safe_changed_signal_files",
        lambda *a, **kw: ["requirements.txt"],
    )
    monkeypatch.setattr(
        verify_mod,
        "commit_files",
        lambda files, message: committed.append((files, message)) or True,
    )

    open_fixes = verify_fix(
        harness, state, fixes, 1, pre_sha="oldsha", pre_snapshot=set()
    )

    assert open_fixes == []
    assert committed == [(["requirements.txt"], "fix(phase-1): resolve review issues")]
    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "fixed"
    assert issue["fixed_sha"] == "newsha"


def test_verify_fix_writes_failure_log_when_tests_fail(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["f.py"]}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        return _run_result(returncode=1, stdout="FAILED test_x", stderr="boom")

    monkeypatch.setattr(subprocess, "run", mock_run)

    open_fixes = verify_fix(harness, state, fixes, 1, pre_sha="oldsha")

    assert len(open_fixes) == 1
    assert "fix tests failed" in open_fixes[0]["reason"]
    log_text = (tmp_workspace / "workspace" / "fix_test_failure.log").read_text(
        encoding="utf-8"
    )
    assert "FAILED test_x" in log_text
    assert "boom" in log_text
    archived = list((tmp_workspace / "workspace" / "fix-test-failures").glob("*.log"))
    assert len(archived) == 1
    archived_text = archived[0].read_text(encoding="utf-8")
    assert "failure_kind: test_failed" in archived_text
    assert "FAILED test_x" in archived_text


def test_verify_fix_rejects_fixed_artifact_quality_failure(
    sample_profile, sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_profile, sample_config)
    state = _sample_state_with_issue()
    state_mod.save_state(state)
    (tmp_workspace / "requirements.txt").write_bytes(
        "# deps\npytest>=8\n".encode("utf-16")
    )
    fixes = [{"id": "1.1", "status": "fixed", "files_changed": ["requirements.txt"]}]

    def mock_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return _run_result(returncode=0, stdout="newsha")
        if cmd[:2] == ["git", "diff"]:
            return _run_result(returncode=0, stdout="requirements.txt\n")
        return _run_result(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    open_fixes = verify_fix(harness, state, fixes, 1, pre_sha="oldsha")

    assert len(open_fixes) == 1
    assert "artifact quality failed" in open_fixes[0]["reason"]
    assert state["phases"][0]["review"]["issues"][0]["status"] == "open"


# --- _remove_from_review_report ---


def test_remove_from_review_report(tmp_workspace):
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text(
        "### 1.1 Missing validation\nDetails here.\n\n### 1.2 Another issue\nOther details.",
        encoding="utf-8",
    )
    _remove_from_review_report("1.1")
    content = report.read_text(encoding="utf-8")
    assert "1.1" not in content
    assert "1.2" in content


def test_remove_from_review_report_does_not_remove_prefix_issue_id(tmp_workspace):
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text(
        "### 1.1 Missing validation\nDetails.\n\n### 1.10 Another issue\nOther.",
        encoding="utf-8",
    )
    _remove_from_review_report("1.1")
    content = report.read_text(encoding="utf-8")
    assert "1.1 Missing validation" not in content
    assert "1.10 Another issue" in content


def test_remove_from_review_report_removes_exact_issue_only(tmp_workspace):
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text(
        "### 1.2 Exact\nDetails.\n\n### 1.3 Next\nOther.", encoding="utf-8"
    )
    _remove_from_review_report("1.2")
    content = report.read_text(encoding="utf-8")
    assert "1.2 Exact" not in content
    assert "1.3 Next" in content
