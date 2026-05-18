# state.json Schema

Harness reads state.json on startup, updates task/issue status in memory, writes back. Contains enough info per task and issue to resume a failed or interrupted run.

## Phase Population Sequence

State.json is built up in three distinct steps — not all at once:

1. `parse_spec(spec_file, state, write_phases=True)` — writes all phase shells `{id, title, status: "pending"}` in one pass (first run only; `write_phases=False` on `--resume` makes the call read-only). Phase `description` and `context` are local variables used to build agent prompts; they are **not** stored in state.json.
2. `build_tasks()` (TASK_BUILD per phase) — fills `tasks[]` under the relevant phase from the TASK_BUILD signal.
3. Harness after REVIEW signal — fills `review.issues[]` under the relevant phase.

```json
{
  "version": "1.0",
  "spec_file": "docs/spec.md",
  "language": "python",
  "initial_sha": "a1b2c3d",
  "task_types": [
    "foundation", "database", "backend", "api",
    "frontend", "integration", "testing"
  ],
  "current_phase": 1,
  "total_phases": 3,
  "phases": [{
    "id": 1,
    "title": "Data Models",
    "status": "building",
    "tasks": [{
      "id": "1.1",
      "title": "Create `User` model in `app/models.py`",
      "task_type": "database",
      "description": "Define User (id, email, hashed_password, created_at) as a SQLAlchemy model in app/models.py with __repr__.",
      "refs": ["docs/08-state-schema.md"],
      "status": "pending",
      "attempts": 0,
      "verify_fails": 0,
      "commit_sha": null,
      "tdd_applied": null,
      "tdd_skipped": null,
      "files_changed": [],
      "last_error": []
    }],
    "review": {
      "status": "pending",
      "verdict": null,
      "sha_at_review": null,
      "issues": [
        {
          "id": "1.1",
          "severity": "CRITICAL",
          "dimension": "Functionality",
          "file": "src/api/users.py:41",
          "title": "POST /users does not return 409 on duplicate email",
          "status": "fixed",
          "attempts": 2,
          "files_changed": ["src/api/users.py", "tests/test_users.py"],
          "fixed_sha": "def5678",
          "last_error": ["Duplicate email check breaks existing test_user_update"]
        },
        {
          "id": "1.2",
          "severity": "HIGH",
          "dimension": "Security",
          "file": "src/api/posts.py:23",
          "title": "No rate limiting on POST /posts endpoint",
          "status": "open",
          "attempts": 0,
          "files_changed": [],
          "fixed_sha": null,
          "last_error": []
        },
        {
          "id": "1.3",
          "severity": "MEDIUM",
          "dimension": "Design/Quality",
          "file": "src/routes/users.py:55",
          "title": "Function exceeds 50 lines",
          "status": "deferred",
          "attempts": 0,
          "files_changed": [],
          "fixed_sha": null,
          "last_error": []
        }
      ]
    },
    "regression": {
      "status": "pending",
      "attempts": 0,
      "commands": [["pytest"]],
      "issues": [],
      "last_error": [],
      "last_run": null,
      "passed_sha": null
    }
  }],
  "last_updated": "2026-04-17T10:00:00Z"
}
```

## Phase Status Lifecycle

- `pending` — phase parsed, task-build not yet run
- `building` — in progress; covers task execution, code review, and fix cycle
- `complete` — all tasks `complete`, all CRITICAL/HIGH issues `fixed`, and phase full regression `passed`; MEDIUM/LOW `deferred` to CLEANUP does not block completion
- `error` — TASK_BUILD signal was not `status="complete"` (ambiguous spec, agent could not classify tasks); set by `error_phase()`; fix the spec, then run `--resume`
- `blocked_external_dependency` — TASK_BUILD could not run because an external dependency failed (for example Claude API 429); resolve the external issue, then run `--resume`

`--resume` behaviour:
- Phase `status="error"` → re-read spec, retry TASK_BUILD once; second failure calls `error_phase()` again and exits
- Phase `status="blocked_external_dependency"` → re-read spec and retry TASK_BUILD without consuming attempts
- Phase `status="building"`, any task `halted` or `error` → print message including `last_error` reason; exit. Manual reset: set task `status` → `"pending"`, then `--resume`
- Phase `status="building"`, no halted/error tasks → find `pending`/`building` tasks and resume EXECUTING
- Phase `status="building"` with `review.status in ("complete", "fixed")` and `regression.status != "passed"` → resume at `REGRESSION_TESTING`
- Phase `status="building"` with `review.status="fixing"` and open CRITICAL/HIGH regression issues → resume at `FIXING`

## Phase Regression Gate

Before `NEXT_PHASE` can mark a phase `complete` and increment `current_phase`,
the harness runs full product regression for all phases up to and including the
current phase.

`phase.regression` fields:

