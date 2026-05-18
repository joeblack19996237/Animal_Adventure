"""
Unit tests for TDD ordering validation in stop_validate_json.py (TASK_BUILD mode).
Runs the hook as a subprocess — same pattern as test_hooks.py.
"""

import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path


_SCRIPTS_DIR = sysconfig.get_path("scripts")
HOOKS_DIR = (
    __import__("pathlib").Path(__file__).parent.parent.parent.parent
    / ".claude"
    / "hooks"
)
PYTHON = sys.executable


def _run_hook(stdin_data: dict, cwd: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HOOKS_DIR)
    env["HARNESS_MODE"] = "1"
    if _SCRIPTS_DIR:
        env["PATH"] = _SCRIPTS_DIR + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_json.py")],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _make_workspace(
    tmp_path: Path,
    phase_id: int,
    phase_type: str,
    *,
    allow_legacy_tdd_triplets: bool = False,
) -> str:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    state = {"phases": [{"id": phase_id, "phase_type": phase_type}]}
    (ws / "state.json").write_text(json.dumps(state), encoding="utf-8")
    harness_dir = tmp_path / "harness"
    harness_dir.mkdir(exist_ok=True)
    config = {
        "task_planning_limits": {
            "allow_legacy_tdd_triplets": allow_legacy_tdd_triplets
        }
    }
    (harness_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return str(tmp_path)


def _stop_input(signal: dict) -> dict:
    # Use last_assistant_message (checked first in hook_utils.read_signal_text)
    # rather than transcript_path, whose JSONL-reader doesn't parse the
    # single-object {"messages": [...]} format written by make_transcript.
    return {"last_assistant_message": json.dumps(signal), "stop_hook_active": False}


def _task(task_id: str, tdd_mode: str, tdd_skipped: str | None = None) -> dict:
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        "task_type": "foundation",
        "description": f"Do task {task_id}.",
        "tdd_mode": tdd_mode,
        "tdd_skipped": tdd_skipped,
    }


def _signal(phase_id: int, tasks: list) -> dict:
    return {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": phase_id,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Phase 1 auto-exempt
# ---------------------------------------------------------------------------


def test_phase1_entirely_exempt_from_ordering():
    sig = _signal(1, [_task("1.1", "exempt", "scaffold — no logic")])
    result = _run_hook(_stop_input(sig))
    assert result.returncode == 0


def test_phase1_task_with_tdd_skipped_passes():
    # Phase 1 (setup) is non-development: TDD triplet not enforced, but tdd_skipped required.
    sig = _signal(1, [_task("1.1", "exempt", "scaffold — no TDD triplet required")])
    result = _run_hook(_stop_input(sig))
    assert result.returncode == 0


def test_phase1_exempt_task_without_tdd_skipped_fails():
    # Phase 1 setup allows TDD modes, but exempt tasks still require an explicit reason.
    sig = _signal(1, [_task("1.1", "exempt", None)])
    result = _run_hook(_stop_input(sig))
    assert result.returncode == 1
    assert "tdd_skipped" in result.stdout


def test_phase1_test_task_may_use_test_first_without_tdd_skipped():
    sig = _signal(1, [_task("1.1", "test_first", None)])
    result = _run_hook(_stop_input(sig))
    assert result.returncode == 0


def test_phase1_rejects_unknown_tdd_mode():
    sig = _signal(1, [_task("1.1", "surprise", None)])
    result = _run_hook(_stop_input(sig))
    assert result.returncode == 1
    assert "tdd_mode" in result.stdout


# ---------------------------------------------------------------------------
# Phase 2+ valid tdd_slice tasks
# ---------------------------------------------------------------------------


def test_phase2_tdd_slice_passes():
    tasks = [_task("2.1", "tdd_slice")]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 0


def test_phase2_two_consecutive_tdd_slices_pass():
    tasks = [_task("2.1", "tdd_slice"), _task("2.2", "tdd_slice")]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 0


def test_phase2_exempt_task_between_tdd_slices_passes():
    tasks = [
        _task("2.1", "tdd_slice"),
        _task("2.2", "exempt", "DDL file — no logic to test"),
        _task("2.3", "tdd_slice"),
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 0


def test_phase2_legacy_triplet_passes_when_enabled(tmp_path: Path):
    cwd = _make_workspace(
        tmp_path,
        phase_id=2,
        phase_type="development",
        allow_legacy_tdd_triplets=True,
    )
    tasks = [
        _task("2.1", "test_first"),
        _task("2.2", "implementation"),
        _task("2.3", "unit_test"),
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)), cwd=cwd)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Phase 2+ violations
# ---------------------------------------------------------------------------


