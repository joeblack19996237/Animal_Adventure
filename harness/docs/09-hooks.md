# Hooks, Settings, and Git Workflow

## .claude/hooks/hook_utils.py — Shared Transcript Parser

Both Stop hooks import this utility to extract the agent's final text from the transcript.
Centralising here means a single fix point if the transcript structure ever changes.

```python
import json, re

def read_signal_text(data: dict) -> str | None:
    """Extract the agent's final text content from the Stop hook stdin payload.
    Returns the raw text string, or None if no text block is found.
    Handles both plain-string content and typed content-block lists."""
    transcript = json.loads(open(data["transcript_path"], encoding="utf-8").read())
    assistant_msgs = [m for m in transcript["messages"] if m["role"] == "assistant"]
    if not assistant_msgs:
        return None
    content = assistant_msgs[-1]["content"]
    if isinstance(content, str):
        return content
    # content is a list of typed blocks — find the last text block
    text_blocks = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return text_blocks[-1] if text_blocks else None
```

---

## .claude/hooks/post_write_verify.py (PostToolUse after Write)

- Read JSON from stdin: `{"tool_input": {"file_path": "..."}, ...}`
- Check `Path(file_path).exists()` (uses `pathlib.Path`)
- If missing: exit code 2 (block) with message
- If ok: exit 0

## .claude/hooks/post_edit_verify.py (PostToolUse after Edit)

- Read stdin, extract `tool_input.file_path` and `tool_input.new_string`
- **Skip Python files** (`file_path.endswith(".py")`) — ruff may reformat content after the edit, making an exact `new_string` match a false positive; `post_py_lint_format.py` handles `.py` files instead
- Read the file and check `new_string` is present in content
- If missing: print warning to **stdout** (not stderr) — Claude Code surfaces stdout back to the agent as tool feedback, so the agent sees it and can retry the edit within the same subprocess
- Exit 0 always — warning only, never blocks

## .claude/hooks/post_py_lint_format.py (PostToolUse after Write and Edit)

Runs automatically on every `.py` file write or edit. Non-Python files are skipped immediately.

```python
import json, subprocess, sys

data = json.loads(sys.stdin.read())
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path.endswith(".py"):
    sys.exit(0)

# Auto-fix formatting and safe lint issues silently
subprocess.run(["ruff", "format", file_path], capture_output=True)
subprocess.run(["ruff", "check", "--fix", file_path], capture_output=True)

# Report any remaining violations the agent must fix manually
result = subprocess.run(["ruff", "check", file_path], capture_output=True, text=True)
if result.returncode != 0 and result.stdout.strip():
    print(f"[RUFF] Lint violations in {file_path!r} — fix before completing the task:\n{result.stdout.strip()}")

sys.exit(0)
```

- `ruff format` — auto-fixes formatting silently (no agent action required)
- `ruff check --fix` — auto-fixes safe lint violations silently
- `ruff check` — reports any remaining violations that require manual fixes; written to stdout so Claude Code surfaces them as tool feedback
- Exit 0 always — violations are feedback, not a block; the agent self-corrects in the same subprocess

## .claude/hooks/stop_validate_json.py (Stop — fires when agent is about to end its turn)

JSON signal contract enforcement within the subprocess. The Stop hook fires before `claude -p` exits, giving the agent one chance to self-correct if its output is not valid JSON.

