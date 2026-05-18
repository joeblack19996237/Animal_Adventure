# Plan: Harden Harness Runtime Stability

## Context

This review is scoped to `.claude/` and `harness/` only. The harness controls a full autonomous development loop: spec parsing, task planning, execution, review, fix, cleanup, and final evaluation through Claude Code subprocesses and hooks.

The stability risks below were found by direct code inspection. They focus on cases where the harness can lose recoverability, record incomplete state, or allow an agent role to mutate more than it should.

## Assumptions

- Controlled `SystemExit` paths from harness helpers are intentional halts/blocks and should release `workspace/run.lock` so users can resume normally.
- Unexpected Python exceptions are different from controlled halts. They should keep crash diagnostics visible and should not silently behave like clean exits.
- Evaluation should be read-mostly. The evaluator needs to write reports, screenshots, and a temporary test script, but not source files.
- The plan intentionally avoids broad refactors. Each change is narrow and covered by unit tests.

---

## Solution Review Before Implementation

| Candidate fix | New issue risk checked | Decision |
|---|---|---|
| Catch evaluator FIX `TimeoutError`/`SubprocessError` and route to `error_evaluate()` | Does not change successful evaluate/fix path; uses existing state statuses and resume behavior. External dependency remains distinct. | Include |
| Add a bulk issue error helper for FIX/CLEANUP subprocess failures | Avoids repeated calls to `error_issue()`, which exits on the first issue. Keeps `error_issue()` unchanged for existing single-issue callers. | Include |
| Reopen fixed issues when targeted re-review is blocked by external dependency | May rerun a fix after the external dependency clears, but that is safer than skipping mandatory targeted re-review. Avoids adding new `pending_rereview` state. | Include |
| Preserve run lock on unexpected crash only | Existing tests expect release on crash; update them to reflect intended reliability docs. Controlled halts still release lock. | Include |
| Restrict evaluator `Write(**)` | Could block evaluator scripts if not paired with instruction/settings update. Include explicit workspace script/report/screenshot write permissions and matching prompt change. | Include |
| Add stricter JSON `additionalProperties: false` everywhere | Could break harmless agent metadata and is not necessary for current stability bugs. | Exclude |
| Replace existing state helpers with non-exiting helpers | Too broad. Add one bulk helper only where repeated `sys.exit()` is currently harmful. | Exclude |

---

## Bug 1 — Evaluator FIX Subprocess Failures Can Crash The Harness

**File:** `harness/evaluate.py` — `_run_evaluate_fix()`

**Problem:** `_run_evaluate_fix()` catches `agents.ExternalDependencyError` only. If `agents.fix_evaluate_issues()` times out or returns malformed/unparseable output, `agents.TimeoutError` or `agents.SubprocessError` bubbles to `Harness.run()` as an unexpected crash. That bypasses the explicit `evaluate.status="timeout"` / `"error"` recovery path added for evaluator calls.

**Change:** Add the missing exception branches:

```python
try:
    fix_result = agents.fix_evaluate_issues(...)
except agents.ExternalDependencyError as e:
    block_evaluate_external_dependency(state, str(e))
    return
except agents.TimeoutError as e:
    error_evaluate(state, "timeout", str(e))
    return
except agents.SubprocessError as e:
    error_evaluate(state, "error", str(e))
    return
```

**Why this is complete:** Both evaluator phases now share the same classification: external dependency, timeout, and malformed subprocess output all become explicit evaluate state instead of an orchestrator crash.

**Risk check:** This does not change the happy path or `ExternalDependencyError`. It only covers exceptions currently unhandled by `_run_evaluate_fix()`.

**Tests in `harness/tests/unit/test_evaluate.py`:**

| Test name | What it verifies |
|---|---|
| `test_run_evaluate_fix_timeout_records_timeout` | `fix_evaluate_issues()` raises `agents.TimeoutError`; state gets `evaluate.status == "timeout"` and `SystemExit` |
| `test_run_evaluate_fix_subprocess_error_records_error` | `fix_evaluate_issues()` raises `agents.SubprocessError`; state gets `evaluate.status == "error"` |
| `test_run_evaluate_fix_external_dependency_records_block` | Existing external dependency behavior remains `blocked_external_dependency` |

