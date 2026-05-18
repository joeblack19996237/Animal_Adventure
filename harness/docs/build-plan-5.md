# Build Plan — Autonomous Dev Harness V1

---

## Prerequisites

Before development starts, ensure the following are in place:

- **Python 3.10+** installed and on PATH
- **`claude` CLI** installed and on PATH (`claude --version` confirms)
- **Claude Pro subscription** — required for E2E tests (auth via Claude Code session)
- **Git** installed and on PATH
- **Claude Code** opened in the project directory (establishes OAuth auth context for `claude -p`)
- **Dev dependencies**: `pip install pytest pytest-mock jsonschema` (add to `harness/requirements.txt`)
- **Design docs read in full**: `docs/01-overview.md` through `docs/12-verification.md`

---

## Phase 10: Verification

**Dependency:** All of Phases 1–9 complete.

---

### Phase 10A: Unit Tests

#### Task 10A.1: `tests/conftest.py` and test fixtures
Shared fixtures: `tmp_workspace` (temp dir with `state.json`, `usage.jsonl`), `sample_state` (minimal valid state dict), `sample_config` (mirrors `config.json`), `sample_profile` (Python LanguageProfile). Used across all unit test modules.
```
[x]
```
**Ref:** `docs/08-state-schema.md`, `docs/07-calibrate-lang-py.md`

---

#### Task 10A.2: `tests/unit/test_state.py`
- `test_save_state_atomic`: verify `.tmp` file created then replaced; state.json intact if `.tmp` write interrupted
- `test_save_state_id_correction`: malformed task id corrected to `"{phase_id}.{seq}"`; `[WARN]` printed
- `test_update_state_task`: kwargs applied to correct task by id
- `test_update_state_issue`: kwargs applied to correct issue by id
- `test_halt_task`: status → `"halted"`, `sys.exit(1)` called
- `test_error_task`: status → `"error"`, reason appended to `last_error`, `sys.exit(1)`
- `test_halt_issue` / `test_error_issue` / `test_error_phase`: same pattern
```
[x]
```
**Ref:** `docs/05-harness-py.md`, `docs/08-state-schema.md`, `docs/12-verification.md`

---

#### Task 10A.3: `tests/unit/test_calibrate.py`
- `test_estimate_call`: `base_prompt_tokens + overhead + output` matches formula
- `test_plan_batches_under_calibrated`: returns all single-task batches when < `min_entries`
- `test_plan_batches_batched`: packs tasks within `max_batch_tokens`; first task always included
- `test_refresh_calibration_under_5_entries`: returns seed values unchanged, no write
- `test_refresh_calibration_p90`: p90 computed with `P90_MARGIN`, calibration.json written once
- `test_log_usage_fields`: all required fields present; `overhead_actual` = `input_tokens - base_prompt_tokens`
- `test_log_usage_invalidates_cache`: `_usage_cache` is `None` after `log_usage()`
- `test_get_session_token_total_5hr_window`: entries outside 5-hour window excluded
- `test_sync_task_types_new_type`: new type added to state and calibration.json with default values
```
[x]
```
**Ref:** `docs/07-calibrate-lang-py.md`, `docs/12-verification.md`

---