- `status` — `pending`, `running`, `failed`, or `passed`
- `attempts` — count of full regression runs for this phase
- `commands` — de-duplicated product verification commands selected from phase verification profiles
- `last_run.commands[]` — per-command `cmd`, `returncode`, `stdout_tail`, and `stderr_tail`
- `issues` — issue IDs generated from regression failures
- `last_error` — latest regression blocker summary
- `passed_sha` — HEAD SHA observed when the full regression gate passed

Regression failures are converted into current-phase review issues using the
normal `"{phase_id}.{seq}"` issue ID format. The next ID is allocated after the
highest existing issue sequence in the phase. Regression issues are stored in
`review.issues[]` with:

- `severity="HIGH"`
- `dimension="Regression"`
- `source="regression"`
- `regression_key` for de-duplicating repeated failures
- `regression_evidence` containing the failing command and output tails

This deliberately reuses the existing FIX signal schema and fix cycle. The
builder must fix the product behavior or legitimate test integration problem; it
must not delete, skip, xfail, or weaken regression coverage to pass the gate.

## ID Format Contract

Both task IDs and issue IDs follow the pattern `"{phase_id}.{seq}"` — e.g. `"1.1"`, `"1.2"`, `"2.3"`.

- `phase_id` — integer matching the enclosing phase's `id`
- `seq` — 1-based integer, sequential within the phase, no gaps
- `seq` is independent between entity types: task seq and issue seq are separate counters within the same phase (task `"1.1"` and issue `"1.1"` can coexist — they live in different arrays)

This format is enforced by `save_state()` in `state.py`: on every write, any task or issue ID that does not match `r"^\d+\.\d+$"` is silently corrected to `"{phase_id}.{seq}"` derived from the enclosing phase id and 1-based position in `tasks[]` or `issues[]` before the file is written. A `[WARN]` line is logged to console for each correction. This lets the harness derive the owning phase from an ID string (split on `.`, take first part) without a cross-phase scan — used by CLEANUP retry to locate the correct phase for a given issue.

## Signal Wrapper Status vs State.json Status

Agent signals and state.json use different status vocabularies. The table below is the authoritative mapping.

| Signal mode | Has wrapper status? | How harness derives outcome | State.json effect |
|---|---|---|---|
| EXECUTE | **No** — removed | scan `tasks[i].status`: `"complete"` → advance; `"failed"` → `attempts++`, retry | each task independently: `complete` or stay `building` |
| FIX | **No** — removed | scan `fixes[i].status`: `"fixed"` → update; `"open"` → `attempts++`; `"deferred"` → defer | each issue independently: `fixed`, `attempts++`, or `deferred` |
| REVIEW | `const: "complete"` | wrapper confirms review ran; `verdict` field drives next state | `review.status` → `complete`, verdict and issues written |
| TASK_BUILD | `const: "complete"` | wrapper confirms task list was built; non-complete → `error_phase()` | tasks[] written to state.json, or phase → `error` |
| EVALUATE | `const: "complete"` | wrapper confirms evaluator ran; `verdict` drives final state/FIX, optional `score` supports early-stop decisions | `evaluate.iterations[]` appended, or `evaluate.status` → `complete`/`halted` |

EXECUTE and FIX carry no wrapper status because per-item statuses already contain everything the harness needs. A wrapper would only add an inconsistency risk (agent summarises incorrectly) with no benefit.

## Task Status Lifecycle

- `pending` → `building` → `complete`
- `halted` — agent emitted `status="failed"` 3 times (`task["attempts"] >= 3`); fix the code manually, set `status` → `"pending"` in state.json, then `--resume`
- `error` — subprocess-level failure (auth, rate limit, network, model overload, or timeout); `last_error` holds the reason. Resolve the infrastructure issue (or increase `SUBPROCESS_TIMEOUT` / split the task for timeouts), set `status` → `"pending"` in state.json, then `--resume`
- `blocked_external_dependency` — external dependency failure during EXECUTE/retry; `--resume` resets it to `pending` without incrementing attempts
- Task stays `building` for the entire retry lifecycle — agent signal `"failed"` increments `attempts` but does not change state.json status. `"failed"` exists only in the agent signal, never in state.json.
- `tdd_mode="unit_test"` tasks are verified locally by the harness without a Claude EXECUTE call. They still run through `verify_execution()` so tests, dirty-file checks, and resume behaviour stay consistent.
- `task["verify_fails"]` — count of consecutive `verify_execution()` failures (compile/test detected by harness) where the agent reported `"complete"`. Incremented by `run_batch_retry_loop()` each time `verify_execution()` returns the task as failed. Reset to `0` when the agent reports `"failed"` (agent-side failure increments `attempts` instead). When `verify_fails >= 2`, the next `verify_execution()` failure is treated identically to an agent `"failed"` signal: `attempts` is incremented, `verify_fails` is reset to `0`, and a harness-generated reason is appended to `last_error`. This caps the total halt threshold at three strikes across both failure paths (agent failures + harness-detected failures), preventing an infinite loop when the agent repeatedly claims completion while tests keep failing.
- `task["last_error"]` is a **list** — each agent `status="failed"` signal appends its `reason` string; compile/test failures detected by `verify_execution()` append a harness-generated message without incrementing `attempts` (unless `verify_fails >= 2` — see above). The `pre_sha==HEAD` case (hook failed to commit) is reported by `verify_execution()` as a failed task signal and retried by `run_batch_retry_loop()`, so external dependency failures during retry can be recorded as `blocked_external_dependency`. All entries are passed as `failure_history` to the next retry prompt.
- `issue["last_error"]` is a **list** (same as task) — each failed fix attempt appends its `reason` string. The fix cycle builds `failure_history: {issue_id: [reason1, reason2, ...]}` (list-value dict) and injects it into the FIX prompt so the agent sees the full sequence of failed strategies and can try a structurally different approach on each retry.

