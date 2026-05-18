# Plan: Prevent Phase Regression Infra Failures From Entering Product FIX

## Context

Phase 11 spent too long in FIXING because the phase regression gate failed on a
pytest collection problem under `.tmp`, then converted that environment/harness
failure into a HIGH product regression issue. The builder was asked to fix a
product issue even though the evidence pointed at a temp-directory collection
failure.

Confirmed evidence:

- `workspace/state.json` recorded phase 11 regression failure at
  `2026-05-18T04:43:58Z`.
- The failing command was:
  `pytest --ignore=harness --asyncio-mode=auto --ignore=.pytest_cache`.
- The stdout tail showed:
  `PermissionError: [WinError 5] ... D:\Animal_Adventure\.tmp\pytest\pytest-of-OEM`.
- The harness created issue `11.4` as HIGH regression work.
- Multiple FIX subprocesses timed out or retried before an external dependency
  429 block stopped progress.

The expected behavior is that product regression failures still become HIGH
current-phase issues, but harness/environment regression failures block the
harness with clear evidence and do not enter product FIX.

## Root Cause

The current phase regression gate treats every non-zero regression command as a
product failure:

- `harness/regression.py` records every failed command as a HIGH issue with
  `source = "regression"`.
- `harness/phase_handlers.py` sends any regression gate failure to FIXING.
- `harness/fix.py` sends open HIGH regression issues to the builder.
- The builder prompt says regression issues should fix product behavior or test
  integration, but it does not distinguish harness/temp/collection infrastructure
  failures.

This creates an expensive retry loop when the failure is not actionable by the
product builder.

## Proposed Solution

Add a narrow regression failure classifier:

- `product_failure`: ordinary test assertion, Playwright/e2e failure, or
  legitimate product test failure. These still create HIGH issues using the
  current phase issue sequence, such as `11.4`, `11.5`, etc.
- `infra_failure`: pytest collection or execution infrastructure failures that
  clearly point at ignored/generated/temp/harness areas such as `.tmp`,
  `.pytest_cache`, `workspace/verification-tmp`, missing executables, or
  command-level exceptions.
- `timeout`: regression command timeout. This is blocked as infra until a human
  confirms whether it is a product hang or an environment problem.

For infra/timeout failures:

- Set `phase.regression.status = "blocked"`.
- Store `failure_kind`, `last_error`, `last_run`, `artifact_path`, and failed
  commands in `State.json`.
- Do not create or reopen product review issues.
- Do not append a product fix section to `workspace/review_report.md`.
- Return `HALTED` from the regression handler so no builder FIX subprocess is
  launched.

For product failures:

- Preserve the existing strict regression gate behavior.
- Create or reopen HIGH regression issues with IDs continuing from the current
  phase's issue sequence.
- Set `review.status = "fixing"` and route through the normal FIX loop.
- Re-run full regression before `NEXT_PHASE`.

## Files To Modify

| File | Planned Change |
|---|---|
| `harness/regression.py` | Add failure classification, artifact writing, blocked state for infra failures, and issue fields for product regression failures. |
| `harness/phase_handlers.py` | Route blocked regression failures to `HALTED` instead of `FIXING`. |
| `harness/fix.py` | Add a guard so existing regression infra issues are not sent to the builder. |
| `harness/harness.py` | Include blocked regression status in current error/status derivation. |
| `harness/agents.py` | Clarify FIX prompt behavior for regression infra evidence. |
| `.claude/agents/builder-execute-fix.md` | Clarify builder rules for regression infra evidence. |
| `harness/config.json` | Add regression gate classification and retry-safety configuration while preserving the current FIX timeout change. |
| `harness/tests/unit/test_regression.py` | Add product-vs-infra regression classification tests. |
| `harness/tests/unit/test_phase_handlers.py` | Add regression blocked routing test. |
| `harness/tests/unit/test_fix.py` | Add guard test for regression infra issues in FIX loop. |
| `harness/tests/unit/test_harness.py` | Add status reporting coverage for blocked regression failures. |

## Test Plan

| Test Case | Expected Result |
|---|---|
| Pytest failure under `.tmp` with `PermissionError` | `phase.regression.status == "blocked"`, `failure_kind == "infra_failure"`, no new HIGH product issue. |
| Missing command / command exception | Regression is blocked as infra and artifact path is recorded. |
| Regression command timeout return code `124` | Regression is blocked as timeout and does not enter FIX. |
| Ordinary product test failure | HIGH issue is created with next phase issue ID and `review.status == "fixing"`. |
| Existing regression infra issue reaches FIX loop | FIX loop halts/blocks the issue and does not call `agents.fix_issues`. |
| `handle_regression_testing()` sees blocked failure | Returns `HarnessState.HALTED`. |
| Status summary sees blocked regression | `last_error` reports the regression blocker. |

## Verification Commands

```powershell
pytest harness/tests/unit/test_regression.py -q
pytest harness/tests/unit/test_phase_handlers.py -q
pytest harness/tests/unit/test_fix.py -q
pytest harness/tests/unit/test_harness.py -q
pytest harness/tests -q
```

Product regression verification after implementation:

```powershell
pytest --ignore=harness --ignore=.pytest_cache --ignore=.tmp --asyncio-mode=auto
npm run test:e2e
```

## Risks

- Over-classifying product failures as infra could hide real product defects.
  Mitigation: only classify as infra when evidence clearly points to generated,
  temp, cache, harness, command, or collection infrastructure. Assertion and
  normal test failures remain product failures.
- Blocking on timeout may require manual diagnosis when the timeout is caused by
  a product deadlock. This is intentional for now because automatic product FIX
  on an ambiguous timeout is expensive and can create churn.
- Existing `source=regression` issues in old state files may lack
  `failure_kind`; they should continue to behave as product failures unless the
  evidence clearly marks them as infra.

## Plan Audit

- The plan changes only harness orchestration, prompts, config, tests, and docs.
- Product code is out of scope.
- Every behavior change has unit coverage.
- Existing strict phase regression gate semantics are preserved for real product
  failures.
- The implementation prevents the exact Phase 11 `.tmp` collection failure from
  launching another product FIX subprocess.