#### Task 10A.4: `tests/unit/test_agents.py`
- `test_extract_signal_clean_json`: plain JSON dict returned
- `test_extract_signal_fenced`: ` ```json ` fence stripped, dict returned
- `test_extract_signal_prose_wrapped`: regex fallback finds JSON object in prose
- `test_extract_signal_no_json`: `ValueError` raised
- `test_build_file_lists`: returns correct paths from profile, no hardcoded values
- `test_file_preamble_format`: output contains all paths in order
- `test_call_claude_timeout`: `SubprocessError` raised; message includes timeout duration and remediation hint
- `test_call_claude_nonzero_exit`: `SubprocessError` raised
- `test_call_claude_success`: returns `{"signal": dict, "usage": dict}`
- `test_execute_prompt_single_with_history`: failure_history block injected into prompt
- `test_execute_prompt_batch_format`: ordered list with wrapper JSON instruction
- `test_execute_timeout_scales`: timeout passed to subprocess = `len(tasks) * base_timeout`
- `test_build_tasks_prompt_contains_phase_data`: phase title/tasks present in prompt sent to subprocess
- `test_review_phase_prompt_contains_base_sha`: `base_sha` injected into review prompt
- `test_fix_issues_prompt_uses_source_file`: source file path (review_report or tech_debt) in prompt
```
[x]
```
**Ref:** `docs/06-agents-py.md`, `docs/12-verification.md`

---

#### Task 10A.5: `tests/unit/test_spec.py`
- `test_parse_spec_single_file`: `## Phase N:` headers extracted; returns correct phase count
- `test_parse_spec_directory`: all `.md` files read; phases from file containing headers
- `test_extract_phases_multiple`: multiple `## Phase N:` blocks parsed correctly
- `test_validate_spec_empty`: `sys.exit(1)` with descriptive message
- `test_validate_spec_missing_title`: `sys.exit(1)`
- `test_validate_spec_non_sequential`: `sys.exit(1)`
```
[x]
```
**Ref:** `harness/spec.py`, `docs/12-verification.md`

---

#### Task 10A.6: `tests/unit/test_verify.py`
- `test_verify_execution_case1_retry_succeeds`: syntax ok → no `attempts++`; empty list returned
- `test_verify_execution_case1_double_fail`: syntax fails twice → task returned as `verify_failed_tasks`
- `test_verify_execution_case2_compile_fail`: compile error → failed task returned
- `test_verify_fix_all_passed`: returns empty open list; state updated to `fixed`
- `test_verify_fix_remaining_open`: unfixed issue returned in open list
- `test_verify_fix_deferred_medium_low`: MEDIUM/LOW issues deferred; not in open list
- `test_remove_from_review_report`: issue section removed from file; other sections intact
```
[x]
```
**Ref:** `harness/verify.py`, `docs/12-verification.md`

---

#### Task 10A.7: `tests/unit/test_fix.py`
- `test_run_batch_retry_loop_halt_on_max`: `halt_task()` called after `max_attempts`
- `test_run_batch_retry_loop_verify_fails_escalation`: `verify_fails >= threshold` → `attempts++`, reset
- `test_run_batch_retry_loop_task_failed_signal`: `task_result.status=="failed"` → `attempts++`, retry
- `test_handle_verdict_approve`: no state change, no fix cycle called
- `test_handle_verdict_warn`: all issues `status="deferred"`, appended to `tech_debt.jsonl`
- `test_handle_verdict_block`: `run_fix_cycle()` called
- `test_run_fix_cycle_resolves_open`: CRITICAL/HIGH issue fixed; `review.status="fixed"`
- `test_run_fix_cycle_deferred_medium_low`: unfixed MEDIUM/LOW → `status="deferred"`, appended to tech_debt.jsonl
- `test_run_cleanup_all_fixed`: all deferred issues fixed; `_finish()` called; tech_debt.jsonl cleared
- `test_run_cleanup_remaining`: unfixed issue remains in tech_debt.jsonl
```
[x]
```
**Ref:** `harness/fix.py`, `docs/12-verification.md`

---

#### Task 10A.8: `tests/unit/test_harness.py`
- `test_check_token_budget_under`: `total_used + estimated <= budget` → proceeds without exit
- `test_check_token_budget_over`: `total_used + estimated > budget` → `sys.exit(0)` with `[BUDGET]` message
- `test_pending_tasks_returns_pending_only`: tasks with `status=="pending"` returned; others excluded
- `test_pending_tasks_no_phase`: returns empty list when phase not found
```
[x]
```
**Ref:** `harness/harness.py`, `docs/12-verification.md`

---