## Evaluate State

- `evaluate.status` is `evaluating`, `complete`, `halted`, `blocked_external_dependency`, `timeout`, or `error`.
- `evaluate.app_type` is the authoritative app type for evaluator prompts when present. It is inferred from the top-level app type, phase languages, and `client/index.html`, then persisted so the evaluator and fix agent read the same value on resume.
- `evaluate.current_iteration` records the in-flight evaluator iteration. It is set before calling the evaluator and cleared after a successful iteration append.
- `evaluate.attempts` increments on each evaluator subprocess attempt, including attempts that later become `blocked_external_dependency`, `timeout`, or `error`.
- `evaluate.last_started_at` and `evaluate.last_finished_at` are UTC timestamps for status/debug visibility.
- `evaluate.last_error` is a list. External dependency failures append with `status="blocked_external_dependency"`, evaluator timeouts append with `status="timeout"`, and malformed/non-timeout evaluator subprocess failures append with `status="error"`.
- Each completed `evaluate.iterations[]` entry contains `iteration`, `verdict`, `sha_at_evaluate`, `issues`, `fix_sha`, and optional `score` copied from the evaluator signal.
- `max_evaluate_iterations` is intentionally capped at 3 because the evaluator Stop hook schema accepts iterations 1 through 3.
- `evaluate_early_stop_on_full_score` defaults to false. If enabled, the harness may mark evaluation complete after two consecutive APPROVE iterations whose optional score is full (`total == max`).

`--resume` behaviour:
- `evaluate.status in ("evaluating", "blocked_external_dependency", "timeout", "error")` → route directly to EVALUATING before scanning phases
- `evaluate.status="complete"` → route to COMPLETE
- `evaluate.status="halted"` → exit; manually fix issues and reset `evaluate.status` to `evaluating` to retry

## Review Status Lifecycle

- `pending` — review not yet run for this phase
- `complete` — review ran, verdict recorded in state.json
- `fixing` — BLOCK verdict received; fix cycle active (open CRITICAL/HIGH remain in state.json)
- `fixed` — all CRITICAL/HIGH issues fixed; harness sets this at end of fix cycle before advancing to next phase
- `blocked_external_dependency` — REVIEW or FIX could not run because an external dependency failed. `blocked_mode="REVIEW"` resumes REVIEWING; `blocked_mode="FIX"` resumes FIXING.

`--resume` behaviour:
- `review.status="fixing"` → re-enter fix cycle; reconcile `review_report.md` against state.json before handing off to fix agent
- `review.status="fixed"` → fix cycle already complete; advance to TASK_BUILD for next phase
- `review.status="blocked_external_dependency"` → resume using `blocked_mode`

## Issue Status Lifecycle

- `open` — found by reviewer, not yet fixed
- `fixed` — fix verified by harness (pytest passed, entry removed from review_report.md)
- `halted` — failed 3 fix attempts; fix the code manually, set `status` → `"open"` in state.json, then `--resume`
- `error` — subprocess-level failure during fix attempt (auth, rate limit, network, or timeout); `last_error` holds the reason. Resolve the issue, set `status` → `"open"` in state.json, then `--resume`
- `deferred` — MEDIUM/LOW appended to tech_debt.jsonl by harness; addressed in CLEANUP state

## Phase 11 Review Error Fields

`review.status="error"` means the REVIEW subprocess failed or timed out. The phase remains `status="building"` so completed tasks are not rebuilt on `--resume`.

Review fields may include `status`, `verdict`, `sha_at_review`, `issues`, `last_error`, and `attempts`. `review.last_error` stores one or more review-level infrastructure failures, and `review.attempts` increments on each failure. Resume routes `phase.status="building"` plus `review.status in ("pending", "error")` back to REVIEWING when all tasks are complete.

## External Dependency Resume Cleanliness

When a parseable Claude 429 reset time is available, the harness writes
`workspace/external_dependency_context.json`, cleans the Claude process tree,
quarantines new untracked artifacts, and records process cleanup status before
sleeping. `--resume` requires this context to be clean before continuing.