def test_phase2_missing_test_first_fails():
    tasks = [
        _task("2.1", "implementation"),
        _task("2.2", "unit_test"),
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 1
    assert "legacy tdd_mode" in result.stdout


def test_phase2_missing_unit_test_fails():
    tasks = [
        _task("2.1", "test_first"),
        _task("2.2", "implementation"),
        # no unit_test
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 1
    assert "legacy tdd_mode" in result.stdout


def test_phase2_unit_test_before_implementation_fails():
    tasks = [
        _task("2.1", "test_first"),
        _task("2.2", "unit_test"),
        _task("2.3", "implementation"),
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 1
    assert "legacy tdd_mode" in result.stdout


def test_phase2_test_first_after_implementation_without_unit_test_fails():
    tasks = [
        _task("2.1", "test_first"),
        _task("2.2", "implementation"),
        _task("2.3", "test_first"),  # missing unit_test before this
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 1
    assert "legacy tdd_mode" in result.stdout


def test_phase2_exempt_missing_reason_fails():
    tasks = [_task("2.1", "exempt", None)]  # tdd_skipped is null
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 1
    assert "no tdd_skipped reason" in result.stdout


def test_phase2_invalid_tdd_mode_value_fails():
    task = {
        "id": "2.1",
        "title": "Bad task",
        "task_type": "foundation",
        "description": "desc",
        "tdd_mode": "wrong_value",
        "tdd_skipped": None,
    }
    result = _run_hook(_stop_input(_signal(2, [task])))
    assert result.returncode == 1
    assert "tdd_mode" in result.stdout  # caught by jsonschema enum validation


def test_phase2_missing_tdd_mode_field_fails():
    task = {
        "id": "2.1",
        "title": "No tdd_mode",
        "task_type": "foundation",
        "description": "desc",
        # tdd_mode absent
    }
    result = _run_hook(_stop_input(_signal(2, [task])))
    assert result.returncode == 1
    assert "[SIGNAL ERROR]" in result.stdout


def test_phase2_phase_ends_after_test_first_only_fails():
    tasks = [_task("2.1", "test_first")]
    result = _run_hook(_stop_input(_signal(2, tasks)))
    assert result.returncode == 1
    assert "legacy tdd_mode" in result.stdout


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------


def test_execute_mode_signal_unaffected_by_tdd_changes():
    signal = {
        "mode": "EXECUTE",
        "phase_id": 1,
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }
    result = _run_hook(_stop_input(signal))
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Gate 2: phase_type-aware TDD enforcement
# ---------------------------------------------------------------------------


def test_integration_phase_skips_tdd_triplet(tmp_path: Path):
    """Integration phase with all tasks having tdd_skipped set → hook exits 0."""
    cwd = _make_workspace(tmp_path, phase_id=2, phase_type="integration")
    tasks = [
        _task("2.1", "exempt", "integration test — no TDD triplet required"),
        _task("2.2", "exempt", "integration test — no TDD triplet required"),
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)), cwd=cwd)
    assert result.returncode == 0


def test_e2e_phase_skips_tdd_triplet(tmp_path: Path):
    """E2E phase with all tasks having tdd_skipped set → hook exits 0."""
    cwd = _make_workspace(tmp_path, phase_id=3, phase_type="e2e")
    tasks = [_task("3.1", "exempt", "e2e test — no TDD triplet required")]
    result = _run_hook(_stop_input(_signal(3, tasks)), cwd=cwd)
    assert result.returncode == 0


def test_development_phase_accepts_tdd_slice(tmp_path: Path):
    """Development phase with state.json present → tdd_slice is accepted."""
    cwd = _make_workspace(tmp_path, phase_id=2, phase_type="development")
    tasks = [_task("2.1", "tdd_slice")]
    result = _run_hook(_stop_input(_signal(2, tasks)), cwd=cwd)
    assert result.returncode == 0


def test_integration_phase_requires_tdd_skipped_on_all_tasks(tmp_path: Path):
    """Integration phase task without tdd_skipped → hook exits 1."""
    cwd = _make_workspace(tmp_path, phase_id=2, phase_type="integration")
    tasks = [_task("2.1", "exempt", None)]  # tdd_skipped is null
    result = _run_hook(_stop_input(_signal(2, tasks)), cwd=cwd)
    assert result.returncode == 1
    assert "tdd_skipped" in result.stdout


def test_development_phase_skips_tasks_with_tdd_skipped(tmp_path: Path):
    """Development phase: exempt task with tdd_skipped set is excluded; remaining validated."""
    cwd = _make_workspace(tmp_path, phase_id=2, phase_type="development")
    tasks = [
        _task("2.1", "tdd_slice"),
        _task("2.2", "exempt", "DDL migration — no testable logic"),
    ]
    result = _run_hook(_stop_input(_signal(2, tasks)), cwd=cwd)
    assert result.returncode == 0


def test_hook_degrades_gracefully_when_state_json_missing(tmp_path: Path):
    """No state.json for phase 2 → defaults to development → valid tdd_slice passes."""
    # tmp_path has no workspace/state.json
    tasks = [_task("2.1", "tdd_slice")]
    result = _run_hook(_stop_input(_signal(2, tasks)), cwd=str(tmp_path))
    assert result.returncode == 0
