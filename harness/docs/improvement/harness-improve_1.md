# Harness Improvement 1: Spec Validation + TDD Task Ordering

## Context

Two independent, additive quality gates:

1. **Spec completeness check** — harness currently starts building with no structural check on the spec. Result: wasted build cycles when the spec is missing key sections (architecture, verification criteria, etc.).
2. **TDD task ordering enforcement** — `spec_frontend.md` E2E run showed TDD was skipped silently. The harness records `tdd_applied` but never enforces that test tasks must be generated at TASK_BUILD time and must precede implementation tasks. The existing constraint is soft (prompt-based only).

---

## Feature A — Spec Completeness Validation

### Design decisions

| Decision | Choice |
|----------|--------|
| App type detection | `--app-type cli\|web` CLI flag |
| Section name matching | Fuzzy full-text keyword search (case-insensitive, any keyword in group suffices) |
| On failure | Print missing labels + `sys.exit(1)` |
| Keywords configuration | `harness/spec_validation.json` — no hardcoded keywords in Python code |
| Data model for CLI | Conditional: required only if spec already contains data-related keywords (has data but no dedicated section) |
| `parse_spec()` signature | Unchanged — `check_spec_completeness()` reads spec files itself |

### New config file: `harness/spec_validation.json`

```json
{
  "app_types": ["cli", "web"],

  "common_requirements": [
    {
      "label": "architecture",
      "keywords": ["architecture"],
      "mode": "required"
    },
    {
      "label": "workflow",
      "keywords": ["workflow", "data flow", "process flow", "user flow", "game flow", "sequence diagram", "state machine", "flow"],
      "mode": "required"
    },
    {
      "label": "requirements",
      "keywords": ["requirement", "requirements", "functional requirement", "user story", "user case"],
      "mode": "required"
    },
    {
      "label": "verification / completion criteria",
      "keywords": ["verification", "completion criteria", "acceptance criteria", "test plan", "done criteria"],
      "mode": "required"
    }
  ],

  "phase1_setup_keywords": ["setup", "foundation", "scaffold", "initialization", "bootstrap", "dependencies"],
  "phase1_domain_disqualifiers": ["database", "db", "api", "server", "frontend", "backend", "client", "ui", "websocket", "auth", "model", "schema", "cache"],

  "app_type_requirements": {
    "web": [
      {
        "label": "api / service",
        "keywords": ["api", "endpoint", "route", "websocket", "rest", "http"],
        "mode": "required"
      },
      {
        "label": "database",
        "keywords": ["database", "db", "schema", "sqlite", "postgres", "mysql", "mongodb"],
        "mode": "required"
      },
      {
        "label": "data model",
        "keywords": ["data model", "model", "entity", "schema"],
        "mode": "required"
      },
      {
        "label": "frontend / client",
        "keywords": ["frontend", "client", "ui", "scene", "view", "page", "component"],
        "mode": "required"
      },
      {
        "label": "log design",
        "keywords": ["log", "logging", "logger", "logback", "structlog"],
        "mode": "required"
      }
    ],
    "cli": [
      {
        "label": "data model",
        "keywords": ["data model", "model", "entity", "schema"],
        "mode": "conditional",
        "condition_keywords": ["database", "schema", "model", "sqlite", "postgres", "mysql"]
      }
    ]
  }
}
```

**Mode semantics:**
- `"required"` — always checked; missing → added to error list → `sys.exit(1)`
- `"conditional"` — checked only if any `condition_keywords` found in spec text; missing → print `[WARN]`, no exit

### Modified files

**`harness/spec_validation.json`** (new file)
- Contains the config above

**`harness/spec.py`** — add one new function, no existing code changed:

```python
def check_spec_completeness(spec_path: str, app_type: str, config_path: Path) -> list[str]:
    """
    Return list of missing required section labels. Empty list = all checks passed.
    Reads spec files itself (single file or all *.md in directory).
    Logs [WARN] for optional/conditional failures without adding to error list.
    Two layers:
      Layer 1 — keyword in headings: searches only lines starting with '#'.
                Ensures a dedicated section exists, not just a passing mention.
      Layer 2 — Phase 1 structural check: Phase 1 title must contain a setup keyword
                and must NOT contain a domain-specific qualifier.
    """
    path = Path(spec_path)
    if path.is_dir():
        spec_text = "\n\n".join(
            f.read_text(encoding="utf-8") for f in sorted(path.glob("*.md"))
        )
    else:
        spec_text = path.read_text(encoding="utf-8")

    # Extract only heading lines (lines starting with one or more '#')
    headings_text = "\n".join(
        line for line in spec_text.splitlines()
        if re.match(r"^#{1,6}\s+", line)
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing: list[str] = []

    def _any_keyword(keywords: list[str]) -> bool:
        pattern = "|".join(re.escape(k) for k in keywords)
        return bool(re.search(pattern, headings_text, re.IGNORECASE))

    # Layer 1: required section heading checks
    for req in config["common_requirements"]:
        if not _any_keyword(req["keywords"]):
            if req["mode"] == "required":
                missing.append(req["label"])

    for req in config["app_type_requirements"].get(app_type, []):
        if req["mode"] == "required":
            if not _any_keyword(req["keywords"]):
                missing.append(req["label"])
        elif req["mode"] == "conditional":
            if _any_keyword(req["condition_keywords"]) and not _any_keyword(req["keywords"]):
                print(f"[WARN] Spec has data-related content but no '{req['label']}' section.")

    # Layer 2: Phase 1 must be a project-level setup/foundation phase.
    # Valid:   "Project Foundation", "Bootstrap", "Project Setup", "Game Foundation"
    # Invalid: "Database Foundation" (domain word), "Frontend Scaffold" (domain word)
    phases = _extract_phases(spec_text)
    if phases:
        phase1_title = phases[0]["title"].lower()
        setup_kws = config["phase1_setup_keywords"]
        disqualifiers = config["phase1_domain_disqualifiers"]
        has_setup = any(kw in phase1_title for kw in setup_kws)
        has_domain = any(kw in phase1_title for kw in disqualifiers)
        if not has_setup or has_domain:
            missing.append(
                f"Phase 1 title '{phases[0]['title']}' does not indicate a project-level setup phase. "
                f"Phase 1 must contain a setup keyword ({', '.join(setup_kws)}) "
                f"without domain-specific qualifiers ({', '.join(disqualifiers)})."
            )
    # Note: if phases is empty, validate_spec() will already have caught it before this call.

    return missing
```

**Design note — `language` vs `app_type`:**
`language` (python | typescript) selects the language profile which drives agent selection (`code-builder.md` vs `frontend-builder.md`). It is retained unchanged. `app_type` (cli | web) is an independent new field that controls which spec sections are required. Both fields coexist in `state.json`. On resume, both are read back from state using the same pattern: use the CLI-supplied value if it differs from the default, otherwise fall back to the saved state value.

**`harness/harness.py`** — five additions:

1. CLI argument:
   ```python
   parser.add_argument("--app-type", choices=["cli", "web"], default="cli",
                       help="App type for spec completeness validation")
   ```

2. Resume branch — read `app_type` back from state (mirrors the existing `language` pattern):
   ```python
   # inside the `if args.resume:` branch, after language resolution
   app_type = args.app_type if args.app_type != "cli" else state.get("app_type", "cli")
   state["app_type"] = app_type
   ```

3. First-run branch — persist `app_type` in state before spec check:
   ```python
   # inside the `else:` (first-run) branch, alongside state["language"] = args.language
   state["app_type"] = args.app_type
   ```

4. First-run branch — spec completeness check after `validate_spec()`:
   ```python
   config_path = Path(__file__).parent / "spec_validation.json"
   missing = check_spec_completeness(args.spec_file_or_dir, state["app_type"], config_path)
   if missing:
       print(f"[ERROR] Spec missing required sections for a '{state['app_type']}' app:")
       for label in missing:
           print(f"  - {label}")
       print(f"\nFix these in: {args.spec_file_or_dir}\nThen re-run the harness.")
       sys.exit(1)
   ```