---

## Bug 2 — FIX/CLEANUP Subprocess Errors Only Mark The First Issue

**Files:** `harness/fix.py`, `harness/cleanup.py`, `harness/state.py`

**Problem:** On a FIX or CLEANUP `agents.SubprocessError`, callers loop over multiple issues and call `error_issue(...)`. But `error_issue()` saves state and immediately `sys.exit(1)`, so only the first issue is marked `error`; the remaining issues in the same failed subprocess keep their previous status. Resume then has partial and misleading state.

**Change:** Add a single bulk helper in `harness/state.py`:

```python
def error_issues(state: dict, phase_id: int, issue_ids: list[str], reason: str) -> None:
    for issue_id in issue_ids:
        issue = find_issue(state, phase_id, issue_id)
        if issue:
            issue["status"] = "error"
            issue.setdefault("last_error", []).append(reason)
    save_state(state)
    logger.error("[ERROR] Phase %d issues aborted: %s.", phase_id, reason)
    sys.exit(1)
```

Use it in:

- `harness/fix.py` — `run_fix_cycle()` `except agents.SubprocessError`
- `harness/cleanup.py` — per-phase cleanup `except agents.SubprocessError`

Keep `error_issue()` unchanged for single-issue flows.

**Why this is complete:** It covers both grouped issue subprocess flows where one agent call is responsible for multiple issues.

**Risk check:** External dependency paths still use `block_review_external_dependency()` / `block_cleanup_external_dependency()` and must not increment attempts or mark issue errors. Single issue helper behavior is unchanged.

**Tests:**

| File | Test name | What it verifies |
|---|---|---|
| `harness/tests/unit/test_state.py` | `test_error_issues_records_all_issue_errors` | Two open issues in one phase both become `error`, both receive the reason |
| `harness/tests/unit/test_fix.py` | `test_run_fix_cycle_subprocess_error_records_all_open_issues` | FIX subprocess error marks all currently open CRITICAL/HIGH issues, not just the first |
| `harness/tests/unit/test_cleanup.py` | `test_cleanup_subprocess_error_records_all_phase_issues` | CLEANUP subprocess error marks every deferred issue in that phase group |
| `harness/tests/unit/test_cleanup.py` | `test_cleanup_external_dependency_does_not_mark_issue_error` | Existing external dependency path remains a cleanup block, issue attempts/status unchanged |

---

## Bug 3 — Targeted Re-Review External Dependency Can Skip Required Re-Review

**File:** `harness/fix.py` — `_targeted_rereview_blocking_fixes()`

**Problem:** `verify_fix()` marks blocking issues fixed before targeted re-review. If targeted re-review then hits `ExternalDependencyError`, `_targeted_rereview_blocking_fixes()` calls `block_review_external_dependency(...)`, which exits immediately. On resume, those issues are already `fixed`, so the fix cycle can finish without ever completing the required targeted re-review.

**Change:** Before blocking on targeted re-review external dependency, reopen the affected fixed blocking issues:

```python
except agents.ExternalDependencyError as e:
    reason = f"targeted re-review blocked: {e}"
    for fix in fixed_blocking:
        state_issue = find_issue(state, phase_id, fix["id"])
        if state_issue:
            last_error = state_issue.setdefault("last_error", [])
            if not last_error or last_error[-1] != reason:
                last_error.append(reason)
            update_state(
                state,
                phase_id=phase_id,
                issue_id=fix["id"],
                status="open",
                last_error=last_error,
            )
    block_review_external_dependency(state, phase_id, str(e), "FIX")
    return []
```

**Why this is complete:** Resume re-enters FIXING with the relevant CRITICAL/HIGH issues open, so the harness cannot advance without another verified fix plus targeted re-review.

**Risk check:** This can rerun a fix that was already applied. That is acceptable because the alternative is silently skipping re-review. Avoid adding a new `pending_rereview` state field because it would touch more state-machine code.

