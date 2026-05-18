# harness/calibrate.py — Estimation + Batch Planning + Calibration (~100 lines)

**Purpose:** pre-call token estimation, subprocess batch planning, post-run calibration from real usage data. No handoff logic.

Current implementation keeps `task_type` as a usage-log field, not as a batching
or prediction key. Claude Pro 5-hour limits are dynamic, so the harness does not
enforce an `effective_token_budget`; it reports actual/cache/combined token
pressure and leaves quota control to soft `claude_session_pacing`.

```python
CHARS_PER_TOKEN = 3.5   # character-to-token ratio for base prompt estimation
P90_MARGIN      = 1.1   # p90 + 10% safety buffer applied when writing calibrated values

# max_batch_tokens, min_entries_before_batching — loaded from harness/config.json at startup.
# subprocess_timeout, max_attempts, verify_fail_escalation, max_evaluate_iterations,
# and evaluate_early_stop_on_full_score — also in config.json (read by harness.py / agents.py).
# Keeping user-tunable params in config.json prevents them from being silently overwritten
# by calibrate.py's auto-update writes to calibration.json.

# Estimates are read from harness/calibration.json — not hardcoded.
# calibration.json ships with conservative seed values and is updated in place by calibrate.py
# once ≥5 usage.jsonl entries exist for a (mode, task_type).
# EXECUTE is keyed by task_type; all other modes use "default".
# New task_types added by sync_task_types() inherit the EXECUTE "default" values until calibrated.
#
# calibration.json structure:
# {
#   "TASK_BUILD": {"default": {"overhead": 15000, "output": 8000}},
#   "EXECUTE": {
#     "default":     {"overhead": 50000, "output": 40000},
#     "foundation":  {"overhead": 50000, "output": 40000},
#     "database":    {"overhead": 50000, "output": 40000},
#     "backend":     {"overhead": 50000, "output": 40000},
#     "api":         {"overhead": 50000, "output": 40000},
#     "frontend":    {"overhead": 50000, "output": 40000},
#     "integration": {"overhead": 50000, "output": 40000},
#     "testing":     {"overhead": 50000, "output": 40000}
#   },
#   "REVIEW":  {"default": {"overhead": 30000, "output": 25000}},
#   "FIX":     {"default": {"overhead": 40000, "output": 30000}},
#   "CLEANUP": {"default": {"overhead": 40000, "output": 30000}}
# }
#
# Note: prompts pass file paths, not content. Agent reads instruction files via Read tool
# (~300-500 tokens each). These costs are absorbed into overhead_actual and calibrated over time.
```

## Functions

