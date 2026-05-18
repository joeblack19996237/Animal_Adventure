# Plan: EVALUATE Mode — E2E Testing Agent for Autonomous Dev Harness

## Context

The harness currently runs: TASK_BUILD → EXECUTING → REVIEWING → FIXING → NEXT_PHASE → CLEANUP → COMPLETE.
No holistic E2E verification happens after all phases are built. We add a new final stage — EVALUATING — where a new `evaluator` agent exercises the fully-built application using Playwright, scores it against a rubric, and drives exactly 3 evaluate iterations (always all 3, regardless of verdict).

---

## Workflow Change

```
... CLEANUP → EVALUATING (iter 1) → [FIX if BLOCK] → EVALUATING (iter 2) → [FIX if BLOCK] → EVALUATING (iter 3)
                                                                              ├── final verdict APPROVE → COMPLETE
                                                                              └── final verdict BLOCK  → HALTED
```

**Key behavior:** All 3 evaluate iterations always run. After each:
- BLOCK verdict → builder runs FIX mode, then next iteration
- APPROVE verdict → no fix needed, next iteration runs anyway (deeper coverage pass)

After the **3rd iteration**:
- APPROVE → `HarnessState.COMPLETE`
- BLOCK → `HarnessState.HALTED` (resume-able after manual fix); harness calls `sys.exit(1)`

---

## Signal Schema (EVALUATE mode)

```json
{
  "status": "complete",
  "mode": "EVALUATE",
  "iteration": 1,
  "phase_id": 7,
  "verdict": "APPROVE | BLOCK",
  "issues": [
    {
      "id": "7.1",
      "severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "dimension": "Functionality | Reliability | UX | Performance | Accessibility",
      "file": "src/api/users.py:41",
      "title": "short title",
      "description": "reproduction steps or detailed description",
      "suggestion": "how to fix",
      "log_info": "relevant log output",
      "refs": "workspace/screenshots/login_fail.png or src/path/to/file.py"
    }
  ]
}
```

**`phase_id`** = `total_phases + 1` (virtual evaluation phase, always distinct from spec phases).  
**`id`** format: `{phase_id}.{issue_seq}` e.g. `7.1`, `7.2` — same two-segment pattern as all other issues.  
Issue seq is sequential within the iteration; evaluator restarts the counter each iteration.  
**`iteration`**: integer 1–3 (informational field in signal; iteration tracking is owned by harness via state.json).  
**Verdict**: BLOCK if any CRITICAL/HIGH present; APPROVE otherwise.

---

## Spec Injection

Two modes depending on how `--spec` is passed to the harness:

- **Single file** (e.g., `--spec docs/spec.md`): harness calls `extract_spec_sections(spec_path)` (see spec.py section below) and passes the result as a text block into the evaluator prompt.
- **Folder** (e.g., `--spec docs/spec/`): harness injects each file's path with an `@` prefix (e.g., `@docs/spec/requirements.md`), so the evaluator agent can `Read` them at runtime. No parsing needed — the agent reads what it needs.

`agents.evaluate()` accepts `spec_sections: str | list[str]` and formats the prompt accordingly.

---

## State.json Extension

Top-level `evaluate` object added alongside `phases`:

```json
"evaluate": {
  "status": "pending | evaluating | complete | halted",
  "phase_id": 7,
  "iterations": [
    {
      "iteration": 1,
      "verdict": "BLOCK",
      "sha_at_evaluate": "abc123",
      "issues": [
        {
          "id": "7.1",
          "severity": "CRITICAL",
          "dimension": "Functionality",
          "file": "src/api/users.py:41",
          "title": "POST /notes DELETE returns 500",
          "description": "...",
          "suggestion": "...",
          "log_info": "...",
          "refs": "workspace/screenshots/delete_fail.png"
        }
      ],
      "fix_sha": "def456"
    }
  ]
}
```

Full issue details live **only** in `state.json`. The harness reads them from there when assembling context for the builder FIX call.

Issue IDs use the same `{phase_id}.{seq}` two-segment pattern as all other issues — `_validate_ids` in state.py is unchanged. The eval phase_id (`total_phases + 1`) makes them globally unique.

---

## rubric-report.md Format

The evaluator writes `workspace/rubric-report.md`. Issue details are NOT duplicated here — only ID + title as references. Iteration summaries are appended (never overwritten).

```markdown
# Rubric Report — Iteration 1 (YYYY-MM-DD HH:MM)

## Score Summary
| Criterion | Type | Max | Score | Verdict |
|-----------|------|-----|-------|---------|
| Feature completeness | Common | 5 | 3 | ❌ -2 |
| Error handling | Common | 5 | 5 | ✅ |
...
**Total: X / Y**

## Per-Criterion Detail

### Feature completeness — 3/5
- **Pass:** Login, registration, and note listing work as specified.
- **Deduction (-2):** Note deletion crashes (see issues 7.1, 7.2).
- **Acceptance criteria:** 4 of 6 spec requirements verified.
- **Improvement:** Fix the DELETE handler error path.

## Issues Reference
| ID | Severity | Title |
|----|----------|-------|
| 7.1 | CRITICAL | POST /notes DELETE returns 500 |
| 7.2 | HIGH | Note body not persisted after page refresh |

## Rubric Table Improvements
(evaluator's meta-feedback on criteria gaps or calibration)

---

## Score Summary — Iteration 2 (YYYY-MM-DD HH:MM)
(appended, not overwritten)
...
```

