# Animal Adventure Harness

Animal Adventure combines a local browser-game MVP specification with an autonomous Claude Code development harness. The repository contains:

- Product docs for the Animal Adventure L3 MVP in `docs/`.
- Static game assets in `assets/` and JSON gameplay configuration in `config/`.
- A Python harness in `harness/` that drives Claude Code build, review, fix, cleanup, and evaluation phases.
- Claude Code project agents, rules, skills, settings, and hooks in `.claude/`.

The harness tests exercise the automation system itself. They do not assert that a generated fixture app is a complete Animal Adventure implementation.

## Product Target

The L3 MVP is a locally deployable game served from a browser. The intended app stack is:

- Frontend: TypeScript, Phaser, Vite.
- Backend: Python, FastAPI, WebSocket.
- Persistence: SQLite with WAL.
- Static/proxy entrypoint: Nginx, default `http://localhost:8080/`.
- Configuration: JSON files under `config/`.

Core gameplay is documented in `docs/requirements.md`, `docs/architecture.md`, and `docs/workflows.md`: name-only login, backend-generated `player_id`, full-map touring, Spawn-area quests for Hopper/Copper/Elisa, inventory/shop/Potion flow, L3 progression, reconnect recovery, and persisted state.

## Repository Layout

```text
.
+-- .claude/                  # Claude Code agents, rules, skills, hooks, settings
+-- assets/                   # Committed image/audio assets
+-- config/                   # Gameplay and asset manifests
+-- docs/                     # Animal Adventure MVP specification
+-- harness/                  # Autonomous development harness
+-- workspace/                # Runtime state and logs, ignored by git
+-- CLAUDE.md                 # Project memory for Claude Code
+-- package.json              # Frontend tooling scripts/dependencies
+-- pytest.ini                # Harness test markers
+-- README.md
+-- requirements.txt          # Python dependencies for local development
```

## Prerequisites

- Python 3.10+.
- Node.js 18+ and npm.
- Claude Code CLI available as `claude` and authenticated in this project directory.
- Optional for full local deployment: Nginx and Playwright Chromium.

Install Python dependencies:

```bash
pip install -r requirements.txt
pip install -r harness/requirements.txt
```

Install Node dependencies:

```bash
npm install
```

## Running The Harness

Recommended run:

```bash
python harness/harness.py docs --app-type game --language python
```

With no arguments, the harness uses defaults from `harness/config.json`: spec path `docs`, app type `game`, and language `python`.

Resume an interrupted run:

```bash
python harness/harness.py --resume
```

Check current run status:

```bash
python harness/harness.py --status
```

Status includes recent `workspace/usage.jsonl` pressure signals and any active
external dependency wait. These usage totals are observability, not a fixed
Claude token budget; `claude_session_pacing` only adds soft delays between calls.
`tdd_mode="unit_test"` tasks are verified locally by the harness without a Claude
EXECUTE subprocess, while still using the same `verify_execution()` checks.

Clean up external evaluation services:

```bash
python harness/eval_services.py cleanup
```

## Runtime Artifacts

The harness writes runtime files under `workspace/`, which is ignored by git:

- `workspace/state.json`
- `workspace/events.jsonl`
- `workspace/harness.log`
- `workspace/run.lock`
- `workspace/harness.pid`
- `workspace/usage.jsonl`
- `workspace/review_report.md`
- `workspace/tech_debt.jsonl`

Status reporting distinguishes the current blocker/error from `historical_last_error`. Evaluation state may use `evaluate.status="blocked_external_dependency"`, `evaluate.status="timeout"`, or `evaluate.status="error"`. Evaluation scoring supports `evaluate_early_stop_on_full_score` and a `"score"` object with `"total"` and `"max"`.

When Claude returns a parseable 429 reset time, the harness cleans the failed
Claude process tree, quarantines new untracked artifacts, records cleanup status
in `workspace/external_dependency_context.json`, waits until reset, then retries
the same call once. Resume preflight requires that context to be clean.

By default, MEDIUM/LOW review findings are recorded in `workspace/tech_debt.jsonl` during cleanup instead of being auto-fixed late in the run.

## Testing

Harness unit tests:

```bash
pytest harness/tests/unit/ -q
```

Harness integration tests:

```bash
pytest harness/tests/integration/ -q
```

Harness e2e tests with mocked Claude:

```bash
pytest harness/tests/e2e/ -q
```

Full harness suite:

```bash
pytest harness/ -q
```

Frontend tooling checks for generated app work:

```bash
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Live Claude smoke tests are opt-in with `HARNESS_LIVE_E2E=1`. Long soak checks are opt-in with `HARNESS_SOAK=1`.

## Claude Code Workflow

This repository follows Claude Code project-memory best practices:

- Keep `CLAUDE.md` specific, structured, and focused on durable project instructions.
- Include common commands so agents do not rediscover them each session.
- Keep architecture and workflow detail in normal docs, then reference those docs from Claude Code prompts.
- Use small, testable increments; ask Claude to plan first for multi-step changes.
- Review generated PR summaries and testing notes before submitting.

Useful prompts inside Claude Code:

```text
give me an overview of this codebase
explain the harness state machine and where resume logic lives
plan a small change to the Animal Adventure MVP docs before editing
run the relevant harness tests and summarize failures
```

Use `@` references when you want Claude to load specific context, for example `@docs/architecture.md`, `@docs/test-plan.md`, or `@harness/harness.py`.

## Development Notes

- Treat `docs/` as the source of truth for product behavior and `harness/` as the source of truth for automation behavior.
- All programming tasks that write code should follow TDD unless they are documentation/config-only.
- Do not hardcode gameplay asset filenames when a logical id exists in `config/assets.json`, `config/characters.json`, or `config/map_tiles.json`.
- Do not serve static assets from FastAPI; Nginx serves `/assets/`.
- Do not commit runtime data, generated build output, caches, dependency folders, or local databases.