5. `_do_task_build()` task shell — add `tdd_mode` field read from TASK_BUILD signal:
   ```python
   # inside the list comprehension at state_phase["tasks"] = [...]
   "tdd_mode": t.get("tdd_mode"),
   ```
   Full shell entry (replacing the existing dict comprehension):
   ```python
   {
       "id": t["id"],
       "title": t["title"],
       "task_type": t["task_type"],
       "description": t.get("description", ""),
       "refs": t.get("refs", []),
       "status": "pending",
       "attempts": 0,
       "verify_fails": 0,
       "tdd_mode": t.get("tdd_mode"),
       "tdd_applied": None,
       "tdd_skipped": None,
       "files_changed": [],
       "last_error": [],
   }
   ```

**Error output example:**
```
[ERROR] Spec missing required sections for a 'web' app:
  - workflow
  - verification / completion criteria
  - log design

Fix these in: docs/frontend/spec_frontend.md
Then re-run the harness.
```

---

## Feature B — TDD Task Ordering Enforcement

### Problem

TASK_BUILD produces a flat task list with no required ordering of test-creation vs implementation tasks. The Stop hook validates JSON schema (field types) only — not semantic ordering. Agents can and do skip test tasks or generate them after implementation tasks.

### New flow

```
TASK_BUILD agent runs
  → produces task list with tdd_mode field on each task
  → each TDD-applicable unit is a strict triplet: test_first → implementation → unit_test

Stop hook (stop_validate_json.py) validates:
  1. Schema: tdd_mode field present and valid on each task
  2. Triplet ordering (Phase 2+ only): walks a state machine over the task list,
     ensuring every implementation is bracketed by test_first before it
     and unit_test immediately after it

If validation fails → hook exits 1 → correction prompt → agent regenerates task list
If valid → harness stores tasks and proceeds to EXECUTE
```

### New `tdd_mode` field

Required field on **every task in every phase** (including Phase 1) in TASK_BUILD signal. Single schema for all phases — no split description in agent.md.

| Value | Meaning |
|-------|---------|
| `"test_first"` | Writes failing tests only — no implementation code |
| `"implementation"` | Writes implementation to make the preceding `test_first` tests pass |
| `"unit_test"` | Runs the language-appropriate test command on the specific test file, verifies all pass and coverage ≥ 80%; no new code written, `files_changed: []` |
| `"exempt"` | TDD not applicable (DDL, config files, static assets in Phase 2+); `tdd_skipped` must be non-null |

**Language-specific test commands for `unit_test` tasks:**

| Agent | Test command in task description |
|-------|----------------------------------|
| `code-builder` (Python) | `pytest <test_file> --cov=<module>` |
| `frontend-builder` (TypeScript) | `npx vitest run <test_file>` |

Each TDD-applicable unit must form a strict triplet in order: **`test_first` → `implementation` → `unit_test`**. `exempt` tasks are independent and may appear anywhere.

### Stop hook ordering validation

Ordering validation is **skipped entirely for `phase_id == 1`** (setup phase, guaranteed by `check_spec_completeness()`).

For Phase 2+, a **state machine** walks the task list (skipping `exempt` tasks) and enforces the strict triplet sequence:

```
States: IDLE → AFTER_TEST_FIRST → AFTER_IMPL → (back to IDLE on unit_test)

Transitions:
  IDLE            + test_first    → AFTER_TEST_FIRST
  IDLE            + implementation → ERROR: missing test_first before implementation
  IDLE            + unit_test     → ERROR: unit_test with no preceding implementation
  AFTER_TEST_FIRST + test_first    → AFTER_TEST_FIRST  (multiple test tasks allowed)
  AFTER_TEST_FIRST + implementation → AFTER_IMPL
  AFTER_TEST_FIRST + unit_test    → ERROR: unit_test before implementation
  AFTER_IMPL      + unit_test     → IDLE  ✓ triplet complete
  AFTER_IMPL      + test_first    → ERROR: missing unit_test after implementation
  AFTER_IMPL      + implementation → ERROR: missing unit_test after previous implementation

End of list:
  state == AFTER_TEST_FIRST → ERROR: test_first has no following implementation + unit_test
  state == AFTER_IMPL       → ERROR: implementation has no following unit_test
```

In `stop_validate_json.py`, TASK_BUILD mode, after existing schema validation:

