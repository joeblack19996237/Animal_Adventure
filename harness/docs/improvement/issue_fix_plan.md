# Plan: Fix Three Harness Correctness Bugs

## Context

All three issues were confirmed real by direct code analysis. They share a common pattern: the harness trusts agent-reported state without independent verification, allowing false-positive "fixed" / "complete" signals to advance the pipeline.

---

## Bug 1 — verify_fix() False-Positive Fixes

**File:** `harness/verify.py` — `verify_fix()` (~line 191)

**Problem:** The function accepts every fix that claims `status == "fixed"` as long as (a) the global test suite passes and (b) *any* file changed somewhere. It never checks whether the files a specific fix claims to have changed (`fix["files_changed"]`) actually appear in `git diff pre_sha..HEAD`. An agent can report fix A as "fixed" while only touching files related to fix B, and the harness accepts it.

**Change — add per-fix file intersection check after the existing empty-diff guard:**

```python
# NEW block, inserted after the existing empty-diff continue (line ~201)
fix_files = set(fix.get("files_changed", []))
if pre_sha and pre_sha != current_sha and fix_files and not (fix_files & diff_files):
    logger.warning(
        "[VERIFY] Fix %s claims files %r were changed but none appear in "
        "git diff %s..HEAD (actual diff: %r) — rejecting.",
        fix["id"], sorted(fix_files), pre_sha, sorted(diff_files),
    )
    open_fixes.append({
        **fix,
        "reason": (
            f"claimed files {sorted(fix_files)} not found in git diff {pre_sha}..HEAD"
        ),
    })
    continue

# Optional log — does not block acceptance
if fix.get("verification_note"):
    logger.info("[VERIFY] Fix %s note: %s", fix["id"], fix["verification_note"])
```

**Condition analysis (must not regress):**
- `pre_sha == ""` → whole condition is False → no intersection check (existing happy path)
- `pre_sha == current_sha` → already caught by the earlier `not diff_files` guard → unreachable here
- `fix_files == set()` → `fix_files and ...` is False → no intersection check (no specific files claimed)

**Schema change — `.claude/hooks/stop_validate_json.py`:** Add optional `verification_note` field to the FIX items schema (advisory, not required):

```python
# In the FIX schema items properties, after "reason":
"verification_note": {"type": "string"},
```

**Existing tests — NO changes required.** Both `test_verify_fix_all_passed` and `test_verify_fix_uses_integration_test_cmd` call `verify_fix(..., phase_id=1)` with no `pre_sha` (default `""`). The new condition evaluates to False and the tests are unaffected.

**New tests in `harness/tests/unit/test_verify.py`:**

| Test name | What it verifies |
|-----------|-----------------|
| `test_verify_fix_rejects_fix_when_claimed_files_not_in_diff` | Fix with `files_changed=["f.py"]`, diff only contains `"other.py"` → rejected, reason mentions "not found in git diff" |
| `test_verify_fix_accepts_fix_when_claimed_files_overlap_diff` | Same fix but diff contains `"f.py"` → accepted, `fix_sha` set in state |
| `test_verify_fix_skips_intersection_check_when_no_pre_sha` | `pre_sha=""` → accepted regardless of diff |
| `test_verify_fix_skips_intersection_check_when_fix_files_empty` | `files_changed=[]` → no intersection check, accepted |
| `test_verify_fix_logs_verification_note` | Fix with `verification_note="Added null check"` → appears in log at INFO level |

---

## Bug 2 — verify_evaluate_fix() Ignores pre_sha and Fix Signal Statuses

**Files:** `harness/evaluate.py` — `verify_evaluate_fix()` (~line 143) and `_run_evaluate_fix()` (~line 79)

### Change A — `verify_evaluate_fix()`: check `current_sha != pre_sha`

Insert immediately after `current_sha = subprocess.run(...).stdout.strip()` (~line 161):

```python
if current_sha == pre_sha:
    logger.warning(
        "[EVALUATE FIX] HEAD SHA unchanged after fix (%r == pre_sha) — "
        "no commit made; skipping fix_sha update.",
        current_sha,
    )
    return
```

This prevents `fix_sha` from being set to a stale SHA when the fix agent made no commit.

### Change B — `_run_evaluate_fix()`: check at least one fix is "fixed"

Replace the final `verify_evaluate_fix(...)` call with a guarded version:

```python
fixes = fix_result["signal"].get("fixes", [])
log_usage(
    task_id=f"evaluate_{iteration}_fix",
    phase_id=eval_phase_id,
    mode="FIX",
    usage=fix_result["usage"],
    files_changed=sum(
        len(f.get("files_changed", []))
        for f in fixes
        if f.get("status") == "fixed"
    ),
)

has_fixed = any(f.get("status") == "fixed" for f in fixes)
if not has_fixed:
    logger.warning(
        "[EVALUATE FIX] Fix agent returned no 'fixed' statuses in iteration %d — "
        "skipping verify_evaluate_fix.",
        iteration,
    )
    last_iter = state["evaluate"]["iterations"][-1]
    last_iter.setdefault("fix_attempts", 0)
    last_iter["fix_attempts"] += 1
    last_iter["last_fix_error"] = "fix agent reported no fixed issues"
    save_state(state)
    return

verify_evaluate_fix(harness, state, eval_phase_id, pre_sha)
```