---

## evaluate_fix.md — FIX Source File

`workspace/evaluate_fix.md` is a per-iteration working file assembled by `evaluate.py` before calling the builder FIX agent. It parallels `workspace/review_report.md`.

- Written by `evaluate.py` at the start of each BLOCK FIX cycle (overwritten each iteration, not appended).
- Contains two parts:
  1. **Current iteration's rubric-report section** — extracted from `workspace/rubric-report.md` by parsing the `# Rubric Report — Iteration N` heading that matches the current iteration. Prior iteration sections are excluded.
  2. **Full issue details for ALL issues in the current iteration** (all severities: CRITICAL, HIGH, MEDIUM, LOW) from `state["evaluate"]["iterations"][-1]["issues"]`. There is no cleanup phase after evaluate, so every issue must be addressed in the FIX pass.
- Cleared (set to empty string) after a successful `verify_evaluate_fix` pass.
- The evaluator agent never writes this file — it writes `rubric-report.md` only.

Harness assembly logic (in `evaluate.py`):
```python
def _write_evaluate_fix_md(state: dict, iteration: int) -> None:
    # Extract current iteration section from rubric-report.md
    rubric_section = _extract_rubric_section(iteration)

    # All issues from current iteration (all severities)
    issues = state["evaluate"]["iterations"][iteration - 1]["issues"]
    issue_lines = []
    for iss in issues:
        issue_lines.append(
            f"## {iss['id']} [{iss['severity']}] {iss['title']}\n"
            f"- File: {iss.get('file', 'N/A')}\n"
            f"- Dimension: {iss.get('dimension', 'N/A')}\n"
            f"- Description: {iss.get('description', '')}\n"
            f"- Suggestion: {iss.get('suggestion', '')}\n"
            f"- Log info: {iss.get('log_info', '')}\n"
            f"- Refs: {iss.get('refs', '')}\n"
        )

    content = rubric_section + "\n\n---\n\n## Issues to Fix\n\n" + "\n".join(issue_lines)
    Path("workspace/evaluate_fix.md").write_text(content, encoding="utf-8")


def _extract_rubric_section(iteration: int) -> str:
    path = Path("workspace/rubric-report.md")
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    # Find the heading for this iteration
    pattern = re.compile(
        rf"^# Rubric Report — Iteration {iteration}\b.*$", re.MULTILINE
    )
    m = pattern.search(content)
    if not m:
        return ""
    start = m.start()
    # End at the next top-level heading or EOF
    next_h1 = re.search(r"^# ", content[start + 1:], re.MULTILINE)
    end = start + 1 + next_h1.start() if next_h1 else len(content)
    return content[start:end].strip()
```

---

## Rubric Design

Stored in `.claude/agents/evaluator.md`. Evaluator selects applicable rows based on `app_type` from state.json.

| Criterion | Score | Type | Notes |
|-----------|-------|------|-------|
| Feature completeness | 5 | Common | Every requirement in spec exercised. Deduct 1 per missing/non-functional requirement. |
| Error handling | 5 | Common | Invalid inputs and failures return meaningful messages, correct status codes, no crashes. Deduct 2 per unhandled exception reaching user. |
| Data persistence | 5 | Common | Data written in one request/session retrievable in a subsequent one. Schema matches spec. Deduct 2 per data-loss scenario. |
| Test suite health | 4 | Common | All unit and integration tests pass in a clean run. Deduct 1 per failing test, cap at 4. |
| Security baseline | 4 | Common | No hardcoded secrets. Input validated before DB/FS use. No path traversal or SQL injection. Deduct 2 per CRITICAL finding. |
| CLI correctness | 5 | CLI | Every subcommand/flag produces spec-described output. Exit code 0 on success, non-zero on error. |
| CLI help & discoverability | 4 | CLI | `--help` accurate on every command. Usage examples match real behavior. |
| CLI output format | 4 | CLI | Consistent, parseable, no debug noise in production mode. |
| API contract | 5 | Web | Every endpoint returns specified HTTP status codes and JSON schema. Error bodies include human-readable message. |
| UI completeness | 5 | Web | All pages/components render without breakage. No 404 assets, no blank panels. |
| User interaction flow | 5 | Web | All flows (forms, buttons, nav) complete without JS errors. Loading states and feedback visible. |
| Web accessibility | 4 | Web | Semantic HTML, focusable controls, ARIA on icon-only buttons. Keyboard nav doesn't trap focus. |
| Game loop stability | 5 | Game | Runs ≥60s without crash, freeze, or console error under simulated normal play. |
| Player controls | 5 | Game | Every input action triggers correct entity state change. Deduct 1 per missing/mis-mapped control. |
| Scoring & win condition | 5 | Game | Score increments exactly as specified. Win/loss conditions fire at correct thresholds. |
| Asset integrity | 4 | Game | All sprites, sounds, tilemaps load (HTTP 200). No console 404 errors during full play session. |

