import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agents
import state as state_mod
import verify as verify_mod
from fix import (
    _targeted_rereview_blocking_fixes,
    _is_excluded_path,
    _normalize_review_report_ids,
    handle_verdict,
    run_batch_retry_loop,
    run_fix_cycle,
)


TECH_DEBT_PATH = Path("workspace/tech_debt.jsonl")


def test_is_excluded_path_matches_trailing_slash_exclude():
    assert _is_excluded_path("dist/app.js", ["dist/"])


def test_is_excluded_path_matches_windows_style_paths():
    assert _is_excluded_path("dist\\app.js:12", ["dist/"])


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def _make_harness(sample_config):
    h = MagicMock()
    h.config = sample_config
    h._default_language = "python"
    h.profile_for = MagicMock(
        return_value={
            "name": "python",
            "execute_model": "claude-sonnet-4-6",
            "build_model": "claude-haiku-4-5-20251001",
            "builder_agent": ".claude/agents/code-builder.md",
            "reviewer_agent": ".claude/agents/code-reviewer.md",
            "builder_skill": ".claude/skills/tdd-workflow/SKILL.md",
            "reviewer_skill": ".claude/skills/security-review/SKILL.md",
            "common_rules": ".claude/rules/common/coding-standards.md",
            "rules_file": ".claude/rules/python/python-standards.md",
            "test_cmd": ["pytest"],
        }
    )
    h.phase_type_for = MagicMock(return_value="development")
    return h


def _state_with_task(status="pending", attempts=0):
    return {
        "spec_file": "spec.md",
        "language": "python",
        "task_types": ["foundation"],
        "phases": [
            {
                "id": 1,
                "title": "Phase One",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Task One",
                        "task_type": "foundation",
                        "status": status,
                        "attempts": attempts,
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


def _state_with_issues(severities=None):
    severities = severities or ["HIGH", "MEDIUM"]
    issues = [
        {
            "id": f"1.{i + 1}",
            "severity": sev,
            "dimension": "Security",
            "file": "app.py",
            "title": f"Issue {i + 1}",
            "status": "open",
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
        for i, sev in enumerate(severities)
    ]
    return {
        "spec_file": "spec.md",
        "language": "python",
        "task_types": ["foundation"],
        "phases": [
            {
                "id": 1,
                "title": "Phase One",
                "status": "building",
                "tasks": [],
                "review": {
                    "status": "fixing",
                    "verdict": "BLOCK",
                    "sha_at_review": "abc",
                    "issues": issues,
                },
            }
        ],
    }


# --- run_batch_retry_loop ---


def test_run_batch_retry_loop_halt_on_max(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=3)
    state_mod.save_state(state)

    with pytest.raises(SystemExit) as exc:
        run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)
    assert exc.value.code == 1
    assert state["phases"][0]["tasks"][0]["status"] == "halted"


def test_run_batch_retry_loop_halt_on_last_error_hard_cap(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state["phases"][0]["tasks"][0]["last_error"] = ["one", "two", "three"]
    state_mod.save_state(state)
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("agent must not run after last_error hard cap")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    assert exc.value.code == 1
    task = state["phases"][0]["tasks"][0]
    assert task["status"] == "halted"
    assert "recorded 3 failures" in task["last_error"][-1]


def test_run_batch_retry_loop_verify_failure_halts_at_last_error_hard_cap(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state["phases"][0]["tasks"][0]["last_error"] = ["one", "two"]
    state_mod.save_state(state)
    execute_signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ]
    }

    import fix as fix_mod
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **kw: {"signal": execute_signal, "usage": {}},
    )
    monkeypatch.setattr(
        fix_mod,
        "verify_execution",
        lambda *a, **kw: [
            {"id": "1.1", "status": "failed", "reason": "pytest failed"}
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    assert exc.value.code == 1
    task = state["phases"][0]["tasks"][0]
    assert task["status"] == "halted"
    assert task["last_error"][-2] == "pytest failed"
    assert "recorded 3 failures" in task["last_error"][-1]


def test_run_batch_retry_loop_halt_on_consecutive_verify_failure_hard_cap(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state["phases"][0]["tasks"][0]["verify_fails"] = 3
    state_mod.save_state(state)
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("agent must not run after verify_fails hard cap")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    assert exc.value.code == 1
    task = state["phases"][0]["tasks"][0]
    assert task["status"] == "halted"
    assert "3 consecutive verify failures" in task["last_error"][-1]


def test_run_batch_retry_loop_verify_fails_escalation(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state["phases"][0]["tasks"][0]["verify_fails"] = 1
    state_mod.save_state(state)

    execute_signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ]
    }
    call_count = [0]

    def mock_execute(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "signal": execute_signal,
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        state["phases"][0]["tasks"][0]["status"] = "complete"
        return {
            "signal": execute_signal,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    # verify_execution returns failure first time, then empty
    verify_count = [0]

    def mock_verify(h, pre_sha, batch, signal, pre_snapshot=None):
        verify_count[0] += 1
        if verify_count[0] == 1:
            return [{"id": "1.1", "status": "failed", "reason": "test failed"}]
        return []

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(agents, "execute", mock_execute)

    import fix as fix_mod

    monkeypatch.setattr(fix_mod, "verify_execution", mock_verify)

    run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)
    # verify_fails threshold=2: first verify fail → verify_fails=2 → escalates attempts
    assert state["phases"][0]["tasks"][0]["status"] == "complete"


def test_run_batch_retry_loop_passes_pre_snapshot_to_verify_execution(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state_mod.save_state(state)
    execute_signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": ["new.py"],
            }
        ]
    }

    import fix as fix_mod
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "execute",
        lambda *a, **kw: {"signal": execute_signal, "usage": {}},
    )
    monkeypatch.setattr(fix_mod, "capture_snapshot", lambda: {"dirty.py"})
    captured = {}

    def mock_verify(h, pre_sha, batch, signal, pre_snapshot=None):
        captured["pre_snapshot"] = pre_snapshot
        return []

    monkeypatch.setattr(fix_mod, "verify_execution", mock_verify)

    run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    assert captured["pre_snapshot"] == {"dirty.py"}


def test_run_batch_retry_loop_passes_spec_context_to_retry_execute(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state_mod.save_state(state)
    execute_signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ]
    }
    captured = {}

    import fix as fix_mod
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        fix_mod, "build_phase_spec_context", lambda spec_file, phase: "phase context"
    )

    def mock_execute(*args, **kwargs):
        captured["spec_context"] = kwargs.get("spec_context")
        return {"signal": execute_signal, "usage": {}}

    monkeypatch.setattr(agents, "execute", mock_execute)
    monkeypatch.setattr(fix_mod, "verify_execution", lambda *a, **kw: [])

    run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    assert captured["spec_context"] == "phase context"


