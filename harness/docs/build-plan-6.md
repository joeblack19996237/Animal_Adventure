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

### Phase 10C: End-to-End Tests

#### Task 10C.1: Create `tests/e2e/spec_sample.md`
Minimal 2-phase test spec: Phase 1 — simple data model (one logic task + one config task); Phase 2 — one API endpoint. Designed to exercise TDD (logic task), `tdd_skipped` (config task), REVIEW, and fix cycle. Kept small to minimise token cost during E2E runs.
```
[ ]
```
**Ref:** `docs/02-spec-format.md`, `docs/12-verification.md`

---

#### Task 10C.2: E2E — Happy path and TASK_BUILD verification (scenarios 1–4 from doc 12)
Run `python harness/harness.py tests/e2e/spec_sample.md`. Verify:
- state.json updated after each task with `tdd_applied`/`tdd_skipped` and `task_type`
- Logic task produces a `tests/` file; config task does not
- `git log --oneline` shows one commit per completed task
- `usage.jsonl` has one entry per subprocess with `estimation_error` populated
```
[ ]
```
**Ref:** `docs/12-verification.md` (scenarios 1–4)

---

#### Task 10C.3: E2E — Review and fix cycle verification (scenarios 5–6 from doc 12)
Verify:
- `review_report.md` created with `## Summary` + verdict after phase 1 completes
- Reviewer only examines files in `git diff {sha}..HEAD`
- At least one `Functionality` dimension finding present
- Two CRITICAL issues → both sent to one FIX subprocess; signal has two entries
- One issue `status="open"` in fix signal → `failure_history` injected into next subprocess
- Fixed issues `status="fixed"` in state.json; `review_report.md` entries removed
```
[ ]
```
**Ref:** `docs/12-verification.md` (scenarios 5–6)

---

#### Task 10C.4: E2E — Resume, halt, and timeout verification (scenarios 6d–7b from doc 12)
Verify:
- Kill mid-run, `--resume` picks up correctly
- Kill after state.json WRITE 1 but before review_report.md WRITE 2 → state consistent on resume
- Set `task.attempts: 2`, re-run → halt fires on 3rd failure; `status="halted"` in state.json
- Set `subprocess_timeout["EXECUTE"]: 1`, run a task → `TimeoutExpired` caught, `status="error"`, `last_error` has timeout message, harness exits cleanly
```
[ ]
```
**Ref:** `docs/12-verification.md` (scenarios 6d–7b)

---

#### Task 10C.5: E2E — Hook and schema validation verification (scenarios 8–13 from doc 12)
Verify:
- `stop_validate_json.py`: prose-wrapped JSON caught, agent self-corrects, `call_claude()` receives clean signal
- `stop_hook_active=True`: hook exits 0, `extract_signal()` handles residue
- `stop_git_commit.py` EXECUTE: only `status=="complete"` files staged; single task → `feat(phase-N): <task title>`; batch → `feat(phase-N): implement N tasks`
- `stop_git_commit.py` FIX: only `status=="fixed"` files staged
- `stop_git_commit.py` TASK_BUILD/REVIEW: no commit
- `pre_bash_security.py`: `rm -rf *` blocked (exit 2)
- `post_write_verify.py`: file existence confirmed
- Syntax error in generated file: `verify_execution()` catches it, retries without `attempts++`
- New task_type from agent: `sync_task_types()` adds to state.json and calibration.json
- Schema validation: signal missing required field → hook rejects, agent self-corrects within same subprocess
```
[ ]
```
**Ref:** `docs/12-verification.md` (scenarios 8–13)

---

#### Task 10C.6: E2E — CLEANUP and tech_debt verification (scenarios 14–15 from doc 12)
Verify:
- Two MEDIUM/LOW issues from review → `status="deferred"`, appended to `tech_debt.jsonl`
- After all phases complete → CLEANUP pass runs; deferred issues fixed; `tech_debt.jsonl` entries updated
- `review.status="fixed"` in state.json after CLEANUP
- `python -c "from harness.state import load_state, save_state"` imports cleanly with no harness.py dependency
```
[ ]
```
**Ref:** `docs/12-verification.md` (scenarios 14–15)
# Phase 11 Harness E2E Reliability Addendum

The Phase 11 hardening work adds deterministic harness E2E fixtures for Python CLI, mixed stack, REVIEW timeout resume, and BLOCK/FIX/targeted re-review. These fixtures are intentionally minimal because the E2E target is harness reliability, not the generated app.

Regression must include unit, integration, deterministic E2E, and skipped-by-default live smoke coverage. Every behavior change is paired with tests and docs: review error state, interrupted task reset, unified subprocess runner, structured events, run lock/PID, dynamic REVIEW timeout policy, pre/post commit gate, structured verification result, and targeted fix re-review.
