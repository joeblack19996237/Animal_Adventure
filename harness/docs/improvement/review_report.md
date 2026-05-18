# Codebase Review Report

**Project:** Autonomous Dev Harness  
**Reviewed:** 2026-04-24  
**Reviewer:** Claude Sonnet 4.6 (manual review, not harness agent)  
**Scope:** All Python source files under `harness/` and `.claude/hooks/`  
**Reference docs:** `docs/05-harness-py.md`, `docs/06-agents-py.md`, `docs/07-calibrate-lang-py.md`, `docs/08-state-schema.md`, `docs/09-hooks.md`

---

## Summary

| Dimension | CRITICAL | HIGH | MEDIUM | LOW |
|-----------|----------|------|--------|-----|
| Functionality | 0 | 4 | 1 | 0 |
| Security | 0 | 2 | 2 | 1 |
| Performance | 0 | 1 | 3 | 1 |
| Design/Quality | 0 | 2 | 3 | 2 |
| **Total** | **0** | **9** | **9** | **4** |

---

## 1. Functionality

Reviewed against design docs in `docs/`. Findings reflect gaps between specified and actual behavior.

---

### F-1 · HIGH · Skills files not injected into agent prompts

**File:** `harness/agents.py:23-27` · `harness/lang.py`

`build_file_lists()` constructs agent file lists from the language profile but omits skills files. The design doc (`docs/06-agents-py.md`) specifies:

```python
# Specified in doc:
builder_files  = [profile["builder_agent"]] + common + [profile["builder_skill"]]
reviewer_files = [profile["reviewer_agent"]] + common + [profile["reviewer_skill"]]

# Actual implementation:
builder_files = [profile["builder_agent"]] + common   # no skill
reviewer_files = [profile["reviewer_agent"]] + common  # no skill
```

The `lang.py` profile has no `builder_skill` or `reviewer_skill` keys. This means the TDD-workflow skill (required for code-builder in EXECUTE mode per `CLAUDE.md`) and the security-review skill (required for code-reviewer per `CLAUDE.md`) are never injected into agent prompts. The CLAUDE.md states these skills MUST be invoked — they currently are not.

**Fix:** Add `builder_skill` and `reviewer_skill` to the Python profile in `lang.py` pointing to the skill `SKILL.md` paths, and include them in `build_file_lists()`.

---

### F-2 · HIGH · Tasks left in "building" status are unrecoverable on `--resume`

**File:** `harness/harness.py:328-329` · `harness/harness.py:95-99`

When the harness crashes or is killed after `update_state(status="building")` but before the agent completes, those tasks remain in `"building"` status. On `--resume`, `_derive_state` returns `HarnessState.EXECUTING`, but `_pending_tasks` only returns tasks with `status == "pending"`. Tasks stuck in `"building"` are invisible to `_pending_tasks` and are silently skipped, sending the phase to REVIEWING without completing them.

```python
# harness.py:95-99
def _pending_tasks(state: dict) -> list:
    ...
    return [t for t in phase.get("tasks", []) if t["status"] == "pending"]
    # "building" tasks are skipped silently
```

**Fix:** `_pending_tasks` should treat `"building"` tasks as `"pending"`, or `_derive_state` should reset interrupted `"building"` tasks back to `"pending"` before returning `EXECUTING`.

---

### F-3 · HIGH · Review subprocess error not recorded in state.json

**File:** `harness/harness.py:443-444`

When `agents.review_phase()` raises `SubprocessError`, the harness calls:

```python
error_task(state, f"phase_{phase_id}_review", str(e))
```

But `error_task` calls `_find_task(state, task_id)` which searches for a task with that ID. The pseudo-ID `"phase_1_review"` matches no task (tasks have IDs like `"1.1"`), so `_find_task` returns `None` and the error is not recorded in `state.json`. The state remains unchanged while the process exits. On `--resume`, `_derive_state` will attempt REVIEWING again without any error record.

**Fix:** Use `error_phase(state, phase_id, str(e))` instead of `error_task` for review subprocess failures. Or introduce a dedicated `error_review` function.