def test_batch_retry_external_dependency_blocks_task(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state_mod.save_state(state)

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "execute",
        MagicMock(side_effect=agents.ExternalDependencyError("429")),
    )

    with pytest.raises(SystemExit):
        run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    task = state["phases"][0]["tasks"][0]
    assert task["status"] == "blocked_external_dependency"
    assert task["attempts"] == 0


def test_run_batch_retry_loop_external_dependency_after_no_commit_blocks_task(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state_mod.save_state(state)
    execute_signal = {
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": [],
            }
        ]
    }
    execute_calls = [0]

    def mock_execute(*args, **kwargs):
        execute_calls[0] += 1
        if execute_calls[0] == 1:
            return {"signal": execute_signal, "usage": {}}
        raise agents.ExternalDependencyError("429")

    import fix as fix_mod
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(agents, "execute", mock_execute)
    monkeypatch.setattr(
        fix_mod,
        "verify_execution",
        lambda *a, **kw: [
            {
                "id": "1.1",
                "status": "failed",
                "reason": "agent completed task but created no commit",
            }
        ],
    )

    with pytest.raises(SystemExit):
        run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)

    task = state["phases"][0]["tasks"][0]
    assert task["status"] == "blocked_external_dependency"
    assert task["attempts"] == 0


def test_run_batch_retry_loop_task_failed_signal(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_task(status="pending", attempts=0)
    state_mod.save_state(state)

    call_count = [0]

    def mock_execute(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "signal": {
                    "tasks": [
                        {
                            "id": "1.1",
                            "title": "T",
                            "task_type": "foundation",
                            "status": "failed",
                            "reason": "oops",
                            "files_changed": [],
                        }
                    ]
                },
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        state["phases"][0]["tasks"][0]["status"] = "complete"
        return {
            "signal": {
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "T",
                        "task_type": "foundation",
                        "status": "complete",
                        "files_changed": [],
                    }
                ]
            },
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(agents, "execute", mock_execute)

    import fix as fix_mod

    monkeypatch.setattr(fix_mod, "verify_execution", lambda *a, **kw: [])

    run_batch_retry_loop(harness, state, [{"id": "1.1"}], 1)
    assert state["phases"][0]["tasks"][0]["attempts"] >= 1


# --- handle_verdict ---


def test_handle_verdict_approve(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)

    review_result = {
        "signal": {"verdict": "APPROVE", "issues": []},
        "usage": {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }

    fix_called = [False]
    import fix as fix_mod

    monkeypatch.setattr(
        fix_mod, "run_fix_cycle", lambda *a: fix_called.__setitem__(0, True)
    )

    handle_verdict(harness, state, 1, review_result)
    assert not fix_called[0]


def test_handle_verdict_warn(sample_config, monkeypatch, tmp_workspace):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["MEDIUM", "LOW"])
    state_mod.save_state(state)

    review_result = {
        "signal": {"verdict": "WARN", "issues": []},
        "usage": {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }

    handle_verdict(harness, state, 1, review_result)

    for issue in state["phases"][0]["review"]["issues"]:
        assert issue["status"] == "deferred"
    assert (tmp_workspace / "workspace" / "tech_debt.jsonl").exists()


def test_handle_verdict_block(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)

    review_result = {
        "signal": {"verdict": "BLOCK", "issues": []},
        "usage": {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }

    fix_called = [False]
    import fix as fix_mod

    monkeypatch.setattr(
        fix_mod, "run_fix_cycle", lambda *a: fix_called.__setitem__(0, True)
    )

    handle_verdict(harness, state, 1, review_result)
    assert fix_called[0]


# --- run_fix_cycle ---


def test_run_fix_cycle_resolves_open(sample_config, monkeypatch, tmp_workspace):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)

    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("### 1.1 Missing validation\nDetails.", encoding="utf-8")

    import subprocess
    import fix as fix_mod

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}]
            },
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    )
    monkeypatch.setattr(
        fix_mod,
        "verify_fix",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)
    assert state["phases"][0]["review"]["status"] == "fixed"