**Existing tests — NO changes required.**
- `test_verify_sets_fix_sha_when_tests_pass`: passes `pre_sha="oldsha"`, mock returns `"sha123"` → different → guard skipped → PASSES
- `test_verify_clears_evaluate_fix_md_on_success`: `pre_sha="pre"`, mock returns `"sha123"` → different → PASSES
- All `run_evaluate_cycle_*` tests use `_fix_result()` which has `status: "fixed"` → `has_fixed=True` → `verify_evaluate_fix` called as before → PASSES
- Tests using `_git_ok` throughout (so `pre_sha == current_sha == "sha123"`) don't assert on `fix_sha`, so the new SHA guard causing early return doesn't break them → PASSES

**New tests in `harness/tests/unit/test_evaluate.py`:**

Add `_run_evaluate_fix` to the existing imports from `evaluate`.

| Test name | What it verifies |
|-----------|-----------------|
| `test_verify_does_not_set_fix_sha_when_sha_unchanged` | `pre_sha="sha123"`, mock returns `"sha123"` → `fix_sha` stays `None` |
| `test_verify_does_not_clear_fix_md_when_sha_unchanged` | Same setup → evaluate_fix.md content not cleared to `""` |
| `test_run_evaluate_fix_skips_verify_when_all_fixes_open` | `_run_evaluate_fix` called with all-"open" fix result → `fix_sha` not set, `fix_attempts == 1` |
| `test_run_evaluate_fix_records_last_fix_error_on_no_fixed` | Same → `last_fix_error` is non-empty string |

---

## Bug 3 — sha_at_review Trusted from Agent Signal

**File:** `harness/phase_handlers.py` — `handle_reviewing()` (~line 211)

**Problem:** After `agents.review_phase()` returns, the agent's `signal["sha_at_review"]` is stored directly into state and used as the diff baseline for the next phase. The harness never independently verifies it against actual `git HEAD`.

**Change — capture actual HEAD and override if it differs:**

Insert after `signal = result["signal"]` (~line 211), before building the `issues` list:

```python
# Capture actual HEAD; use it as sha_at_review regardless of agent's value
_sha_run = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
actual_sha = _sha_run.stdout.strip() if _sha_run.returncode == 0 else None
agent_sha = signal.get("sha_at_review")
if actual_sha and agent_sha and agent_sha != actual_sha:
    logger.warning(
        "[REVIEW] Agent sha_at_review=%r differs from actual HEAD %r — overriding.",
        agent_sha,
        actual_sha,
    )
sha_at_review = actual_sha if actual_sha else agent_sha
```

Change `update_state(...)` call to use `sha_at_review=sha_at_review` instead of `sha_at_review=signal.get("sha_at_review")`.

`subprocess` is already imported at the top of `phase_handlers.py`. `logger` is already defined.

**Existing tests — NO changes required.** `test_handle_reviewing_returns_next_phase` does not monkeypatch `subprocess.run`. In the test environment, `tmp_workspace` is not a git repo, so `git rev-parse HEAD` returns `returncode != 0`. The fallback path sets `actual_sha = None`, then `sha_at_review = agent_sha = "sha123"`. Return value `HarnessState.NEXT_PHASE` is unaffected → PASSES.

**New tests in `harness/tests/unit/test_phase_handlers.py`:**

Add `import subprocess` at the top.

| Test name | What it verifies |
|-----------|-----------------|
| `test_handle_reviewing_stores_actual_head_as_sha_at_review` | Mock `subprocess.run` to return `"actual_sha"` for git, agent signal has `"agent_sha"` → state stores `"actual_sha"` |
| `test_handle_reviewing_logs_warning_when_sha_mismatch` | Same setup + `caplog` → "overriding" in WARNING log |
| `test_handle_reviewing_uses_agent_sha_when_git_fails` | Mock git to `returncode=1` → state stores agent's `"sha123"` (graceful fallback) |
| `test_handle_reviewing_no_warning_when_shas_match` | Agent and actual SHA are identical → no "overriding" in log |

---

## Files to Modify

| File | Change |
|------|--------|
| `harness/verify.py` | Per-fix intersection check + `verification_note` log in `verify_fix()` |
| `harness/evaluate.py` | SHA guard in `verify_evaluate_fix()`; `has_fixed` guard in `_run_evaluate_fix()` |
| `harness/phase_handlers.py` | Capture actual HEAD and override `sha_at_review` in `handle_reviewing()` |
| `.claude/hooks/stop_validate_json.py` | Add optional `verification_note` to FIX schema |
| `harness/tests/unit/test_verify.py` | 5 new tests |
| `harness/tests/unit/test_evaluate.py` | Add `_run_evaluate_fix` to imports; 4 new tests |
| `harness/tests/unit/test_phase_handlers.py` | Add `subprocess` import; 4 new tests |

---

## Implementation Order

1. `phase_handlers.py` (isolated, no callers change)
2. `evaluate.py` (isolated, no API surface change)
3. `verify.py` + `stop_validate_json.py` (most callers, do last)
4. Tests for each, added alongside the corresponding production change

---

## Verification

```bash
# Run full unit test suite — must be green before and after each change
pytest harness/tests/unit/ -v

# Run integration tests
pytest harness/tests/integration/ -v

# Full suite
pytest harness/ -v
```

Manual check: after a review phase completes, verify `workspace/state.json` → `phases[N].review.sha_at_review` matches `git rev-parse HEAD`.
