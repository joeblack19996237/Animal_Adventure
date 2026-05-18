# Overview

## Context

Build a standalone, reusable project template called `autonomous-dev-harness`. It orchestrates two Claude Code agents — a `code-builder` and a `code-reviewer` — in a closed loop to develop an application from a spec file with no human involvement. Users clone the template into their project, provide a spec, and run `python harness/harness.py spec.md`.

V1 targets Python projects. The harness is invoked via CLI from within an active Claude Code session — the user opens Claude Code in the project directory first (establishing OAuth auth for Claude Pro), then runs `python harness/harness.py spec.md` from the terminal. Each agent call uses `claude -p` as a subprocess inheriting that auth context. It is small, stable, and self-contained.

Language-specific behaviour (compile command, test command, rules file, task type seeds) is defined in `harness/lang.py` as a `LanguageProfile`. V1 ships with a Python profile only. Adding a new language in V2 requires one new profile entry in `lang.py` and one new rules file — no changes to the state machine, agents, or calibration logic.

---

## Technical Approach (Plain Language)

1. **harness.py** drives a state machine. It reads a spec file, extracts phases, and loops through build → review → fix cycles by calling `claude -p` as a subprocess. **state.py** handles all state.json I/O (load, save, update, halt, error) — harness.py imports it; no logic flows the other way.
2. **Each `claude -p` call handles one unit of work** (one task, or one issue fix). V1: always one EXECUTE task per subprocess. V1.1: `plan_batches()` may group multiple low-overhead tasks into one subprocess once each task_type has ≥`MIN_ENTRIES_BEFORE_BATCHING` (5) real usage entries — below that threshold all tasks run solo to avoid partial-commit scenarios from unreliable seed estimates.
3. **Agent instruction files are passed by path, not by content** — prompts reference `agents/code-builder.md`, `rules/common/coding-standards.md`, and the language-specific rules file (from `LanguageProfile`) by file path. The agent reads them via its `Read` tool at the start of each subprocess. This avoids command-line length limits (Windows 32KB cap) and keeps prompts short. Prompt caching via content injection is deferred to V1.1 once usage.jsonl data shows the token cost difference justifies the complexity.
4. **state.json is the single source of truth** — records task and issue status with enough detail to resume interrupted runs. Harness reads it on startup, updates task/issue status in memory, writes back.
5. **Hooks run inside the Claude session** (when the agent uses Write/Edit/Bash tools) to verify file changes and block dangerous commands.
6. **No mid-session handoff.** Each `claude -p` subprocess ends after its task. `state.json` and `review_report.md` carry all state between subprocesses. In TASK_BUILD mode, the agent emits a JSON signal as its final stdout response — harness captures it, parses the task list, and writes each task (with `task_type`) into `state.json`. No intermediate file is used.

---

## Complexity: Ambitious

Estimated: 500–700 lines of Python (harness.py + state.py + agents.py + calibrate.py), 6–8 agent/rule/skill Markdown files, 3 Python hook scripts, 1 settings.json.

---

## Project Structure

```
autonomous-dev-harness/
├── CLAUDE.md                          # Resolver index — loaded first by all agents
├── .claude/
│   ├── settings.json                  # Hook registrations and permissions
│   ├── agents/
│   │   ├── code-builder.md            # NEW: reads spec phases, creates tasks, writes code
│   │   └── code-reviewer.md           # ADAPTED from ECC agents/code-reviewer.md
│   ├── rules/
│   │   ├── common/
│   │   │   └── coding-standards.md    # Universal: naming, error handling, no debug logs
│   │   └── python/
│   │       └── python-standards.md    # PEP8, type hints, pytest, no bare except
│   ├── skills/
│   │   ├── python-development-workflow.md    # Loaded by code-builder agent for context
│   │   └── python-code-review-workflow.md    # Loaded by code-reviewer agent for context
│   └── hooks/
│       ├── hook_utils.py              # Shared: read_signal_text() — extracts agent's final text from transcript
│       ├── post_write_verify.py       # Verify file exists after Write tool
│       ├── post_edit_verify.py        # Verify file changed after Edit tool
│       ├── pre_bash_security.py       # Block dangerous commands + injection patterns
│       ├── stop_validate_json.py      # Stop hook: validate agent output is JSON before subprocess exits
│       └── stop_git_commit.py         # Stop hook: stage files_changed from signal and commit (runs after stop_validate_json.py)
├── docs/
│   └── spec-template.md               # Example spec showing required phase format; users drop their spec.md here
├── workspace/                         # Runtime artifacts — created at run time; not shipped with the template
│   ├── review_report.md               # Active CRITICAL/HIGH issues for current phase only
│   ├── tech_debt.jsonl                # Accumulated MEDIUM/LOW issues across all phases (one JSON object per line)
│   ├── state.json                     # Auto-managed by harness.py
│   └── usage.jsonl                    # Per-call token usage log — cost accounting + calibration input
├── harness/
│   ├── harness.py                     # State machine + main loop + orchestration (~150 lines)
│   ├── state.py                       # State I/O — load/save/update state.json, halt, error (~100 lines)
│   ├── agents.py                      # All claude -p calls, prompt builders, output parsers (~250 lines)
│   ├── calibrate.py                   # Pre-call estimation + batch planning + post-run calibration (~100 lines)
│   ├── config.json                    # User-tunable params: timeouts, batch limits, retry thresholds, token budget
│   ├── calibration.json               # Auto-updated: seed + calibrated overhead/output per (mode, task_type)
│   ├── lang.py                        # LanguageProfile definitions — compile/test commands, models, rules path, task type seeds
│   └── requirements.txt               # Harness Python dependencies (e.g. jsonschema); install with pip install -r harness/requirements.txt
├── .gitignore                         # Excludes workspace/ from git — prevents state files from being committed
└── README.md
```

---

## Build Location

The harness directory IS the project root. Generated source code, tests, and the spec files all live in the same directory. Users:
1. Clone the template
2. Drop their spec file(s) into `docs/`
3. Run `python harness/harness.py docs/spec.md` (or `docs/spec/` for multi-file)
4. The agents build code directly in the project root

---

## What You'll Need

- `claude` CLI installed and on PATH (Claude Pro subscription — no API key required)
- Python 3.10+
- Harness dependencies: `pip install -r harness/requirements.txt` (includes `jsonschema` for Stop hook validation)
- Claude Code opened in the project directory (sets up auth context for `claude -p`)
- A spec.md (or spec directory) following the phase format in `docs/spec-template.md`
