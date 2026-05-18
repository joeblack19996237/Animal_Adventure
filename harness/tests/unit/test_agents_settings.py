import json

import pytest

import agents
from subprocess_runner import ProcessResult


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)


def _make_subprocess_result(returncode=0, stdout="", stderr=""):
    return ProcessResult(
        stdout=stdout, stderr=stderr, returncode=returncode, elapsed=0.0
    )


def _make_envelope(signal: dict) -> str:
    return json.dumps({"result": json.dumps(signal), "usage": {}})


def _settings_from_cmd(cmd: list) -> str | None:
    try:
        idx = cmd.index("--settings")
        return cmd[idx + 1]
    except (ValueError, IndexError):
        return None


_PYTHON_PROFILE = {
    "name": "python",
    "build_model": "claude-haiku-4-5-20251001",
    "execute_model": "claude-sonnet-4-6",
    "builder_agent": ".claude/agents/builder.md",
    "reviewer_agent": ".claude/agents/reviewer.md",
    "builder_skill": ".claude/skills/tdd-workflow/SKILL.md",
    "reviewer_skill": ".claude/skills/security-review/SKILL.md",
    "common_rules": ".claude/rules/common/coding-standards.md",
    "rules_file": ".claude/rules/python/python-standards.md",
    "builder_guide": ".claude/rules/python/python-builder-guide.md",
    "reviewer_guide": ".claude/rules/python/python-review-standards.md",
    "integration_test_cmd": ["pytest", "-m", "integration"],
    "builder_settings": ".claude/settings.builder.json",
    "reviewer_settings": ".claude/settings.reviewer.json",
    "review_exclude_paths": [],
}

_TS_PROFILE = {
    "name": "typescript",
    "build_model": "claude-haiku-4-5-20251001",
    "execute_model": "claude-sonnet-4-6",
    "builder_agent": ".claude/agents/builder.md",
    "reviewer_agent": ".claude/agents/reviewer.md",
    "builder_skill": ".claude/skills/tdd-workflow/SKILL.md",
    "reviewer_skill": ".claude/skills/security-review/SKILL.md",
    "common_rules": ".claude/rules/common/coding-standards.md",
    "rules_file": ".claude/rules/typescript/typescript-standards.md",
    "builder_guide": ".claude/rules/typescript/typescript-builder-guide.md",
    "reviewer_guide": ".claude/rules/typescript/typescript-review-standards.md",
    "integration_test_cmd": ["npx", "vitest", "run"],
    "builder_settings": ".claude/settings.builder.json",
    "reviewer_settings": ".claude/settings.reviewer.json",
    "review_exclude_paths": [],
}

_PROFILE_WITHOUT_SETTINGS = {
    "name": "legacy",
    "build_model": "claude-haiku-4-5-20251001",
    "execute_model": "claude-sonnet-4-6",
    "builder_agent": ".claude/agents/builder.md",
    "reviewer_agent": ".claude/agents/reviewer.md",
    "builder_skill": ".claude/skills/tdd-workflow/SKILL.md",
    "reviewer_skill": ".claude/skills/security-review/SKILL.md",
    "common_rules": ".claude/rules/common/coding-standards.md",
    "rules_file": ".claude/rules/python/python-standards.md",
    "builder_guide": ".claude/rules/python/python-builder-guide.md",
    "reviewer_guide": ".claude/rules/python/python-review-standards.md",
    "review_exclude_paths": [],
    # intentionally missing builder_settings / reviewer_settings
}


# --- build_tasks ---


