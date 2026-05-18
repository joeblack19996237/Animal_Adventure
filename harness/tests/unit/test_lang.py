import pytest

from lang import LANGUAGE_PROFILES, apply_profile_overrides, get_profile

REQUIRED_KEYS = {
    "name",
    "compile_cmd",
    "compile_extensions",
    "test_cmd",
    "integration_test_cmd",
    "build_model",
    "execute_model",
    "builder_agent",
    "reviewer_agent",
    "builder_guide",
    "reviewer_guide",
    "builder_skill",
    "reviewer_skill",
    "common_rules",
    "rules_file",
    "builder_settings",
    "reviewer_settings",
    "review_exclude_paths",
}


# --- profile registry ---


def test_both_profiles_registered():
    assert set(LANGUAGE_PROFILES.keys()) == {"python", "typescript"}


def test_get_profile_python_returns_correct_profile():
    assert get_profile("python")["name"] == "python"


def test_get_profile_typescript_returns_correct_profile():
    assert get_profile("typescript")["name"] == "typescript"


def test_get_profile_is_case_insensitive():
    assert get_profile("Python")["name"] == "python"
    assert get_profile("TypeScript")["name"] == "typescript"


def test_get_profile_unknown_language_raises_value_error():
    with pytest.raises(ValueError, match="Unknown language"):
        get_profile("ruby")


def test_get_profile_error_message_lists_available_languages():
    with pytest.raises(ValueError, match="python"):
        get_profile("unknown")


# --- required keys ---


def test_python_profile_has_all_required_keys():
    missing = REQUIRED_KEYS - set(get_profile("python").keys())
    assert not missing, f"Missing keys: {missing}"


def test_typescript_profile_has_all_required_keys():
    missing = REQUIRED_KEYS - set(get_profile("typescript").keys())
    assert not missing, f"Missing keys: {missing}"


# --- Python profile values ---


def test_python_test_cmd_includes_asyncio_mode():
    assert "--asyncio-mode=auto" in get_profile("python")["test_cmd"]


def test_python_uses_python_security_skill():
    assert (
        get_profile("python")["reviewer_skill"]
        == ".claude/skills/security-review/SKILL.md"
    )


def test_python_uses_python_rules_file():
    assert "python" in get_profile("python")["rules_file"]


def test_python_builder_settings_points_to_builder_json():
    assert get_profile("python")["builder_settings"] == ".claude/settings.builder.json"


def test_python_reviewer_settings_points_to_reviewer_json():
    assert (
        get_profile("python")["reviewer_settings"] == ".claude/settings.reviewer.json"
    )


# --- TypeScript profile values ---


def test_typescript_uses_typescript_rules_file():
    assert "typescript" in get_profile("typescript")["rules_file"]


def test_typescript_uses_unified_security_skill():
    assert (
        get_profile("typescript")["reviewer_skill"]
        == ".claude/skills/security-review/SKILL.md"
    )


def test_typescript_reviewer_settings_same_as_python():
    assert (
        get_profile("typescript")["reviewer_settings"]
        == get_profile("python")["reviewer_settings"]
    )


def test_typescript_compile_cmd_uses_tsc_no_emit():
    cmd = get_profile("typescript")["compile_cmd"]
    assert cmd == ["npm", "run", "typecheck"]


def test_typescript_review_excludes_dist_and_playwright_report():
    excludes = get_profile("typescript")["review_exclude_paths"]
    assert "dist/" in excludes
    assert "playwright-report/" in excludes


# --- Gate 2: new keys and values ---


def test_python_profile_has_integration_test_cmd():
    cmd = get_profile("python")["integration_test_cmd"]
    assert "pytest" in cmd
    assert "-m" in cmd
    assert "integration" in cmd


def test_typescript_profile_has_integration_test_cmd():
    cmd = get_profile("typescript")["integration_test_cmd"]
    assert cmd == ["npm", "run", "test:e2e"]


def test_typescript_profile_test_cmd_is_vitest_not_playwright():
    cmd = get_profile("typescript")["test_cmd"]
    assert cmd == ["npm", "test"]
    assert "playwright" not in " ".join(cmd)


def test_both_profiles_use_builder_md():
    assert get_profile("python")["builder_agent"] == ".claude/agents/builder.md"
    assert get_profile("typescript")["builder_agent"] == ".claude/agents/builder.md"


def test_both_profiles_use_reviewer_md():
    assert get_profile("python")["reviewer_agent"] == ".claude/agents/reviewer.md"
    assert get_profile("typescript")["reviewer_agent"] == ".claude/agents/reviewer.md"


def test_both_profiles_have_builder_guide_key():
    assert "builder_guide" in get_profile("python")
    assert "python-builder-guide" in get_profile("python")["builder_guide"]
    assert "builder_guide" in get_profile("typescript")
    assert "typescript-builder-guide" in get_profile("typescript")["builder_guide"]


def test_both_profiles_have_reviewer_guide_key():
    assert "reviewer_guide" in get_profile("python")
    assert "python-review-standards" in get_profile("python")["reviewer_guide"]
    assert "reviewer_guide" in get_profile("typescript")
    assert "typescript-review-standards" in get_profile("typescript")["reviewer_guide"]


def test_task_types_not_in_profiles():
    assert "task_types" not in get_profile("python")
    assert "task_types" not in get_profile("typescript")


def test_typescript_uses_unified_settings_builder_json():
    assert (
        get_profile("typescript")["builder_settings"] == ".claude/settings.builder.json"
    )


def test_apply_profile_overrides_replaces_typescript_commands():
    profile = get_profile("typescript")
    config = {
        "profile_overrides": {
            "typescript": {
                "compile_cmd": ["npm", "run", "typecheck"],
                "test_cmd": ["npm", "test"],
                "integration_test_cmd": ["npm", "run", "test:e2e"],
            }
        }
    }
    merged = apply_profile_overrides(profile, config)
    assert merged["compile_cmd"] == ["npm", "run", "typecheck"]
    assert merged["test_cmd"] == ["npm", "test"]
    assert merged["integration_test_cmd"] == ["npm", "run", "test:e2e"]
    assert get_profile("typescript")["compile_cmd"] == ["npm", "run", "typecheck"]
