# harness/ — Core Modules

Five modules. `harness.py` orchestrates the state machine; `spec.py`, `verify.py`, and `fix.py` handle isolated concerns; `state.py` manages all state I/O.

---

# harness/state.py — State I/O (~100 lines)

Pure state read/write. No workflow logic, no subprocess calls, no agent interaction.

Imported by `harness.py` via `from state import update_state, halt_task, error_task, error_phase, halt_issue, error_issue`.
`sync_task_types` lives in `calibrate.py` (updates both state.json and calibration.json) — harness calls it directly as `calibrate.sync_task_types(state, new_tasks, profile)`.

## Functions

```python
def load_state() -> dict:
    # Read workspace/state.json; return parsed dict
    # Called once on startup by harness.py

def save_state(state: dict) -> None:
    # Correct then write state dict back to workspace/state.json atomically.
    # Atomicity mechanism: write to workspace/state.json.tmp, then os.replace() over
    #   workspace/state.json. os.replace() is atomic on POSIX and atomic on Windows
    #   (same volume). A crash during write leaves state.json intact; .tmp is orphaned
    #   and ignored on next startup.
    # Before writing: scan every task id and issue id against r"^\d+\.\d+$"
    #   if an id is malformed, replace it with "{phase_id}.{seq}" derived from
    #   the enclosing phase id and 1-based position in tasks[] or issues[]
    #   logs a [WARN] line to console for any id that was corrected

def update_state(state, **kwargs) -> None:
    # Apply kwargs updates to the relevant entity in state dict, then save_state()
    # covers all four entities:
    #   task   — status, attempts, verify_fails, tdd_applied, tdd_skipped, files_changed, last_error
    #   issue  — status, attempts, files_changed, fixed_sha, last_error
    #   review — status (pending → complete → fixing → fixed), verdict, sha_at_review
    #   phase  — status (pending → building → complete);
    #            set to "complete" when all tasks complete AND all CRITICAL/HIGH fixed

def halt_task(state, task_id: str) -> None:
    # Set task status="halted", save_state()
    # Print: "[HALT] Task {task_id} failed 3 times. Fix manually, then run --resume."
    # sys.exit(1)

def error_task(state, task_id: str, reason: str) -> None:
    # Set task status="error", append reason to task["last_error"], save_state()
    # Print: "[ERROR] Task {task_id} aborted: {reason}."
    #        "To retry: open workspace/state.json, set this task's status to 'pending', then run --resume."
    # sys.exit(1)

def halt_issue(state, phase_id: int, issue_id: str) -> None:
    # Set issue status="halted", save_state()
    # Print: "[HALT] Issue {issue_id} failed 3 times. Fix manually, then run --resume."
    # sys.exit(1)

def error_issue(state, phase_id: int, issue_id: str, reason: str) -> None:
    # Set issue status="error", save_state()
    # Print: "[ERROR] Issue {issue_id} aborted: {reason}. Resolve the issue, then run --resume."
    # sys.exit(1)

def error_phase(state, phase_id: int, reason: str) -> None:
    # Set phase status="error", save_state()
    # Print: "[ERROR] Phase {phase_id} TASK_BUILD failed: {reason}. Fix the spec, then run --resume."
    # sys.exit(1)
    # Called by build_tasks() when the TASK_BUILD signal is not status="complete".
    # On --resume, harness retries TASK_BUILD once; if it fails again, error_phase() fires again.
```

## Phase 11 Runtime Reliability Notes

Optional CLI flags:

- `python harness/harness.py --status` prints `workspace/run.lock` status without mutating harness state. `last_error` means the current blocker/error only; older retained errors are reported as `historical_last_error`. If `workspace/external_dependency_context.json` exists, status includes `external_dependency_wait` with reset/cleanup metadata so operators can see whether a Claude quota wait is clean, blocked, or ready to resume. Status also reports `stale_execution` when a stale run lock overlaps with in-flight state or unmatched current-run Claude subprocess starts.
- `python harness/harness.py --clear-stale-lock` removes `workspace/run.lock` and `workspace/harness.pid` only when the recorded PID is no longer alive.

The orchestrator emits structured events to `workspace/events.jsonl` and human-readable lines to `workspace/harness.log`. Startup, resume decisions, state transitions, Claude subprocess outcomes, verification commands, completion, and clean halts should be visible there.