```python
import json, sys, re
import jsonschema
import hook_utils

SIGNAL_SCHEMAS = {
    "TASK_BUILD": {
        "type": "object",
        "required": ["status", "mode", "phase_id", "tasks"],
        "properties": {
            "status":   {"type": "string", "const": "complete"},
            "mode":     {"type": "string", "const": "TASK_BUILD"},
            "phase_id": {"type": "integer"},
            "tasks": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "title", "task_type"],
                    "properties": {
                        "id":        {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "title":     {"type": "string"},
                        "task_type": {"type": "string"}
                    }
                }
            }
        }
    },
    "EXECUTE": {
        # No wrapper status — outcome is derived by harness from tasks[].status values.
        # tasks[].status drives all retry/halt logic; a redundant wrapper risks inconsistency.
        "type": "object",
        "required": ["mode", "phase_id", "tasks"],
        "properties": {
            "mode":     {"type": "string", "const": "EXECUTE"},
            "phase_id": {"type": "integer"},
            "tasks": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "title", "task_type", "status", "files_changed"],
                    "properties": {
                        "id":            {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "title":         {"type": "string"},
                        "task_type":     {"type": "string"},
                        "status":        {"type": "string", "enum": ["complete", "failed"]},
                        "tdd_applied":   {"type": ["boolean", "null"]},
                        "tdd_skipped":   {"type": ["string", "null"]},
                        "files_changed": {"type": "array", "items": {"type": "string"}},
                        "reason":        {"type": "string"}
                    }
                }
            }
        }
    },
    "FIX": {
        # No wrapper status — outcome is derived by harness from fixes[].status values.
        # fixes[].status=="open" drives retry; fixes[].status=="fixed" drives state updates.
        # minItems:1 ensures the agent always reports per-issue results.
        "type": "object",
        "required": ["mode", "fixes"],
        "properties": {
            "mode":   {"type": "string", "const": "FIX"},
            "fixes": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "severity", "title", "status", "files_changed"],
                    "properties": {
                        "id":            {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "severity":      {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                        "title":         {"type": "string"},
                        "status":        {"type": "string", "enum": ["fixed", "open", "deferred"]},
                        "files_changed": {"type": "array", "items": {"type": "string"}},
                        "reason":        {"type": "string"}
                    }
                }
            }
        }
    },
    "REVIEW": {
        "type": "object",
        "required": ["status", "mode", "phase_id", "verdict", "sha_at_review", "issues"],
        "properties": {
            "status":        {"type": "string", "const": "complete"},
            "mode":          {"type": "string", "const": "REVIEW"},
            "phase_id":      {"type": "integer"},
            "verdict":       {"type": "string", "enum": ["APPROVE", "WARN", "BLOCK"]},
            "sha_at_review": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "severity", "dimension", "file", "title"],
                    "properties": {
                        "id":        {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "severity":  {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                        "dimension": {"type": "string"},
                        "file":      {"type": "string"},
                        "title":     {"type": "string"}
                    }
                }
            }
        }
    },
    "EVALUATE": {
        "type": "object",
        "required": ["status", "mode", "iteration", "phase_id", "verdict", "issues"],
        "properties": {
            "status":   {"type": "string", "enum": ["complete"]},
            "mode":     {"type": "string", "enum": ["EVALUATE"]},
            "iteration": {"type": "integer", "minimum": 1, "maximum": 3},
            "phase_id": {"type": "integer"},
            "verdict":  {"type": "string", "enum": ["APPROVE", "BLOCK"]},
            "score": {
                "type": "object",
                "required": ["total", "max"],
                "properties": {
                    "total": {"type": "number"},
                    "max":   {"type": "number"}
                }
            },
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "severity", "dimension", "title", "description", "suggestion"],
                    "properties": {
                        "id":          {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "severity":    {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                        "dimension":   {"type": "string"},
                        "file":        {"type": "string"},
                        "title":       {"type": "string"},
                        "description": {"type": "string"},
                        "suggestion":  {"type": "string"},
                        "log_info":    {"type": "string"},
                        "refs":        {"type": "string"}
                    }
                }
            }
        }
    }
}

data = json.loads(sys.stdin.read())

# stop_hook_active=True means this is already a retry turn — exit unconditionally
# to avoid an infinite loop. The harness fallback (extract_signal) handles it.
if data.get("stop_hook_active"):
    sys.exit(0)

text = hook_utils.read_signal_text(data)
if text is None:
    sys.exit(0)  # no text block in final message — nothing to validate

stripped = re.sub(r'^```json\s*|^```\s*|```$', '', text.strip(), flags=re.MULTILINE).strip()
try:
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Expected object", stripped, 0)
except json.JSONDecodeError as e:
    print(
        f"[SIGNAL ERROR] Your response is not valid JSON: {e}. "
        f"Respond with ONLY a valid JSON object matching the required schema. "
        f"No prose, no markdown fences. Raw output was: {text[:300]!r}"
    )
    sys.exit(1)

mode = parsed.get("mode")
schema = SIGNAL_SCHEMAS.get(mode)
if schema is None:
    print(
        f"[SIGNAL ERROR] Missing or unknown 'mode' field: {mode!r}. "
        f"Must be one of: {list(SIGNAL_SCHEMAS)}."
    )
    sys.exit(1)

try:
    jsonschema.validate(parsed, schema)
except jsonschema.ValidationError as e:
    print(
        f"[SIGNAL ERROR] Schema validation failed at '{e.json_path}': {e.message}. "
        f"Fix your JSON and respond with ONLY the corrected signal object."
    )
    sys.exit(1)

