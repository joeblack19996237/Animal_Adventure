from pathlib import Path

import pytest

import external_dependency
from subprocess_runner import ProcessCleanupResult


@pytest.fixture(autouse=True)
def no_real_process_listing(monkeypatch):
    monkeypatch.setattr(external_dependency, "list_named_processes", lambda names: [])
    monkeypatch.setattr(external_dependency, "process_exists", lambda pid: True)


def test_cleanup_before_wait_quarantines_new_untracked_files(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    created = tmp_workspace / "app" / "db.py"
    created.parent.mkdir()
    created.write_text("partial", encoding="utf-8")

    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )
    monkeypatch.setattr(
        external_dependency,
        "new_untracked_files_since",
        lambda snapshot, **kwargs: ["app/db.py"],
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda snapshot, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "capture_status_snapshot", lambda: {}
    )

    context = {"root_pid": 123, "pre_git_snapshot": {}}
    result = external_dependency.cleanup_before_wait(context)

    assert result["cleanup_status"] == "clean"
    assert result["quarantined_files"] == ["app/db.py"]
    assert result["process_cleanup"]["ok"] is True
    assert not created.exists()


def test_cleanup_before_wait_records_process_cleanup_ok(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, [456]),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["process_cleanup"]["attempted"] is True
    assert result["process_cleanup"]["ok"] is True
    assert result["process_cleanup"]["terminated_pids"] == [456]