`Harness.run()` acquires `workspace/run.lock` and writes `workspace/harness.pid` at run start. Normal COMPLETE and clean zero-code exits release the lock. Unexpected crashes preserve the lock so a second harness run cannot corrupt `workspace/state.json`; stale locks are cleared only through PID liveness checks.

On `--resume`, the harness captures whether the previous lock was stale before acquiring a new one. If stale execution state exists, resume first runs Claude CLI cleanup. If cleanup cannot prove the old CLI environment is safe (for example protection data is incomplete while CLI candidates remain, or cleanup reports errors), resume exits before starting a new Claude subprocess. If cleanup is safe, interrupted `status="building"` tasks are reset to `pending`, a `stale_execution_recovered` event is emitted, and normal resume derivation continues. The harness never kills Claude Desktop and never kills CLI candidates when it cannot protect the current Claude Code session.

REVIEW subprocess failures use `review.status="error"` instead of mutating `phase.status`. When all phase tasks are complete and `review.status` is `pending` or `error`, `--resume` routes to REVIEWING and does not rebuild completed tasks. Interrupted task-level `status="building"` entries are reset to `pending` before pending-task selection.

EVALUATE resume states are handled before the phase loop. `evaluate.status` values `evaluating`, `blocked_external_dependency`, `timeout`, and `error` route to EVALUATING; `complete` routes to COMPLETE; `halted` exits until the user manually resets evaluation. This prevents a fully built project from falling back to TASK_BUILD after an evaluator failure.

The setup phase may use normal TDD modes for tests and their implementations because Phase 1 can contain executable harness-facing checks. Pure scaffold/config setup tasks may still use `exempt`; exempt setup tasks still require `tdd_skipped`.

---

# harness/spec.py — Spec Parser (~73 lines)

Parses spec Markdown files into in-memory phase structures. No state writes except when `write_phases=True`.

## Functions

```python
_PHASE_HEADER_RE = re.compile(r"^##\s+Phase\s+(\d+)\s*[:\-—]\s*(.+)$", re.MULTILINE)
# Matches: "## Phase 1: Title", "## Phase 1 - Title", "## Phase 1 — Title"

def parse_spec(spec_path: str, state: dict, *, write_phases: bool) -> tuple[list, str]:
    # Return (phases, context). phases = [{id, title, description}]. context = extra text.
    #
    # single file: extract ## Phase N: headers; phase description = text between headers
    # directory: read all *.md files, concatenate into all_text; extract from combined text;
    #            context = all_text (injected into agent prompts)
    #
    # write_phases=True  (first run only): writes all phase shells to state["phases"] and saves state
    #   Each shell: {id, title, status: "pending", tasks: [], review: {status: "pending", ...}}
    #   Also sets state["total_phases"] = len(phases)
    # write_phases=False (--resume): read-only — extracts into memory only, does NOT touch state
    #   Only called when resume path is TASK_BUILD; skipped for EXECUTING/FIXING/CLEANUP paths
    # write_phases is keyword-only (*) — callers must be explicit; accidental phase overwrite is impossible
    #
    # Phase population sequence (first run — three separate steps):
    #   1. parse_spec(..., write_phases=True)  → all phase shells written to state.json (id, title, status only)
    #   2. build_tasks() → tasks[] filled under the relevant phase (one phase at a time, TASK_BUILD)
    #   3. review signal → review.issues[] filled under the relevant phase (after each REVIEW call)

def _extract_phases(text: str) -> list:
    # Find all _PHASE_HEADER_RE matches; for each: extract id, title, and body text up to next header
    # Returns list of {id: int, title: str, description: str}

def validate_spec(phases: list) -> None:
    # Called immediately after parse_spec(), before entering TASK_BUILD
    # Checks: (1) at least one phase extracted; (2) each phase has a non-empty title;
    #         (3) phase IDs are sequential integers starting at 1
    # On failure: print descriptive error (e.g. "Phase 2 has no title") and sys.exit(1)
    # No subprocess is ever called if validation fails
```

---

# harness/harness.py — Orchestrator (~417 lines)

Entry point:
```
python harness/harness.py [<spec_file_or_dir>] [--language python] [--resume] [--max-phase N] [--token-budget N]
```