```python
def estimate_call(prompt: str, mode: str, task_type: str = "default") -> tuple[int, int]:
    """Estimate total token consumption for one subprocess call.
    Returns (estimated_tokens, base_prompt_tokens).
    base_prompt_tokens is passed directly to log_usage() — no re-derivation needed.
    task_type defaults to "default" — non-EXECUTE callers (REVIEW, FIX, CLEANUP, TASK_BUILD)
    omit it; _cal_entry() always uses "default" for those modes anyway."""
    base_prompt_tokens = int(len(prompt) / CHARS_PER_TOKEN)
    overhead = load_calibrated_overhead(mode, task_type)
    output = load_calibrated_output(mode, task_type)
    return int(base_prompt_tokens + overhead + output), base_prompt_tokens

def plan_batches(tasks: list, base_prompt_tokens: int, config: dict) -> list[list]:
    """Group EXECUTE tasks into subprocess batches within config["max_batch_tokens"].
    Minimum 1 task per batch. Each task's cost is looked up by its task_type from calibration.json.
    Returns list of batches; each batch is a list of task dicts {id, title, task_type, description}.
    Harness passes each batch to execute() — single task (len==1) or multi-task (len>1).

    Batching is only enabled once every task_type in `tasks` has >= config["min_entries_before_batching"]
    usage.jsonl entries (EXECUTE mode). If any task_type is under-calibrated, all tasks are
    returned as single-element batches — safe default that avoids partial-commit scenarios."""
    if not _calibration_mature(tasks, config):
        return [[t] for t in tasks]   # one task per subprocess until estimates are reliable
    max_batch_tokens = config["max_batch_tokens"]
    batches = []
    i = 0
    while i < len(tasks):
        # Always include at least 1 task — minimum batch size regardless of token estimate
        batch = [tasks[i]]
        remaining = max_batch_tokens - base_prompt_tokens - _task_cost(tasks[i])
        i += 1
        # Pack additional tasks while budget allows, using each task's own type cost
        while i < len(tasks):
            cost = _task_cost(tasks[i])
            if remaining >= cost:
                batch.append(tasks[i])
                remaining -= cost
                i += 1
            else:
                break
        batches.append(batch)
    return batches

def _calibration_mature(tasks: list, config: dict) -> bool:
    """Return True if every task_type in tasks has >= config["min_entries_before_batching"] EXECUTE
    entries in usage.jsonl. A single under-calibrated task_type blocks batching for the whole list."""
    threshold = config["min_entries_before_batching"]
    usage = read_usage_jsonl()
    for task in tasks:
        count = sum(1 for e in usage
                    if e["mode"] == "EXECUTE" and e["task_type"] == task["task_type"])
        if count < threshold:
            return False
    return True

def _task_cost(task: dict) -> int:
    """Estimated token cost for one EXECUTE task, by task_type."""
    entry = _refresh_calibration("EXECUTE", task["task_type"])
    return entry["overhead"] + entry["output"]

_usage_cache: list | None = None   # module-level; None = not yet loaded

def read_usage_jsonl() -> list:
    """Return all entries from workspace/usage.jsonl.
    Loaded once on first call; subsequent calls return the cached list.
    Invalidated (reset to None) by log_usage() after each append."""
    global _usage_cache
    if _usage_cache is None:
        path = Path("workspace/usage.jsonl")
        _usage_cache = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] \
                       if path.exists() else []
    return _usage_cache

def get_session_token_total() -> int:
    """Sum actual_input_tokens + actual_output_tokens for usage.jsonl entries in the last 5 hours.
    Scoped to 5-hour window so the count resets naturally with the Claude Pro usage window.
    Returns 0 if usage.jsonl is empty or has no recent entries."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(hours=5)
    return sum(
        e.get("actual_input_tokens", 0) + e.get("actual_output_tokens", 0)
        for e in read_usage_jsonl()
        if datetime.fromisoformat(e["ts"]).replace(tzinfo=timezone.utc) >= cutoff
    )

def load_config() -> dict:
    """Read harness/config.json. Returns the full config dict.
    Called once on startup by harness.py; the returned dict is passed through
    to agents.py, calibrate.py, and harness.py methods as needed."""

def validate_config(config: dict) -> None:
    """Validate user-tunable config. Evaluation iterations must stay within the
    hook schema cap (1..3), and evaluate_early_stop_on_full_score must be a boolean."""

def load_calibration() -> dict:
    """Read harness/calibration.json. Returns the full calibration dict."""

def save_calibration(cal: dict) -> None:
    """Write updated calibration dict back to harness/calibration.json."""

def _cal_entry(cal: dict, mode: str, task_type: str) -> dict:
    """Return the {overhead, output} entry for (mode, task_type).
    EXECUTE looks up by task_type, falls back to 'default'.
    All other modes always use 'default'."""
    bucket = cal.get(mode, {})
    if mode == "EXECUTE":
        return bucket.get(task_type) or bucket.get("default", {"overhead": 50000, "output": 40000})
    return bucket.get("default", {"overhead": 30000, "output": 25000})

def _refresh_calibration(mode: str, task_type: str) -> dict:
    """Recompute p90 overhead and output for (mode, task_type) in one pass.
    Loads calibration.json once, updates both fields if ≥5 history entries exist,
    writes back once, and returns the {overhead, output} entry.
    Callers (load_calibrated_overhead, load_calibrated_output, _task_cost) all call
    this so calibration.json is never written more than once per (mode, task_type)
    lookup regardless of how many callers are chained."""
    cal = load_calibration()
    entry = _cal_entry(cal, mode, task_type)
    history = [
        e for e in read_usage_jsonl()
        if e["mode"] == mode and e["task_type"] == task_type
    ]
    if len(history) < 5:
        return entry                               # seed values — no write
    overheads = sorted(e["overhead_actual"]        for e in history)
    outputs   = sorted(e["actual_output_tokens"]   for e in history)
    def p90(values: list) -> int:
        idx = math.ceil(len(values) * 0.9) - 1    # nearest-rank p90 (0-indexed)
        return int(values[idx] * P90_MARGIN)       # p90 + safety margin from module constant
    entry["overhead"] = p90(overheads)
    entry["output"]   = p90(outputs)
    save_calibration(cal)                          # single write for both fields
    return entry

def load_calibrated_overhead(mode: str, task_type: str) -> int:
    """Return current overhead estimate for (mode, task_type). See _refresh_calibration."""
    return _refresh_calibration(mode, task_type)["overhead"]

def load_calibrated_output(mode: str, task_type: str) -> int:
    """Return current output estimate for (mode, task_type). See _refresh_calibration."""
    return _refresh_calibration(mode, task_type)["output"]

def sync_task_types(state: dict, new_tasks: list, profile: dict) -> dict:
    """Add any new task_type from TASK_BUILD signal into state['task_types'] and calibration.json.
    New task_types inherit EXECUTE 'default' values in calibration.json until enough data exists."""
    known = set(state.setdefault("task_types", list(profile["task_types"])))
    cal = load_calibration()
    execute_bucket = cal.setdefault("EXECUTE", {})
    default = execute_bucket.get("default", {"overhead": 50000, "output": 40000})
    changed = False
    for task in new_tasks:
        task_type = task.get("task_type", "").strip().lower()
        if task_type and task_type not in known:
            known.add(task_type)
            state["task_types"].append(task_type)
            print(f"[HARNESS] New task_type discovered: '{task_type}' — added to state.json")
        if task_type and task_type not in execute_bucket:
            execute_bucket[task_type] = dict(default)   # inherit defaults
            changed = True
    if changed:
        save_calibration(cal)
    return state

def log_usage(state: dict, task_id: str, phase_id: int,
              mode: str, base_prompt_tokens: int, estimated_tokens: int, usage: dict, files_changed: int,
              task_type: str = "default"):
    """Append one usage entry to workspace/usage.jsonl.
    Called once per subprocess call — for every mode, not just EXECUTE.
    For all modes except EXECUTE, called once per subprocess with full unmodified usage.

    task_id sentinels for non-EXECUTE modes:
        TASK_BUILD → f"phase_{phase_id}_build"
        REVIEW     → f"phase_{phase_id}_review"
        FIX        → f"phase_{phase_id}_fix"
        CLEANUP    → "cleanup"  (phase_id=0 — not tied to a specific phase)

    files_changed semantics per mode:
        TASK_BUILD → 0   (no files created)
        REVIEW     → 0   (no source files changed by reviewer)
        FIX        → sum(len(fix["files_changed"]) for fix in signal["fixes"])
        CLEANUP    → same as FIX
        EXECUTE    → len(task["files_changed"]) per task

    For batch EXECUTE calls only — harness splits the subprocess usage with two separate weights
    before calling — input and output are calibrated independently so must be split independently:
        execute_weight  = task_estimated_overhead / sum(estimated_overhead for all tasks in batch)
        output_weight   = task_estimated_output   / sum(estimated_output   for all tasks in batch)
        actual_input_tokens  = round(raw["input_tokens"]  * execute_weight)
        actual_output_tokens = round(raw["output_tokens"] * output_weight)
        cache_*_tokens       = round(raw["cache_*"]       * execute_weight)
    This keeps overhead_actual and actual_output_tokens accurate per task_type for calibration."""
    known = state.get("task_types", [])
    if task_type not in known:
        print(f"[WARN] task_type '{task_type}' not in known list — logging as-is")
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "phase_id": phase_id,
        "task_id": task_id,
        "mode": mode,
        "task_type": task_type,
        "files_changed": files_changed,
        "estimated_input_tokens": estimated_tokens,
        "actual_input_tokens": usage["input_tokens"],
        "actual_output_tokens": usage["output_tokens"],
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "overhead_actual": usage["input_tokens"] - base_prompt_tokens,
        "estimation_error": usage["input_tokens"] - estimated_tokens
    }
    append_jsonl("workspace/usage.jsonl", entry)
    global _usage_cache
    _usage_cache = None    # invalidate so next read_usage_jsonl() reloads from disk
```