def test_run_fix_cycle_passes_spec_context(sample_config, monkeypatch, tmp_workspace):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    (tmp_workspace / "workspace" / "review_report.md").write_text(
        "### 1.1 Missing validation\nDetails.", encoding="utf-8"
    )
    captured = {}

    import subprocess
    import fix as fix_mod

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )

    def mock_fix(*args, **kwargs):
        captured["spec_context"] = kwargs.get("spec_context")
        return {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(agents, "fix_issues", mock_fix)
    monkeypatch.setattr(fix_mod, "verify_fix", lambda *a, **kw: [])
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)

    assert "Spec manifest" in captured["spec_context"]


def test_run_fix_cycle_passes_pre_snapshot_to_verify_fix(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    (tmp_workspace / "workspace" / "review_report.md").write_text(
        "### 1.1 Missing validation\nDetails.", encoding="utf-8"
    )
    captured = {}

    import subprocess
    import fix as fix_mod

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(fix_mod, "capture_snapshot", lambda: {"before.txt"})
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["a.py"]}]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )

    def mock_verify_fix(*args, **kwargs):
        captured["pre_snapshot"] = args[5]
        return []

    monkeypatch.setattr(fix_mod, "verify_fix", mock_verify_fix)
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)

    assert captured["pre_snapshot"] == {"before.txt"}


def test_run_fix_cycle_test_failure_reason_enters_issue_last_error(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    (tmp_workspace / "workspace" / "review_report.md").write_text(
        "### 1.1 Severe\nDetails.", encoding="utf-8"
    )

    import subprocess
    import fix as fix_mod

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(
        fix_mod,
        "verify_fix",
        lambda *a, **kw: [
            {
                "id": "1.1",
                "status": "open",
                "reason": "fix tests failed; see workspace/fix_test_failure.log",
            }
        ],
    )
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)

    last_error = state["phases"][0]["review"]["issues"][0]["last_error"]
    assert any("fix tests failed" in e for e in last_error)
    assert any("fix_test_failure.log" in e for e in last_error)