def test_cleanup_before_wait_treats_missing_root_pid_as_clean(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    cleanup_calls = []
    monkeypatch.setattr(external_dependency, "process_exists", lambda pid: False)
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: cleanup_calls.append(pid),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["cleanup_status"] == "clean"
    assert result["process_cleanup"]["ok"] is True
    assert result["process_cleanup"]["root_pid"] == 123
    assert "no longer active" in result["process_cleanup"]["error"]
    assert cleanup_calls == []


def test_cleanup_before_wait_missing_root_pid_still_blocks_product_dirty(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(external_dependency, "process_exists", lambda pid: False)
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency,
        "tracked_dirty_files_since",
        lambda s, **kwargs: ["src/main.ts"],
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["cleanup_status"] == "failed"
    assert result["process_cleanup"]["ok"] is True
    assert result["tracked_dirty_files"] == ["src/main.ts"]


def test_cleanup_before_wait_records_claude_process_snapshots(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    snapshots = [
        [{"pid": 123, "name": "claude", "path": "claude.exe", "start_time": "before"}],
        [{"pid": 789, "name": "claude", "path": "claude.exe", "start_time": "after"}],
    ]
    monkeypatch.setattr(
        external_dependency, "list_named_processes", lambda names: snapshots.pop(0)
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, [123]),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["claude_processes_before_cleanup"][0]["pid"] == 123
    assert result["claude_processes_after_cleanup"][0]["pid"] == 789


def test_cleanup_before_wait_reports_possible_orphan_processes_without_failing_clean(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    snapshots = [
        [{"pid": 123, "name": "claude", "path": "", "start_time": ""}],
        [{"pid": 789, "name": "claude", "path": "", "start_time": ""}],
    ]
    monkeypatch.setattr(
        external_dependency, "list_named_processes", lambda names: snapshots.pop(0)
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, [123]),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["cleanup_status"] == "clean"
    assert result["possible_orphan_processes"] == [
        {"pid": 789, "name": "claude", "path": "", "start_time": ""}
    ]


def test_cleanup_before_wait_fails_when_process_cleanup_fails(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, False, pid, [], "Access denied"),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["cleanup_status"] == "failed"
    assert result["process_cleanup"]["ok"] is False
    assert result["process_cleanup"]["error"] == "Access denied"


def test_cleanup_before_wait_fails_on_tracked_dirty_files(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency,
        "tracked_dirty_files_since",
        lambda s, **kwargs: ["app/main.py"],
    )
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["cleanup_status"] == "failed"
    assert result["tracked_dirty_files"] == ["app/main.py"]


def test_cleanup_before_wait_ignores_control_plane_dirty_files(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    seen = {"untracked": [], "tracked": []}
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )

    def new_untracked(snapshot, **kwargs):
        seen["untracked"].append(kwargs)
        return [] if kwargs.get("ignore_control_plane") else ["harness/git_changes.py"]

    def tracked_dirty(snapshot, **kwargs):
        seen["tracked"].append(kwargs)
        return [] if kwargs.get("ignore_control_plane") else [".claude/settings.json"]

    monkeypatch.setattr(external_dependency, "new_untracked_files_since", new_untracked)
    monkeypatch.setattr(external_dependency, "tracked_dirty_files_since", tracked_dirty)
    monkeypatch.setattr(external_dependency, "capture_status_snapshot", lambda: {})

    result = external_dependency.cleanup_before_wait(
        {"root_pid": 123, "pre_git_snapshot": {}}
    )

    assert result["cleanup_status"] == "clean"
    assert result["quarantined_files"] == []
    assert result["tracked_dirty_files"] == []
    assert seen["untracked"] == [{"ignore_control_plane": True}]
    assert seen["tracked"] == [{"ignore_control_plane": True}]


def test_preflight_clears_context_when_clean(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.CONTEXT_PATH.parent.mkdir(exist_ok=True)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is True
    assert external_dependency.load_context() is None


def test_preflight_clears_context_when_root_pid_is_missing(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    cleanup_calls = []
    monkeypatch.setattr(external_dependency, "process_exists", lambda pid: False)
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: cleanup_calls.append(pid),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is True
    assert result["process_cleanup"]["ok"] is True
    assert "no longer active" in result["process_cleanup"]["error"]
    assert cleanup_calls == []
    assert external_dependency.load_context() is None


def test_preflight_missing_root_pid_still_blocks_product_dirty(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    monkeypatch.setattr(external_dependency, "process_exists", lambda pid: False)
    monkeypatch.setattr(
        external_dependency,
        "new_untracked_files_since",
        lambda s, **kwargs: ["tests/foo.spec.ts"],
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is False
    assert result["process_cleanup"]["ok"] is True
    assert result["untracked_files"] == ["tests/foo.spec.ts"]
    assert external_dependency.load_context()["cleanup_status"] == "failed"


def test_preflight_unknown_process_existence_keeps_cleanup_failure_behavior(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    cleanup_calls = []
    monkeypatch.setattr(external_dependency, "process_exists", lambda pid: None)
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: cleanup_calls.append(pid)
        or ProcessCleanupResult(True, False, pid, [], "Access denied"),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert cleanup_calls == [123]
    assert result["ok"] is False
    assert result["process_cleanup"]["error"] == "Access denied"


def test_preflight_ignores_control_plane_dirty_files(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    seen = {"untracked": [], "tracked": []}
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )

    def new_untracked(snapshot, **kwargs):
        seen["untracked"].append(kwargs)
        return [] if kwargs.get("ignore_control_plane") else ["harness/harness.py"]

    def tracked_dirty(snapshot, **kwargs):
        seen["tracked"].append(kwargs)
        return [] if kwargs.get("ignore_control_plane") else [".claude/settings.json"]

    monkeypatch.setattr(external_dependency, "new_untracked_files_since", new_untracked)
    monkeypatch.setattr(external_dependency, "tracked_dirty_files_since", tracked_dirty)

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is True
    assert result["untracked_files"] == []
    assert result["tracked_dirty_files"] == []
    assert external_dependency.load_context() is None
    assert seen["untracked"] == [{"ignore_control_plane": True}]
    assert seen["tracked"] == [{"ignore_control_plane": True}]


def test_preflight_blocks_unknown_untracked_files(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )
    monkeypatch.setattr(
        external_dependency,
        "new_untracked_files_since",
        lambda s, **kwargs: ["app/db.py"],
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is False
    assert result["untracked_files"] == ["app/db.py"]
    assert external_dependency.load_context()["cleanup_status"] == "failed"


def test_preflight_still_blocks_product_dirty_with_control_plane_ignored(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )
    monkeypatch.setattr(
        external_dependency,
        "new_untracked_files_since",
        lambda s, **kwargs: ["src/main.ts"],
    )
    monkeypatch.setattr(
        external_dependency,
        "tracked_dirty_files_since",
        lambda s, **kwargs: ["tests/foo.spec.ts"],
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is False
    assert result["untracked_files"] == ["src/main.ts"]
    assert result["tracked_dirty_files"] == ["tests/foo.spec.ts"]
    assert external_dependency.load_context()["cleanup_status"] == "failed"


def test_preflight_keeps_context_when_process_cleanup_fails(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, False, pid, [], "Access denied"),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is False
    assert result["process_cleanup"]["ok"] is False
    assert result["process_cleanup"]["error"] == "Access denied"
    assert external_dependency.load_context()["cleanup_status"] == "failed"


def test_preflight_context_updates_process_snapshot_and_keeps_context_on_cleanup_failure(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {"root_pid": 123, "clean_snapshot_after_cleanup": {}, "cleanup_status": "clean"}
    )
    monkeypatch.setattr(
        external_dependency,
        "list_named_processes",
        lambda names: [{"pid": 789, "name": "claude", "path": "", "start_time": ""}],
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, False, pid, [], "Access denied"),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    monkeypatch.setattr(
        external_dependency, "tracked_dirty_files_since", lambda s, **kwargs: []
    )

    result = external_dependency.preflight_context(allow_quarantine=False)
    context = external_dependency.load_context()

    assert result["ok"] is False
    assert result["claude_processes_after_cleanup"][0]["pid"] == 789
    assert context["possible_orphan_processes"][0]["pid"] == 789


def test_preflight_uses_original_snapshot_after_failed_cleanup(
    tmp_workspace, monkeypatch
):
    monkeypatch.chdir(tmp_workspace)
    external_dependency.save_context(
        {
            "root_pid": 123,
            "pre_git_snapshot": {},
            "clean_snapshot_after_cleanup": {"app/main.py": " M"},
            "cleanup_status": "failed",
        }
    )
    monkeypatch.setattr(
        external_dependency,
        "cleanup_process_tree",
        lambda pid: ProcessCleanupResult(True, True, pid, []),
    )
    monkeypatch.setattr(
        external_dependency, "new_untracked_files_since", lambda s, **kwargs: []
    )
    seen = []

    def tracked_dirty(snapshot, **kwargs):
        seen.append(snapshot)
        return ["app/main.py"] if snapshot == {} else []

    monkeypatch.setattr(external_dependency, "tracked_dirty_files_since", tracked_dirty)

    result = external_dependency.preflight_context(allow_quarantine=False)

    assert result["ok"] is False
    assert seen == [{}]