---

## File Refactoring (harness.py and fix.py split)

Both files currently ~530 lines. Split each into two focused modules:

### harness.py → harness.py + phase_handlers.py
- **`harness.py`** (keeps): `HarnessState` enum, `Harness` class (`__init__`, `run`, `_derive_state`, `profile_for`, `phase_type_for`), entry point
- **`phase_handlers.py`** (new): `handle_task_build`, `handle_executing`, `handle_reviewing`, `handle_fixing`, `handle_next_phase` — extracted from `Harness._do_*` methods; called by `run()` via dispatch table

### fix.py → fix.py + cleanup.py
- **`fix.py`** (keeps): `run_fix_cycle`, `handle_verdict`, `verify_fix`, `run_batch_retry_loop` — the per-phase fix loop
- **`cleanup.py`** (new): `run_cleanup`, `_finish` — the post-all-phases deferred issue cleanup

`evaluate.py` is a new third module (not split from existing).

Import chain after split:
- `harness.py` imports `phase_handlers` (for dispatch) and `evaluate` (for `run_evaluate_cycle`)
- `harness.py` imports `run_cleanup` from `cleanup` (previously from `fix`)
- `fix.py` no longer exports `run_cleanup`; `cleanup.py` does
- `evaluate.py` imports from `agents`, `state`, `calibrate`, `verify`

---

## Files to Create

| File | Purpose |
|------|---------|
| `.claude/agents/evaluator.md` | Evaluator agent instructions: EVALUATE mode protocol, rubric table, Playwright patterns, report format |
| `.claude/settings.evaluator.json` | Stop hook + pre_bash_security + post_write_verify only (no git commit, no lint) |
| `harness/evaluate.py` | `run_evaluate_cycle()` — 3-iteration loop, evaluate agent call, FIX dispatch, state updates |
| `harness/phase_handlers.py` | Extracted from harness.py — per-phase state machine handlers |
| `harness/cleanup.py` | Extracted from fix.py — `run_cleanup`, `_finish` |
| `harness/tests/unit/test_evaluate.py` | Unit tests for `evaluate.py` functions |
| `harness/tests/unit/test_phase_handlers.py` | Unit tests for extracted phase handler functions |
| `harness/tests/unit/test_cleanup.py` | Unit tests for extracted cleanup functions |

---

## Files to Modify

| File | Change |
|------|--------|
| `harness/harness.py` | Add `EVALUATING` to `HarnessState`; import `phase_handlers`, `evaluate`; CLEANUP→EVALUATING transition; EVALUATING handler in `run()`; resume path; `workspace/screenshots/` creation in `__init__`; `--app-type game` in argparse |
| `harness/fix.py` | Remove `run_cleanup`/`_finish` (moved to cleanup.py); import from cleanup |
| `harness/agents.py` | Add `evaluate(harness, state, iteration, spec_sections) → dict`; add `fix_evaluate_issues(source_file, profiles, config, failure_history) → dict` |
| `harness/state.py` | Add `init_evaluate_state()`, `update_evaluate_iteration()`, `update_evaluate_status()`, `find_evaluate_issue()` |
| `harness/spec.py` | Add `extract_spec_sections(spec_path: str) → str` |
| `harness/config.json` | Add `"EVALUATE": 600` to `subprocess_timeout`; add `"max_evaluate_iterations": 3` |
| `.claude/hooks/stop_validate_json.py` | Add EVALUATE schema block |
| `requirements.txt` | Add `playwright`, `pytest-playwright` |
| `harness/tests/unit/test_harness.py` | Add regression tests for EVALUATING state transitions |
| `harness/tests/unit/test_agents.py` | Add tests for `evaluate()` and `fix_evaluate_issues()` functions |
| `harness/tests/unit/test_state.py` | Add tests for new evaluate state functions |
| `harness/tests/unit/test_fix.py` | Regression tests confirming `run_fix_cycle` unaffected by split |

---

## Key Design Details

### evaluate.py — run_evaluate_cycle()