- `<spec_file_or_dir>` — required on first run; omitted on `--resume` (path read from `state["spec_file"]`)
- `--language` — required on first run; omitted on `--resume` (value read from `state["language"]`). Default: `"python"`
- `--resume` — load state.json and derive current position; re-reads spec file if resume path leads to TASK_BUILD; skips spec re-read for EXECUTING/FIXING/CLEANUP paths
- `--token-budget N` — maximum total tokens (input + output) for the current 5-hour window. Default: `config["default_token_budget"]`. Stops before next subprocess if estimated total would exceed this value.

Imports from `agents`, `calibrate`, `fix`, `lang`, `spec`, `state`, and `verify`.

## Module-Level Functions

```python
def _parse_args() -> argparse.Namespace:
    # argparse setup; returns parsed args

def _git_startup(state: dict) -> None:
    # Run once on startup before any agent dispatch.
    result = subprocess.run(["git", "status"], capture_output=True)
    if result.returncode != 0 and b"not a git repository" in result.stderr:
        subprocess.run(["git", "init"])
        subprocess.run(["git", "add", "-A"])
        subprocess.run(["git", "commit", "-m", "chore: init harness"])

    # Capture initial_sha before any building starts — used as base_sha for phase 1 review.
    # Only written once: skipped on --resume if state["initial_sha"] is already set.
    if not state.get("initial_sha"):
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        state["initial_sha"] = sha
        save_state(state)

def _pending_tasks(state: dict) -> list:
    # Returns all tasks with status="pending" for the current phase from state.json
    # Called at start of _do_executing(); result passed to calibrate.plan_batches()
    # Harness controls task selection — agent never self-selects tasks
```

## State Machine

```python
class HarnessState(Enum):
    INIT, PARSING, TASK_BUILD, EXECUTING, REVIEWING, FIXING, NEXT_PHASE, CLEANUP, COMPLETE, HALTED
```

## Harness Class Methods

