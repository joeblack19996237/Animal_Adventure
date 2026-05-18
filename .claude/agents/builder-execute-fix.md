# EXECUTE / FIX / EVALUATE_TESTS modes

## Rules

Before writing any code, read and internalize these rule files:

- `.claude/rules/common/coding-guidelines.md` — behavioral guidelines: think before coding, simplicity first, surgical changes, goal-driven execution
- `.claude/rules/common/coding-standards.md` — universal standards: naming, error handling, no debug output, no hardcoded secrets, no bare `except:`, testing requirements

These rules are non-negotiable. Every line of code you write or modify must comply with them.

---

## TDD Workflow (EXECUTE mode)

**Step 1 — Assess applicability.** TDD is required unless the task is one of:
- Config/settings file (no logic)
- Migration file (schema only)
- `__init__.py` or pure scaffolding
- Static asset or data file

**Step 2 — If TDD applies**, follow the Red → Green → Refactor workflow in `.claude/skills/tdd-workflow/SKILL.md`. Git commit is handled automatically by `stop_git_commit.py` — do NOT run git commands.

For `tdd_slice` tasks, keep tests compact and representative. Do not enumerate every malformed field combination unless the task explicitly requires exhaustive validation. Prefer table-driven cases and keep each new test file under 250 lines by default.

**Step 3 — If TDD does not apply**, state reason in the signal: `"tdd_skipped": "config file — no logic to test"`

**Already satisfied implementation tasks:** If a task is already satisfied by existing tracked files, do not return an empty no-op signal. Return `"status": "complete"`, list the existing tracked files that satisfy the task in `files_changed`, and set `tdd_skipped` to explain that the task is already satisfied by existing tracked files.

---

## Completion Self-checks

**Before emitting signal in EXECUTE mode:**
- [ ] Read `.claude/rules/common/coding-guidelines.md` and `.claude/rules/common/coding-standards.md`
- [ ] All files named in the task description exist and are non-empty
- [ ] Text artifacts are UTF-8 without BOM, not UTF-16, and contain no NUL bytes
- [ ] Compile check passes for every new source file (see language guide for command)
- [ ] If TDD applied: test file exists in `tests/`, tests pass
- [ ] No bare `except:`, no `print()` debug statements, no `TODO` left in new code
- [ ] Code is minimal and surgical — no speculative features, no unrelated changes
- [ ] `files_changed` lists every file created or modified (hook uses this to stage and commit)
- [ ] If no file needed modification because existing tracked files already satisfy the task, `files_changed` lists those existing tracked files and `tdd_skipped` explains why no code change was needed
- [ ] **Security baseline** — no hardcoded secrets or API keys; all external input validated before use; subprocess calls use list form (not `shell=True` with user data); no `pickle.loads()` on untrusted data; no path traversal (user-controlled paths resolved and boundary-checked with `Path.resolve().is_relative_to(root)`)

**Before emitting signal in FIX mode (all CRITICAL/HIGH in one subprocess):**
- [ ] Read `.claude/rules/common/coding-guidelines.md` and `.claude/rules/common/coding-standards.md`
- [ ] Read ALL open issues from `review_report.md` before starting
- [ ] Fix each issue in severity order (CRITICAL first, then HIGH)
- [ ] Each fix is surgical — touches only what the issue requires, no adjacent cleanup
- [ ] For regression issues, treat `Dimension: Regression` as HIGH severity and fix the product behavior or legitimate test integration problem; do not delete, skip, xfail, or weaken regression coverage to make the command pass
- [ ] If regression evidence clearly points to harness/environment infrastructure (`.tmp`, `.pytest_cache`, `workspace/verification-tmp`, pytest collection `PermissionError`, missing command, timeout cleanup failure), do not modify product code; return the issue as `"open"` with a concise harness infra blocker reason
- [ ] For evaluation fixes, preserve all tests authored in `EVALUATE_TESTS`; do not delete, skip, xfail, weaken assertions, or change expected behavior merely to pass
- [ ] After all fixes: run the test command (see language guide) — no regressions introduced
- [ ] Text artifacts touched by fixes are UTF-8 without BOM and contain no NUL bytes
- [ ] Signal reports per-issue status: `"fixed"`, `"open"`, or `"deferred"` with reason for each open issue
- [ ] Each completed fix entry includes `files_changed`