```
1. eval_phase_id = state["total_phases"] + 1
2. init_evaluate_state(state, eval_phase_id)  → sets phase_id, status="evaluating"
3. spec_sections = extract_spec_sections(state["spec_file"])
4. For iteration in 1..3:
   a. Check resume: if last saved iteration has verdict=BLOCK and fix_sha is None
      → skip agent call, go straight to step (d) for that iteration (see Resume section)
   b. result = agents.evaluate(harness, state, iteration, spec_sections)
   c. update_evaluate_iteration(state, result)  # save to state.json
   d. log_usage(task_id=f"evaluate_{iteration}", phase_id=eval_phase_id, mode="EVALUATE",
                usage=result["usage"], files_changed=0)
   e. If result["verdict"] == "BLOCK":
      - _write_evaluate_fix_md(state, iteration)
        # Contains: current iteration rubric section + ALL issues (all severities)
        # No CRITICAL/HIGH filter — no cleanup phase follows evaluate
      - pre_sha = git rev-parse HEAD
      - fix_result = agents.fix_evaluate_issues("workspace/evaluate_fix.md", profiles, config)
      - log_usage(task_id=f"evaluate_{iteration}_fix", ...)
      - verify_evaluate_fix(harness, state, eval_phase_id, pre_sha)
      - update fix_sha = git rev-parse HEAD in current iteration entry
   f. (continue to next iteration regardless of verdict)
5. final_verdict = state["evaluate"]["iterations"][-1]["verdict"]
6. If final_verdict == "APPROVE": update_evaluate_status(state, "complete")
7. If final_verdict == "BLOCK":
      update_evaluate_status(state, "halted")
      logger.error("[HALT] Evaluate: final iteration BLOCK. Fix manually, then --resume.")
      sys.exit(1)
```

`profiles` = unique profiles across all phases:
```python
seen, profiles = set(), []
for sp in state["phases"]:
    p = harness.profile_for(sp["id"])
    if p["name"] not in seen:
        seen.add(p["name"])
        profiles.append(p)
```

### agents.py — evaluate() function

