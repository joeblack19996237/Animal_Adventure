from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_docs_reference_review_error_state():
    text = _text("harness/docs/08-state-schema.md") + _text(
        "harness/docs/05-harness-py.md"
    )
    assert 'review.status="error"' in text
    assert "review.last_error" in text
    assert "REVIEWING" in text


def test_docs_reference_events_jsonl_and_harness_log():
    text = _text("README.md") + _text("harness/docs/05-harness-py.md")
    assert "workspace/events.jsonl" in text
    assert "workspace/harness.log" in text


def test_docs_reference_run_lock_and_pid():
    text = _text("README.md") + _text("harness/docs/05-harness-py.md")
    assert "workspace/run.lock" in text
    assert "workspace/harness.pid" in text


def test_docs_reference_pre_post_commit_gate():
    text = _text("harness/docs/09-hooks.md") + _text(
        "harness/docs/10-completion-criteria.md"
    )
    assert "pre/post git snapshot gate" in text
    assert "signal-listed safe paths" in text


def test_docs_state_e2e_targets_harness_not_fixture_app():
    text = _text("README.md") + _text("harness/docs/02-spec-format.md")
    assert "validate the harness" in text
    assert "not generated fixture app completeness" in text


def test_readme_runtime_files_include_new_artifacts():
    text = _text("README.md")
    for artifact in [
        "workspace/events.jsonl",
        "workspace/harness.log",
        "workspace/run.lock",
        "workspace/harness.pid",
    ]:
        assert artifact in text


def test_reviewer_docs_reference_targeted_rereview():
    text = _text(".claude/agents/reviewer.md")
    assert "targeted re-review" in text
    assert "no re-review" not in text


def test_evaluator_docs_prioritize_evaluate_app_type():
    text = _text(".claude/agents/evaluator.md")
    assert "evaluate.app_type" in text
    assert "top-level `app_type`" in text
    assert "authoritative" in text


def test_evaluator_docs_restrict_writes_to_artifacts():
    text = _text(".claude/agents/evaluator.md")
    assert "workspace/rubric-report.md" in text
    assert "workspace/screenshots/**" in text
    assert "workspace/eval_playwright.py" in text
    assert "Do not write source files" in text
    assert "workspace/state.json" in text
    assert "harness code" in text


def test_evaluator_docs_forbid_playwright_install_and_inline_python():
    text = _text(".claude/agents/evaluator.md")
    assert "Do not install Playwright" in text
    assert "Do not use inline `python -c`" in text


def test_evaluator_docs_use_eval_services_for_startup_and_cleanup():
    text = _text(".claude/agents/evaluator.md")
    assert "python harness/eval_services.py start-api" in text
    assert "python harness/eval_services.py start-vite" in text
    assert "python harness/eval_services.py start-nginx" in text
    assert "python harness/eval_services.py check-nginx" in text
    assert "python harness/eval_services.py cleanup" in text


def test_docs_reference_evaluate_error_statuses():
    text = (
        _text("README.md")
        + _text("CLAUDE.md")
        + _text("harness/docs/08-state-schema.md")
    )
    assert 'evaluate.status="blocked_external_dependency"' in text
    assert 'evaluate.status="timeout"' in text
    assert 'evaluate.status="error"' in text


def test_docs_reference_parseable_429_wait_retry():
    text = _text("harness/docs/05-harness-py.md") + _text(
        "harness/docs/06-agents-py.md"
    )
    assert "parseable Claude 429 reset time" in text
    assert "external_dependency_wait_start" in text
    assert "external_dependency_wait_end" in text
    assert "external_dependency_context.json" in text
    assert "external_dependency_artifacts" in text


def test_docs_reference_session_pacing_not_token_budget():
    text = (
        _text("README.md")
        + _text("CLAUDE.md")
        + _text("harness/docs/06-agents-py.md")
        + _text("harness/docs/07-calibrate-lang-py.md")
    )
    assert "claude_session_pacing" in text
    assert "not a token budget" in text or "not a fixed Claude token budget" in text
    assert "effective_token_budget" in text


def test_docs_reference_unit_test_local_verification():
    text = _text("README.md") + _text("CLAUDE.md") + _text(
        "harness/docs/08-state-schema.md"
    )
    assert 'tdd_mode="unit_test"' in text
    assert "verified locally by the harness" in text


def test_docs_reference_external_dependency_clean_resume():
    text = _text("README.md") + _text("CLAUDE.md") + _text(
        "harness/docs/08-state-schema.md"
    )
    assert "External Dependency Resume Cleanliness" in text
    assert "process tree" in text
    assert "--resume" in text


def test_docs_reference_review_untracked_status_check():
    text = _text("harness/docs/06-agents-py.md")
    assert "git status --short" in text
    assert "untracked" in text


def test_docs_reference_setup_phase_tdd_modes():
    text = _text("harness/docs/05-harness-py.md") + _text(
        ".claude/agents/builder.md"
    )
    assert "setup phase may use normal TDD modes" in text
    assert "exempt setup tasks still require `tdd_skipped`" in text


