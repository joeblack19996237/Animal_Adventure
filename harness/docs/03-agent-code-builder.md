# Agent: code-builder

File: `.claude/agents/code-builder.md`

Frontmatter: `tools: [Read, Write, Edit, Bash, Grep, Glob]`, `model: sonnet`

## Responsibilities

- **Task-building mode**: Read one phase, parse requirements, classify each task by `task_type`, emit JSON signal — harness writes tasks to `state.json`
- **Task-execution mode**: Read one task, implement it using TDD where applicable, exit with completion signal
- **Fix mode**: Read `workspace/review_report.md`, fix all CRITICAL/HIGH issues in severity order, exit with a completion signal after each fix

## task_type Assignment (TASK_BUILD mode)

Agent classifies each task by Python development domain. Seed types:
- `foundation` — project setup, config files, `__init__.py`, requirements
- `database` — models, migrations, schema definitions
- `backend` — business logic, services, utilities
- `api` — endpoints, serializers, request/response handling
- `frontend` — templates, static assets, UI components
- `integration` — third-party services, external APIs, auth providers
- `testing` — test fixtures, conftest, test utilities

Agent may introduce new types beyond this list if the task domain doesn't fit. Harness registers new types automatically via `sync_task_types()`.

## TDD Workflow (EXECUTE and FIX modes)

**Step 1 — Assess applicability.** TDD is required unless the task is one of:
- Config/settings file (no logic)
- Migration file (schema only)
- `__init__.py` or pure scaffolding
- Static asset or data file

**Step 2 — If TDD applies:**
```
1. Write a failing test in tests/ that defines the expected behavior (Red)
2. Run: pytest <test_file> — confirm it fails
3. Write the minimal implementation to pass the test (Green)
4. Run: pytest <test_file> — confirm it passes
5. Refactor if needed, re-run pytest
```
(git commit is handled automatically by the stop_git_commit.py Stop hook — agent does not commit manually)

**Step 3 — If TDD does not apply**, state reason in the JSON signal: `"tdd_skipped": "config file — no logic to test"`

**Already satisfied implementation tasks:** If a task is already satisfied by existing tracked files, do not return an empty no-op signal. Return `"status": "complete"`, list the existing tracked files that satisfy the task in `files_changed`, and set `tdd_skipped` to explain that the task is already satisfied by existing tracked files.

## Completion Self-checks

**Task build completion self-check (before emitting signal):**
- [ ] All files named in the task description exist and are non-empty
- [ ] `python -m py_compile <file>` passes for every new Python file
- [ ] If TDD applied: test file exists in `tests/`, `pytest` passes
- [ ] No bare `except:`, no `print()` debug statements, no `TODO` left in new code
- [ ] `files_changed` in signal lists every file created or modified (hook uses this to stage and commit)
- [ ] If no file needed modification because existing tracked files already satisfy the task, `files_changed` lists those existing tracked files and `tdd_skipped` explains why no code change was needed

**Issue fix completion self-check (before emitting signal — FIX mode fixes ALL CRITICAL/HIGH in one subprocess):**
- [ ] Read ALL open issues from `review_report.md` before starting
- [ ] Fix each issue in severity order (CRITICAL first, then HIGH)
- [ ] After all fixes attempted: `pytest` passes — no regressions introduced
- [ ] Signal reports per-issue status — "fixed", "open", or "deferred" (MEDIUM/LOW) with reason for each open issue
- [ ] Each completed fix entry includes `files_changed` (hook uses this to stage and commit)

## Output Contract

Add this block verbatim at the **top** of `.claude/agents/code-builder.md`, before all other sections:

```
## Output Contract
Your COMPLETE response must be the JSON signal below. Output ONLY the JSON object.
No prose, no status lines, no markdown fences before or after.
The Stop hook validates your output — any non-JSON content will trigger a correction prompt,
costing you an extra retry turn.
```

Same block must appear at the top of `.claude/agents/code-reviewer.md`.