- Settings: `.claude/settings.evaluator.json`
- Tools: `Read,Write,Bash,Grep,Glob` (no Edit — evaluator doesn't modify code)
- Prompt injects: evaluator.md, spec sections, state.json path, current iteration, app_type, `workspace/screenshots/` path
- Timeout: `config["subprocess_timeout"]["EVALUATE"]` (600s)

### agents.py — fix_evaluate_issues() function

Cross-language FIX calls during evaluate must handle issues that span both frontend and backend files in a single agent call. A single-profile approach would inject the wrong language rules for half the issues.

```python
def fix_evaluate_issues(
    source_file: str,
    profiles: list[dict],
    config: dict,
    failure_history: dict | None = None,
) -> dict:
    # Merge builder_files from all profiles (dedup, preserve order)
    seen: set[str] = set()
    all_builder_files: list[str] = []
    for profile in profiles:
        builder_files, _ = build_file_lists(profile)
        for f in builder_files:
            if f not in seen:
                seen.add(f)
                all_builder_files.append(f)

    # Collect all unique test commands
    test_cmds: list[list[str]] = []
    seen_cmds: set[tuple] = set()
    for profile in profiles:
        cmd = tuple(profile.get("test_cmd", ["pytest"]))
        if cmd not in seen_cmds:
            seen_cmds.add(cmd)
            test_cmds.append(list(cmd))

    test_run_instruction = " and then ".join(
        f"`{' '.join(cmd)}`" for cmd in test_cmds
    )
    model = profiles[0]["execute_model"]

    prompt = (
        file_preamble(all_builder_files)
        + f"\nMODE=FIX. Read all open issues from {source_file}. Fix each in severity order. "
        + f"Run {test_run_instruction} after all fixes."
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt, model=model, mode="FIX", config=config,
        settings_file=".claude/settings.builder.json",
    )
```

The builder agent receives rules for all languages in play, writes fixes to whichever files are needed, and runs all test suites. Single call, full cross-language context.

### spec.py — extract_spec_sections()

```python
def extract_spec_sections(spec_path: str) -> str:
    """Return Requirements, Verification Plan, and Architecture sections as a text block.

    For folder specs: returns @-prefixed paths for the evaluator to Read at runtime.
    For single-file specs: extracts matching top-level ## sections by heading name.
    """
    path = Path(spec_path)
    if path.is_dir():
        # Folder mode — return @path references for evaluator to Read
        lines = []
        for f in sorted(path.iterdir()):
            if f.suffix == ".md":
                lines.append(f"@{f}")
        return "\n".join(lines)

    # Single file — extract target sections
    TARGET_SECTIONS = {"requirements", "verification", "architecture"}
    content = path.read_text(encoding="utf-8")
    section_re = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(section_re.finditer(content))
    extracted: list[str] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip().lower()
        if any(kw in heading for kw in TARGET_SECTIONS):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            extracted.append(content[start:end].strip())
    return "\n\n".join(extracted)
```

Lives in `spec.py`. Uses `re` (already imported).

### state.py — New evaluate functions

```python
def init_evaluate_state(state: dict, phase_id: int) -> None:
    """Initialise state["evaluate"] if not already present."""
    if "evaluate" not in state:
        state["evaluate"] = {
            "status": "evaluating",
            "phase_id": phase_id,
            "iterations": [],
        }
    else:
        state["evaluate"]["status"] = "evaluating"
    save_state(state)


def update_evaluate_iteration(state: dict, result: dict) -> None:
    """Append a completed iteration entry to state["evaluate"]["iterations"]."""
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    entry = {
        "iteration": result["signal"]["iteration"],
        "verdict": result["signal"]["verdict"],
        "sha_at_evaluate": sha,
        "issues": result["signal"].get("issues", []),
        "fix_sha": None,
    }
    state["evaluate"]["iterations"].append(entry)
    save_state(state)


def update_evaluate_status(state: dict, status: str) -> None:
    state["evaluate"]["status"] = status
    save_state(state)


def find_evaluate_issue(state: dict, issue_id: str) -> dict | None:
    """Find an issue in any evaluate iteration by ID."""
    for iteration in state.get("evaluate", {}).get("iterations", []):
        for issue in iteration.get("issues", []):
            if issue["id"] == issue_id:
                return issue
    return None
```

`_validate_ids` in state.py is **unchanged** — evaluate issues use the same `^\d+\.\d+$` pattern (e.g. `7.1`, `7.2`).

### evaluate.py — verify_evaluate_fix()

The existing `verify_fix` in verify.py routes through `state["phases"]` and cannot be used for evaluate issues. A dedicated function handles evaluate fix verification:

```python
def verify_evaluate_fix(
    harness: Harness, state: dict, eval_phase_id: int, pre_sha: str
) -> None:
    """Run all test suites after an evaluate FIX call; update fix_sha on success."""
    seen_cmds: set[tuple] = set()
    for sp in state["phases"]:
        cmd = tuple(harness.profile_for(sp["id"]).get("test_cmd", ["pytest"]))
        if cmd not in seen_cmds:
            seen_cmds.add(cmd)
            result = subprocess.run(list(cmd), capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning(
                    "[EVALUATE FIX] Tests failed after fix: %s",
                    result.stdout[-500:],
                )
                return  # fix_sha stays None; will be retried or halted externally

    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    last_iter = state["evaluate"]["iterations"][-1]
    last_iter["fix_sha"] = current_sha
    save_state(state)
    Path("workspace/evaluate_fix.md").write_text("", encoding="utf-8")
```

### .claude/settings.evaluator.json

Stop hook + bash security only. No git commit (evaluator doesn't modify code). No lint hooks (evaluator writes only rubric-report.md, not source files). Write verify hook included so rubric-report.md write is confirmed.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [{"type": "command", "command": "python .claude/hooks/stop_validate_json.py", "timeout_ms": 10000}],
        "description": "Validate agent output is valid JSON before subprocess exits",
        "id": "stop:validate-json"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [{"type": "command", "command": "python .claude/hooks/post_write_verify.py", "timeout_ms": 5000}],
        "description": "Verify file exists after Write",
        "id": "post:write:verify-exists"
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "python .claude/hooks/pre_bash_security.py", "timeout_ms": 5000}],
        "description": "Block dangerous commands and prompt injection",
        "id": "pre:bash:security"
      }
    ]
  }
}
```

### evaluator.md — Key Instructions

- Read state.json to detect `app_type` (`cli`, `web`, `game`); select applicable rubric rows
- Read injected spec sections to build acceptance checklist before testing
- **web/game**: start app server via Bash; install Playwright (`playwright install --with-deps chromium`); write and execute a Playwright Python script in a temp file; capture screenshots to `workspace/screenshots/`
- **CLI**: exercise every command/flag via Bash; check stdout/stderr and exit codes
- **API**: use `httpx` or `curl` via Bash for each endpoint
- **DB**: connect via CLI or inline Python; query expected tables/rows
- Write `workspace/rubric-report.md` in a single Write call (first iteration) or append via a second Write of the full file (iterations 2–3); do NOT use Edit
- Output: JSON signal only, no prose

### stop_validate_json.py — EVALUATE Schema Addition

```python
"EVALUATE": {
    "type": "object",
    "required": ["status", "mode", "iteration", "phase_id", "verdict", "issues"],
    "properties": {
        "status": {"type": "string", "enum": ["complete"]},
        "mode": {"type": "string", "enum": ["EVALUATE"]},
        "iteration": {"type": "integer", "minimum": 1, "maximum": 3},
        "phase_id": {"type": "integer"},
        "verdict": {"type": "string", "enum": ["APPROVE", "BLOCK"]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "severity", "dimension", "title", "description", "suggestion"],
                "properties": {
                    "id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                    "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                    "dimension": {"type": "string"},
                    "file": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "log_info": {"type": "string"},
                    "refs": {"type": "string"}
                }
            }
        }
    }
}
```

### harness.py — CLEANUP → EVALUATING Transition

```python
elif current_state == HarnessState.CLEANUP:
    run_cleanup(self, state)
    current_state = HarnessState.EVALUATING  # was COMPLETE

