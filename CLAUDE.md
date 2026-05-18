# Animal Adventure Claude Code Notes

## Project Context

- This repository contains the Animal Adventure L3 MVP specification, static assets, JSON gameplay config, and an autonomous Claude Code harness.
- The harness orchestrates Claude Code subprocesses through build, review, fix, cleanup, and evaluation phases. Harness tests validate harness behavior; they do not prove a generated fixture app is feature-complete.
- The generated Animal Adventure app is expected to be a local browser game: TypeScript + Phaser + Vite frontend, Python + FastAPI backend, SQLite persistence, Nginx static/proxy entrypoint.
- Treat `docs/` as the product spec source of truth and `harness/` as the automation implementation. Treat `assets/` and `config/` as committed project inputs.

## Claude Code Working Rules

- Start broad, then narrow: read `README.md`, `docs/requirements.md`, `docs/architecture.md`, `docs/workflows.md`, and the relevant harness module before changing behavior.
- Keep project memory specific and short. Put durable project conventions in this file, not transient notes.
- Prefer small, testable changes. For multi-file or risky work, make a plan first and verify after each meaningful step.
- Follow the existing code style and module boundaries. Do not introduce new frameworks, services, or deployment assumptions unless the spec requires them.
- Do not overwrite unrelated user changes. Check `git status --short` before and after edits.
- Do not commit `workspace/`, `data/*.sqlite3`, `logs/`, `dist/`, Playwright reports, caches, virtualenvs, or dependency folders.

## Common Commands

```bash
python harness/harness.py
python harness/harness.py docs --app-type game --language python
python harness/harness.py --resume
python harness/harness.py --status
python harness/eval_services.py cleanup
```

```bash
pytest harness/tests/unit/ -q
pytest harness/tests/integration/ -q
pytest harness/tests/e2e/ -q
pytest harness/ -q
```

```bash
npm run typecheck
npm test
npm run build
npm run test:e2e
```

## Harness Defaults And State

- Default settings live in `harness/config.json`: spec path `docs`, app type `game`, language `python`, max attempts `3`, evaluation minimum score `0.9`.
- Runtime artifacts live in `workspace/`: `state.json`, `events.jsonl`, `harness.log`, `run.lock`, `harness.pid`, `usage.jsonl`, `review_report.md`, and `tech_debt.jsonl`.
- Resume interrupted runs with `python harness/harness.py --resume`. If state is blocked, inspect `workspace/state.json`, `workspace/harness.log`, and `workspace/events.jsonl`.
- `evaluate.status` may be `blocked_external_dependency`, `timeout`, or `error`. Status reporting separates the current blocker from `historical_last_error`.
- `python harness/harness.py --status` reports recent `workspace/usage.jsonl` pressure, the latest Claude usage record, session pacing settings, and active external dependency wait details.
- `claude_session_pacing` is a soft delay mechanism, not a fixed token budget. It does not predict quota by `task_type`.
- `tdd_mode="unit_test"` tasks are verified locally by the harness without a Claude EXECUTE subprocess, but still run through `verify_execution()`.
- Parseable Claude 429 waits clean the failed Claude process tree, quarantine new untracked artifacts, record `workspace/external_dependency_context.json`, and require a clean resume preflight.
- MEDIUM/LOW review findings are normally appended to `workspace/tech_debt.jsonl` during cleanup instead of being fixed late in the run.

## Implementation Constraints

- Product behavior must stay aligned with the L3 MVP docs: name-only login, backend-owned `player_id`, server-authoritative quests/rewards/inventory/progression, WebSocket identity from `/ws/{player_id}`, SQLite WAL, Nginx-served assets, and full-map touring with Spawn-area interactions only.
- Frontend asset paths must resolve through `/assets/...`; use `config/assets.json`, `config/characters.json`, and `config/map_tiles.json` instead of hardcoding raw filenames in gameplay logic.
- The map client must render prepared tiles from `assets/images/MapTiles/` and must not load `assets/images/Items/game_map_full.png` as one large Phaser texture.
- FastAPI serves API and WebSocket traffic only. Static files are served by Nginx.
- Gameplay mutations that can race, including quest accept, turn-in, shop purchase, Potion use, and level-up, must be atomic and idempotent where rewards are involved.

## Testing Expectations

- All programming tasks that write code follow TDD unless the task is clearly documentation/config-only.
- Use targeted tests first, then broader suites when behavior crosses module boundaries.
- For harness changes, prefer the relevant `harness/tests/unit/` file, then integration or e2e tests if state-machine behavior changes.
- For generated app work, verify the matching phase expectations in `docs/test-plan.md`.
- Live Claude smoke tests are opt-in with `HARNESS_LIVE_E2E=1`; long soak tests are opt-in with `HARNESS_SOAK=1`.