```python
class Harness:
    def __init__(args)
                           # os.makedirs("workspace", exist_ok=True)  ← always first, before any state I/O
                           # load_config(), load_state(), get_profile(args.language)
                           # self.token_budget = args.token_budget or config["default_token_budget"]

    def run()              # main loop — reads state, dispatches to agent calls
                           #
                           # First run (no --resume):
                           #   validate CLI args (spec_file_or_dir required)
                           #   write state["spec_file"] and state["language"] to state.json
                           #   _git_startup(state)
                           #   parse_spec(spec_file, state, write_phases=True) then validate_spec()
                           #   state["current_phase"] = 1; save_state()
                           #   → TASK_BUILD
                           #
                           # --resume:
                           #   load state.json; read spec_file from state["spec_file"],
                           #   language from state["language"] (CLI --language overrides if provided)
                           #   _git_startup(state)
                           #   skip validate_spec() — spec was already validated on first run
                           #   current_state = _derive_state()
                           #
                           # Main loop dispatches:
                           #   TASK_BUILD  → _do_task_build()
                           #   EXECUTING   → _do_executing()
                           #   REVIEWING   → _do_reviewing()
                           #   FIXING      → run_fix_cycle() [fix.py]; → NEXT_PHASE
                           #   NEXT_PHASE  → advance current_phase; → TASK_BUILD or CLEANUP
                           #   CLEANUP     → run_cleanup() [fix.py]; → COMPLETE

    def _derive_state()    # derive current HarnessState from state.json on --resume
                           #
                           # Step 1 — scan for terminal/error states:
                           #   any task has status="halted" or "error"   → print last_error; sys.exit(1)
                           #   any issue has status="halted" or "error"  → print last_error; sys.exit(1)
                           #
                           # Step 2 — scan phases in order, return first unfinished state:
                           #   phase status="error"                                              → TASK_BUILD (retry once)
                           #   phase status="building", review.status="fixing"                  → FIXING
                           #   phase status="building", review.status in ("complete","fixed")    → TASK_BUILD (advance)
                           #   phase status="building", tasks pending/building                   → EXECUTING
                           #   phase status="pending"                                            → TASK_BUILD
                           #   phase status="complete"                                           → continue to next phase
                           #
                           # After all phases scanned:
                           #   deferred issues remain in state.json                             → CLEANUP
                           #   no deferred issues                                               → COMPLETE
                           #
                           # If derived state is TASK_BUILD: calls _load_spec_into_memory()
                           #   to extract descriptions + context needed for build_tasks()

    def _load_spec_into_memory()
                           # calls parse_spec(spec_file, state, write_phases=False)
                           # populates self.phases and self.context; does NOT touch state.json

    def _get_phase_data(phase_id: int) -> dict
                           # returns the phase dict from self.phases matching phase_id
                           # returns {} if not found

    def _do_task_build(state, phase_id) -> HarnessState
                           # 1. _get_phase_data(); if missing, call _load_spec_into_memory() first
                           # 2. build prompt preview; _check_token_budget(prompt, "TASK_BUILD")
                           # 3. update_state(phase status="building")
                           # 4. agents.build_tasks(phase_data, context, profile, config, state)
                           #    → SubprocessError: error_phase() → HALTED
                           # 5. unpack signal["tasks"]; write task shells into state_phase["tasks"]
                           #    each shell: {id, title, task_type, status:"pending", attempts:0,
                           #                 verify_fails:0, tdd_applied:None, tdd_skipped:None,
                           #                 files_changed:[], last_error:[]}
                           # 6. sync_task_types(state, new_tasks, profile)
                           # 7. save_state(); log_usage(mode="TASK_BUILD")
                           # → EXECUTING

    def _do_executing(state, phase_id) -> HarnessState
                           # 1. tasks = _pending_tasks(); if empty → REVIEWING
                           # 2. base_prompt = agents.file_preamble(builder_files)
                           # 3. batches = plan_batches(tasks, base_prompt_tokens, config)
                           # 4. for each batch:
                           #      set each task status="building" via update_state()
                           #      _check_token_budget(prompt, "EXECUTE", batch[0]["task_type"])
                           #      pre_sha = git rev-parse HEAD
                           #      agents.execute(batch, ...) → SubprocessError: error_task() → HALTED
                           #      verify_failures = verify_execution(self, pre_sha, batch, signal)  [verify.py]
                           #      process signal["tasks"]:
                           #        "complete" + not in verify_failed_ids → update_state(status="complete")
                           #        "failed" → attempts++, append reason to last_error, update_state()
                           #      failed_tasks = agent-reported failures + verify_execution() failures
                           #      log_usage() per task (proportional weight split for batches)
                           #      if failed_tasks: run_batch_retry_loop(self, state, failed_tasks, ...)  [fix.py]
                           # → REVIEWING

    def _do_reviewing(state, phase_id) -> HarnessState
                           # 1. derive base_sha:
                           #    phase 1 → state["initial_sha"]
                           #    phase N → prev_phase["review"]["sha_at_review"]
                           # 2. _check_token_budget(prompt, "REVIEW")
                           # 3. agents.review_phase(phase_id, base_sha, spec_paths, profile, config)
                           #    → SubprocessError: error_task() → HALTED
                           # 4. build issues list from signal["issues"]; each issue shell:
                           #    {id, severity, dimension, file, title, status:"open", attempts:0,
                           #     files_changed:[], fixed_sha:None, last_error:[]}
                           # 5. update_state(review status="complete", verdict, sha_at_review, issues)
                           # 6. handle_verdict(self, state, phase_id, result, ...)  [fix.py]
                           # → NEXT_PHASE

    def _check_token_budget(prompt, mode, task_type="default")
                           # called before every call_claude() dispatch
                           # task_type defaults to "default" — only EXECUTE callers pass a real task_type;
                           #   TASK_BUILD, REVIEW, FIX, CLEANUP callers omit it
                           # total_used = get_session_token_total()  ← sums last-5-hour window from usage.jsonl
                           # estimated, _ = estimate_call(prompt, mode, task_type)
                           # if total_used + estimated > self.token_budget:
                           #     print(f"[BUDGET] {total_used:,} used + ~{estimated:,} estimated = "
                           #           f"{total_used + estimated:,} would exceed budget of {self.token_budget:,}. "
                           #           f"Stopping before next subprocess — run --resume after your 5-hour window resets.")
                           #     sys.exit(0)
                           # called before: build_tasks(), execute() (per batch), review_phase(),
                           #                fix_issues(), and run_cleanup() dispatch
```