elif current_state == HarnessState.EVALUATING:
    run_evaluate_cycle(self, state)
    current_state = HarnessState.COMPLETE  # or sys.exit(1) if HALTED
```

`Harness.__init__` adds:
```python
os.makedirs("workspace/screenshots", exist_ok=True)
```

`--app-type` argparse updated to:
```python
parser.add_argument(
    "--app-type",
    choices=["cli", "web", "game"],
    default="cli",
)
```

### Resume from EVALUATING

In `_derive_state()`, add BEFORE the all-phases-complete path:

```python
evaluate = state.get("evaluate", {})
ev_status = evaluate.get("status")

if ev_status == "halted":
    logger.error(
        "[RESUME] Evaluate is halted. Fix the issues manually, "
        "set state['evaluate']['status'] = 'evaluating', then --resume."
    )
    sys.exit(1)

if ev_status in ("evaluating",):
    # Detect partial-iteration resume: last iteration has verdict=BLOCK but fix_sha=None
    # → crashed after saving the iteration result but before completing the FIX call.
    # run_evaluate_cycle() checks this at the top of each iteration loop and skips
    # the agent call, going straight to the FIX step.
    return HarnessState.EVALUATING
```

This block must appear BEFORE the `for phase in state.get("phases", [])` loop so that a fully-built project with evaluate in progress does not restart from TASK_BUILD.

In `run_evaluate_cycle()`, at the start of each iteration:

```python
iterations = state["evaluate"].get("iterations", [])
# Determine starting iteration: count already-saved iterations
completed_count = len(iterations)

for iteration in range(1, MAX_EVALUATE_ITERATIONS + 1):
    if iteration <= completed_count:
        # Already saved — check if FIX step was interrupted
        saved = iterations[iteration - 1]
        if saved["verdict"] == "BLOCK" and saved["fix_sha"] is None:
            # Re-enter FIX for this iteration, skip agent call
            _run_evaluate_fix(harness, state, saved["issues"], eval_phase_id)
        continue  # move to next iteration

    # Normal path: run agent
    result = agents.evaluate(...)
    ...
