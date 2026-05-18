import copy


LANGUAGE_PROFILES = {
    "python": {
        "name": "python",
        "compile_cmd": ["python", "-m", "py_compile", "{file}"],
        "compile_extensions": ["*.py"],
        "test_cmd": ["pytest", "--ignore=harness", "--asyncio-mode=auto"],
        "integration_test_cmd": [
            "pytest",
            "--ignore=harness",
            "-m",
            "integration",
            "--asyncio-mode=auto",
        ],
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
    },
    "typescript": {
        "name": "typescript",
        "compile_cmd": ["npm", "run", "typecheck"],
        "compile_extensions": ["*.ts", "*.tsx"],
        "test_cmd": ["npm", "test"],
        "integration_test_cmd": ["npm", "run", "test:e2e"],
        "build_model": "claude-haiku-4-5-20251001",
        "execute_model": "claude-sonnet-4-6",
        "builder_agent": ".claude/agents/builder.md",
        "reviewer_agent": ".claude/agents/reviewer.md",
        "builder_guide": ".claude/rules/typescript/typescript-builder-guide.md",
        "reviewer_guide": ".claude/rules/typescript/typescript-review-standards.md",
        "builder_skill": ".claude/skills/tdd-workflow-ts/SKILL.md",
        "reviewer_skill": ".claude/skills/security-review/SKILL.md",
        "common_rules": ".claude/rules/common/coding-standards.md",
        "rules_file": ".claude/rules/typescript/typescript-standards.md",
        "builder_settings": ".claude/settings.builder.json",
        "reviewer_settings": ".claude/settings.reviewer.json",
        "review_exclude_paths": [
            ".claude",
            "harness",
            "harness/docs",
            "CLAUDE.md",
            "README.md",
            "dist/",
            "playwright-report/",
        ],
    },
}


def get_profile(language: str) -> dict:
    profile = LANGUAGE_PROFILES.get(language.lower())
    if not profile:
        raise ValueError(
            f"Unknown language '{language}'. Available: {list(LANGUAGE_PROFILES)}"
        )
    return copy.deepcopy(profile)


def apply_profile_overrides(profile: dict, config: dict | None) -> dict:
    merged = copy.deepcopy(profile)
    overrides = (config or {}).get("profile_overrides", {}).get(profile["name"], {})
    for key, value in overrides.items():
        if key in merged:
            merged[key] = value
    return merged