**Before emitting signal in EVALUATE_TESTS mode:**
- [ ] Read all evaluation issues and their `test_cases`
- [ ] Write only automated test files needed to reproduce the evaluation issues; do not modify application/source/config files
- [ ] Each authored test should fail against the current unfixed code and pass only after the issue is fixed
- [ ] Run the targeted command for each authored test if possible
- [ ] Signal reports per-test status: `"authored"` or `"open"` with reason for each open test
- [ ] Each authored test entry includes `files_changed` and the targeted `command`

---

## Correction turn

**Correction turn (stop hook requests JSON-only output)**: If the stop hook asks you to correct a non-JSON response, the correction turn must include every required field: `"mode": "EXECUTE"`, `"phase_id": <integer from the prompt, not null>`, and a `"tasks"` array containing the current task entry. Do not output `"tasks": []`; an empty array loses the active task and causes the harness to HALT.

---

## JSON Signals

**ID format:** `"{phase_id}.{seq}"` — e.g. `"1.1"`, `"1.2"`, `"2.3"`. Phase and sequence are 1-based.

### EXECUTE (all succeeded)
```json
{
  "mode": "EXECUTE",
  "phase_id": 1,
  "tasks": [
    {"id": "1.1", "title": "Create User model",        "task_type": "database",   "status": "complete", "tdd_applied": true,  "tdd_skipped": null,                     "files_changed": ["src/models.py", "tests/test_models.py"]},
    {"id": "1.2", "title": "Set up Flask app factory", "task_type": "foundation", "status": "complete", "tdd_applied": null,  "tdd_skipped": "config file — no logic", "files_changed": ["config/settings.py"]}
  ]
}
```

### EXECUTE (mixed results)
```json
{
  "mode": "EXECUTE",
  "phase_id": 1,
  "tasks": [
    {"id": "1.1", "title": "Create User model",             "task_type": "database", "status": "complete", "tdd_applied": true, "tdd_skipped": null, "files_changed": ["src/models.py", "tests/test_models.py"]},
    {"id": "1.3", "title": "Implement POST /users endpoint", "task_type": "api",     "status": "failed",   "tdd_applied": null, "tdd_skipped": null, "files_changed": [], "reason": "Cannot resolve circular import"}
  ]
}
```

Wrapper: `mode`(R), `phase_id`(R), `tasks`(R)
Task item: `id`(R), `title`(R), `task_type`(R), `status`(R), `files_changed`(R), `tdd_applied`(O), `tdd_skipped`(O), `reason`(O — required when `status="failed"`)

> **Correction turn** (stop hook requires re-output of JSON): if the stop hook rejects a response
> because it is not pure JSON, the correction turn **must** include all required fields:
> `"mode": "EXECUTE"`, `"phase_id": <integer from the prompt — never null>`, and a `"tasks"`
> array containing the current task entry. **Never output `"tasks": []`** — an empty array drops
> the active task and causes the harness to HALT.

### FIX (all fixed)
```json
{
  "mode": "FIX",
  "fixes": [
    {"id": "1.1", "severity": "CRITICAL", "title": "POST /users does not return 409 on duplicate email", "status": "fixed", "files_changed": ["src/api/users.py", "tests/test_users.py"]},
    {"id": "1.2", "severity": "HIGH",     "title": "No rate limiting on POST /posts endpoint",          "status": "fixed", "files_changed": ["src/api/posts.py", "tests/test_posts.py"]}
  ]
}
```

### FIX (mixed results)
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

### EVALUATE_TESTS
```json
{
  "mode": "EVALUATE_TESTS",
  "phase_id": 17,
  "iteration": 1,
  "tests": [
    {
      "id": "17.1-t1",
      "issue_id": "17.1",
      "status": "authored",
      "files_changed": ["tests/test_notes.py"],
      "command": ["pytest", "tests/test_notes.py", "-q"]
    }
  ]
}
```

Wrapper: `mode`(R), `phase_id`(R), `iteration`(R), `tests`(R)
Test item: `id`(R), `issue_id`(R), `status`(R), `files_changed`(R), `command`(R), `reason`(O — required when `status="open"`)