---

# harness/verify.py — Verification (~117 lines)

Runs compile/test checks after execute and fix agent calls. No agent subprocess calls — verification only.

Imported by both `harness.py` (via `_do_executing`) and `fix.py` (via `run_fix_cycle`, `run_cleanup`).

## Functions

```python
REVIEW_REPORT_PATH = Path("workspace/review_report.md")
FIX_TEST_FAILURE_LOG_PATH = Path("workspace/fix_test_failure.log")

def verify_execution(harness: object, pre_sha: str, batch: list, signal: dict) -> list:
    # Returns list of failed task signals (empty = all passed).
    #
    # TWO distinct failure cases — handled differently:
    #
    # Case 1 — pre_sha == HEAD (no commit made):
    #   stop_git_commit.py silently failed or was skipped.
    #   The agent's work may be on disk but uncommitted — a hook failure, not a code failure.
    #   verify_execution() first attempts a fallback commit of signal-listed safe paths.
    #   Setup/exempt/test_first tasks are accepted as no-op only when the signal files
    #   are already tracked and clean, or when no files were claimed.
    #   Otherwise verify_execution() returns all batch tasks as failed with reason
    #   "agent completed task but created no commit".
    #   Retry happens in run_batch_retry_loop(), where ExternalDependencyError can be
    #   recorded as blocked_external_dependency instead of crashing the harness.
    #
    # Case 2 — compile or test failure:
    #   git diff shows commits were made but py_compile or pytest fails.
    #   The agent wrote and committed bad code — a code failure requiring agent re-work.
    #   Returned as failed task list → caller passes to run_batch_retry_loop().
    #   No attempts++ (agent believed the task was complete; harness detected otherwise).
    #
    # artifact quality gate runs before compile/tests for changed text artifacts, including
    # setup/exempt outputs: UTF-8 without BOM, not UTF-16, and no NUL bytes.
    # requirements.txt also gets a minimal parseability check for malformed dependency lines.
    #
    # filter changed files to profile["compile_extensions"] (e.g. ["*.py"]) before compile loop
    # run profile["compile_cmd"] on each filtered file; then run profile["test_cmd"] once
    # returns list[dict] of task signals with compile/test failures (empty = all passed)

def verify_fix(harness: object, state: dict, fixes: list, phase_id: int, pre_sha: str = "", pre_snapshot: set[str] | None = None) -> list:
    # Runs profile["test_cmd"]; on pass, persists confirmed fixes with write ordering.
    # Returns list of still-open fix signals (test failed or fix["status"] != "fixed").
    # If tests fail, writes workspace/fix_test_failure.log with command, return code,
    # and stdout/stderr tails so the next retry has diagnosable evidence.
    # If tests pass but the FIX agent made disk changes without a commit, attempts a
    # fallback commit of signal-listed fix files before marking issues fixed.
    # Fixed text artifacts pass the same artifact quality gate as EXECUTE before state
    # is updated: UTF-8 without BOM, not UTF-16, and no NUL bytes.
    #
    # for each fix in fixes:
    #   if fix["status"] == "fixed" and test_passed:
    #     WRITE 1: update_state(issue status="fixed", files_changed, fixed_sha)  ← state.json first
    #     WRITE 2: _remove_from_review_report(fix["id"])                         ← file after
    #   elif fix["status"] == "deferred":
    #     update_state(issue status="deferred")
    #   else:
    #     open_fixes.append(fix)
    # return open_fixes

def _remove_from_review_report(issue_id: str) -> None:
    # Removes the section for issue_id from workspace/review_report.md using regex
    # No-op if review_report.md does not exist
```

---

# harness/fix.py — Fix & Cleanup (~319 lines)

Fix cycle, cleanup, and batch retry logic. All public functions receive `harness` as first argument to access `harness.config` and `harness.profile`.

Imports `verify_execution` and `verify_fix` from `verify.py`.

## Functions

