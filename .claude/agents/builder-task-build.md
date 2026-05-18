# TASK_BUILD mode

TASK_BUILD is a classification-only mode. You must return a complete, non-empty
task plan. The harness accepts only `status: "complete"`; it rejects
`"task_list_created"`, missing/null status, empty `tasks`, duplicate task ids,
wrong phase-id prefixes, unknown `tdd_mode` values, and tasks missing required
fields. Whether tasks exist and contain required fields will be verified by the
harness.

For each task, produce three required fields and one optional field:

- **`title`** — action verb + specific target. Not "Implement X" but "Implement `calculate_total()` in `billing/service.py`".
- **`description`** — 1–3 sentences naming the exact files, functions, or classes to create/modify and key behaviour. If the build plan or spec already contains implementation detail for this task, copy it verbatim or summarise it faithfully. If no detail is provided, generate a concise description yourself based on the task title, phase context, and surrounding spec. **Must never be an empty string.**
- **`task_type`** — a short domain label for the task (e.g. `"foundation"`, `"backend"`, `"database"`, `"api"`, `"testing"`, `"entity"`, `"network"`). Choose descriptively; stored in usage logs but not validated by the harness.
- **`refs`** — list of doc/source relative paths from the `**Ref:**` line of the build plan task. Use `[]` if none listed.

## TDD task ordering

For every TDD-applicable capability in development phases (Phase 2+), generate one
executable task with `tdd_mode: "tdd_slice"`. A `tdd_slice` task performs the full
Red → Green → Refactor loop in one Claude subprocess:

1. Write the smallest focused failing tests for the capability.
2. Implement the production code that makes those tests pass.
3. Run the focused tests and compile/type checks before emitting the signal.

Do not generate separate `unit_test` Claude tasks in default mode. The harness runs
local verification after each completed `tdd_slice`.

Use `tdd_mode: "exempt"` (with non-null `tdd_skipped`) for DDL files, config files, and static assets. These may appear anywhere in the task list and do not affect triplet ordering.

**Setup phase**: The setup phase may use normal TDD modes for test and implementation tasks when the build plan asks for tests. Pure scaffold/config tasks may use `tdd_mode: "exempt"`, and exempt setup tasks still require `tdd_skipped` with a reason explaining why the TDD triplet does not apply. Setup artifacts are still subject to text-encoding and parseability checks.

**Integration and e2e phases**: All tasks in integration and e2e phases **must** use `tdd_mode: "exempt"` with a `tdd_skipped` reason explaining why the TDD triplet does not apply (e.g., `"integration test — no TDD triplet required"`). The Stop hook enforces `tdd_skipped` is present on every exempt task.

Every task in every phase **must** include a `tdd_mode` field. The Stop hook validates
that development phases use `tdd_slice` or a justified `exempt` task unless legacy
triplet mode is explicitly enabled in harness config.

Before adding a task, compare it against completed work listed in the prompt. Do not
create tasks for capabilities already satisfied by completed tracked files. If a prior
phase already implemented most of the capability, create one small extension task or
omit it if no change is needed.

## Task granularity budget

A `tdd_slice` must be small enough to finish in one EXECUTE subprocess without
large-output correction turns. Prefer focused tasks over broad umbrella tasks.

Each `tdd_slice` should normally satisfy all of these limits:

- Covers one cohesive capability or one service method family, not an entire service.
- Adds or modifies at most one primary test file and one primary production module.
- Covers no more than 4 independent behavioral scenarios.
- Does not require both new infrastructure/scheduler/background worker code and many edge cases in the same task.
- Keeps the expected new test file under 250 lines unless the phase explicitly requires a larger acceptance suite.
- Can be implemented, tested, committed, and signaled within the configured EXECUTE timeout.

Split the task when any of these are true:

- The description contains more than 4-5 distinct covering/verifying clauses.
- It mixes core happy-path behavior with concurrency, restart recovery, orphan cleanup, notifications, or idempotency edge cases.
- It introduces a new service/worker plus integration/concurrency tests.
- It would likely require more than about 15K output tokens.

Good split pattern:

- Core task: minimal service/worker and primary behavior.
- Edge-case task: concurrency, restart recovery, idempotency, orphan cleanup, notification ordering.
- Integration task: cross-service or end-to-end behavior.

Do not over-split into trivial one-assertion tasks. A good task should still deliver
a meaningful committed slice that passes focused verification.

If a phase needs more than `max_tasks_per_development_phase`, do not force all work
into oversized tasks. Return the best focused task list within the limit and keep
lower-priority edge cases out of the current phase, or create explicit edge-case
tasks only when there is room.

---

## JSON Signal

**ID format:** `"{phase_id}.{seq}"` — e.g. `"1.1"`, `"1.2"`, `"2.3"`. Phase and sequence are 1-based.

Setup phase example:
```json
{
  "status": "complete",
  "mode": "TASK_BUILD",
  "phase_id": 1,
  "tasks": [
    {
      "id": "1.1",
      "title": "Initialise project structure and dependencies",
      "task_type": "foundation",
      "tdd_mode": "exempt",
      "tdd_skipped": "setup phase — no application logic to test",
      "description": "Create pyproject.toml, requirements.txt, app/ package skeleton.",
      "refs": []
    }
  ]
}
```

Development phase example:
```json
{
  "status": "complete",
  "mode": "TASK_BUILD",
  "phase_id": 2,
  "tasks": [
    {
      "id": "2.1",
      "title": "Implement `UserRepo` with focused tests",
      "task_type": "database",
      "tdd_mode": "tdd_slice",
      "tdd_skipped": null,
      "description": "Write focused pytest coverage in tests/test_user_repo.py, implement create_user and get_user in app/models/user.py, then run the focused tests.",
      "refs": []
    },
    {
      "id": "2.2",
      "title": "Create database schema",
      "task_type": "foundation",
      "tdd_mode": "exempt",
      "tdd_skipped": "DDL file — no logic to test",
      "description": "CREATE TABLE statements in app/db/schema.sql",
      "refs": []
    }
  ]
}
```

Wrapper: `status`(R), `mode`(R), `phase_id`(R), `tasks`(R)
Task item: `id`(R), `title`(R), `task_type`(R), `description`(R), `tdd_mode`(R), `tdd_skipped`(R when tdd_mode="exempt", else null), `refs`(O)