def test_docs_reference_artifact_quality_gate():
    text = _text("harness/docs/05-harness-py.md")
    assert "artifact quality gate" in text
    assert "UTF-8 without BOM" in text
    assert "UTF-16" in text
    assert "NUL" in text


def test_docs_reference_fix_fallback_commit_and_failure_log():
    text = _text("harness/docs/05-harness-py.md")
    assert "fallback commit" in text
    assert "workspace/fix_test_failure.log" in text
    assert "signal-listed fix files" in text


def test_agent_docs_reference_utf8_no_bom_text_artifacts():
    text = (
        _text(".claude/agents/builder.md")
        + _text(".claude/agents/reviewer.md")
        + _text("harness/docs/06-agents-py.md")
    )
    assert "UTF-8 without BOM" in text
    assert "UTF-16" in text
    assert "NUL-byte" in text or "NUL bytes" in text


def test_builder_docs_reference_existing_tracked_noop_signal():
    text = _text(".claude/agents/builder.md") + _text(
        "harness/docs/03-agent-code-builder.md"
    )
    assert "already satisfied by existing tracked files" in text
    assert "empty no-op signal" in text
    assert "files_changed" in text
    assert "tdd_skipped" in text


def test_docs_reference_status_current_vs_historical_error():
    text = _text("README.md") + _text("harness/docs/05-harness-py.md")
    assert "historical_last_error" in text
    assert "current blocker/error" in text


def test_docs_reference_evaluate_score_and_early_stop():
    text = (
        _text("README.md")
        + _text("harness/docs/07-calibrate-lang-py.md")
        + _text("harness/docs/08-state-schema.md")
        + _text("harness/docs/09-hooks.md")
    )
    assert "evaluate_early_stop_on_full_score" in text
    assert '"score"' in text
    assert '"total"' in text
    assert '"max"' in text


def test_evaluator_docs_include_animal_adventure_game_criteria():
    text = _text(".claude/agents/evaluator.md")
    for marker in [
        "canvas is visible and non-empty",
        "/assets/images/MapTiles/",
        "game_map_full.png",
        "name-only login",
        "state_sync",
        "server-authoritative movement bounds",
        "quest accept, pickup, turn-in",
        "backend restart persistence",
        "backend tracebacks",
        "Nginx routes frontend",
        "webkit-ipad",
        "touch joystick",
        "npm run test:e2e:nginx",
        "workspace/eval-services/eval.sqlite3",
        "workspace/eval-services/api.log",
        "workspace/eval-services/nginx-error.log",
        "Production entrypoint integrity",
    ]:
        assert marker in text
    assert "phase 16" not in text.lower()


def test_builder_and_reviewer_docs_preserve_assets_and_config():
    text = (
        _text(".claude/rules/common/coding-guidelines.md")
        + _text(".claude/agents/builder.md")
        + _text(".claude/agents/reviewer.md")
    )
    assert "Preserve existing `assets/` and `config/`" in text
    assert "overwrite" in text
    assert "regenerate" in text
    assert "targeted config update" in text


def test_builder_docs_protect_assets_and_target_config_only():
    text = _text(".claude/agents/builder.md")
    assert "Treat `assets/**` as read-only" in text
    assert "Only edit `config/**`" in text


def test_builder_docs_use_gitkeep_for_empty_scaffold_dirs():
    text = _text(".claude/agents/builder.md") + _text("docs/build-plan.md")
    assert ".gitkeep" in text


def test_each_build_plan_phase_has_ref_line():
    text = _text("docs/build-plan.md")
    sections = [s for s in text.split("\n## Phase ") if s.strip()]
    phase_sections = [s for s in sections if s[0].isdigit()]
    assert phase_sections
    assert all("**Ref:**" in section for section in phase_sections)


def test_build_plan_requires_playwright_preflight_not_install():
    text = _text("docs/build-plan.md")
    assert "Preflight Chromium availability" in text
    assert "npx playwright install chromium" not in text


def test_test_plan_mentions_tooling_config_files():
    text = _text("docs/test-plan.md")
    for marker in ["tsconfig.json", "vite.config.ts", "playwright.config.ts"]:
        assert marker in text


def test_pytest_ini_registers_e2e_marks():
    text = _text("pytest.ini")
    assert "e2e:" in text
    assert "live_e2e:" in text


def test_evaluator_docs_require_service_cleanup():
    text = _text(".claude/agents/evaluator.md")
    assert "harness/eval_services.py" in text
    assert "finally" in text
    assert "process tree" in text


def test_animal_build_plan_has_no_mixed_implementation_phase_titles():
    text = _text("docs/build-plan.md")
    for line in text.splitlines():
        if not line.startswith("## Phase "):
            continue
        lower = line.lower()
        if "integration" in lower or "e2e" in lower:
            continue
        assert not ("python" in lower and "typescript" in lower), line