```

### --max-phase and EVALUATING

`current_phase` is only updated for phases 1..total_phases. `evaluate.py` never writes to `state["current_phase"]`; evaluate progress is tracked entirely in `state["evaluate"]`.

The guard `if args.max_phase and phase_id > args.max_phase` reads `phase_id = state.get("current_phase", 1)`. During EVALUATING, `current_phase` is still the last normal phase (total_phases). If `max_phase == total_phases`, then `total_phases > total_phases` is False — evaluation always runs when all phases are complete.

This invariant must be documented as a requirement: `evaluate.py` MUST NOT update `state["current_phase"]`.

### log_usage for evaluate

In `run_evaluate_cycle`, after each `agents.evaluate()` call:

```python
log_usage(
    task_id=f"evaluate_{iteration}",
    phase_id=eval_phase_id,
    mode="EVALUATE",
    usage=result["usage"],
    files_changed=0,
)
```

After each `fix_evaluate_issues()` call:

```python
log_usage(
    task_id=f"evaluate_{iteration}_fix",
    phase_id=eval_phase_id,
    mode="FIX",
    usage=fix_result["usage"],
    files_changed=sum(
        len(f.get("files_changed", []))
        for f in fix_result["signal"].get("fixes", [])
        if f.get("status") == "fixed"
    ),
)
```

---

## TDD / Testing Plan

All new and modified code follows TDD: write failing tests first, implement, make them pass.

Test run command: `pytest --asyncio-mode=auto` (existing command).

---

### `harness/tests/unit/test_evaluate.py` (new)

#### `run_evaluate_cycle`
- `test_three_approve_verdicts_sets_status_complete` — all 3 iterations return APPROVE; `state["evaluate"]["status"]` == "complete"; FIX agent never called
- `test_block_triggers_fix_then_continues` — iteration 1 returns BLOCK; FIX agent called once; iteration 2 still runs
- `test_block_all_three_sets_status_halted_and_exits` — all 3 iterations return BLOCK; after iteration 3, `update_evaluate_status` called with "halted"; `sys.exit(1)` raised
- `test_approve_after_block_sets_status_complete` — iterations 1+2 BLOCK, iteration 3 APPROVE; exits cleanly with status "complete"
- `test_fix_not_called_on_approve_verdict` — APPROVE verdict; `agents.fix_evaluate_issues` is never called
- `test_log_usage_called_per_iteration` — 3 iterations; `log_usage` called 3 times with `mode="EVALUATE"` and correct `task_id=f"evaluate_{n}"`
- `test_log_usage_called_for_fix` — BLOCK iteration; `log_usage` called with `mode="FIX"` and `task_id=f"evaluate_{n}_fix"`
- `test_current_phase_not_mutated` — `state["current_phase"]` is unchanged after `run_evaluate_cycle` completes (max_phase invariant)

#### Resume from mid-iteration crash
- `test_resume_skips_completed_iterations` — state has 2 saved iterations; cycle starts at iteration 3 only; evaluate agent called once
- `test_resume_reruns_fix_when_fix_sha_is_none` — last saved iteration has verdict=BLOCK and fix_sha=None; agent call is skipped; FIX agent called directly; `fix_sha` updated after verify passes
- `test_resume_skips_fix_when_fix_sha_present` — last saved iteration has verdict=BLOCK and fix_sha set; no FIX call on resume for that iteration

#### `_write_evaluate_fix_md`
- `test_writes_current_iteration_rubric_section_only` — rubric-report.md has 3 iteration sections; only the matching section appears in evaluate_fix.md
- `test_includes_all_severities` — current iteration has CRITICAL, HIGH, MEDIUM, LOW issues; all four appear in evaluate_fix.md
- `test_overwrites_previous_iteration_content` — called for iteration 1, then iteration 2; file contains only iteration 2 content
- `test_includes_full_issue_fields` — description, suggestion, log_info, refs all present in output
- `test_handles_missing_rubric_report` — rubric-report.md does not exist; file written with issues section only, no error raised

#### `_extract_rubric_section`
- `test_returns_correct_section_for_iteration` — multi-iteration rubric-report.md; returns only the requested iteration's block
- `test_returns_empty_string_when_file_absent` — rubric-report.md does not exist; returns `""`
- `test_returns_empty_string_when_iteration_not_found` — file exists but has no matching heading; returns `""`
- `test_does_not_include_next_iteration_content` — iteration 1 section ends before iteration 2 heading

#### `verify_evaluate_fix`
- `test_updates_fix_sha_when_all_tests_pass` — all test commands return 0; `last_iter["fix_sha"]` set to current HEAD SHA
- `test_clears_evaluate_fix_md_on_success` — after passing verify, `workspace/evaluate_fix.md` is empty
- `test_fix_sha_stays_none_when_tests_fail` — any test command returns non-zero; `fix_sha` remains None; evaluate_fix.md not cleared
- `test_runs_all_unique_test_commands` — two profiles with different test_cmds; both commands executed
- `test_deduplicates_identical_test_commands` — two profiles with identical test_cmd; command run only once

#### `profiles` collection
- `test_deduplicates_profiles_by_name` — phases use python + typescript + python; result has 2 unique profiles
- `test_single_language_project_yields_one_profile` — all phases are python; exactly one profile in list

---

### `harness/tests/unit/test_state.py` (modified — add evaluate tests)

#### `init_evaluate_state`
- `test_creates_evaluate_block_when_absent` — fresh state; `state["evaluate"]` created with status="evaluating", correct phase_id, empty iterations
- `test_resets_status_to_evaluating_when_present` — state already has evaluate block with status="halted"; status reset to "evaluating"
- `test_saves_state_after_init` — state.json written after call

#### `update_evaluate_iteration`
- `test_appends_iteration_entry` — first call appends one entry; second call appends a second
- `test_entry_has_correct_fields` — entry contains iteration, verdict, sha_at_evaluate, issues, fix_sha=None
- `test_fix_sha_initialises_to_none` — newly appended entry always has `fix_sha` as None

#### `update_evaluate_status`
- `test_sets_status_and_saves` — status updated and state.json written

#### `find_evaluate_issue`
- `test_finds_issue_across_iterations` — issue in iteration 2; found correctly
- `test_returns_none_when_not_found` — unknown ID; returns None
- `test_returns_none_when_evaluate_absent` — no evaluate block in state; returns None

---

### `harness/tests/unit/test_agents.py` (modified — add evaluate tests)

#### `evaluate()`
- `test_uses_evaluator_settings_file` — subprocess called with `--settings .claude/settings.evaluator.json`
- `test_tools_exclude_edit` — `--allowedTools` does not contain `Edit`
- `test_uses_evaluate_timeout` — timeout taken from `config["subprocess_timeout"]["EVALUATE"]`
- `test_injects_spec_sections_string` — single-file spec; spec text present in prompt
- `test_injects_spec_sections_paths` — folder spec; `@path` references present in prompt

#### `fix_evaluate_issues()`
- `test_merges_builder_files_from_all_profiles` — two profiles with distinct builder files; both sets present in prompt (deduped)
- `test_deduplicates_shared_builder_files` — both profiles share common_rules; file appears only once
- `test_includes_all_unique_test_commands_in_prompt` — python profile has `pytest`, ts profile has `npx vitest run`; both in prompt
- `test_deduplicates_identical_test_commands` — two profiles with same test_cmd; command appears once in prompt
- `test_uses_builder_settings_file` — called with `.claude/settings.builder.json`
- `test_mode_is_fix` — `call_claude` receives `mode="FIX"`

---

### `harness/tests/unit/test_spec.py` (modified — add extract_spec_sections tests)

- `test_extracts_requirements_section` — spec with `## Requirements` heading; section returned
- `test_extracts_verification_section` — spec with `## Verification Plan` heading; section returned
- `test_extracts_architecture_section` — spec with `## Architecture` heading; section returned
- `test_extracts_multiple_sections` — all three present; all returned separated by blank lines
- `test_ignores_non_target_sections` — spec has `## Phase 1` and `## Requirements`; only Requirements extracted
- `test_returns_empty_string_when_no_sections_match` — spec has no target headings; returns `""`
- `test_folder_mode_returns_at_paths` — folder with 3 .md files; returns 3 `@path` lines
- `test_folder_mode_sorted_paths` — file paths are sorted
- `test_folder_mode_skips_non_md_files` — folder has .md and .txt files; only .md paths returned
- `test_section_ends_at_next_heading` — two consecutive target sections; each extracted independently