sys.exit(0)
```

- Exit 0 → subprocess completes, harness receives the valid signal
- Exit 1 + stdout message → Claude Code injects the message into agent context; agent self-corrects within the same subprocess
- `stop_hook_active` guard prevents infinite retry loop; if it triggers, `extract_signal()` in `call_claude()` handles the residue
- `jsonschema` must be listed in harness dependencies (`pip install jsonschema`)

## .claude/hooks/stop_git_commit.py (Stop — fires after stop_validate_json.py)

Reads `files_changed` from the agent's signal and commits exactly those files. Agent never runs git.

```python
import json, sys, re, subprocess
import hook_utils

data = json.loads(sys.stdin.read())
# No stop_hook_active guard here — unlike stop_validate_json.py, this hook always
# exits 0 and never injects a correction message, so it cannot cause an infinite loop.
# On a correction turn (stop_hook_active=True), the agent's second response contains
# the valid corrected signal — we should commit it rather than skip and force a
# retry through run_batch_retry_loop() after verify_execution() reports pre_sha==HEAD.

text = hook_utils.read_signal_text(data)
if text is None:
    sys.exit(0)  # no text block — nothing to commit
stripped = re.sub(r'^```json\s*|^```\s*|```$', '', text.strip(), flags=re.MULTILINE).strip()

try:
    signal = json.loads(stripped)
except json.JSONDecodeError:
    sys.exit(0)  # stop_validate_json.py handles invalid JSON — don't duplicate

# All signals are wrapper objects — EXECUTE uses tasks[], FIX uses fixes[]
mode = signal.get("mode", "")

if mode in ("TASK_BUILD", "REVIEW"):
    sys.exit(0)  # no code changes to commit for these modes

# Collect files_changed and build commit message
if mode == "EXECUTE":
    completed = [t for t in signal.get("tasks", []) if t.get("status") == "complete"]
    files = [f for task in completed for f in task.get("files_changed", [])]
    # Use task title for single-task calls; generic label for batches
    if len(completed) == 1:
        msg = f"feat(phase-{signal.get('phase_id', '?')}): {completed[0]['title']}"
    else:
        msg = f"feat(phase-{signal.get('phase_id', '?')}): implement {len(completed)} tasks"
elif mode in ("FIX", "CLEANUP"):
    files = [f for fix in signal.get("fixes", []) if fix.get("status") == "fixed"
             for f in fix.get("files_changed", [])]
    # phase_id derived from first fix id — format is "{phase_id}.{seq}" e.g. "2.1" → phase 2
    fixes = signal.get("fixes", [])
    phase_id = fixes[0]["id"].split(".")[0] if fixes else "?"
    msg = f"fix(phase-{phase_id}): fix CRITICAL/HIGH issues"
else:
    sys.exit(0)

if not files:
    sys.exit(0)

subprocess.run(["git", "add"] + files, check=True)
result = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
if result.returncode != 0 and "nothing to commit" not in result.stdout:
    print(f"[WARN] git commit failed: {result.stderr}", file=sys.stderr)
