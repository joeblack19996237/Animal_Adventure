import json
from pathlib import Path

import pytest

from calibrate import (
    get_claude_session_pacing,
    get_evaluation_min_score_pct,
    get_evaluate_early_stop_on_full_score,
    get_external_dependency_config,
    get_game_quick_smoke_phase_ids,
    get_max_evaluate_iterations,
    validate_config,
)

_HARNESS_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_default_config_has_timeout_policy():
    config = json.loads((_HARNESS_ROOT / "config.json").read_text(encoding="utf-8"))
    assert "timeout_policy" in config
    assert "REVIEW" in config["timeout_policy"]


def test_config_has_animal_adventure_defaults():
    config = json.loads((_HARNESS_ROOT / "config.json").read_text(encoding="utf-8"))
    assert config["default_language"] == "python"
    assert config["default_app_type"] == "game"
    assert config["default_spec_path"] == "docs"
    assert config["subprocess_timeout"]["EVALUATE"] == 2400
    assert config["subprocess_timeout"]["EVALUATE_TESTS"] == 900
    assert config["subprocess_timeout"]["FIX"] == 900
    assert config["verification_timeout"] == 900
    assert get_evaluation_min_score_pct(config) == 0.9
    assert "cleanup_fix_deferred_issues" not in config
    assert get_game_quick_smoke_phase_ids(config) == [5, 8, 11, 14, 16]


def test_sample_config_matches_required_keys(sample_config):
    for key in [
        "subprocess_timeout",
        "timeout_policy",
        "max_attempts",
        "verify_fail_escalation",
    ]:
        assert key in sample_config


def test_config_accepts_evaluate_iterations_1_to_3(sample_config):
    for value in (1, 2, 3):
        config = {**sample_config, "max_evaluate_iterations": value}
        validate_config(config)
        assert get_max_evaluate_iterations(config) == value


def test_config_rejects_evaluate_iterations_above_hook_cap(sample_config):
    config = {**sample_config, "max_evaluate_iterations": 4}
    with pytest.raises(ValueError, match="max_evaluate_iterations"):
        validate_config(config)


def test_config_accepts_evaluate_early_stop_boolean(sample_config):
    for value in (True, False):
        config = {**sample_config, "evaluate_early_stop_on_full_score": value}
        validate_config(config)
        assert get_evaluate_early_stop_on_full_score(config) is value


def test_config_rejects_non_boolean_evaluate_early_stop(sample_config):
    config = {**sample_config, "evaluate_early_stop_on_full_score": "yes"}
    with pytest.raises(ValueError, match="evaluate_early_stop_on_full_score"):
        validate_config(config)


def test_config_rejects_invalid_evaluation_min_score_pct(sample_config):
    config = {**sample_config, "evaluation_min_score_pct": 1.5}
    with pytest.raises(ValueError, match="evaluation_min_score_pct"):
        validate_config(config)


def test_config_accepts_game_quick_smoke_phase_ids(sample_config):
    config = {**sample_config, "game_quick_smoke_phase_ids": [5, 8]}
    validate_config(config)
    assert get_game_quick_smoke_phase_ids(config) == [5, 8]


def test_default_config_has_claude_session_pacing():
    config = json.loads((_HARNESS_ROOT / "config.json").read_text(encoding="utf-8"))
    pacing = get_claude_session_pacing(config)
    assert pacing["enabled"] is True
    assert pacing["usage_window_seconds"] == 18000


def test_default_config_has_external_dependency_wait_limit():
    config = json.loads((_HARNESS_ROOT / "config.json").read_text(encoding="utf-8"))
    settings = get_external_dependency_config(config)
    assert settings["max_in_process_wait_seconds"] == 900


def test_config_rejects_invalid_external_dependency_wait_limit(sample_config):
    config = {
        **sample_config,
        "external_dependency": {"max_in_process_wait_seconds": -1},
    }
    with pytest.raises(ValueError, match="external_dependency"):
        validate_config(config)


def test_config_rejects_invalid_claude_session_pacing_values(sample_config):
    config = {
        **sample_config,
        "claude_session_pacing": {"min_seconds_between_calls": -1},
    }
    with pytest.raises(ValueError, match="claude_session_pacing"):
        validate_config(config)


def test_config_rejects_invalid_claude_session_pacing_type(sample_config):
    config = {**sample_config, "claude_session_pacing": []}
    with pytest.raises(ValueError, match="claude_session_pacing"):
        validate_config(config)


def test_config_does_not_duplicate_typescript_profile_defaults():
    config = json.loads((_HARNESS_ROOT / "config.json").read_text(encoding="utf-8"))
    overrides = config.get("profile_overrides", {}).get("typescript", {})
    assert "compile_cmd" not in overrides
    assert "test_cmd" not in overrides
    assert "integration_test_cmd" not in overrides


def test_builder_settings_ts_hook_timeout_exceeds_internal_tool_budget():
    settings = json.loads(
        (_REPO_ROOT / ".claude/settings.builder.json").read_text(encoding="utf-8")
    )
    hooks = settings["hooks"]["PostToolUse"]
    ts_hooks = [
        hook
        for hook in hooks
        if hook.get("id") in {"post:write:ts-lint-format", "post:edit:ts-lint-format"}
    ]

    assert len(ts_hooks) == 2
    assert all(hook["hooks"][0]["timeout_ms"] >= 35000 for hook in ts_hooks)