def test_run_fix_cycle_halts_issue_on_harness_verification_blocker(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    (tmp_workspace / "workspace" / "review_report.md").write_text(
        "### 1.1 Severe\nDetails.", encoding="utf-8"
    )

    import subprocess
    import fix as fix_mod

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "call_id": "fix-test",
        },
    )
    blocker = verify_mod.VerificationResult(
        open_fixes=[
            {
                "id": "1.1",
                "status": "fixed",
                "reason": "claimed fixed but no commit was created",
            }
        ],
        harness_blocker=True,
        blocker_reason="claimed fixed but no commit was created",
        failure_kind="fixed_without_commit",
    )
    monkeypatch.setattr(fix_mod, "verify_fix", lambda *a, **kw: blocker)
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    with pytest.raises(SystemExit):
        run_fix_cycle(harness, state, 1)

    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "halted"
    assert issue["attempts"] == 0
    assert issue["last_error"][-1] == "claimed fixed but no commit was created"


def test_run_fix_cycle_deferred_medium_low(sample_config, monkeypatch, tmp_workspace):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH", "MEDIUM"])
    state_mod.save_state(state)

    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("## Issues\n### 1.1 Severe\n### 1.2 Minor\n", encoding="utf-8")

    import subprocess
    import fix as fix_mod

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [
                    {"id": "1.1", "status": "fixed", "files_changed": []},
                    {"id": "1.2", "status": "open", "files_changed": []},
                ]
            },
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    )
    monkeypatch.setattr(fix_mod, "verify_fix", lambda *a, **kw: [a[2][1]])
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)
    medium_issue = next(
        i for i in state["phases"][0]["review"]["issues"] if i["id"] == "1.2"
    )
    assert medium_issue["status"] == "deferred"


def test_fix_cycle_external_dependency_does_not_increment_issue_attempts(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("### 1.1 Severe\nDetails.", encoding="utf-8")

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        MagicMock(side_effect=agents.ExternalDependencyError("429")),
    )

    with pytest.raises(SystemExit):
        run_fix_cycle(harness, state, 1)

    issue = state["phases"][0]["review"]["issues"][0]
    review = state["phases"][0]["review"]
    assert issue["attempts"] == 0
    assert issue["status"] == "open"
    assert review["status"] == "blocked_external_dependency"
    assert review["blocked_mode"] == "FIX"


def test_fix_cycle_subprocess_error_increments_attempts_and_records_error(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("### 1.1 Severe\nDetails.", encoding="utf-8")

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        MagicMock(
            side_effect=agents.SubprocessError(
                "claude exited with code 1: API Error: Unable to connect to API (ConnectionRefused)"
            )
        ),
    )

    with pytest.raises(SystemExit):
        run_fix_cycle(harness, state, 1)

    issue = state["phases"][0]["review"]["issues"][0]
    review = state["phases"][0]["review"]
    assert issue["attempts"] == 1
    assert issue["status"] == "error"
    assert review["status"] == "fixing"
    assert "ConnectionRefused" in issue["last_error"][-1]


def test_run_fix_cycle_subprocess_error_records_all_open_issues(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH", "CRITICAL"])
    state_mod.save_state(state)
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("### 1.1 Severe\n\n### 1.2 Worse\n", encoding="utf-8")

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: MagicMock(stdout="sha", returncode=0)
    )
    monkeypatch.setattr(
        agents,
        "fix_issues",
        MagicMock(side_effect=agents.SubprocessError("could not extract signal")),
    )

    with pytest.raises(SystemExit):
        run_fix_cycle(harness, state, 1)

    issues = state["phases"][0]["review"]["issues"]
    assert [issue["status"] for issue in issues] == ["error", "error"]
    assert [issue["attempts"] for issue in issues] == [1, 1]
    assert [issue["last_error"] for issue in issues] == [
        ["could not extract signal"],
        ["could not extract signal"],
    ]