sys.exit(0)
```

## .claude/hooks/pre_bash_security.py (PreToolUse before Bash)

- Read `tool_input.command` from stdin JSON
- Block patterns (exit code 2):
  - `rm -rf /` or `rm -rf *`
  - `DROP TABLE`, `DROP DATABASE`
  - `curl | bash`, `wget | sh`
  - `git push --force` to main/master
  - `python -c "..."` or `python -c '...'` — inline code execution as prompt injection vector
  - Prompt injection: `IGNORE PREVIOUS INSTRUCTIONS`
- Exit 0 for safe commands

## .claude/settings.json

```json
{
  "permissions": {
    "allow": [
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Glob(*)",
      "Grep(*)",
      "Bash(git *)",
      "Bash(pytest*)",
      "Bash(python -m py_compile*)",
      "Bash(python -m pytest*)",
      "Bash(ruff*)"
    ],
    "deny": [
      "Bash(rm -rf*)",
      "Bash(git push*)",
      "Bash(curl*)",
      "Bash(wget*)"
    ]
  },
  "hooks": {
    "Stop": [
      {
        "hooks": [{"type": "command", "command": "python .claude/hooks/stop_validate_json.py"}],
        "description": "Validate agent output is valid JSON before subprocess exits",
        "id": "stop:validate-json"
      },
      {
        "hooks": [{"type": "command", "command": "python .claude/hooks/stop_git_commit.py"}],
        "description": "Stage files_changed from signal and commit — runs after JSON validation",
        "id": "stop:git-commit"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [{"type": "command", "command": "python .claude/hooks/post_write_verify.py"}],
        "description": "Verify file exists after Write",
        "id": "post:write:verify-exists"
      },
      {
        "matcher": "Write",
        "hooks": [{"type": "command", "command": "python .claude/hooks/post_py_lint_format.py"}],
        "description": "Run ruff format + lint on Python files after Write",
        "id": "post:write:py-lint-format"
      },
      {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": "python .claude/hooks/post_edit_verify.py"}],
        "description": "Verify edit applied for non-Python files after Edit",
        "id": "post:edit:verify-changed"
      },
      {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": "python .claude/hooks/post_py_lint_format.py"}],
        "description": "Run ruff format + lint on Python files after Edit",
        "id": "post:edit:py-lint-format"
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "python .claude/hooks/pre_bash_security.py"}],
        "description": "Block dangerous commands and prompt injection",
        "id": "pre:bash:security"
      }
    ]
  }
}
```

**Note on deny/allow layering:** `deny` and `allow` are enforced by Claude Code at the permission level — before any hook fires. The `deny` list entries (`rm -rf*`, `git push*`, `curl*`, `wget*`) are redundant against the `allow` list (only explicitly allowed patterns pass), but are kept as a second line of defence and to make the intent explicit. The `pre_bash_security.py` hook is a third independent layer that runs after permission checks — it adds pattern-based logging and blocks injection attempts that the allowlist cannot express (e.g. `IGNORE PREVIOUS INSTRUCTIONS`).

Mode-specific settings files (`settings.builder.json`, `settings.reviewer.json`, and `settings.evaluator.json`) include their own explicit `permissions` block. The harness does not rely on Claude Code merging `.claude/settings.json` into a mode override.

## Hook Feedback Routing

- `stop_validate_json.py` writes to **stdout** + exits 1 → Claude Code injects stdout as feedback into agent context → agent reformats JSON within the same subprocess. On retry, `stop_hook_active=True` → hook exits 0 unconditionally → `extract_signal()` in `call_claude()` handles any residue
- `stop_git_commit.py` runs after `stop_validate_json.py` (registration order) — reads `files_changed` from the valid signal, stages only those files, commits. Skips for TASK_BUILD and REVIEW modes. Always exits 0 — git errors logged to stderr only, never block the subprocess.
- **Stop hooks do NOT fire on `subprocess.TimeoutExpired`** — both Stop hooks only run on normal subprocess exit. When `claude -p` is killed by the harness timeout, no hooks run. Files the agent wrote to disk are on disk but uncommitted. Partial recovery is handled entirely by `call_claude()` in `agents.py` — see `docs/06-agents-py.md`.
  **stop_hook_active behaviour:** if `stop_validate_json.py` corrected the agent's signal (agent needed a retry turn), both hooks fire again with `stop_hook_active=True`. `stop_validate_json.py` exits 0 unconditionally (guard prevents infinite loop). `stop_git_commit.py` has no such guard — it parses the agent's corrected signal and commits normally. If no commit is created, `verify_execution()` reports the task as failed and the retry is owned by `run_batch_retry_loop()`.
- `post_py_lint_format.py` fires after every Write and Edit on `.py` files — auto-fixes formatting and safe lint violations silently, then writes any remaining violations to **stdout** as tool feedback → agent self-corrects in the same subprocess. `post_edit_verify.py` skips `.py` files entirely to avoid false positives from ruff reformatting.

## Phase 11 Commit Gate

Commit staging is intentionally narrow. `stop_git_commit.py` stages only signal-listed safe paths, and the harness fallback commit uses a pre/post git snapshot gate so preexisting dirty files and unrelated untracked files are never swept into a task commit. There is no broad foundation-task auto-stage fallback.
- `post_edit_verify.py` writes warnings to **stdout** → Claude Code injects stdout back into the agent's context as tool feedback → agent can self-correct within the same subprocess (non-Python files only)
- `call_claude()` captures subprocess stderr and prints any `[WARN]` lines to console — diagnostic only, not written to state.json
- `verify_execution()` / `verify_fix()` are the hard verification gates regardless of hook warnings

## Git Workflow Integration

Commits are handled by the `stop_git_commit.py` Stop hook — the agent never runs git commands directly.

The hook fires after `stop_validate_json.py` confirms the signal is valid JSON. It reads the agent's signal from the transcript and:
- Extracts `files_changed` from EXECUTE signals, or all `files_changed` from completed entries in FIX `fixes[]`
- Runs `git add <files_changed>` — stages only the specific files reported in the signal, no unintended files
- Commits with the appropriate message derived from the signal mode and content
- Skips commit entirely for TASK_BUILD and REVIEW mode signals (no code changes to commit)

This eliminates `git add -A` risk and guarantees every completed task and fix is committed before the subprocess exits.

### `base_sha` Derivation for Review Scoping

`review_phase()` receives a `base_sha` parameter — the SHA from which the reviewer's diff starts. Harness derives it as follows:
- Phase 1: `state["initial_sha"]` — captured at INIT before any building starts
- Phase N+1: `state["phases"][N-1]["review"]["sha_at_review"]` — the SHA recorded when the previous phase's review completed

`state.json` stores the SHA at the time of each review completion as `sha_at_review` in the phase's `review` object.

When `review_phase()` is called:
1. Harness derives `base_sha` from state.json using the rules above
2. Harness passes `base_sha` to `review_phase()` in `agents.py`
3. Review prompt instructs the agent: `"Run git diff {base_sha}..HEAD to see exactly what changed since the last review. Review only those files."`

`state.json` update after review completes:
```json
"review": {
  "status": "complete",
  "verdict": "BLOCK",
  "sha_at_review": "abc1234",
  "issues": [
    {"id": "1.1", "severity": "CRITICAL", "status": "open", "attempts": 0, "fixed_sha": null, "last_error": [], ...},
    {"id": "1.2", "severity": "HIGH",     "status": "open", "attempts": 0, "fixed_sha": null, "last_error": [], ...},
    {"id": "1.3", "severity": "MEDIUM",   "status": "open", "attempts": 0, "fixed_sha": null, "last_error": [], ...}
  ]
  // All issues written as "open" at review time regardless of severity.
  // handle_verdict() transitions MEDIUM/LOW to "deferred" after review:
  //   WARN verdict  → all issues set to "deferred" immediately by handle_verdict()
  //   BLOCK verdict → CRITICAL/HIGH enter fix cycle; MEDIUM/LOW set to "deferred"
  //                   by handle_verdict() → run_fix_cycle() Step 2 after all CRITICAL/HIGH fixed
}
```

### Startup Git Block

```python
result = subprocess.run(["git", "status"], capture_output=True)
if result.returncode != 0 and b"not a git repository" in result.stderr:
    subprocess.run(["git", "init"])
    # .gitignore ships with the template and excludes workspace/ — git add -A is safe here
    subprocess.run(["git", "add", "-A"])          # stage harness template files
    subprocess.run(["git", "commit", "-m", "chore: init harness"])