---

### F-4 · HIGH · Phase status never set to "complete"

**File:** `harness/harness.py:176-183` · `harness/state.py:140-145`

The state schema doc (`docs/08-state-schema.md`) and the `_apply_phase_fields` docstring specify that phase status should transition `pending → building → complete`. However, no code in the harness sets phase status to `"complete"`. The `NEXT_PHASE` handler only increments `current_phase`:

```python
elif current_state == HarnessState.NEXT_PHASE:
    next_id = phase_id + 1
    state["current_phase"] = next_id
    save_state(state)
    current_state = HarnessState.TASK_BUILD  # phase stays "building" forever
```

`_derive_state` handles advancement via `review.status` checks, which works functionally, but the phase status field never reflects its true terminal state. Observability tooling or external scripts that read `state.json` and check `phase.status == "complete"` will find no completed phases.

**Fix:** Set `update_state(state, entity_type="phase", phase_id=phase_id, status="complete")` in `NEXT_PHASE` before advancing, or at the end of `handle_verdict` for APPROVE/WARN verdicts.

---

### F-5 · MEDIUM · `phase_id` passed as string in no-commit retry path

**File:** `harness/verify.py:22-26`

In `verify_execution`, when no commit was detected (`current_sha == pre_sha`), the retry call passes `phase_id` extracted from the task ID string:

```python
result = agents.execute(
    batch,
    phase_id=batch[0]["id"].split(".")[0],  # returns str "1", not int 1
    ...
)
```

The JSON schema for EXECUTE signals requires `phase_id` as an integer. The `stop_validate_json.py` hook will reject the signal, triggering a correction loop. The harness then receives a signal with the wrong type echo-back, and the state-machine loop may enter unexpected behavior.

**Fix:** Cast to `int`: `phase_id=int(batch[0]["id"].split(".")[0])`.

---

## 2. Security

Reviewed against the security checklist (subprocess safety, input validation, path traversal, secrets, sensitive data exposure).

---

### S-1 · HIGH · Agent-supplied file paths committed without validation

**File:** `.claude/hooks/stop_git_commit.py:56`

The stop_git_commit hook stages files listed in the agent's signal `files_changed`:

```python
subprocess.run(["git", "add"] + files, check=True)
```

`files` come directly from the agent subprocess output with no path validation. A compromised or hijacked agent could include paths like `../../.env`, `~/.ssh/id_rsa`, or other sensitive files outside the project directory. Using list-form subprocess prevents shell injection, but `git add` with arbitrary paths can still stage unintended files.

**Fix:** Validate each path in `files` against the project root before staging:
```python
from pathlib import Path
root = Path(".").resolve()
for f in files:
    resolved = (root / f).resolve()
    if not str(resolved).startswith(str(root)):
        print(f"[SECURITY] Blocked path outside project root: {f!r}")
        sys.exit(1)
```

---

### S-2 · HIGH · Agent-supplied file paths used in compile commands

**File:** `harness/verify.py:54-55`

File paths from agent signals are passed directly to the compile command:

```python
cmd = [part.replace("{file}", f) for part in harness.profile["compile_cmd"]]
result = subprocess.run(cmd, capture_output=True, text=True)
```

`f` comes from `task_sig.get("files_changed", [])` — agent-supplied. While `shell=False` prevents shell injection, a path like `--check` or a file outside the project could affect the Python interpreter's behavior. Combined with S-1, this is a defence-in-depth gap.

**Fix:** Apply the same project-root boundary check as S-1 before passing paths to compile commands. Also skip non-existent paths rather than silently passing them.

---

### S-3 · MEDIUM · `git add -A` on first run may commit unintended files

**File:** `harness/harness.py:84-85`

When no git repository exists, `_git_startup` runs:

```python
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "commit", "-m", "chore: init harness"], check=True)
```

`git add -A` stages everything in the working directory, which may include `.env` files, credentials, local config, or large binaries the user did not intend to commit. There is no `.gitignore` check before this operation.

