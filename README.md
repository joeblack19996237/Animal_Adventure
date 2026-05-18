# Animal Adventure AI Harness

Animal Adventure is an AI-assisted software engineering portfolio project. It
contains two connected systems:

- A full-stack browser game case study: **Animal Adventure**, built with
  TypeScript, Phaser, Vite, Python, FastAPI, WebSocket, SQLite, and Playwright.
- A local autonomous development harness that orchestrates Claude Code agents
  through planning, implementation, review, fix, evaluation, and regression
  gates.

The product demonstrates the harness on a non-trivial game project. The harness
demonstrates AI workflow engineering: prompt contracts, JSON signal validation,
state-machine resume behavior, TDD enforcement, review/fix loops, evaluator
iterations, and phase-level full regression gates.

## Highlights

- **Agent orchestration:** TASK_BUILD, EXECUTE, REVIEW, FIX, CLEANUP, and
  EVALUATE modes with role-specific prompts under `.claude/agents/`.
- **Stateful resumability:** `workspace/state.json` tracks phases, tasks,
  issues, evaluation iterations, regression status, attempts, errors, and
  evidence.
- **Strict TDD and verification:** builder instructions and hooks enforce test
  ordering, structured signals, safe commits, and verification before accepting
  work.
- **Evaluation coverage loop:** evaluator findings include test case contracts;
  tests are authored before fixes, red-verified, fixed, targeted-verified, and
  followed by full regression.
- **Phase regression gate:** every phase must pass full product regression
  before `NEXT_PHASE`; failures become HIGH regression issues and re-enter FIX.
- **Real product surface:** backend APIs, WebSocket session sync, frontend game
  state, login flow, responsive UI, asset loading, smoke tests, and e2e tests.

## Product Scope

Animal Adventure is a local L3 MVP browser game:

- Frontend: TypeScript, Phaser, Vite.
- Backend: Python, FastAPI, WebSocket.
- Persistence: SQLite with WAL.
- Static/proxy deployment: Nginx config under `deploy/`.
- Configuration: JSON gameplay data under `config/`.

Core gameplay is documented in `docs/requirements.md`, `docs/architecture.md`,
and `docs/workflows.md`: name-only login, backend-generated `player_id`,
character selection, full-map touring, Spawn-area quests, inventory/shop/Potion
flow, L3 progression, reconnect recovery, and persisted state.

## Harness Scope

The harness lives in `harness/` and is configured by `harness/config.json`. It
coordinates Claude Code subprocesses and records run state in `workspace/`.

High-level flow:

```text
TASK_BUILD -> EXECUTING -> REVIEWING -> FIXING -> REGRESSION_TESTING
          -> NEXT_PHASE -> CLEANUP -> EVALUATING -> COMPLETE
```

Important gates:

- `verify_execution()` verifies task output and commit behavior.
- `run_fix_cycle()` fixes CRITICAL/HIGH review issues and re-verifies fixes.
- `REGRESSION_TESTING` runs full product regression before phase advancement.
- `run_evaluate_cycle()` performs evaluator iterations after cleanup.
- Evaluation fixes require authored tests, red verification, targeted green
  verification, and full regression before the next evaluation iteration.

See:

- `harness/docs/08-state-schema.md`
- `harness/docs/improvement/evaluate-test-coverage-loop-plan-2026-05-18.md`
- `harness/docs/improvement/phase-regression-gate-plan-2026-05-18.md`

## Repository Layout

```text
.
+-- .claude/                  # Agent prompts, rules, hooks, skills, settings
+-- app/                      # FastAPI backend and services
+-- assets/                   # Game image/audio assets
+-- config/                   # Gameplay and asset manifests
+-- deploy/                   # Nginx and deployment helper scripts
+-- docs/                     # Product architecture, requirements, workflows
+-- harness/                  # AI development harness implementation and tests
+-- src/                      # TypeScript/Phaser frontend
+-- tests/                    # Product Python, Vitest, and Playwright tests
+-- workspace/                # Runtime state/logs, ignored by git
+-- package.json              # Frontend tooling
+-- requirements.txt          # Python product dependencies
+-- pytest.ini                # Product Python test config
```

## Prerequisites

- Python 3.10+.
- Node.js 18+ and npm.
- Claude Code CLI available as `claude` for harness runs.
- Optional for full local deployment: Nginx.
- Playwright browser dependencies for e2e tests.

Install product dependencies:

```bash
pip install -r requirements.txt
npm install
```

Install harness dependencies if running harness tests:

```bash
pip install -r harness/requirements.txt
```

## Product Commands

Run backend/product Python tests:

```bash
pytest tests -q --ignore=tests/e2e
```

Run TypeScript checks and frontend/unit integration tests:

```bash
npm run typecheck
npm test
```

Run a production build:

```bash
npm run build
```

Run browser e2e tests:

```bash
npm run test:e2e
```

On Windows PowerShell, use `npm.cmd` if script execution policy blocks
`npm.ps1`:

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
```

## Harness Commands

Start a harness run:

```bash
python harness/harness.py docs --app-type game --language python
```

Resume an interrupted run:

```bash
python harness/harness.py --resume
```

Check current harness status:

```bash
python harness/harness.py --status
```

Clean up external evaluation services:

```bash
python harness/eval_services.py cleanup
```

Harness unit and integration checks:

```bash
pytest harness/tests/unit -q
pytest harness/tests/integration -q
```

## Regression Notes

Recent product-only regression coverage included:

- Python/FastAPI product tests: `445 passed`.
- TypeScript typecheck: passed.
- Vitest product tests: `365 passed`.
- Production build: passed.
- Playwright e2e test bodies completed successfully; on this Windows environment
  the Playwright runner can hang during webServer teardown, so inspect output for
  completed `ok`/`skipped` cases when diagnosing local runs.

Recent harness regression coverage included:

- Harness unit tests: `853 passed`.
- Harness integration tests: `15 passed`.

If Windows temp permissions block pytest, point temp dirs into the workspace:

```powershell
New-Item -ItemType Directory -Force -Path .tmp\pytest | Out-Null
$env:TMP=(Resolve-Path .tmp\pytest)
$env:TEMP=$env:TMP
pytest harness/tests/unit -q
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

Do not commit runtime data, generated build output, caches, dependency folders,
local databases, or personal Claude settings such as
`.claude/settings.local.json`.

## Portfolio Framing

This repo is intended to show AI engineering work, not just a finished game. The
interesting parts are the control loops:

- How agents receive bounded prompts and emit machine-validated JSON signals.
- How the harness distinguishes agent failures, harness verification failures,
  external dependency blocks, and resumable interruptions.
- How evaluator findings become test contracts before fixes.
- How phase-level regression failures become HIGH issues and loop through FIX
  before the next phase can start.

For product behavior, start with `docs/requirements.md`. For harness behavior,
start with `harness/harness.py`, `harness/phase_handlers.py`,
`harness/evaluate.py`, `harness/regression.py`, and
`harness/docs/08-state-schema.md`.