# Capture initial_sha before any building starts — used as base_sha for phase 1 review.
# Only written once: skipped on --resume if state["initial_sha"] is already set.
if not state.get("initial_sha"):
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    state["initial_sha"] = sha
    save_state(state)
```

## CLAUDE.md — Resolver Index

```markdown
# Autonomous Dev Harness — Agent Onboarding

## Agent Files
- .claude/agents/code-builder.md — Code builder agent instructions
- .claude/agents/code-reviewer.md — Code reviewer agent instructions

## Rules (always follow)
- .claude/rules/common/coding-guidelines.md
- .claude/rules/common/coding-standards.md
- .claude/rules/<language>/python-standards.md  ← resolved from LanguageProfile at runtime

## Skills
- .claude/skills/tdd-workflow/SKILL.md — Red→Green→Refactor with pytest patterns (used by code-builder)
- .claude/skills/verification-loop/SKILL.md — syntax→lint→test→secrets→diff gates (used by code-builder)
- .claude/skills/security-review/SKILL.md — Python security checklist (used by code-reviewer)

## Docs (runtime state)
- workspace/state.json — Current harness state (includes task_types registry)
- workspace/review_report.md — Open CRITICAL/HIGH issues for current phase (FIX mode source)
- workspace/tech_debt.jsonl — Accumulated MEDIUM/LOW issues across all phases (CLEANUP mode source)
- workspace/usage.jsonl — Per-call token usage log

## Git Rules
- code-builder: NEVER run git manually — the Stop hook reads `files_changed` from your signal and commits automatically. Include every created or modified file in `files_changed`.
- code-reviewer: use git diff {base_sha}..HEAD to scope review (base_sha injected by harness into prompt). Do not commit anything.

## Stop Hook Validation
Your final response is validated by a Stop hook before the subprocess exits. If your output is not valid JSON or fails schema validation, you will receive a correction prompt — respond with ONLY the corrected JSON signal. On a second failure the hook exits unconditionally and the harness retries the whole call.

See your agent `.md` file for the required JSON signal schema for each mode.
```
