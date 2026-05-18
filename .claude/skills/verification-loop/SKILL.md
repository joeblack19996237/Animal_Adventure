---
name: verification-loop
description: >
  Trigger keywords: verify, before complete, status complete, done implementing, check syntax,
  run lint, ruff, run tests, pytest, secrets scan, diff review, gate, ready to commit.
  Runs five sequential gates — syntax → lint → tests → secrets → diff — and produces a
  VERIFICATION REPORT before any task is marked complete.
origin: ECC (adapted for Python/pytest)
---

# Verification Loop Skill

## When to Use

- After completing a feature or significant code change
- Before signaling `status: complete` on any task
- After refactoring

## Verification Phases

### Phase 1: Syntax Check

```bash
python -m py_compile harness/<module>.py
```

If any file fails to compile, STOP and fix before continuing.

### Phase 2: Lint

```bash
ruff check . 2>&1 | head -30
```

Fix all reported violations. Auto-fixable issues:

```bash
ruff check --fix .
ruff format .
```

### Phase 3: Test Suite

```bash
pytest --tb=short 2>&1 | tail -30
```

With coverage for new modules:

```bash
pytest --cov=harness --cov-report=term-missing 2>&1 | tail -40
```

Report:
- Total tests: X
- Passed: X
- Failed: X
- Coverage: X% (target ≥ 80% for new modules)

If any test fails, STOP and fix before continuing.

### Phase 4: Secrets Scan

```bash
grep -rn "api_key\s*=\s*['\"]" --include="*.py" . 2>/dev/null | head -10
grep -rn "password\s*=\s*['\"]" --include="*.py" . 2>/dev/null | head -10
grep -rn "sk-" --include="*.py" . 2>/dev/null | head -10
```

Flag any hardcoded secrets. They must be moved to environment variables or config files excluded from git.

### Phase 5: Diff Review

```bash
git diff --stat
git diff HEAD -- <changed-files>
```

Review each changed file for:
- Unintended changes outside task scope
- Missing error handling on new code paths
- Debug prints left in (`print(`, `pprint(`)

```bash
grep -rn "^\s*print(" --include="*.py" harness/ 2>/dev/null | head -10
```

## Output Format

After running all phases, produce a verification report:

```
VERIFICATION REPORT
==================

Syntax:    [PASS/FAIL]
Lint:      [PASS/FAIL] (X violations)
Tests:     [PASS/FAIL] (X/Y passed, Z% coverage)
Secrets:   [PASS/FAIL] (X issues)
Diff:      [X files changed, review clean/needs attention]

Overall:   [READY/NOT READY]

Issues to Fix:
1. ...
2. ...
```

## Checkpoints

Run a verification pass:
- After completing each task in EXECUTE mode
- Before emitting the final JSON signal

Hooks catch issues immediately after each file write/edit. This skill provides the comprehensive end-of-task review.