**Tests in `harness/tests/unit/test_fix.py`:**

| Test name | What it verifies |
|---|---|
| `test_targeted_rereview_external_dependency_reopens_fixed_blocking_issue` | A fixed HIGH issue becomes `open` and gets a targeted re-review error before the block |
| `test_targeted_rereview_external_dependency_preserves_blocked_mode_fix` | Review status becomes `blocked_external_dependency` with `blocked_mode == "FIX"` |
| `test_targeted_rereview_subprocess_error_still_reopens_issue` | Existing non-external subprocess error behavior remains open/retryable |

---

## Bug 4 — Unexpected Crashes Release The Run Lock

**File:** `harness/harness.py` — `Harness.run()`

**Problem:** `Harness.run()` currently releases `workspace/run.lock` in `finally` for all paths, including unexpected exceptions. This contradicts the reliability model documented in `harness/docs/05-harness-py.md` and weakens crash diagnostics: a real crash looks like a clean unlocked exit.

**Change:** Release the lock on:

- normal completion
- controlled `SystemExit` paths

Preserve the lock on unexpected exceptions after emitting `harness_crash`.

Implementation sketch:

```python
release_on_exit = False
try:
    self._run_locked(args, state)
except SystemExit:
    release_on_exit = True
    raise
except Exception as e:
    emit_event("harness_crash", error_type=type(e).__name__)
    raise
else:
    release_on_exit = True
    emit_event("harness_complete")
    log_line("[HARNESS] complete")
finally:
    if lock_acquired and release_on_exit:
        release_lock()
```

**Why this is complete:** Controlled halts still behave as resumable exits. Unexpected crashes leave lock metadata for `--status`; because the crashed process exits, the existing stale-lock path can clear it safely.

**Risk check:** This changes one existing unit test that expected crash lock release. Update the test to match the documented intent. Add a separate controlled `SystemExit` test so users are not forced to clear locks after normal harness blocks.

**Tests in `harness/tests/unit/test_harness.py`:**

| Test name | What it verifies |
|---|---|
| `test_run_preserves_lock_on_unexpected_exception` | A runtime error leaves `workspace/run.lock` present and `lock_status()["active"] is True` in-process |
| `test_run_releases_lock_on_controlled_system_exit` | A controlled `SystemExit` releases lock and PID files |
| Update `test_run_raises_on_unhandled_state_and_releases_lock` | Rename/adjust to expected preserved-lock behavior |

---

## Bug 5 — Evaluator Has Broad Source Write Permission

**Files:** `.claude/settings.evaluator.json`, `.claude/agents/evaluator.md`

**Problem:** The evaluator runs without `Edit`, but `.claude/settings.evaluator.json` grants `Write(**)`. Since evaluator mode has no git commit hook and is supposed to audit, broad write permission can let it overwrite source files, state files, or harness artifacts. The prompt also suggests writing a Playwright script to `/tmp`, which is not aligned with a narrow workspace-only write policy.

**Change:** Restrict evaluator writes to evaluation artifacts and align the prompt:

```json
"allow": [
  "Read(**)",
  "Write(workspace/rubric-report.md)",
  "Write(workspace/screenshots/**)",
  "Write(workspace/eval_playwright.py)",
  ...
  "Bash(python workspace/eval_playwright.py*)"
]
```

Update `.claude/agents/evaluator.md`:

- Replace `/tmp/eval_playwright.py` with `workspace/eval_playwright.py`
- State that evaluator must not write source files, `workspace/state.json`, or harness code
- Keep screenshots under `workspace/screenshots/`

**Why this is complete:** It preserves the evaluator's needed write surfaces while removing source mutation ability from the audit role.

**Risk check:** The evaluator needs to write a script and report. The explicit `workspace/eval_playwright.py` permission plus matching Bash permission prevents a permission dead-end.

**Tests:**