**Fix:** Ensure `.gitignore` is in place before `git add -A`. Alternatively, use `git add harness/ .claude/ docs/` to stage only harness-owned files rather than staging everything.

---

### S-4 · MEDIUM · `print()` used throughout instead of structured logging

**File:** Multiple — `harness/harness.py`, `harness/state.py`, `harness/calibrate.py`, `harness/fix.py`, `.claude/hooks/`

The coding standards (`.claude/rules/common/coding-standards.md`) prohibit `print()` in production code and require the logging module. The harness uses `print()` for all operational output: `[BUDGET]`, `[WARN]`, `[HALT]`, `[ERROR]`, `[HARNESS]` messages. This precludes log-level filtering, structured output, and file-based log capture.

**Fix:** Replace `print()` with `logging.getLogger(__name__)` calls using appropriate levels (`logger.warning`, `logger.error`, `logger.info`). Configure a stream handler in the entry point.

---

### S-5 · LOW · `extract_signal` greedy regex can match across multiple JSON objects

**File:** `harness/agents.py:46-49`

The fallback JSON extraction uses:

```python
m = re.search(r"\{.*\}", stripped, re.DOTALL)
```

This greedy pattern, if the input contains multiple JSON objects separated by text (e.g., prose interleaved with JSON), matches from the first `{` to the last `}`, producing invalid JSON. The resulting `json.loads(m.group())` raises `JSONDecodeError`, which propagates uncaught at this point and surfaces as a `SubprocessError`. The fallback is intended as a last resort, but the failure mode is an unhandled exception rather than a descriptive error.

**Fix:** Wrap `json.loads(m.group())` in a try/except and raise a descriptive `ValueError`:
```python
try:
    return json.loads(m.group())
except json.JSONDecodeError as e:
    raise ValueError(f"Greedy JSON extraction failed: {e} — raw: {raw[:200]!r}") from e
```

---

## 3. Performance

---

### P-1 · HIGH · O(n²) JSONL reads from repeated `_refresh_calibration` calls

**File:** `harness/calibrate.py:105-130` · `harness/agents.py:198-213`

`_refresh_calibration` calls `read_usage_jsonl()` and filters the full list on every invocation. In `agents.execute()` for a batch of n tasks, it is called 2n times (once for overhead, once for output per task):

```python
overheads = [_refresh_calibration("EXECUTE", t["task_type"])["overhead"] for t in tasks]
outputs   = [_refresh_calibration("EXECUTE", t["task_type"])["output"] for t in tasks]
```

`_refresh_calibration` also calls `load_calibration()` (a file read) and `save_calibration()` (a file write) on each invocation when calibration is updated. For a 10-task batch with a 1000-entry JSONL file, this is 20 full file reads and up to 20 write cycles.

Additionally, `_usage_cache` is invalidated in `log_usage()` on every write, so every subsequent `read_usage_jsonl()` call re-reads the file from disk.

**Fix:** Cache the calibration lookup results per `(mode, task_type)` within a single harness run. Refactor `plan_batches` and `execute` to call `_refresh_calibration` once per unique task_type rather than once per task. Consider keeping a running sum for `get_session_token_total` rather than re-scanning the full JSONL each call.

---

### P-2 · MEDIUM · `save_state` + `_correct_ids` on every `update_state` call

**File:** `harness/state.py:19-22` · `harness/state.py:25-41`

Every `update_state()` call ends with `save_state()`, which calls `_correct_ids()` (a full scan of all phases/tasks/issues) then writes the entire state dict to disk. In tight loops like `run_batch_retry_loop`, multiple consecutive `update_state` calls each trigger this full-scan + write cycle. For a state with many phases and tasks, `_correct_ids` becomes O(n) per call.

**Fix:** Batch state writes where possible. Separate `_correct_ids` into an on-load cleanup that runs once rather than on every save. Or, at minimum, skip `_correct_ids` in the hot path and only run it on `load_state` and explicit saves.

---