---

# harness/lang.py — Language Profiles

```python
# LanguageProfile keys:
#   name                — language identifier (matches --language flag value)
#   compile_cmd         — syntax check command; {file} replaced per file by verify_execution()
#   compile_extensions  — file glob patterns to filter before compile loop (e.g. ["*.py"]);
#                         verify_execution() skips files that don't match any pattern
#   test_cmd            — test runner command used by verify_execution() and verify_fix()
#   build_model         — Claude model used for TASK_BUILD (cheap classification task)
#   execute_model       — Claude model used for EXECUTE, FIX, REVIEW, CLEANUP
#   builder_agent       — path to builder agent instruction file
#   reviewer_agent      — path to reviewer agent instruction file
#   common_rules        — path to language-agnostic coding standards file
#   rules_file          — path to language-specific rules file
#   builder_skill       — path to builder workflow skill file
#   reviewer_skill      — path to reviewer workflow skill file
#   task_types          — seed task type list for this language; loaded into state.json on first run
#
# build_file_lists() is fully profile-driven — no hardcoded paths.
# Adding a new language requires one new profile entry only; no code changes elsewhere.

LANGUAGE_PROFILES = {
    "python": {
        "name":               "python",
        "compile_cmd":        ["python", "-m", "py_compile", "{file}"],
        "compile_extensions": ["*.py"],
        "test_cmd":           ["pytest"],
        "build_model":        "claude-haiku-4-5-20251001",  # cheap classification — no quality loss
        "execute_model":      "claude-sonnet-4-6",          # EXECUTE, FIX, REVIEW, CLEANUP
        "builder_agent":  ".claude/agents/code-builder.md",
        "reviewer_agent": ".claude/agents/code-reviewer.md",
        "common_rules":   ".claude/rules/common/coding-standards.md",
        "rules_file":     ".claude/rules/python/python-standards.md",
        "builder_skill":  ".claude/skills/python-development-workflow.md",
        "reviewer_skill": ".claude/skills/python-code-review-workflow.md",
        "task_types":  [
            "foundation", "database", "backend",
            "api", "frontend", "integration", "testing"
        ],
    }
    # V2: add "java" profile here — no changes to harness.py, agents.py, or calibrate.py
}

def get_profile(language: str) -> dict:
    """Return the LanguageProfile for the given language. Raise ValueError if unknown."""
    profile = LANGUAGE_PROFILES.get(language.lower())
    if not profile:
        raise ValueError(f"Unknown language '{language}'. Available: {list(LANGUAGE_PROFILES)}")
    return profile
```
# Phase 11 Timeout Policy

`harness/config.json` keeps `subprocess_timeout` as the stable base timeout map. The additive `timeout_policy` section lets REVIEW scale by phase task count, changed file count, and diff line count with min/max bounds. Language profiles do not need to duplicate this policy unless a future language-specific override is introduced.

`evaluate_early_stop_on_full_score` defaults to `false`. When enabled, EVALUATE can stop after two consecutive `APPROVE` iterations with full `score.total == score.max`; the default preserves the configured `max_evaluate_iterations` behavior.