```python
# Phase 1 (setup/foundation) is auto-exempt from ordering validation.
if phase_id == 1:
    pass  # skip ordering check entirely
else:
    VALID_TDD_MODES = {"test_first", "implementation", "unit_test", "exempt"}
    ordering_errors: list[str] = []
    state = "IDLE"  # IDLE | AFTER_TEST_FIRST | AFTER_IMPL
    last_impl_id = None

    for task in tasks:
        tdd_mode = task.get("tdd_mode")
        tid = task.get("id", "?")
        ttitle = task.get("title", "")

        if tdd_mode not in VALID_TDD_MODES:
            ordering_errors.append(
                f"Task {tid} has invalid tdd_mode: {tdd_mode!r}. "
                f"Use one of: {', '.join(sorted(VALID_TDD_MODES))}."
            )
            continue

        if tdd_mode == "exempt":
            if not task.get("tdd_skipped"):
                ordering_errors.append(
                    f"Task {tid} has tdd_mode='exempt' but no tdd_skipped reason."
                )
            continue  # exempt tasks don't affect state machine

        if tdd_mode == "test_first":
            if state == "AFTER_IMPL":
                ordering_errors.append(
                    f"Task {tid} ({ttitle!r}): 'test_first' follows 'implementation' "
                    f"task {last_impl_id} with no 'unit_test' in between."
                )
            state = "AFTER_TEST_FIRST"

        elif tdd_mode == "implementation":
            if state == "IDLE":
                ordering_errors.append(
                    f"Task {tid} ({ttitle!r}): 'implementation' has no preceding 'test_first'."
                )
            elif state == "AFTER_IMPL":
                ordering_errors.append(
                    f"Task {tid} ({ttitle!r}): 'implementation' follows task {last_impl_id} "
                    f"with no 'unit_test' in between."
                )
            state = "AFTER_IMPL"
            last_impl_id = tid

        elif tdd_mode == "unit_test":
            if state != "AFTER_IMPL":
                ordering_errors.append(
                    f"Task {tid} ({ttitle!r}): 'unit_test' has no preceding 'implementation'."
                )
            state = "IDLE"

    if state == "AFTER_TEST_FIRST":
        ordering_errors.append(
            "Phase ends with a 'test_first' task but no following 'implementation' and 'unit_test'."
        )
    elif state == "AFTER_IMPL":
        ordering_errors.append(
            f"Phase ends after 'implementation' task {last_impl_id} with no following 'unit_test'."
        )

    if ordering_errors:
        for err in ordering_errors:
            print(f"[SIGNAL ERROR] TDD ordering: {err}")
        sys.exit(1)
```

### Updated TASK_BUILD JSON examples

