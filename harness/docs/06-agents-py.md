# harness/agents.py — Agent Caller (~250 lines)

All `claude -p` subprocess logic lives here. `harness.py` imports and calls these functions.

## Agent File Lists (Profile-Driven)

```python
# File lists are fully profile-driven — all paths come from the active LanguageProfile
def build_file_lists(profile: dict) -> tuple[list, list]:
    """Return (builder_files, reviewer_files) for the active language profile.
    All paths come from the profile — no hardcoded values."""
    common = [profile["common_rules"], profile["rules_file"]]
    builder_files  = [profile["builder_agent"]]  + common + [profile["builder_skill"]]
    reviewer_files = [profile["reviewer_agent"]] + common + [profile["reviewer_skill"]]
    return builder_files, reviewer_files

def file_preamble(paths: list[str]) -> str:
    """Return a prompt block instructing the agent to read its instruction files first."""
    lines = ["Read these files before starting (use your Read tool, in order):"]
    lines += [f"- {p}" for p in paths]
    return "\n".join(lines)
```

## Functions

```python
# SUBPROCESS_TIMEOUT loaded from harness/config.json — not hardcoded here.
# agents.py receives config dict on startup; callers pass it into call_claude().

def call_claude(prompt, model, tools="Read,Write,Edit,Bash,Grep,Glob", mode="EXECUTE", config=None) -> dict:
    # timeout = config["subprocess_timeout"][mode]
    # try:
    #     result = subprocess.run(["claude", "--print", "--model", model,
    #                              "--output-format", "json", "--allowedTools", tools],
    #                             input=prompt, text=True, capture_output=True,
    #                             timeout=timeout)
    # except RunnerTimeout:
    #     # Stop hooks do NOT fire on timeout — subprocess is killed before hooks run.
    #     # Any files written to disk are uncommitted; state.json and git are consistent
    #     # (no partial commit happened). After one retry, raise TimeoutError.
    #     raise TimeoutError(f"timeout after {timeout}s ({mode} mode) — "
    #                        "increase subprocess_timeout in harness/config.json or split the task")
    #
    # Two distinct failure modes — handled differently by harness.py:
    #
    # 1. Subprocess-level infrastructure errors:
    #    - api_error_status == 429 raises ExternalDependencyError, except when
    #      the message includes a parseable Claude 429 reset time within the
    #      safe wait window; then call_claude emits external_dependency_wait_start
    #      and external_dependency_wait_end, sleeps in-process, and retries once
    #    - timeout after one retry raises TimeoutError
    #    - nonzero exit, unparseable envelope, and bad signal extraction raise SubprocessError
    #    Callers record distinct state statuses where needed. Evaluate uses
    #    blocked_external_dependency, timeout, and error so --status can tell current
    #    external blocks apart from malformed evaluator output.
    #
    # 2. Agent logic failure (envelope["result"] is not valid JSON):
    #    Agent ran but did not complete the task correctly.
    #    Return the parsed signal — harness reads per-item statuses (tasks[i].status,
    #    fixes[i].status) to detect failures and increment attempts. No wrapper status.
    #
    # Signal parsing — two-layer defence:
    #   Primary:  stop_validate_json.py Stop hook fires within the subprocess before
    #             claude -p exits. If agent output is not valid JSON, the hook injects
    #             an error message back to the agent for self-correction in the same
    #             subprocess. By the time call_claude() gets the result, the hook has
    #             already enforced the JSON contract.
    #   Fallback: if the hook failed to correct it (stop_hook_active guard triggered),
    #             extract_signal() below strips any residual prose wrapping before parse.
    #
    # envelope = json.loads(result.stdout)          # outer CLI JSON
    # signal   = extract_signal(envelope["result"]) # strip prose, then json.loads
    # usage    = envelope["usage"]                  # token counts for usage.jsonl
    # Inspect result.stderr: print any "[WARN]" lines to console only.
    # state.json tracks task/issue status only — no debug or diagnostic entries.
    # returns {"signal": dict, "usage": dict}

Review prompts tell the reviewer to run both the scoped diff command and `git status --short` so phase-relevant untracked files are not missed.

Before starting a Claude subprocess, `call_claude()` may apply session pacing from
`claude_session_pacing`. This is a soft delay, not a token budget: Claude Pro
5-hour limits are dynamic, so the harness uses recent `workspace/usage.jsonl`
pressure signals to spread calls out without predicting a hard quota.

## Subprocess Envelope — Full Example

The `claude --output-format json` CLI wraps the agent's final message in an envelope.
`call_claude()` reads `result.stdout` which is always this envelope, never the raw agent text.

**Raw `result.stdout` (EXECUTE mode, one task succeeded):**
```json
{
  "result": "{\"mode\":\"EXECUTE\",\"phase_id\":1,\"tasks\":[{\"id\":\"1.1\",\"title\":\"Create User model\",\"task_type\":\"database\",\"status\":\"complete\",\"tdd_applied\":true,\"tdd_skipped\":null,\"files_changed\":[\"src/models.py\",\"tests/test_models.py\"]}]}",
  "usage": {
    "input_tokens": 1842,
    "output_tokens": 312,
    "cache_read_input_tokens": 1490,
    "cache_creation_input_tokens": 0
  }
}
```

**After `signal = extract_signal(envelope["result"])`:**
```json
{
  "mode": "EXECUTE",
  "phase_id": 1,
  "tasks": [
    {
      "id": "1.1",
      "title": "Create User model",
      "task_type": "database",
      "status": "complete",
      "tdd_applied": true,
      "tdd_skipped": null,
      "files_changed": ["src/models.py", "tests/test_models.py"]
    }
  ]
}
```

**state.json fields updated from signal (task "1.1"):**
```json
{
  "status": "complete",
  "tdd_applied": true,
  "tdd_skipped": null,
  "files_changed": ["src/models.py", "tests/test_models.py"]
}
```
Fields NOT in signal — managed by harness: `attempts`, `last_error`

**Raw `envelope["usage"]` fields (for reference — NOT the usage.jsonl format):**
```json
{"input_tokens": 1842, "output_tokens": 312, "cache_read_input_tokens": 1490, "cache_creation_input_tokens": 0}
```
`call_claude()` passes these raw fields to `log_usage()`, which computes derived fields (`overhead_actual`, `estimation_error`) and writes the full entry using the schema defined in `calibrate.py` (fields: `ts`, `task_type`, `estimated_input_tokens`, `overhead_actual`, etc.). `log_usage()` is called after every subprocess — not just EXECUTE — using mode-specific task_id sentinels (e.g. `"phase_1_review"`, `"phase_1_build"`). See `docs/07-calibrate-lang-py.md`.

def extract_signal(raw: str) -> dict:
    # Last-resort harness-side JSON extraction — should rarely fire if Stop hook works.
    # Returns dict (wrapper signal object — always a dict after wrapper design).
    # Raises ValueError (treated as agent logic failure → retry) if no JSON found.
    import re
    stripped = re.sub(r'^```json\s*|^```\s*|```$', '', raw.strip(), flags=re.MULTILINE).strip()
    # Fast path: stripped text is already clean JSON (common case after fence removal)
    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Fallback: prose surrounds the JSON — find the outermost object with regex
    m = re.search(r'\{.*\}', stripped, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON found in agent output: {raw[:200]!r}")
    return json.loads(m.group())

def build_tasks(phase, context, profile, config) -> dict:
    # Calls call_claude(..., model=profile["build_model"], mode="TASK_BUILD", config=config)
    # TASK_BUILD is a pure classification task (read phase → emit task list) — Haiku is used here;
    # cheaper and faster than Sonnet with no quality loss for JSON classification work.
    # calibrate.py log_usage() tracks build_model entries separately from execute_model in usage.jsonl.
    # Prompt: file_preamble(builder_files) + TASK-BUILD mode — read phase, classify tasks by task_type, emit JSON signal
    # Harness captures stdout, parses JSON signal, writes task list to state.json
    # On non-"complete" signal or SubprocessError: call error_phase(state, phase_id, reason) → sys.exit(1)
    # On --resume from phase status="error": harness retries build_tasks() once; second failure is final

def execute(tasks: list, failure_history: dict | None = None) -> dict:
    # One subprocess call regardless of batch size — always returns {"signal": dict, "usage": dict}
    # tasks: list of {id, title, task_type} — one element for single/retry, multiple for batch
    # failure_history: {task_id: [reason, ...]} — injected into prompt only when len(tasks) == 1 (retry path)
    #                  ignored for fresh batches (no per-task history on first attempt)
    #
    # Prompt branches on len(tasks):
    #   len == 1: focused single-task prompt — "MODE=EXECUTE. Task {id}: {desc}. Prior attempts: {history_if_any}."
    #             agent responds with wrapper {"mode": "EXECUTE", "status": ..., "phase_id": N, "tasks": [{...}]}
    #   len >  1: ordered list prompt — "MODE=EXECUTE. Complete these tasks in order: 1. {id}: {desc} ..."
    #             agent responds with wrapper {"mode": "EXECUTE", "status": ..., "phase_id": N, "tasks": [{...}, {...}]}
    #
    # Timeout: len(tasks) * config["subprocess_timeout"]["EXECUTE"]  ← scales naturally; len==1 gives base timeout unchanged
    #
    # Usage split: for len > 1 only — proportional weights applied before log_usage() calls
    #              input_weight  = task_overhead  / sum(overhead  for all tasks in batch)
    #              output_weight = task_output    / sum(output    for all tasks in batch)
    #
    # Prompt includes text artifact guidance: write UTF-8 without BOM; do not create
    # UTF-16 or NUL-byte text files.
    #
    # signal is always a wrapper dict — harness reads signal["tasks"] to process per-task results

def review_phase(phase_id, base_sha, spec_paths) -> dict:
    # Prompt: file_preamble(reviewer_files) + REVIEW mode — read spec, run git diff {base_sha}..HEAD, review 4 dimensions
    # base_sha derived by harness: state["initial_sha"] for phase 1, prior phase sha_at_review for phase N+1

def fix_issues(source_file, failure_history=None) -> dict:
    # Prompt: file_preamble(BUILDER_FILES) + FIX mode — fix ALL issues in source_file in one subprocess
    # source_file: review_report.md (phase fix cycle) or tech_debt.jsonl (CLEANUP)
    # failure_history: {issue_id: [reason1, reason2, ...]} from prior failed attempts — full list injected
    #                  into prompt so agent sees all prior strategies and can try a different approach
    # Prompt includes text artifact guidance: write UTF-8 without BOM; do not create
    # UTF-16 or NUL-byte text files.
    #
    # Harness drives retry logic from signal["fixes"] and state.json — no issue list pre-enumeration needed
    # Returns {"signal": dict, "usage": dict} where signal["fixes"] is a per-issue result array

# verify_execution(), verify_fix(), and run_batch_retry_loop() live in harness.py (Harness class methods) — not here.
# agents.py contains only claude -p subprocess logic.
```

## Prompt Patterns

Every prompt ends with: `"Your entire response must be a single valid JSON object. No prose, no explanation, no markdown. Only JSON."` All modes return a wrapper object — EXECUTE wraps per-task results in `tasks[]`, FIX wraps per-issue results in `fixes[]`.

| Call type | Prompt structure |
|-----------|-----------------|
| Build tasks | `file_preamble(builder_files) + "\nMODE=TASK_BUILD. Phase: {phase_text}. Respond with JSON only — your entire response is the task list signal."` |
| Execute (single / retry, len==1) | `file_preamble(builder_files) + "\nMODE=EXECUTE. Phase {phase_id}. Task {task_id}: {desc}.{failure_history_block}. Write text artifacts as UTF-8 without BOM; do not create UTF-16 or NUL-byte text files. Respond with JSON only."` where `failure_history_block` = `"\nPrior attempts:\n- Attempt 1: {reason}\n- Attempt 2: {reason}"` (omitted on first attempt). Harness injects `phase_id` so it is echoed back in the signal. |
| Execute (batch, len>1) | `file_preamble(builder_files) + "\nMODE=EXECUTE. Phase {phase_id}. Complete these tasks in order:\n1. {task_1_id}: {desc}\n2. {task_2_id}: {desc}\n...\nWrite text artifacts as UTF-8 without BOM; do not create UTF-16 or NUL-byte text files. Respond with a JSON wrapper object: {\"mode\": \"EXECUTE\", \"phase_id\": N, \"tasks\": [one object per task in order]}."` |
| Review | `file_preamble(reviewer_files) + "\nMODE=REVIEW. Phase {id}. Spec files: {spec_paths}. Base SHA for diff: {base_sha}. Run git diff {base_sha}..HEAD to scope your review. Write findings to workspace/review_report.md. Respond with JSON only."` |
| Fix (phase fix cycle) | `file_preamble(builder_files) + "\nMODE=FIX. Read all open issues from workspace/review_report.md. Fix each in severity order. Prior failed attempts: {failure_history_if_any}. Write text artifacts as UTF-8 without BOM; do not create UTF-16 or NUL-byte text files. Run pytest after all fixes. Respond with JSON only."` |
| Fix (CLEANUP) | `file_preamble(builder_files) + "\nMODE=FIX. Read all open issues from workspace/tech_debt.jsonl (newline-delimited JSON, one issue per line). Fix each MEDIUM issue first, then LOW, in file order. Prior failed attempts: {failure_history_if_any}. Write text artifacts as UTF-8 without BOM; do not create UTF-16 or NUL-byte text files. Run pytest after all fixes. Respond with JSON only."` |

## Phase 11 Agent Runtime Notes

All Claude CLI calls go through `harness/subprocess_runner.py`. `agents.call_claude()` still owns command construction, JSON envelope parsing, and signal extraction, but process execution, timeout metadata, stdout/stderr tails, and process cleanup are centralized. Timeout and nonzero exit events are written to `workspace/events.jsonl`.

When Claude returns a parseable 429 reset time, the harness must prove the workspace is clean before sleeping and retrying. It writes `workspace/external_dependency_context.json`, cleans the Claude subprocess tree, quarantines new untracked files from the failed call under `workspace/external_dependency_artifacts/`, blocks on newly dirty tracked files, emits `external_dependency_wait_start`, sleeps until reset, then runs a final preflight before retrying the same Claude call once. `--resume` also reads the context and runs the same preflight before advancing state, so a reset after a killed or interrupted wait never resumes into a dirty environment.

`timeout_policy.compute_timeout()` preserves `subprocess_timeout` as the base value. REVIEW can scale by phase task count, changed file count, and diff line count, bounded by configured min/max values. This keeps small reviews quick while giving large diffs enough time without changing EXECUTE/FIX/CLEANUP defaults.

After CRITICAL/HIGH fixes pass verification, `agents.review_fix()` asks the reviewer to inspect only the fixed issue IDs and the safe diff scope. The fix cycle marks `review.status="fixed"` only after targeted re-review returns no blocking CRITICAL/HIGH issue.
