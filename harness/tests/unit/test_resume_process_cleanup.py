import json
from pathlib import Path

import resume_process_cleanup
from subprocess_runner import ProcessCleanupResult


def _events():
    path = Path("workspace/events.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_resume_cleanup_kills_stale_claude_cli_processes(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: [50]
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [
            {
                "pid": 111,
                "name": "claude",
                "path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2/claude.exe",
                "parent_pid": 1,
            }
        ],
    )
    calls = []

    def cleanup(pid, include_root=False):
        calls.append((pid, include_root))
        return ProcessCleanupResult(True, True, pid, [pid])

    monkeypatch.setattr(resume_process_cleanup, "cleanup_process_tree", cleanup)

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert calls == [(111, True)]
    assert result["candidate_pids"] == [111]
    assert result["killed_pids"] == [111]
    assert result["errors"] == []


def test_resume_cleanup_protects_current_session_ancestor_claude(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: [111, 50]
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [
            {
                "pid": 111,
                "name": "claude",
                "path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2/claude.exe",
                "parent_pid": 50,
            }
        ],
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "cleanup_process_tree",
        lambda pid, include_root=False: (_ for _ in ()).throw(
            AssertionError("protected process must not be killed")
        ),
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["protected_pids"] == [50, 111]
    assert result["killed_pids"] == []
    assert result["skipped_pids"] == [111]
    assert any(
        event.get("event") == "resume_claude_cleanup_skip"
        and event.get("reason") == "protected_current_session"
        for event in _events()
    )


def test_resume_cleanup_skips_claude_desktop(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: [50]
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [
            {
                "pid": 222,
                "name": "claude",
                "path": "C:/Program Files/WindowsApps/Claude_1.0.0.0_x64__id/app/Claude.exe",
                "parent_pid": 1,
            }
        ],
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "cleanup_process_tree",
        lambda pid, include_root=False: (_ for _ in ()).throw(
            AssertionError("Claude Desktop must not be killed")
        ),
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["candidate_pids"] == []
    assert result["killed_pids"] == []
    assert result["skipped_pids"] == [222]


def test_resume_cleanup_skips_unknown_path_when_parent_chain_incomplete(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: []
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [{"pid": 333, "name": "claude", "path": "", "parent_pid": None}],
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "cleanup_process_tree",
        lambda pid, include_root=False: (_ for _ in ()).throw(
            AssertionError("unknown Claude process must not be killed")
        ),
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["protection_incomplete"] is True
    assert result["candidate_pids"] == []
    assert result["skipped_pids"] == [333]


def test_resume_cleanup_skips_cli_candidate_when_parent_chain_incomplete(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: []
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [
            {
                "pid": 444,
                "name": "claude",
                "path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2/claude.exe",
                "parent_pid": None,
            }
        ],
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "cleanup_process_tree",
        lambda pid, include_root=False: (_ for _ in ()).throw(
            AssertionError("CLI candidate must not be killed without protection data")
        ),
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["protection_incomplete"] is True
    assert result["candidate_pids"] == [444]
    assert result["killed_pids"] == []
    assert result["skipped_pids"] == [444]
    assert result["unsafe_to_resume"] is True
    assert any(
        event.get("event") == "resume_claude_cleanup_skip"
        and event.get("reason") == "protection_incomplete"
        for event in _events()
    )


def test_resume_cleanup_records_failed_kill_without_crashing(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: [50]
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [
            {
                "pid": 444,
                "name": "claude",
                "path": "C:/Users/OEM/.local/bin/claude.exe",
                "parent_pid": 1,
            }
        ],
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "cleanup_process_tree",
        lambda pid, include_root=False: ProcessCleanupResult(
            True, False, pid, [], "Access denied"
        ),
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["candidate_pids"] == [444]
    assert result["killed_pids"] == []
    assert result["errors"] == [{"pid": 444, "error": "Access denied"}]
    assert result["unsafe_to_resume"] is True


def test_resume_cleanup_safe_when_no_cli_candidates(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: []
    )
    monkeypatch.setattr(
        resume_process_cleanup, "list_named_processes", lambda names: []
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["candidate_pids"] == []
    assert result["unsafe_to_resume"] is False


def test_resume_cleanup_safe_after_successful_kill(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        resume_process_cleanup, "current_process_ancestor_pids", lambda: [50]
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "list_named_processes",
        lambda names: [
            {
                "pid": 555,
                "name": "claude",
                "path": "C:/Users/OEM/AppData/Roaming/Claude/claude-code/2/claude.exe",
                "parent_pid": 1,
            }
        ],
    )
    monkeypatch.setattr(
        resume_process_cleanup,
        "cleanup_process_tree",
        lambda pid, include_root=False: ProcessCleanupResult(True, True, pid, [pid]),
    )

    result = resume_process_cleanup.cleanup_stale_claude_processes()

    assert result["candidate_pids"] == [555]
    assert result["killed_pids"] == [555]
    assert result["unsafe_to_resume"] is False


# --- cleanup_resume_temp_dirs tests ---


def test_cleanup_temp_dirs_removes_pytest_dirs(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    workspace = tmp_workspace / "workspace"
    (workspace / "pytest-abc123").mkdir()
    (workspace / "pytest-xyz").mkdir()

    result = resume_process_cleanup.cleanup_resume_temp_dirs()

    assert not (workspace / "pytest-abc123").exists()
    assert not (workspace / "pytest-xyz").exists()
    assert len(result["removed"]) == 2
    assert result["errors"] == []


def test_cleanup_temp_dirs_removes_verification_tmp(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    workspace = tmp_workspace / "workspace"
    vtmp = workspace / "verification-tmp"
    vtmp.mkdir()
    (vtmp / "somefile.txt").write_text("data", encoding="utf-8")

    result = resume_process_cleanup.cleanup_resume_temp_dirs()

    assert not vtmp.exists()
    assert any("verification-tmp" in r for r in result["removed"])
    assert result["errors"] == []
    events = _events()
    assert any(e.get("event") == "resume_temp_cleanup_end" for e in events)


def test_cleanup_temp_dirs_skips_missing_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = resume_process_cleanup.cleanup_resume_temp_dirs()

    assert result["removed"] == []
    assert result["errors"] == []


def test_cleanup_temp_dirs_records_error_without_raising(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    workspace = tmp_workspace / "workspace"
    (workspace / "pytest-fail").mkdir()

    def _raise(path, ignore_errors=False):
        raise PermissionError("Access denied")

    monkeypatch.setattr(resume_process_cleanup.shutil, "rmtree", _raise)

    result = resume_process_cleanup.cleanup_resume_temp_dirs()

    assert result["removed"] == []
    assert len(result["errors"]) == 1
    assert "Access denied" in result["errors"][0]["error"]