| File | Test name | What it verifies |
|---|---|---|
| `harness/tests/unit/test_config_shape.py` | `test_evaluator_settings_do_not_allow_general_write` | `Write(**)` is absent from evaluator settings |
| `harness/tests/unit/test_config_shape.py` | `test_evaluator_settings_allow_evaluation_artifact_writes` | Report, screenshots, and eval script write permissions exist |
| `harness/tests/unit/test_config_shape.py` | `test_evaluator_settings_allow_eval_script_execution` | `Bash(python workspace/eval_playwright.py*)` exists |
| `harness/tests/unit/test_docs.py` | `test_evaluator_docs_restrict_writes_to_artifacts` | Evaluator prompt says not to write source/state/harness files |

---

## Files To Modify

| File | Change |
|---|---|
| `harness/evaluate.py` | Catch `TimeoutError` and `SubprocessError` in `_run_evaluate_fix()` |
| `harness/state.py` | Add `error_issues()` bulk helper |
| `harness/fix.py` | Use `error_issues()` for grouped FIX subprocess failures; reopen issues on targeted re-review external dependency |
| `harness/cleanup.py` | Use `error_issues()` for grouped CLEANUP subprocess failures |
| `harness/harness.py` | Preserve lock on unexpected crash, release on clean/control-flow exits |
| `.claude/settings.evaluator.json` | Replace `Write(**)` with narrow evaluation artifact writes; allow explicit eval script execution |
| `.claude/agents/evaluator.md` | Align evaluator scratch script path and write restrictions |
| `harness/tests/unit/test_evaluate.py` | Add evaluator FIX exception tests |
| `harness/tests/unit/test_state.py` | Add `error_issues()` tests |
| `harness/tests/unit/test_fix.py` | Add grouped FIX error and targeted re-review external dependency tests |
| `harness/tests/unit/test_cleanup.py` | Add grouped CLEANUP error tests |
| `harness/tests/unit/test_harness.py` | Add/adjust lock release vs crash tests |
| `harness/tests/unit/test_config_shape.py` | Add evaluator settings permission tests |
| `harness/tests/unit/test_docs.py` | Add evaluator prompt restriction test |

---

## Implementation Order

1. `harness/evaluate.py` + focused tests
2. `harness/state.py`, `harness/fix.py`, `harness/cleanup.py` + grouped issue tests
3. `harness/fix.py` targeted re-review external dependency reopening + tests
4. `harness/harness.py` lock behavior + tests
5. `.claude/settings.evaluator.json` and `.claude/agents/evaluator.md` + settings/docs tests
6. Run focused tests after each step; run full harness regression at the end

---

## Verification Criteria

Focused verification:

```bash
pytest harness/tests/unit/test_evaluate.py -q
pytest harness/tests/unit/test_state.py -q
pytest harness/tests/unit/test_fix.py -q
pytest harness/tests/unit/test_cleanup.py -q
pytest harness/tests/unit/test_harness.py -q
pytest harness/tests/unit/test_config_shape.py -q
pytest harness/tests/unit/test_docs.py -q
```

Full regression:

```bash
pytest harness/tests/unit/ -q
pytest harness/tests/integration/ -q
pytest harness/tests/e2e/ -q
pytest harness/ -q
```

Manual sanity checks:

- Simulate an evaluator FIX timeout and confirm `workspace/state.json` records `evaluate.status="timeout"` instead of a `harness_crash`.
- Simulate a FIX subprocess parse failure with two open issues and confirm both receive `status="error"`.
- Simulate targeted re-review 429 and confirm affected fixed blocking issues are reopened before `review.status="blocked_external_dependency"`.
- Trigger an unexpected exception in `Harness.run()` in a test workspace and confirm `workspace/run.lock` remains present until stale-lock cleanup.
- Confirm evaluator settings no longer include `Write(**)` and evaluator prompt writes scripts/reports only under `workspace/`.

## Non-Goals

- No changes to generated application code outside `.claude/` and `harness/`.
- No broad state-machine rewrite.
- No new persistent state fields unless a test proves they are necessary.
- No stricter JSON schema lockdown beyond the evaluator write-permission plan.