```python
TECH_DEBT_PATH = Path("workspace/tech_debt.jsonl")

def run_batch_retry_loop(harness, state, failed_tasks, phase_id) -> None:
    # called with pre-collected failed_tasks from _do_executing() batch loop:
    #   agent-reported failures  (tasks[].status=="failed"): attempts++ already done
    #   compile/test failures from verify_execution: no attempts++
    #   hook commit failure (pre_sha==HEAD): retried here so 429 remains resumable
    #   parseable Claude 429 reset time: call_claude waits in-process, emits
    #   external_dependency_wait_start / external_dependency_wait_end, then retries
    #   the same subprocess call once before recording blocked_external_dependency
    # each retry calls agents.execute([task]) with exactly one task
    #
    # algorithm:
    #   failed_tasks = sorted by task_id
    #   for task in failed_tasks:
    #     while task.status != "complete":
    #       if task["attempts"] >= config["max_attempts"]:
    #           halt_task(task_id) → sys.exit(1)
    #       build failure_history = {task_id: task["last_error"]}
    #       pre_sha = git rev-parse HEAD
    #       agents.execute([task], failure_history) → SubprocessError: error_task() → return
    #       verify_failures = verify_execution(harness, pre_sha, [task], signal)
    #       if signal["tasks"][0]["status"] == "failed":
    #           task["attempts"] += 1
    #           task["verify_fails"] = 0    ← agent saw the failure; reset harness counter
    #           append reason to task["last_error"]; update_state(); continue
    #       if verify_failures:
    #           task["verify_fails"] += 1
    #           append harness reason to task["last_error"]
    #           if task["verify_fails"] >= config["verify_fail_escalation"]:
    #               task["attempts"] += 1; task["verify_fails"] = 0
    #           update_state(); continue
    #       # signal complete + verify passed
    #       task["verify_fails"] = 0; task.status = "complete"; update_state(); break

def run_fix_cycle(harness, state, phase_id) -> None:
    # Entry: reconcile review_report.md against state.json (remove already-fixed entries)
    # Then: fix all CRITICAL+HIGH in a loop; defer MEDIUM/LOW; halt on 3 failures
    # See Fix Cycle Workflow diagram below for full step-by-step logic

def handle_verdict(harness, state, phase_id, review_result, base_prompt_tokens, estimated_tokens) -> None:
    # Called after REVIEW signal written to state.json (all issues initially "open")
    # First: log_usage(mode="REVIEW", ...)
    #
    # APPROVE: no issues — return (harness advances to NEXT_PHASE)
    # WARN:   all issues are MEDIUM/LOW — mark all status="deferred" via update_state(),
    #         append each to tech_debt.jsonl, then return (harness advances to NEXT_PHASE)
    # BLOCK:  call run_fix_cycle(harness, state, phase_id)
    #         after fix cycle: remaining MEDIUM/LOW already deferred inside run_fix_cycle()

def run_cleanup(harness, state) -> None:
    # Called when all phases complete and deferred issues remain in state.json
    # Entry: re-derive active issue list via _all_deferred_issues(state)
    # If none: call _finish() and return
    #
    # Loop:
    #   still_open = _all_deferred_issues(state)
    #   if not still_open: break
    #   for issue in still_open:
    #     if attempts >= max_attempts: halt_issue() → sys.exit(1)
    #   agents.fix_issues(source_file="workspace/tech_debt.jsonl", failure_history)
    #   log_usage(task_id="cleanup", mode="CLEANUP")
    #   for each fix:
    #     if fixed: WRITE 1 state.json, reconstruct tech_debt.jsonl excluding fixed entries
    #     else: attempts++, append to failure_history, update_state()
    #   rewrite TECH_DEBT_PATH with remaining unfixed entries
    #
    # _finish(): final pytest run → print summary → COMPLETE
```

## Private Helpers

```python
def _finish() -> None:
    # Run pytest; print "[HARNESS] All phases complete." + output; print "[HARNESS] COMPLETE."

def _reconcile_review_report(state, phase_id) -> None:
    # Remove review_report.md entries for issues already marked "fixed" in state.json
    # Called at start of run_fix_cycle() to sync file state on --resume

def _open_critical_high(state, phase_id) -> list:
    # Return issues from state.json with status="open" and severity in ("CRITICAL", "HIGH")

def _append_medium_low_to_tech_debt(state, phase_id) -> None:
    # Append MEDIUM/LOW issues (status "open" or "deferred") to tech_debt.jsonl
    # Also marks each as status="deferred" in state.json via update_state()
    # Called by run_fix_cycle() after all CRITICAL/HIGH are resolved

def _append_issue_to_tech_debt(issue: dict) -> None:
    # Append single issue dict as JSON line to tech_debt.jsonl
    # Called by handle_verdict() for WARN verdict

def _all_deferred_issues(state: dict) -> list:
    # Return all issues across all phases with status="deferred"
    # Used by run_cleanup() and _derive_state() to detect CLEANUP state
```

