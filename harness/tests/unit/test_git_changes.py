from pathlib import Path

import git_changes


def test_changed_signal_file_is_stageable(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"a.py"})
    assert git_changes.safe_changed_signal_files(set(), ["a.py"]) == ["a.py"]


def test_preexisting_dirty_file_not_stageable(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"a.py", "b.py"})
    assert git_changes.safe_changed_signal_files({"a.py"}, ["a.py", "b.py"]) == ["b.py"]


def test_preexisting_dirty_signal_file_can_be_adopted(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"a.py", "b.py"})
    assert git_changes.safe_changed_signal_files(
        {"a.py"},
        ["a.py", "b.py"],
        include_preexisting_signal_files=True,
    ) == ["a.py", "b.py"]


def test_unrelated_untracked_file_not_stageable(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"a.py", "secret.txt"})
    assert git_changes.safe_changed_signal_files(set(), ["a.py"]) == ["a.py"]


def test_path_outside_repo_rejected(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"../x.py"})
    assert git_changes.safe_changed_signal_files(set(), ["../x.py"]) == []


def test_deleted_signal_file_handled_safely(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"gone.py"})
    assert git_changes.safe_changed_signal_files(set(), ["gone.py"]) == ["gone.py"]


def test_changed_files_since_snapshot_returns_only_new_dirty_files(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"a.py", "b.py"})

    assert git_changes.changed_files_since_snapshot({"a.py"}) == ["b.py"]


def test_changed_files_since_snapshot_ignores_generated_artifact_dirs(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        git_changes,
        "capture_snapshot",
        lambda: {
            "coverage/index.html",
            "test-results/out.txt",
            "playwright-report/index.html",
            "workspace/state.json",
            "pkg/__pycache__/mod.pyc",
            "src/app.py",
        },
    )

    assert git_changes.changed_files_since_snapshot(set()) == ["src/app.py"]


def test_changed_files_since_snapshot_without_baseline_is_empty(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"a.py"})

    assert git_changes.changed_files_since_snapshot(None) == []


def test_capture_status_snapshot_marks_untracked_and_tracked_dirty(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)

    class Result:
        returncode = 0
        stdout = "?? app/db.py\0 M app/main.py\0"

    monkeypatch.setattr(git_changes.subprocess, "run", lambda *a, **kw: Result())

    assert git_changes.capture_status_snapshot() == {
        "app/db.py": "??",
        "app/main.py": " M",
    }


def test_parse_porcelain_z_rename_records_destination_path():
    assert git_changes._parse_porcelain_z("R  app/new.py\0app/old.py\0") == {
        "app/new.py": "R "
    }


def test_parse_porcelain_z_copy_records_destination_path():
    assert git_changes._parse_porcelain_z("C  app/copy.py\0app/source.py\0") == {
        "app/copy.py": "C "
    }


def test_changed_files_since_snapshot_uses_rename_destination(monkeypatch):
    monkeypatch.setattr(git_changes, "capture_snapshot", lambda: {"app/new.py"})

    assert git_changes.changed_files_since_snapshot(set()) == ["app/new.py"]


def test_new_untracked_files_since_excludes_preexisting_and_user_owned(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        git_changes,
        "capture_status_snapshot",
        lambda: {
            "old.py": "??",
            "app/db.py": "??",
            ".claude/skills/issue-resolution-plan/SKILL.md": "??",
        },
    )

    assert git_changes.new_untracked_files_since({"old.py": "??"}) == ["app/db.py"]


def test_new_untracked_files_since_keeps_control_plane_by_default(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        git_changes,
        "capture_status_snapshot",
        lambda: {
            ".claude/settings.json": "??",
            ".claude/agents/builder.md": "??",
            "harness/git_changes.py": "??",
        },
    )

    assert git_changes.new_untracked_files_since({}) == [
        ".claude/agents/builder.md",
        ".claude/settings.json",
        "harness/git_changes.py",
    ]


def test_new_untracked_files_since_can_ignore_control_plane(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        git_changes,
        "capture_status_snapshot",
        lambda: {
            ".claude/settings.json": "??",
            ".claude/agents/builder.md": "??",
            "harness/git_changes.py": "??",
            "app/db.py": "??",
        },
    )

    assert git_changes.new_untracked_files_since(
        {}, ignore_control_plane=True
    ) == ["app/db.py"]


def test_tracked_dirty_files_since_reports_new_tracked_dirty(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        git_changes,
        "capture_status_snapshot",
        lambda: {"old.py": " M", "app/main.py": " M", "new.py": "??"},
    )

    assert git_changes.tracked_dirty_files_since({"old.py": " M"}) == ["app/main.py"]


def test_tracked_dirty_files_since_can_ignore_control_plane(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        git_changes,
        "capture_status_snapshot",
        lambda: {
            ".claude/settings.json": " M",
            ".claude/agents/builder.md": " M",
            "harness/git_changes.py": " M",
            "app/main.py": " M",
        },
    )

    assert git_changes.tracked_dirty_files_since(
        {}, ignore_control_plane=True
    ) == ["app/main.py"]