def test_fix_cycle_runs_targeted_rereview_after_high_fix(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    calls = []

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        lambda **kw: (
            calls.append(kw)
            or {"signal": {"verdict": "APPROVE", "issues": []}, "usage": {}}
        ),
    )

    result = _targeted_rereview_blocking_fixes(
        harness,
        state,
        1,
        [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
        "oldsha",
    )

    assert result == []
    assert calls[0]["issue_ids"] == ["1.1"]
    assert calls[0]["base_sha"] == "oldsha"
    assert calls[0]["head_sha"] == "newsha"


def test_fix_cycle_advances_when_targeted_rereview_approves(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        lambda **kw: {"signal": {"verdict": "APPROVE", "issues": []}, "usage": {}},
    )

    result = _targeted_rereview_blocking_fixes(
        harness,
        state,
        1,
        [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
        "oldsha",
    )

    assert result == []


def test_fix_cycle_keeps_issue_open_when_targeted_rereview_blocks(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        lambda **kw: {
            "signal": {
                "verdict": "BLOCK",
                "issues": [{"id": "1.1", "title": "Still broken"}],
            },
            "usage": {},
        },
    )

    result = _targeted_rereview_blocking_fixes(
        harness,
        state,
        1,
        [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
        "oldsha",
    )

    assert result[0]["status"] == "open"
    issue = state["phases"][0]["review"]["issues"][0]
    assert issue["status"] == "open"
    assert "Still broken" in issue["last_error"][-1]


def test_targeted_rereview_subprocess_error_reopens_fixed_issue(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"
    state_mod.save_state(state)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        MagicMock(side_effect=agents.SubprocessError("timeout")),
    )

    result = _targeted_rereview_blocking_fixes(
        harness,
        state,
        1,
        [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
        "oldsha",
    )

    assert result[0]["status"] == "open"
    assert state["phases"][0]["review"]["issues"][0]["status"] == "open"


def test_targeted_rereview_subprocess_error_records_last_error(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"
    state_mod.save_state(state)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        MagicMock(side_effect=agents.SubprocessError("timeout")),
    )

    result = _targeted_rereview_blocking_fixes(
        harness,
        state,
        1,
        [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
        "oldsha",
    )

    assert "targeted re-review failed" in result[0]["reason"]
    assert (
        "targeted re-review failed"
        in state["phases"][0]["review"]["issues"][0]["last_error"][-1]
    )


def test_targeted_rereview_external_dependency_reopens_fixed_blocking_issue(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"
    state_mod.save_state(state)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        MagicMock(side_effect=agents.ExternalDependencyError("429")),
    )

    with pytest.raises(SystemExit):
        _targeted_rereview_blocking_fixes(
            harness,
            state,
            1,
            [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
            "oldsha",
        )

    review = state["phases"][0]["review"]
    issue = review["issues"][0]
    assert review["status"] == "blocked_external_dependency"
    assert review["blocked_mode"] == "FIX"
    assert issue["status"] == "open"
    assert issue["attempts"] == 0
    assert issue["last_error"][-1] == "targeted re-review blocked: 429"


def test_targeted_rereview_external_dependency_preserves_blocked_mode_fix(
    sample_config, monkeypatch
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["status"] = "fixed"
    state_mod.save_state(state)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(
        agents,
        "review_fix",
        MagicMock(side_effect=agents.ExternalDependencyError("429")),
    )

    with pytest.raises(SystemExit):
        _targeted_rereview_blocking_fixes(
            harness,
            state,
            1,
            [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
            "oldsha",
        )

    review = state["phases"][0]["review"]
    assert review["status"] == "blocked_external_dependency"
    assert review["blocked_mode"] == "FIX"


def test_run_fix_cycle_increments_attempt_after_targeted_rereview_error(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("### 1.1 Severe\nDetails.", encoding="utf-8")

    import fix as fix_mod

    git_shas = iter(["oldsha\n", "newsha\n"])

    def mock_run(cmd, **kw):
        if cmd[:3] == ["git", "status", "--porcelain=v1"]:
            return MagicMock(stdout="", returncode=0)
        return MagicMock(stdout=next(git_shas, "newsha\n"), returncode=0)

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(fix_mod, "verify_fix", lambda *a, **kw: [])
    monkeypatch.setattr(
        agents,
        "review_fix",
        MagicMock(side_effect=agents.SubprocessError("timeout")),
    )
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)

    assert state["phases"][0]["review"]["issues"][0]["attempts"] == 1


def test_run_fix_cycle_does_not_duplicate_targeted_rereview_error(
    sample_config, monkeypatch, tmp_workspace
):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["HIGH"])
    state_mod.save_state(state)
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("### 1.1 Severe\nDetails.", encoding="utf-8")

    import fix as fix_mod

    git_shas = iter(["oldsha\n", "newsha\n"])

    def mock_run(cmd, **kw):
        if cmd[:3] == ["git", "status", "--porcelain=v1"]:
            return MagicMock(stdout="", returncode=0)
        return MagicMock(stdout=next(git_shas, "newsha\n"), returncode=0)

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}]
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    monkeypatch.setattr(fix_mod, "verify_fix", lambda *a, **kw: [])
    monkeypatch.setattr(
        agents,
        "review_fix",
        MagicMock(side_effect=agents.SubprocessError("timeout")),
    )
    monkeypatch.setattr(
        fix_mod,
        "_open_critical_high",
        MagicMock(side_effect=[state["phases"][0]["review"]["issues"][:1], []]),
    )

    run_fix_cycle(harness, state, 1)

    errors = state["phases"][0]["review"]["issues"][0]["last_error"]
    assert len([e for e in errors if "targeted re-review failed" in e]) == 1


def test_warn_only_phase_does_not_targeted_rereview(sample_config, monkeypatch):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["MEDIUM"])
    state_mod.save_state(state)
    called = []

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout="newsha\n", returncode=0),
    )
    monkeypatch.setattr(agents, "review_fix", lambda **kw: called.append(kw))

    result = _targeted_rereview_blocking_fixes(
        harness,
        state,
        1,
        [{"id": "1.1", "status": "fixed", "files_changed": ["app.py"]}],
        "oldsha",
    )

    assert result == []
    assert called == []


# --- run_cleanup ---


def test_run_cleanup_all_fixed(sample_config, monkeypatch, tmp_workspace):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["MEDIUM"])
    state["phases"][0]["review"]["issues"][0]["status"] = "deferred"
    state_mod.save_state(state)

    debt = tmp_workspace / "workspace" / "tech_debt.jsonl"
    debt.write_text(
        json.dumps(state["phases"][0]["review"]["issues"][0]) + "\n", encoding="utf-8"
    )

    import subprocess
    import cleanup as cleanup_mod

    shas = iter(["oldsha\n", "newsha\n"])

    def mock_run(cmd, **kw):
        if cmd[:2] == ["git", "rev-parse"]:
            return MagicMock(stdout=next(shas, "newsha\n"), returncode=0, stderr="")
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return MagicMock(stdout="app.py\n", returncode=0, stderr="")
        return MagicMock(stdout="", returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        agents,
        "fix_issues",
        lambda *a, **kw: {
            "signal": {
                "fixes": [{"id": "1.1", "status": "fixed", "files_changed": []}]
            },
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    )

    finish_called = [False]
    monkeypatch.setattr(
        cleanup_mod, "_finish", lambda *_: finish_called.__setitem__(0, True)
    )

    from cleanup import run_cleanup

    run_cleanup(harness, state)
    assert finish_called[0]
    remaining = debt.read_text(encoding="utf-8").strip()
    assert remaining == ""


def test_run_cleanup_remaining(sample_config, monkeypatch, tmp_workspace):
    harness = _make_harness(sample_config)
    state = _state_with_issues(["MEDIUM"])
    state["phases"][0]["review"]["issues"][0]["status"] = "deferred"
    state_mod.save_state(state)

    debt = tmp_workspace / "workspace" / "tech_debt.jsonl"
    debt.write_text(
        json.dumps(state["phases"][0]["review"]["issues"][0]) + "\n", encoding="utf-8"
    )

    import subprocess
    import cleanup as cleanup_mod

    call_count = [0]

    def mock_fix(*a, **kw):
        call_count[0] += 1
        # Fail once, then escalate attempts so loop exits
        return {
            "signal": {
                "fixes": [
                    {
                        "id": "1.1",
                        "status": "open",
                        "reason": "not done",
                        "files_changed": [],
                    }
                ]
            },
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }

    def mock_run(cmd, **kw):
        r = MagicMock()
        r.stdout = "sha\n"
        r.returncode = 0
        r.stderr = ""
        return r

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(agents, "fix_issues", mock_fix)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *_: None)

    # Force halt after 1 fix attempt by setting attempts to max
    state["phases"][0]["review"]["issues"][0]["attempts"] = 2

    with pytest.raises(SystemExit):
        from cleanup import run_cleanup

        run_cleanup(harness, state)


# --- _normalize_review_report_ids ---


def _state_for_normalize(phase_id, issue_ids, statuses=None):
    if statuses is None:
        statuses = ["open"] * len(issue_ids)
    issues = [
        {
            "id": iid,
            "severity": "HIGH",
            "dimension": "Functionality",
            "file": "app.py",
            "title": f"Issue {iid}",
            "status": status,
            "attempts": 0,
            "files_changed": [],
            "fixed_sha": None,
            "last_error": [],
        }
        for iid, status in zip(issue_ids, statuses)
    ]
    return {
        "spec_file": "spec.md",
        "language": "python",
        "task_types": ["foundation"],
        "phases": [
            {
                "id": phase_id,
                "title": "Phase",
                "status": "building",
                "tasks": [],
                "review": {
                    "status": "fixing",
                    "verdict": "BLOCK",
                    "sha_at_review": "abc",
                    "issues": issues,
                },
            }
        ],
    }


def test_normalize_rewrites_sequential_headings(tmp_workspace):
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text(
        "## Issue 1\nDetails for first.\n\n## Issue 2\nDetails for second.\n",
        encoding="utf-8",
    )
    state = _state_for_normalize(2, ["2.1", "2.2"])
    _normalize_review_report_ids(state, 2)

    content = report.read_text(encoding="utf-8")
    assert "## 2.1" in content
    assert "## 2.2" in content
    assert "## Issue 1" not in content
    assert "## Issue 2" not in content


def test_normalize_preserves_heading_suffix(tmp_workspace):
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text(
        "## Issue 1 [CRITICAL] — Functionality\nDetails.\n",
        encoding="utf-8",
    )
    state = _state_for_normalize(3, ["3.1"])
    _normalize_review_report_ids(state, 3)

    assert "## 3.1 [CRITICAL] — Functionality" in report.read_text(encoding="utf-8")


def test_normalize_count_mismatch_renames_by_position(tmp_workspace):
    # 1 bare heading but 2 issues: seq=1 maps to all_issues[0] → renamed, no error raised
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("## Issue 1\nDetails.\n", encoding="utf-8")

    state = _state_for_normalize(2, ["2.1", "2.2"])
    _normalize_review_report_ids(state, 2)

    content = report.read_text(encoding="utf-8")
    assert "## 2.1" in content
    assert "## Issue 1" not in content


def test_normalize_missing_report_is_noop():
    state = _state_for_normalize(1, ["1.1"])
    _normalize_review_report_ids(state, 1)  # file absent — must not raise


def test_normalize_rewrites_bare_headings_regardless_of_status(tmp_workspace):
    # Bare headings are normalized even when all issues are already fixed, because
    # _reconcile_review_report removes fixed sections before this function runs in
    # practice; here we verify the function itself normalizes any bare ID it finds.
    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("## Issue 1\nDetails.\n", encoding="utf-8")

    state = _state_for_normalize(1, ["1.1"], statuses=["fixed"])
    _normalize_review_report_ids(state, 1)

    content = report.read_text(encoding="utf-8")
    assert "## 1.1" in content
    assert "## Issue 1" not in content


# --- _is_excluded_path ---


def test_is_excluded_path_matches_claude_subpath():
    from fix import _is_excluded_path

    assert _is_excluded_path(".claude/hooks/foo.py:10", [".claude", "harness"])


def test_is_excluded_path_matches_exact_filename():
    from fix import _is_excluded_path

    assert _is_excluded_path("CLAUDE.md", ["CLAUDE.md", "README.md"])


def test_is_excluded_path_no_match_for_src():
    from fix import _is_excluded_path

    assert not _is_excluded_path("src/api/users.py:41", [".claude", "harness", "docs"])


def test_is_excluded_path_no_partial_prefix_match():
    from fix import _is_excluded_path

    # "harness_extra/foo.py" should NOT match exclude path "harness"
    assert not _is_excluded_path("harness_extra/foo.py", ["harness"])


# --- _skip_excluded_issues ---


def _make_issue(issue_id: str, file: str, severity: str = "HIGH") -> dict:
    return {
        "id": issue_id,
        "severity": severity,
        "dimension": "Security",
        "file": file,
        "title": "Test issue",
        "status": "open",
        "attempts": 0,
        "files_changed": [],
        "fixed_sha": None,
        "last_error": [],
    }


def test_skip_excluded_issues_defers_protected_file(tmp_workspace):
    from fix import _skip_excluded_issues

    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["file"] = ".claude/hooks/foo.py:10"
    state_mod.save_state(state)

    result = _skip_excluded_issues(
        state["phases"][0]["review"]["issues"],
        [".claude", "harness"],
        state,
        phase_id=1,
    )

    assert result == []
    assert state["phases"][0]["review"]["issues"][0]["status"] == "deferred"


def test_skip_excluded_issues_passes_through_deliverable(tmp_workspace):
    from fix import _skip_excluded_issues

    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["file"] = "src/api/users.py:20"
    state_mod.save_state(state)

    result = _skip_excluded_issues(
        state["phases"][0]["review"]["issues"],
        [".claude", "harness"],
        state,
        phase_id=1,
    )

    assert len(result) == 1
    assert state["phases"][0]["review"]["issues"][0]["status"] == "open"


def test_skip_excluded_issues_empty_excludes_noop(tmp_workspace):
    from fix import _skip_excluded_issues

    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["file"] = ".claude/hooks/foo.py"
    state_mod.save_state(state)

    issues = state["phases"][0]["review"]["issues"]
    result = _skip_excluded_issues(issues, [], state, phase_id=1)

    assert result == issues


# --- _purge_excluded_from_tech_debt ---


def test_purge_excluded_from_tech_debt_removes_protected(tmp_workspace):
    from cleanup import _purge_excluded_from_tech_debt

    debt = tmp_workspace / "workspace" / "tech_debt.jsonl"
    kept_issue = _make_issue("1.1", "src/app.py:5", "MEDIUM")
    removed_issue = _make_issue("1.2", ".claude/hooks/foo.py:10", "MEDIUM")
    debt.write_text(
        json.dumps(kept_issue) + "\n" + json.dumps(removed_issue) + "\n",
        encoding="utf-8",
    )

    _purge_excluded_from_tech_debt([".claude", "harness"])

    lines = [
        line for line in debt.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "1.1"


def test_purge_excluded_from_tech_debt_noop_when_no_file(tmp_workspace):
    from cleanup import _purge_excluded_from_tech_debt

    # Should not raise if tech_debt.jsonl does not exist
    _purge_excluded_from_tech_debt([".claude"])


# --- _fixable_deferred ---


def test_fixable_deferred_filters_excluded(tmp_workspace):
    from cleanup import _fixable_deferred

    state = _state_with_issues(["MEDIUM", "MEDIUM"])
    state["phases"][0]["review"]["issues"][0]["status"] = "deferred"
    state["phases"][0]["review"]["issues"][0]["file"] = ".claude/hooks/foo.py"
    state["phases"][0]["review"]["issues"][1]["status"] = "deferred"
    state["phases"][0]["review"]["issues"][1]["file"] = "src/app.py"
    state_mod.save_state(state)

    result = _fixable_deferred(state, [".claude"])
    assert len(result) == 1
    assert result[0]["file"] == "src/app.py"


# --- run_fix_cycle with excluded path ---


def test_run_fix_cycle_defers_excluded_path_issue(
    sample_config, monkeypatch, tmp_workspace
):
    """Issues whose file is in review_exclude_paths are deferred, not sent to FIX agent."""
    harness = _make_harness(sample_config)
    harness.profile_for.return_value["review_exclude_paths"] = [".claude", "harness"]

    state = _state_with_issues(["HIGH"])
    state["phases"][0]["review"]["issues"][0]["file"] = ".claude/hooks/foo.py:10"
    state_mod.save_state(state)

    report = tmp_workspace / "workspace" / "review_report.md"
    report.write_text("## 1.1 Hook issue\nDetails.", encoding="utf-8")

    fix_called = [False]

    monkeypatch.setattr(
        agents, "fix_issues", lambda *a, **kw: fix_called.__setitem__(0, True)
    )

    run_fix_cycle(harness, state, 1)

    assert not fix_called[0]
    assert state["phases"][0]["review"]["issues"][0]["status"] == "deferred"
    assert state["phases"][0]["review"]["status"] == "fixed"