## Fix Cycle Workflow (`run_fix_cycle`)

```
BLOCK verdict received
    │
    ├─ Step 1: fix all open CRITICAL+HIGH issues in ONE subprocess
    │     failure_history = {} (empty on first attempt)
    │     call fix_issues(source_file="workspace/review_report.md",
    │                     failure_history=failure_history)   # one claude -p call
    │     log_usage(mode="FIX", ...)
    │
    │     verify_fix(signal["fixes"]):
    │         run pytest once — if fails globally, write workspace/fix_test_failure.log
    │             and treat all as failed (retry all)
    │         if pytest passes but no FIX commit exists, fallback commit signal-listed fix files
    │         run artifact quality gate before accepting fixed text artifacts
    │         for each fix in signal["fixes"]:
    │             if fix["status"] == "fixed":
    │                 WRITE 1: state.json issue status="fixed"      ← source of truth first
    │                 WRITE 2: remove entry from review_report.md   ← file updated after
    │             if fix["status"] == "open":
    │                 increment issue["attempts"] in state.json
    │                 append reason to issue["last_error"] list in state.json
    │                 append reason to failure_history[issue_id] list: {issue_id: [reason, ...]}
    │             if fix["status"] == "deferred":
    │                 state.json issue status="deferred"            ← harness sets, no retry
    │                 append issue to tech_debt.jsonl               ← MEDIUM/LOW accumulator
    │
    ├─ Step 1b: retry loop for remaining failed issues
    │     while any issue status="open" in state.json:
    │         for each open issue:
    │             if issue["severity"] in ("MEDIUM", "LOW"):
    │                 # Severity-weighted halt: defer immediately after first failed attempt.
    │                 # Budget is reserved for CRITICAL/HIGH — MEDIUM/LOW go to CLEANUP.
    │                 state.json issue status="deferred"
    │                 append to tech_debt.jsonl
    │                 continue  ← skip retry
    │             if issue["attempts"] >= config["max_attempts"]:   # CRITICAL/HIGH only reach here
    │                 halt_issue(state, phase_id, issue_id)   # sets status="halted", saves state, sys.exit(1)
    │         call fix_issues(source_file="workspace/review_report.md",
    │                         failure_history=failure_history)  # new subprocess, remaining open CRITICAL/HIGH only
    │         log_usage(mode="FIX", ...)
    │         verify_fix() as above — state.json WRITE 1 before review_report.md WRITE 2
    │
    ├─ Step 2: after all CRITICAL+HIGH fixed (all status="fixed" in state.json)
    │     update_state(review.status="fixed")               ← marks fix cycle complete
    │     _append_medium_low_to_tech_debt(state, phase_id)  ← defer remaining MEDIUM/LOW
    │     REVIEW_REPORT_PATH.write_text("")                 ← empty for next phase
    │     NO re-review triggered here
    │
    ├─ Step 3: loop to TASK_BUILD for next phase
    │     fixes and next phase's tasks reviewed together in the next REVIEW call
    │     reviewer picks up all commits via git diff {base_sha}..HEAD
    │
    └─ Step 4: CLEANUP (after all phases complete)
          handled by run_cleanup() — see above
          re-derives active issue list from state.json (status="deferred") on entry (and on --resume)
          failure_history = {}
          call fix_issues(source_file="workspace/tech_debt.jsonl",
                          failure_history=failure_history)  # all MEDIUM+LOW in one subprocess
          verify_fix(): same write-order rules — state.json WRITE 1, tech_debt.jsonl WRITE 2
                        (harness rewrites tech_debt.jsonl excluding fixed entries, not line-by-line deletion)
          retry loop for failed issues (same pattern as phase fix cycle, up to 3 attempts per issue)
          final pytest run → print summary → COMPLETE
```