def _settings(path: str) -> dict:
    return json.loads((_REPO_ROOT / path).read_text(encoding="utf-8"))


def test_mode_settings_include_permissions_block():
    for path in [
        ".claude/settings.builder.json",
        ".claude/settings.reviewer.json",
        ".claude/settings.evaluator.json",
    ]:
        settings = _settings(path)
        assert "permissions" in settings
        assert settings["permissions"]["allow"]
        assert "Bash(curl*)" in settings["permissions"]["deny"]


def test_builder_settings_allow_git_commit_hook_commands():
    allow = set(_settings(".claude/settings.builder.json")["permissions"]["allow"])
    assert "Bash(git add*)" in allow
    assert "Bash(git commit*)" in allow
    assert "Write(**)" not in allow
    assert "Edit(**)" not in allow


def test_builder_settings_allow_required_project_write_paths():
    allow = set(_settings(".claude/settings.builder.json")["permissions"]["allow"])
    for permission in [
        "Write(app/**)",
        "Edit(app/**)",
        "Write(src/**)",
        "Edit(src/**)",
        "Write(tests/**)",
        "Edit(tests/**)",
        "Write(deploy/**)",
        "Edit(deploy/**)",
        "Write(data/.gitkeep)",
        "Write(logs/.gitkeep)",
        "Write(config/**)",
        "Edit(config/**)",
        "Write(playwright.config.ts)",
        "Edit(playwright.config.ts)",
    ]:
        assert permission in allow


def test_builder_settings_do_not_allow_asset_write():
    allow = set(_settings(".claude/settings.builder.json")["permissions"]["allow"])
    assert "Write(assets/**)" not in allow
    assert "Edit(assets/**)" not in allow


def test_reviewer_settings_do_not_allow_general_write_or_edit():
    allow = set(_settings(".claude/settings.reviewer.json")["permissions"]["allow"])
    assert "Write(**)" not in allow
    assert "Edit(**)" not in allow
    assert "Write(workspace/review_report.md)" in allow


def test_evaluator_settings_do_not_allow_general_write_or_edit():
    allow = set(_settings(".claude/settings.evaluator.json")["permissions"]["allow"])
    assert "Write(**)" not in allow
    assert "Edit(**)" not in allow


def test_evaluator_settings_allow_evaluation_artifact_writes():
    allow = set(_settings(".claude/settings.evaluator.json")["permissions"]["allow"])
    assert "Write(workspace/rubric-report.md)" in allow
    assert "Write(workspace/screenshots/**)" in allow
    assert "Write(workspace/eval_playwright.py)" in allow
    assert "Write(workspace/eval_http.py)" in allow
    assert "Write(workspace/eval_db.py)" in allow
    assert "Write(workspace/eval_ws.py)" in allow


def test_evaluator_settings_allow_eval_script_execution():
    allow = set(_settings(".claude/settings.evaluator.json")["permissions"]["allow"])
    assert "Bash(python workspace/eval_playwright.py*)" in allow
    assert "Bash(python workspace/eval_http.py*)" in allow
    assert "Bash(python workspace/eval_db.py*)" in allow
    assert "Bash(python workspace/eval_ws.py*)" in allow


def test_builder_settings_allow_root_npm_and_uvicorn_commands():
    allow = set(_settings(".claude/settings.builder.json")["permissions"]["allow"])
    for command in [
        "Bash(npm install*)",
        "Bash(npm run typecheck*)",
        "Bash(npm test*)",
        "Bash(npm run build*)",
        "Bash(npm run test:e2e*)",
        "Bash(npx playwright*)",
        "Bash(python -m uvicorn*)",
        "Bash(uvicorn*)",
    ]:
        assert command in allow


def test_evaluator_settings_allow_root_npm_uvicorn_and_service_cleanup():
    allow = set(_settings(".claude/settings.evaluator.json")["permissions"]["allow"])
    for command in [
        "Bash(npm install*)",
        "Bash(npm run typecheck*)",
        "Bash(npm test*)",
        "Bash(npm run build*)",
        "Bash(npm run test:e2e*)",
        "Bash(npx playwright*)",
        "Bash(python -m uvicorn*)",
        "Bash(uvicorn*)",
        "Bash(python harness/eval_services.py cleanup*)",
    ]:
        assert command in allow


def test_evaluator_settings_allow_eval_service_start_and_check_commands():
    allow = set(_settings(".claude/settings.evaluator.json")["permissions"]["allow"])
    for command in [
        "Bash(python harness/eval_services.py start-api*)",
        "Bash(python harness/eval_services.py start-vite*)",
        "Bash(python harness/eval_services.py start-nginx*)",
        "Bash(python harness/eval_services.py check-nginx*)",
        "Bash(python harness/eval_services.py cleanup*)",
    ]:
        assert command in allow


def test_gitignore_contains_runtime_outputs_without_source_dirs():
    lines = set((_REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    for pattern in [
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        "dist/",
        "logs/",
        "data/*.sqlite3",
        "data/*.db",
        "playwright-report/",
        "test-results/",
        "workspace/",
    ]:
        assert pattern in lines
    assert "assets/" not in lines
    assert "config/" not in lines
    assert "docs/" not in lines