**Phase 1 (setup — ordering validation skipped entirely):**
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
      "tdd_skipped": "project scaffold — no logic to test",
      "description": "Create pyproject.toml, requirements.txt, server/ package skeleton",
      "refs": []
    }
  ]
}
```

**Phase 2+ (strict triplets enforced):**
```json
{
  "status": "complete",
  "mode": "TASK_BUILD",
  "phase_id": 2,
  "tasks": [
    {
      "id": "2.1",
      "title": "Write failing tests for GameRepo",
      "task_type": "testing",
      "tdd_mode": "test_first",
      "tdd_skipped": null,
      "description": "Write pytest tests: create_game, get_game, update_state in tests/test_game_repo.py",
      "refs": []
    },
    {
      "id": "2.2",
      "title": "Implement GameRepo",
      "task_type": "database",
      "tdd_mode": "implementation",
      "tdd_skipped": null,
      "description": "Implement to make task 2.1 tests pass",
      "refs": []
    },
    {
      "id": "2.3",
      "title": "Run and verify GameRepo tests",
      "task_type": "testing",
      "tdd_mode": "unit_test",
      "tdd_skipped": null,
      "description": "Run pytest tests/test_game_repo.py --cov=server/models/game; verify all pass, coverage ≥ 80%",
      "refs": []
    },
    {
      "id": "2.4",
      "title": "Write failing tests for PlayerRepo",
      "task_type": "testing",
      "tdd_mode": "test_first",
      "tdd_skipped": null,
      "description": "Write pytest tests: create, get, list_by_game, update_score in tests/test_player_repo.py",
      "refs": []
    },
    {
      "id": "2.5",
      "title": "Implement PlayerRepo",
      "task_type": "database",
      "tdd_mode": "implementation",
      "tdd_skipped": null,
      "description": "Implement to make task 2.4 tests pass",
      "refs": []
    },
    {
      "id": "2.6",
      "title": "Run and verify PlayerRepo tests",
      "task_type": "testing",
      "tdd_mode": "unit_test",
      "tdd_skipped": null,
      "description": "Run pytest tests/test_player_repo.py --cov=server/models/player; verify all pass, coverage ≥ 80%",
      "refs": []
    },
    {
      "id": "2.7",
      "title": "Create database schema",
      "task_type": "foundation",
      "tdd_mode": "exempt",
      "tdd_skipped": "DDL file — no logic to test",
      "description": "CREATE TABLE statements in server/db/schema.sql",
      "refs": []
    }
  ]
}
```

**TypeScript equivalent (frontend-builder — same triplet structure, different test command):**
```json
{
  "id": "2.3",
  "title": "Run and verify GameClient tests",
  "task_type": "testing",
  "tdd_mode": "unit_test",
  "tdd_skipped": null,
  "description": "Run npx vitest run tests/GameClient.test.ts; verify all pass, coverage ≥ 80%",
  "refs": []
}
```

---

## Complete file impact list

| File | Type | Change |
|------|------|--------|
| `harness/spec_validation.json` | **NEW** | App type + section keyword config |
| `harness/spec.py` | Modify | Add `check_spec_completeness()` |
| `harness/harness.py` | Modify | Add `--app-type` flag; handle `app_type` in both resume and first-run branches; call spec check; add `tdd_mode` to `_do_task_build()` task shell |
| `harness/state.py` | Modify | `_apply_task_fields()` allowed set: add `"tdd_mode"`; task shell default: add `"tdd_mode": None` |
| `.claude/hooks/stop_validate_json.py` | Modify | TASK_BUILD schema: add `tdd_mode`; add ordering validation block |
| `.claude/agents/code-builder.md` | Modify | TASK_BUILD section: add `tdd_mode` field, triplet ordering rule, `unit_test` uses `pytest`, updated JSON example |
| `.claude/agents/frontend-builder.md` | Modify | TASK_BUILD section: same as code-builder.md but `unit_test` uses `npx vitest run` |

**Specific instruction block to add to both agent TASK_BUILD sections** (language-specific test command differs):

For **`code-builder.md`**:
```
## TDD task ordering (TASK_BUILD mode)

For every TDD-applicable module in Phase 2+, generate exactly three tasks in this order:

1. `tdd_mode: "test_first"` — write the failing test file only
2. `tdd_mode: "implementation"` — write implementation to make those tests pass
3. `tdd_mode: "unit_test"` — run `pytest <test_file> --cov=<module>`; verify all pass, coverage ≥ 80%;
   no code written, files_changed: []

Use `tdd_mode: "exempt"` (with non-null `tdd_skipped`) for DDL files, config files, and static assets.
These may appear anywhere in the task list and do not affect triplet ordering.

Phase 1 is exempt from this ordering rule — all Phase 1 tasks use `tdd_mode: "exempt"`.

The Stop hook validates this ordering. An `implementation` task without a preceding `test_first`,
or without a following `unit_test`, will be rejected and you will receive a correction prompt.
```

For **`frontend-builder.md`** — identical except:
```
3. `tdd_mode: "unit_test"` — run `npx vitest run <test_file>`; verify all pass, coverage ≥ 80%;
   no code written, files_changed: []
```

**No changes to:** `agents.py`, `fix.py`, `verify.py`, `lang.py`, reviewer agents, `calibrate.py`

---

## Testing Plan

### 1. New unit tests — Feature A: `harness/tests/unit/test_spec_completeness.py`

Tests follow existing pattern in `test_spec.py`: use `tmp_path`, write spec files, call function directly.

```python
# test_spec_completeness.py test cases:

# --- Layer 1: keyword in headings ---

def test_heading_match_passes(tmp_path):
    # Spec with "## System Architecture" — "architecture" found in heading
    # Expected: architecture NOT in missing list

def test_body_text_only_does_not_pass(tmp_path):
    # Spec with "architecture" only in body paragraph, no heading
    # Expected: "architecture" IN missing list (headings-only search)