### P-3 · MEDIUM · `get_session_token_total` re-scans full JSONL with datetime parsing

**File:** `harness/calibrate.py:201-207`

```python
def get_session_token_total() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=5)
    return sum(
        ...
        for e in read_usage_jsonl()
        if datetime.fromisoformat(e["ts"]).replace(tzinfo=timezone.utc) >= cutoff
    )
```

This is called before every agent dispatch. With a growing `usage.jsonl`, it parses every timestamp on every call. The `.replace(tzinfo=timezone.utc)` is also redundant — `datetime.now(timezone.utc).isoformat()` already produces a timezone-aware string that `fromisoformat` returns as timezone-aware; replacing tzinfo is a no-op.

**Fix:** Since usage entries are appended in chronological order, binary-search or scan from the tail to find the 5-hour cutoff rather than scanning the full file. Alternatively, track `session_start` in the harness and only sum entries written after that time.

---

### P-4 · MEDIUM · `_calibration_mature` rescans JSONL for every task in every batch planning call

**File:** `harness/calibrate.py:160-171`

```python
def _calibration_mature(tasks: list, config: dict) -> bool:
    threshold = config["min_entries_before_batching"]
    usage = read_usage_jsonl()
    for task in tasks:
        count = sum(1 for e in usage if e["mode"] == "EXECUTE" and e["task_type"] == task["task_type"])
        if count < threshold:
            return False
    return True
```

For n tasks, this is O(n × m) where m is the JSONL length. `read_usage_jsonl()` is called once (cached if cache is warm), but the inner `sum` still iterates m entries per task.

**Fix:** Build a `Counter` of `(mode, task_type)` from the JSONL once, then check the counter per task:
```python
from collections import Counter
counts = Counter((e["mode"], e["task_type"]) for e in usage)
return all(counts[("EXECUTE", t["task_type"])] >= threshold for t in tasks)
```

---

### P-5 · LOW · Redundant `git rev-parse HEAD` calls in cleanup loop

**File:** `harness/fix.py:262-264`

In `run_cleanup`, `fixed_sha` is captured inside the `for fix in fixes` loop:

```python
fixed_sha=subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True
).stdout.strip(),
```

All fixes in one `agents.fix_issues()` call are committed by the stop hook as a single commit, so HEAD is the same for all fixes. The `rev-parse` call should be made once before the loop.

**Fix:** Capture `current_sha = subprocess.run(["git", "rev-parse", "HEAD"], ...).stdout.strip()` once before the `for fix in fixes` loop.

---

## 4. Design / Quality

---

### D-1 · HIGH · `harness: object` type hint with blanket `# type: ignore`

**File:** `harness/fix.py:27,106,174,208` · `harness/verify.py:12,91`

All cross-module functions that receive the `Harness` instance type it as `object` to avoid a circular import, then suppress type errors with `# type: ignore[attr-defined]` at every attribute access:

```python
def run_batch_retry_loop(harness: object, state: dict, ...) -> None:
    ...
    if task["attempts"] >= harness.config["max_attempts"]:  # type: ignore[attr-defined]
```

This defeats static analysis, makes IDE navigation impossible, and hides real attribute errors. The coding guidelines require all functions to have correct type annotations.

**Fix:** Define a `HarnessProtocol` using `typing.Protocol` with `config: dict` and `profile: dict` attributes, or use a `TYPE_CHECKING` forward reference:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from harness import Harness

def run_batch_retry_loop(harness: Harness, state: dict, ...) -> None:
    ...
```

---

### D-2 · HIGH · Task-tracker comments left in committed code

**File:** `harness/agents.py:18-21, 52-55, 114-116, 148-150, 218-221`

```python
# ---------------------------------------------------------------------------
# Task 5.1 — File lists, preamble, signal extraction
# ---------------------------------------------------------------------------
```

The coding guidelines (`.claude/rules/common/coding-standards.md`) prohibit `TODO` left in committed code and state that comments must explain WHY, not WHAT. These section headers are development-phase task tracker markers with no informational value for a reader. They also fragment a module into sections that have no bearing on its public API.

**Fix:** Remove all `# Task N.M —` comment blocks. If section breaks are desired, a single blank line between function groups is sufficient.