## JSON Completion Signals

Fields marked **(R)** are required — schema validation in `stop_validate_json.py` will reject the signal if missing. Fields marked **(O)** are optional.

**ID format:** all `id` fields (task and issue) must follow `"{phase_id}.{seq}"` — e.g. `"1.1"`, `"1.2"`, `"2.3"`. `phase_id` matches the enclosing phase; `seq` is 1-based and sequential within the phase. Task seq and issue seq are independent of each other.

**TASK_BUILD:**
```json
{
  "status": "complete",    
  "mode": "TASK_BUILD",   
  "phase_id": 1,           
  "tasks": [
    {"id": "1.1", "title": "Create User and Post models", "task_type": "database"},
    {"id": "1.2", "title": "Set up Flask app factory",    "task_type": "foundation"},
    {"id": "1.3", "title": "Implement POST /users endpoint", "task_type": "api"}
  ]
}
```
Wrapper: `status`(R), `mode`(R), `phase_id`(R), `tasks`(R)
Task item: `id`(R), `title`(R), `task_type`(R)

**EXECUTE (all tasks succeeded):**
```json
{
  "mode": "EXECUTE",
  "phase_id": 1,
  "tasks": [
    {"id": "1.1", "title": "Create User model",       "task_type": "database",   "status": "complete", "tdd_applied": true, "tdd_skipped": null,                      "files_changed": ["src/models.py", "tests/test_models.py"]},
    {"id": "1.2", "title": "Set up Flask app factory","task_type": "foundation", "status": "complete", "tdd_applied": null, "tdd_skipped": "config file — no logic", "files_changed": ["config/settings.py"]}
  ]
}
```

**EXECUTE (mixed results):**
```json
{
  "mode": "EXECUTE",
  "phase_id": 1,
  "tasks": [
    {"id": "1.1", "title": "Create User model",            "task_type": "database", "status": "complete", "tdd_applied": true, "tdd_skipped": null, "files_changed": ["src/models.py", "tests/test_models.py"]},
    {"id": "1.3", "title": "Implement POST /users endpoint","task_type": "api",      "status": "failed",   "tdd_applied": null, "tdd_skipped": null, "files_changed": [], "reason": "Cannot resolve circular import"}
  ]
}
```
Wrapper: `mode`(R), `phase_id`(R), `tasks`(R)
Task item: `id`(R), `title`(R), `task_type`(R), `status`(R), `files_changed`(R), `tdd_applied`(O), `tdd_skipped`(O), `reason`(O — required when `status="failed"`)

**FIX (all issues fixed):**
```json
{
  "mode": "FIX",
  "fixes": [
    {"id": "1.1", "severity": "CRITICAL", "title": "POST /users does not return 409 on duplicate email", "status": "fixed",    "files_changed": ["src/api/users.py", "tests/test_users.py"]},
    {"id": "1.2", "severity": "HIGH",     "title": "No rate limiting on POST /posts endpoint",          "status": "fixed",    "files_changed": ["src/api/posts.py", "tests/test_posts.py"]}
  ]
}
```

**FIX (mixed results, including deferred MEDIUM/LOW):**
```json
{
  "mode": "FIX",
  "fixes": [
    {"id": "1.1", "severity": "CRITICAL", "title": "POST /users does not return 409 on duplicate email", "status": "fixed",    "files_changed": ["src/api/users.py", "tests/test_users.py"]},
    {"id": "1.2", "severity": "HIGH",     "title": "No rate limiting on POST /posts endpoint",          "status": "open",     "files_changed": [], "reason": "Flask-Limiter not in requirements — cannot install without spec change"},
    {"id": "1.3", "severity": "MEDIUM",   "title": "Function exceeds 50 lines",                         "status": "deferred", "files_changed": []}
  ]
}
```
Wrapper: `mode`(R), `fixes`(R)
Fix item: `id`(R), `severity`(R), `title`(R), `status`(R), `files_changed`(R), `reason`(O — required when `status="open"`)