def test_bold_text_does_not_pass(tmp_path):
    # Spec with "**Requirements:**" in body (bold, not heading)
    # Expected: "requirements" IN missing list

def test_required_section_missing(tmp_path):
    # Spec with no workflow-related heading at all
    # Expected: "workflow" in result list

def test_all_common_sections_present_passes(tmp_path):
    # Spec has ## Architecture, ## Workflow, ## Requirements, ## Verification headings
    # Expected: empty list returned

def test_web_app_missing_log_design(tmp_path):
    # web app spec with no ## Log or ## Logging heading
    # Expected: "log design" in missing list

def test_web_app_all_sections_present(tmp_path):
    # web app spec with all required headings
    # Expected: empty list

def test_phase_title_heading_counts_as_section(tmp_path):
    # Spec with "## Phase 4: REST Lobby API" — "api" keyword in phase title heading
    # Expected: "api / service" NOT in missing list (phase titles are valid headings)

def test_cli_data_model_not_triggered_without_data_heading(tmp_path):
    # CLI spec with no database/schema/model heading
    # Expected: "data model" NOT in missing list (conditional not triggered)

def test_cli_data_model_warns_when_data_heading_present(tmp_path, capsys):
    # CLI spec has "## Database Schema" but no "## Data Model" heading
    # Expected: [WARN] printed, NOT in error list

def test_spec_directory_reads_all_md_files(tmp_path):
    # spec dir: ## Architecture in one .md, ## Workflow in another
    # Expected: both found, neither missing

def test_unknown_app_type_returns_only_common_requirements(tmp_path):
    # app_type not in app_type_requirements → only common headings checked
    # Expected: no KeyError, returns only common failures

# --- Layer 2: Phase 1 setup title check ---

def test_phase1_project_foundation_passes(tmp_path):
    # Spec with "## Phase 1: Project Foundation" — has_setup=True, has_domain=False
    # Expected: no Phase 1 error

def test_phase1_bootstrap_passes(tmp_path):
    # Spec with "## Phase 1: Bootstrap" — has_setup=True, has_domain=False
    # Expected: no Phase 1 error

def test_phase1_project_setup_passes(tmp_path):
    # Spec with "## Phase 1: Project Setup" — has_setup=True, has_domain=False
    # Expected: no Phase 1 error

def test_phase1_game_foundation_passes(tmp_path):
    # Spec with "## Phase 1: Game Foundation" — "game" is NOT a disqualifier
    # Expected: no Phase 1 error (game projects can have a foundation phase)

def test_phase1_database_foundation_fails(tmp_path):
    # Spec with "## Phase 1: Database Foundation" — has_domain=True (database)
    # Expected: Phase 1 error in missing list

def test_phase1_frontend_scaffold_fails(tmp_path):
    # Spec with "## Phase 1: Frontend Scaffold" — has_domain=True (frontend)
    # Expected: Phase 1 error in missing list

def test_phase1_game_logic_fails(tmp_path):
    # Spec with "## Phase 1: Game Logic" — no setup keyword at all
    # Expected: Phase 1 error in missing list

def test_phase1_title_check_case_insensitive(tmp_path):
    # Spec with "## Phase 1: PROJECT INITIALIZATION" — uppercase
    # Expected: no Phase 1 error

def test_no_phases_in_spec_skips_phase1_check(tmp_path):
    # Spec with no Phase headers at all (validate_spec catches this first)
    # Expected: phases list is empty, Layer 2 skipped gracefully, no IndexError
```

### 2. New unit tests — Feature B: `harness/tests/unit/test_tdd_ordering.py`

Tests run Stop hook as subprocess via `run_hook()` (same pattern as `test_hooks.py`).

```python
# test_tdd_ordering.py test cases:

# --- Phase 1 auto-exempt ---

def test_phase1_entirely_exempt_from_ordering(tmp_path):
    # phase_id=1, tasks: [exempt(1.1, tdd_skipped="scaffold")]
    # Expected: hook exit 0

def test_phase1_implementation_without_test_first_passes(tmp_path):
    # phase_id=1, tasks: [implementation(1.1)] — would fail in Phase 2+
    # Expected: hook exit 0 (Phase 1 skips all ordering checks)

# --- Phase 2+ valid triplets ---