---

### `harness/tests/unit/test_harness.py` (modified — add EVALUATING tests)

- `test_derive_state_returns_evaluating_when_status_evaluating` — state has `evaluate.status="evaluating"`; returns `HarnessState.EVALUATING`
- `test_derive_state_exits_when_status_halted` — state has `evaluate.status="halted"`; `sys.exit(1)` called
- `test_derive_state_evaluating_check_before_phases_loop` — all phases complete AND evaluate status is "evaluating"; returns EVALUATING not CLEANUP
- `test_cleanup_transitions_to_evaluating` — CLEANUP handler sets `current_state = HarnessState.EVALUATING`
- `test_evaluating_transitions_to_complete_on_approve` — `run_evaluate_cycle` returns normally; `current_state` = COMPLETE
- `test_workspace_screenshots_created_on_init` — `Harness.__init__` creates `workspace/screenshots/` directory
- `test_app_type_game_accepted` — `--app-type game` parses without error
- `test_max_phase_does_not_block_evaluating` — `max_phase = total_phases`; EVALUATING state is still entered

---

### `harness/tests/unit/test_hooks.py` (modified — add EVALUATE schema tests)

- `test_evaluate_approve_signal_passes_schema` — valid APPROVE signal with empty issues list passes validation
- `test_evaluate_block_signal_with_issues_passes_schema` — BLOCK signal with full issue objects passes
- `test_evaluate_rejects_missing_required_fields` — signal missing `verdict`; hook exits with code 1
- `test_evaluate_rejects_invalid_verdict` — verdict="WARN"; schema rejects it
- `test_evaluate_accepts_two_segment_issue_id` — id="7.1"; passes pattern validation
- `test_evaluate_rejects_three_segment_issue_id` — id="7.1.1"; schema rejects it (wrong pattern)
- `test_evaluate_rejects_invalid_severity` — severity="INFO"; schema rejects it
- `test_evaluate_iteration_must_be_1_to_3` — iteration=4; schema rejects it

---

### `harness/tests/unit/test_phase_handlers.py` (new)

Regression coverage for code extracted from `harness.py` into `phase_handlers.py`:

- `test_handle_task_build_returns_executing` — successful TASK_BUILD signal; returns `HarnessState.EXECUTING`
- `test_handle_task_build_returns_halted_on_subprocess_error` — agent raises SubprocessError; returns `HarnessState.HALTED`
- `test_handle_executing_returns_reviewing_when_no_pending_tasks` — no pending tasks; returns `HarnessState.REVIEWING`
- `test_handle_reviewing_calls_handle_verdict` — review complete; `handle_verdict` invoked
- `test_handle_next_phase_advances_phase_id` — advances `current_phase` and returns `HarnessState.TASK_BUILD`
- `test_handle_next_phase_transitions_to_cleanup_on_last_phase` — last phase completes; returns `HarnessState.CLEANUP`

---

### `harness/tests/unit/test_cleanup.py` (new)

Regression coverage for code extracted from `fix.py` into `cleanup.py`:

- `test_run_cleanup_calls_finish_when_no_deferred_issues` — no deferred issues; `_finish` called; no FIX agent call
- `test_run_cleanup_fixes_deferred_issues` — deferred issues present; FIX agent called; issues updated to "fixed"
- `test_finish_runs_all_test_commands` — two unique test_cmds across phases; both executed
- `test_finish_warns_on_test_failure` — test command returns non-zero; warning printed, no exception raised

---

### `harness/tests/unit/test_fix.py` (modified — regression after split)

- `test_run_fix_cycle_still_importable_after_split` — `from fix import run_fix_cycle` succeeds; `run_cleanup` no longer importable from fix
- `test_run_cleanup_importable_from_cleanup` — `from cleanup import run_cleanup` succeeds

---

## Verification Plan

1. Run existing test suite — confirm all pass before starting implementation
2. For each new module: write all failing tests → implement → confirm green
3. Run full test suite after each module — confirm no regressions
4. Implementation order: `state.py` → `spec.py` → `agents.py` → `evaluate.py` → `harness.py` → `phase_handlers.py` + `cleanup.py` → hook schema