def test_build_tasks_python_uses_builder_settings(
    sample_config, sample_state, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": 1,
        "tasks": [{"id": "1.1", "title": "T", "task_type": "foundation"}],
    }
    captured = []

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(signal)),
        )[1],
    )
    agents.build_tasks(
        {"id": 1, "title": "T", "description": "d"},
        "",
        _PYTHON_PROFILE,
        sample_config,
        sample_state,
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


def test_build_tasks_typescript_uses_unified_builder_settings(
    sample_config, sample_state, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": 1,
        "tasks": [{"id": "1.1", "title": "T", "task_type": "foundation"}],
    }
    captured = []

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(signal)),
        )[1],
    )
    agents.build_tasks(
        {"id": 1, "title": "T", "description": "d"},
        "",
        _TS_PROFILE,
        sample_config,
        sample_state,
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


def test_build_tasks_falls_back_to_default_when_key_missing(
    sample_config, sample_state, monkeypatch
):
    signal = {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": 1,
        "tasks": [{"id": "1.1", "title": "T", "task_type": "foundation"}],
    }
    captured = []

    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(signal)),
        )[1],
    )
    agents.build_tasks(
        {"id": 1, "title": "T", "description": "d"},
        "",
        _PROFILE_WITHOUT_SETTINGS,
        sample_config,
        sample_state,
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


# --- execute ---


def _execute_signal() -> dict:
    return {
        "mode": "EXECUTE",
        "phase_id": 1,
        "tasks": [
            {
                "id": "1.1",
                "title": "T",
                "task_type": "backend",
                "status": "complete",
                "files_changed": [],
            }
        ],
    }


def test_execute_python_uses_builder_settings(sample_config, monkeypatch):
    captured = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(_execute_signal())),
        )[1],
    )
    agents.execute(
        [{"id": "1.1", "title": "T", "task_type": "backend"}],
        1,
        _PYTHON_PROFILE,
        sample_config,
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


def test_execute_typescript_uses_unified_builder_settings(sample_config, monkeypatch):
    captured = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(_execute_signal())),
        )[1],
    )
    agents.execute(
        [{"id": "1.1", "title": "T", "task_type": "entity"}],
        1,
        _TS_PROFILE,
        sample_config,
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


def test_execute_falls_back_to_default_when_key_missing(sample_config, monkeypatch):
    captured = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(_execute_signal())),
        )[1],
    )
    agents.execute(
        [{"id": "1.1", "title": "T", "task_type": "backend"}],
        1,
        _PROFILE_WITHOUT_SETTINGS,
        sample_config,
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


# --- review_phase ---


def _review_signal() -> dict:
    return {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": 1,
        "verdict": "APPROVE",
        "sha_at_review": "abc123",
        "issues": [],
    }


def test_review_phase_python_uses_reviewer_settings(sample_config, monkeypatch):
    captured = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(_review_signal())),
        )[1],
    )
    agents.review_phase(1, "abc1234", ["spec.md"], _PYTHON_PROFILE, sample_config)
    assert _settings_from_cmd(captured[0]) == ".claude/settings.reviewer.json"


def test_review_phase_typescript_uses_reviewer_settings(sample_config, monkeypatch):
    captured = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(_review_signal())),
        )[1],
    )
    agents.review_phase(1, "abc1234", ["spec.md"], _TS_PROFILE, sample_config)
    assert _settings_from_cmd(captured[0]) == ".claude/settings.reviewer.json"


def test_review_phase_falls_back_to_default_when_key_missing(
    sample_config, monkeypatch
):
    captured = []
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(_review_signal())),
        )[1],
    )
    agents.review_phase(
        1, "abc1234", ["spec.md"], _PROFILE_WITHOUT_SETTINGS, sample_config
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.reviewer.json"


# --- fix_issues ---


def test_fix_issues_python_uses_builder_settings(sample_config, monkeypatch):
    captured = []
    signal = {"mode": "FIX", "fixes": []}
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(signal)),
        )[1],
    )
    agents.fix_issues("workspace/review_report.md", _PYTHON_PROFILE, sample_config)
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


def test_fix_issues_typescript_uses_unified_builder_settings(
    sample_config, monkeypatch
):
    captured = []
    signal = {"mode": "FIX", "fixes": []}
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(signal)),
        )[1],
    )
    agents.fix_issues("workspace/review_report.md", _TS_PROFILE, sample_config)
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"


def test_fix_issues_falls_back_to_default_when_key_missing(sample_config, monkeypatch):
    captured = []
    signal = {"mode": "FIX", "fixes": []}
    monkeypatch.setattr(
        agents,
        "run_claude_process",
        lambda cmd, *args, **_: (
            captured.append(list(cmd)),
            _make_subprocess_result(stdout=_make_envelope(signal)),
        )[1],
    )
    agents.fix_issues(
        "workspace/review_report.md", _PROFILE_WITHOUT_SETTINGS, sample_config
    )
    assert _settings_from_cmd(captured[0]) == ".claude/settings.builder.json"