def test_phase2_complete_triplet_passes(tmp_path):
    # phase_id=2, tasks: [test_first(2.1), implementation(2.2), unit_test(2.3)]
    # Expected: hook exit 0

def test_phase2_two_consecutive_triplets_pass(tmp_path):
    # phase_id=2, tasks: [test_first(2.1), implementation(2.2), unit_test(2.3),
    #                      test_first(2.4), implementation(2.5), unit_test(2.6)]
    # Expected: hook exit 0

def test_phase2_exempt_task_between_triplets_passes(tmp_path):
    # phase_id=2, tasks: [test_first, implementation, unit_test,
    #                      exempt(tdd_skipped="DDL"), test_first, implementation, unit_test]
    # Expected: hook exit 0 (exempt tasks don't affect state machine)

def test_phase2_multiple_test_first_before_implementation_passes(tmp_path):
    # phase_id=2, tasks: [test_first(2.1), test_first(2.2), implementation(2.3), unit_test(2.4)]
    # Expected: hook exit 0 (multiple test_first tasks allowed before implementation)

# --- Phase 2+ violations ---

def test_phase2_missing_test_first_fails(tmp_path):
    # phase_id=2, tasks: [implementation(2.1), unit_test(2.2)]
    # Expected: hook exit 1, "has no preceding 'test_first'"

def test_phase2_missing_unit_test_fails(tmp_path):
    # phase_id=2, tasks: [test_first(2.1), implementation(2.2)]  — no unit_test
    # Expected: hook exit 1, "Phase ends after 'implementation' ... with no following 'unit_test'"

def test_phase2_unit_test_before_implementation_fails(tmp_path):
    # phase_id=2, tasks: [test_first(2.1), unit_test(2.2), implementation(2.3)]
    # Expected: hook exit 1, "'unit_test' has no preceding 'implementation'"

def test_phase2_test_first_after_implementation_without_unit_test_fails(tmp_path):
    # phase_id=2, tasks: [test_first(2.1), implementation(2.2), test_first(2.3), ...]
    # Expected: hook exit 1, "'test_first' follows 'implementation' ... with no 'unit_test'"

def test_phase2_exempt_missing_reason_fails(tmp_path):
    # phase_id=2, tasks: [exempt(2.1, tdd_skipped=null)]
    # Expected: hook exit 1

def test_phase2_invalid_tdd_mode_value_fails(tmp_path):
    # phase_id=2, tasks: [task with tdd_mode="wrong_value"]
    # Expected: hook exit 1

def test_phase2_missing_tdd_mode_field_fails(tmp_path):
    # phase_id=2, tasks: [task with no tdd_mode key]
    # Expected: hook exit 1

def test_phase2_phase_ends_after_test_first_only_fails(tmp_path):
    # phase_id=2, tasks: [test_first(2.1)]  — no implementation or unit_test follows
    # Expected: hook exit 1, "Phase ends with a 'test_first' task but no following..."

# --- Regression ---

def test_execute_mode_signal_unaffected_by_tdd_changes(tmp_path):
    # mode=EXECUTE signal — no tdd_mode field
    # Expected: hook exit 0 (EXECUTE validation unchanged)