---

### D-3 · MEDIUM · Private functions imported across module boundaries

**File:** `harness/harness.py:35-37`

```python
from state import (
    _find_phase,
    _find_task,
    ...
)
```

Importing `_find_phase` and `_find_task` (private by Python convention) from an external module breaks encapsulation. If `state.py` internals change, callers break. The `update_state` function already wraps these lookups — callers should use the public API.

**Fix:** Expose `find_phase` and `find_task` as public functions in `state.py` (remove the `_` prefix), or add a dedicated query function like `get_phase(state, phase_id)` that external callers use.

---

### D-4 · MEDIUM · No token budget check before `fix_issues` calls

**File:** `harness/fix.py:119-124` · `harness/fix.py:225-232`

`run_fix_cycle` and `run_cleanup` call `agents.fix_issues()` directly without checking the token budget. All three harness dispatch methods (`_do_task_build`, `_do_executing`, `_do_reviewing`) call `self._check_token_budget()` before dispatching. Fix and cleanup cycles are the most token-intensive operations (multiple agent calls per cycle) yet have no budget guard.

**Fix:** Add `harness._check_token_budget(prompt_preview, "FIX")` (or `"CLEANUP"`) at the top of `run_fix_cycle` and `run_cleanup` before calling `agents.fix_issues()`.

---

### D-5 · MEDIUM · `requirements.txt` has unpinned dependencies

**File:** `harness/requirements.txt`

```
jsonschema
ruff
pytest
pytest-cov
pytest-mock
```

No version constraints. A `pip install` in a new environment may install an incompatible major version of `jsonschema` (breaking schema validation) or `ruff` (changing lint behavior). The coding standards require pinned or constrained versions.

**Fix:** Pin to known-good versions or use `~=` constraints:
```
jsonschema~=4.23
ruff~=0.9
pytest~=8.3
pytest-cov~=6.1
pytest-mock~=3.14
```

---

### D-6 · LOW · `_correct_ids` positional correction is fragile

**File:** `harness/state.py:25-41`

When an ID fails the `^\d+\.\d+$` regex, it is silently replaced with `{phase_id}.{seq}` where `seq` is the 1-based position in the list. If issues are reordered, partially populated, or removed by a harness crash, the positional reassignment will produce wrong IDs. The `[WARN]` message is easy to miss.

**Fix:** Make `_correct_ids` stricter: if a malformed ID is detected, log at WARNING and do not auto-correct. Raise an exception or print a clear prompt asking the user to fix `state.json` manually. Auto-correction of IDs can mask data corruption.

---

### D-7 · LOW · Module-level `_usage_cache` global state

**File:** `harness/calibrate.py:9`

```python
_usage_cache: list | None = None
```

Module-level mutable state makes unit tests depend on import order and requires explicit reset between tests. The cache is invalidated on every `log_usage()` call, making it nearly stateless in practice while still carrying the complexity of a cache.

**Fix:** If caching is valuable, pass the cache as a parameter or encapsulate calibration state in a `CalibrationContext` class. If the cache is rarely effective (reset on every write), remove it and simplify `read_usage_jsonl()` to always read from disk.

---

## Cross-Cutting Observation

The harness has a solid architectural foundation — atomic state writes, explicit state-machine transitions, JSON schema validation on agent output, and good subprocess isolation. The most impactful fixes to prioritize are:

1. **F-1** (skill injection) — without TDD and security-review skills, the quality loop the harness is designed to enforce is broken.
2. **F-2** (building-status recovery) — crash recovery is incomplete, defeating the `--resume` guarantee.
3. **P-1** (JSONL O(n²) reads) — will degrade significantly as projects grow past a few phases.
4. **S-1 / S-2** (agent-supplied path validation) — the agent is the only untrusted component; its file paths should be treated as external input.
