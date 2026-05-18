import json

import pytest

CONFIG = {
    "subprocess_timeout": {
        "TASK_BUILD": 120,
        "EXECUTE": 300,
        "REVIEW": 240,
        "FIX": 300,
        "CLEANUP": 300,
        "EVALUATE_TESTS": 300,
        "EVALUATE": 600,
    },
    "max_attempts": 3,
    "verify_fail_escalation": 2,
    "cleanup_fix_deferred_issues": True,
    "timeout_policy": {
        "REVIEW": {
            "min": 480,
            "max": 1200,
            "per_task": 30,
            "per_changed_file": 45,
            "per_diff_line": 0.25,
        }
    },
}


@pytest.fixture
def tmp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness_dir = tmp_path / "harness"
    harness_dir.mkdir()
    (harness_dir / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    return tmp_path


@pytest.fixture
def sample_state():
    return {
        "spec_file": "spec.md",
        "language": "python",
        "initial_sha": "abc123",
        "current_phase": 1,
        "total_phases": 1,
        "phases": [
            {
                "id": 1,
                "title": "Phase One",
                "language": "python",
                "phase_type": "setup",
                "status": "building",
                "tasks": [
                    {
                        "id": "1.1",
                        "title": "Task One",
                        "task_type": "foundation",
                        "description": "Set up the project foundation.",
                        "refs": [],
                        "status": "pending",
                        "attempts": 0,
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
        "last_updated": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def sample_config():
    return dict(CONFIG)


@pytest.fixture
def sample_profile():
    return {
        "name": "python",
        "compile_cmd": ["python", "-m", "py_compile", "{file}"],
        "compile_extensions": ["*.py"],
        "test_cmd": ["pytest"],
        "integration_test_cmd": ["pytest", "-m", "integration"],
        "build_model": "claude-haiku-4-5-20251001",
        "execute_model": "claude-sonnet-4-6",
        "builder_agent": ".claude/agents/builder.md",
        "reviewer_agent": ".claude/agents/reviewer.md",
        "builder_guide": ".claude/rules/python/python-builder-guide.md",
        "reviewer_guide": ".claude/rules/python/python-review-standards.md",
        "builder_skill": ".claude/skills/tdd-workflow/SKILL.md",
        "reviewer_skill": ".claude/skills/security-review/SKILL.md",
        "common_rules": ".claude/rules/common/coding-standards.md",
        "rules_file": ".claude/rules/python/python-standards.md",
        "builder_settings": ".claude/settings.builder.json",
        "reviewer_settings": ".claude/settings.reviewer.json",
        "review_exclude_paths": [
            ".claude",
            "harness",
            "harness/docs",
            "CLAUDE.md",
            "README.md",
        ],
    }