```

### 3. Updated existing tests

**`harness/tests/unit/test_spec.py`** — existing tests unchanged (no signature change to `parse_spec()`). No modifications needed.

**`harness/tests/unit/test_hooks.py`** — existing `test_stop_validate_json_*` tests:
- `test_stop_validate_json_valid_execute` — unchanged (EXECUTE mode, not TASK_BUILD)
- Add: valid TASK_BUILD signal with `tdd_mode` fields → exit 0
- Add: TASK_BUILD signal with ordering violation → exit 1

**`harness/tests/conftest.py`** — add `"tdd_mode": None` to default task dict in fixtures.

**`harness/tests/integration/test_state_machine.py`** — add `"tdd_mode": None` to task dicts in test data.

**`harness/tests/integration/test_resume.py`** — add `"tdd_mode": None` to task dicts in test data.

**`harness/tests/unit/test_fix.py`** — add `"tdd_mode": None` to task dicts in test data.

### 4. Regression testing

After all changes, run full existing test suite from project root:

```bash
cd D:\AI\claude_code\autonomous-dev-harness
pytest harness/tests/ -v --tb=short
```

All existing tests must pass with zero regressions. The `tdd_mode: None` additions to fixtures are backward-compatible — the new field is stored but not validated in EXECUTE/FIX modes.

### 5. Integration test with `docs/backend/spec_backend.md`

**Step 1 — Verify spec completeness check (expected to FAIL with multiple missing sections):**
```bash
python harness/harness.py docs/backend/spec_backend.md --language python --app-type web
```

`spec_backend.md` was analysed against `spec_validation.json`. See "Full expected error output" below for the authoritative result.

Headings present in `spec_backend.md` (Layer 1 search target):
```
# Project Spec: Multiplayer Coin Rush
## Harness Invocation (two runs, in order)
## Architecture
## Phase 1: Database Foundation
## Phase 2: Game Logic
## Phase 3: WebSocket Server
## Phase 4: REST Lobby API
```

Layer 1 heading check results:
- `architecture` ✅ — `## Architecture`
- `workflow` ❌ — no heading contains workflow/flow/state machine keywords
- `requirements` ❌ — `**Requirements:**` is bold text in body, not a heading
- `verification` ❌ — no heading with verification/test plan keywords
- `api / service` ✅ — `## Phase 4: REST Lobby API` contains "api"; `## Phase 3: WebSocket Server` contains "websocket"
- `database` ✅ — `## Phase 1: Database Foundation` contains "database"
- `data model` ❌ — no heading contains "model", "entity", or "data model"
- `frontend / client` ❌ — no heading contains frontend/client/ui keywords
- `log design` ❌ — no heading contains log/logging keywords

Layer 2 Phase 1 title check:
- `## Phase 1: Database Foundation` → has_setup=True ("foundation") BUT has_domain=True ("database") → ❌

Full expected error output:
```
[ERROR] Spec missing required sections for a 'web' app:
  - workflow
  - requirements
  - verification / completion criteria
  - data model
  - frontend / client
  - log design
  - Phase 1 title 'Database Foundation' does not indicate a project-level setup phase. ...
```

This FAIL is **the correct and expected result** — `spec_backend.md` is an incomplete spec that should be fixed before running the harness. The integration test validates that the feature correctly identifies the gaps.

**Step 1b — After fixing all missing sections in `spec_backend.md`:**

Add all missing sections to `spec_backend.md`: `## Workflow`, `## Requirements`, `## Verification Plan`, `## Data Model`, `## Frontend / Client`, `## Log Design`. Also rename `## Phase 1: Database Foundation` to `## Phase 1: Project Foundation` (or add a neutral setup phase before it) to fix the Phase 1 title check.

Then re-run:
```bash
python harness/harness.py docs/backend/spec_backend.md --language python --app-type web --max-phase 1
```
Expected: spec check passes, harness proceeds to TASK_BUILD for Phase 1. Phase 1 is auto-exempt from TDD ordering validation in the stop hook.

**Step 2 — Verify TDD ordering enforcement:**

Using `--resume` from an existing state or with `--max-phase 1`:
```bash
python harness/harness.py docs/backend/spec_backend.md --language python --app-type web --max-phase 1
```

Observe TASK_BUILD output:
- Agent should generate tasks with `tdd_mode` fields
- If agent skips `tdd_mode` or orders implementation before test_first → Stop hook rejects → correction prompt → agent retries

**Step 3 — Verify backward compatibility of `--app-type` default:**
```bash
python harness/harness.py docs/backend/spec_backend.md --language python
# (no --app-type, defaults to "cli")
```
Expected: only common requirements checked (no web-specific checks), harness proceeds normally.

---

## Implementation order

1. Create `harness/spec_validation.json`
2. Add `check_spec_completeness()` to `harness/spec.py` + unit tests
3. Add `--app-type` and spec check call to `harness/harness.py`
4. Run Feature A tests + regression suite
5. Add `tdd_mode` to `harness/state.py` allowed fields and task shell default
6. Update fixture files with `"tdd_mode": None`
7. Update `stop_validate_json.py` with ordering validation + schema change
8. Update `code-builder.md` and `frontend-builder.md` TASK_BUILD sections
9. Run Feature B tests + regression suite
10. Integration test with `docs/backend/spec_backend.md`