#### Task 10A.9: `tests/unit/test_hooks.py`
- `test_post_write_verify_exists`: exit 0
- `test_post_write_verify_missing`: exit 2 with message
- `test_post_edit_verify_content_found`: exit 0, no stdout output
- `test_post_edit_verify_content_missing`: warning printed to stdout, exit 0
- `test_post_edit_verify_python_skip`: `.py` file → exit 0 immediately, no content check
- `test_post_py_lint_format_non_python_skip`: non-`.py` file → exit 0, no output
- `test_post_py_lint_format_no_violations`: `.py` file, ruff clean → exit 0, no stdout
- `test_post_py_lint_format_violations`: `.py` file, ruff reports issues → `[RUFF]` printed to stdout, exit 0
- `test_pre_bash_security_safe_command`: exit 0
- `test_pre_bash_security_rm_rf`: exit 2
- `test_pre_bash_security_injection`: exit 2 for `IGNORE PREVIOUS INSTRUCTIONS`
- `test_pre_bash_security_python_c`: `python -c "..."` pattern → exit 2
- `test_stop_validate_json_valid_execute`: exit 0 for valid EXECUTE signal
- `test_stop_validate_json_invalid_json`: exit 1 with `[SIGNAL ERROR]` message
- `test_stop_validate_json_schema_fail_missing_field`: exit 1 with field path in message
- `test_stop_validate_json_hook_active`: exit 0 unconditionally, no validation
- `test_stop_validate_json_unknown_mode`: exit 1 listing valid modes
- `test_stop_git_commit_execute_single_task`: only `status=="complete"` files staged; commit message = `feat(phase-N): <task title>`
- `test_stop_git_commit_execute_batch`: only `status=="complete"` files staged; commit message = `feat(phase-N): implement N tasks`
- `test_stop_git_commit_fix_fixed_only`: only `status=="fixed"` fixes' files staged; `open`/`deferred` skipped
- `test_stop_git_commit_cleanup_fixed_only`: CLEANUP mode — only `status=="fixed"` fixes staged (same as FIX)
- `test_stop_git_commit_task_build`: exit 0, no git call
- `test_stop_git_commit_no_files`: exit 0, no git call
- `test_read_signal_text_plain_string`: plain string content → returned as-is
- `test_read_signal_text_typed_content_block`: list with `{"type":"text","text":"..."}` → text extracted
- `test_read_signal_text_no_assistant_messages`: non-assistant messages skipped
- `test_read_signal_text_no_text_blocks`: non-text blocks skipped → empty string
```
[x]
```
**Ref:** `docs/09-hooks.md`, `.claude/hooks/`, `docs/12-verification.md`

---

### Phase 10B: Integration Tests

#### Task 10B.1: `tests/integration/test_state_machine.py`
Mock `call_claude()` to return controlled signals. Run full single-phase cycle:
- `INIT → PARSING → TASK_BUILD`: verify tasks written to state.json with correct task_types
- `EXECUTING`: verify task status transitions `pending → building → complete`; verify `usage.jsonl` entry written
- `REVIEWING (APPROVE)`: verify phase advances to `COMPLETE`
- `REVIEWING (BLOCK)`: verify fix cycle entered; CRITICAL/HIGH resolved; MEDIUM/LOW deferred to `tech_debt.jsonl`
- `CLEANUP`: verify deferred issues fixed; final pytest run called
```
[x]
```
**Ref:** `docs/05-harness-py.md`, `docs/12-verification.md`

---

#### Task 10B.2: `tests/integration/test_resume.py`
Test `--resume` re-entry from each interruptible state:
- Resume from `EXECUTING` (task `status="building"`): correct task picked up
- Resume from `FIXING` (review `status="fixing"`): `review_report.md` reconciled before fix agent called
- Resume from `CLEANUP`: active issue list re-derived from state.json, not `tech_debt.jsonl`
- Resume from task `status="error"`: prints `last_error` reason + reset instructions, exits
- Resume from task `status="halted"`: prints halt message, exits
- Resume after state.json WRITE 1 but before review_report.md WRITE 2 (crash-between-writes): issue not re-attempted
```
[x]
```
**Ref:** `docs/05-harness-py.md`, `docs/08-state-schema.md`, `docs/12-verification.md`
