# Final Acceptance Execution Plan

Generated for the Codex-run final acceptance path on 2026-05-20.

This plan is based on `docs/final-acceptance-test.md`. It assumes Phase 16 has been removed from the harness build plan and that final Nginx-served acceptance will be run manually/Codex-side before resuming the harness into cleanup/evaluate.

## Goal

Prove that Animal Adventure is ready for final harness evaluation by validating the production-like local Windows deployment path:

- Build artifacts in `dist/`
- FastAPI on `127.0.0.1:8000`
- Nginx browser entrypoint on `http://localhost:8080/`
- Built JS/CSS served from `/assets/`, with game images and music served from `/assets/images/` and `/assets/music/`
- API, health, ready, and WebSocket routes proxied through Nginx
- End-to-end gameplay path through login, reconnect, duplicate session, quest/shop/inventory, Potion use, and L3 progression
- No critical browser console errors, page errors, backend tracebacks, or asset failures

The 30-minute soak is opt-in and must not block the default final acceptance path unless intentionally requested.

## Operating Rules

- Do not resume the harness into cleanup/evaluate until quick final acceptance passes.
- Use PowerShell commands with explicit executable paths because this machine blocks `npm.ps1` and bare `python` resolves to an inaccessible WindowsApps shim.
- Keep Nginx pid, logs, and temp files under `D:\Animal_Adventure\.tmp`.
- Do not edit `D:\nginx\conf\nginx.conf` unless explicitly requested; use a generated workspace wrapper config for acceptance.
- Leave `VITE_WS_URL` unset so the frontend derives `ws://localhost:8080` from `window.location.origin`.
- Keep the 30-minute soak behind `HARNESS_SOAK=1`.
- Capture evidence for every failure before fixing it.

## Verified Local Constants

- Workspace: `D:\Animal_Adventure`
- Node: `C:\Program Files\nodejs\node.exe`
- npm for PowerShell: `C:\Program Files\nodejs\npm.CMD`
- Python: `C:\Users\OEM\AppData\Local\Python\bin\python.exe`
- Nginx: `D:\nginx\nginx.exe`
- Nginx version: `nginx/1.30.0`
- Backend URL: `http://127.0.0.1:8000`
- Browser URL: `http://localhost:8080`
- Current Vite e2e URL: `http://localhost:5173`
- Project Nginx server block: `D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf`
- Runtime wrapper config: `D:\Animal_Adventure\.tmp\nginx-animal-adventure-wrapper.conf`
- Runtime Nginx pid: `D:\Animal_Adventure\.tmp\nginx.pid`
- Runtime Nginx logs: `D:\Animal_Adventure\.tmp\nginx-access.log`, `D:\Animal_Adventure\.tmp\nginx-error.log`

## Phase A — Final Acceptance Infrastructure

### A1. Add Nginx Playwright Config

Create `playwright.nginx.config.ts`.

Requirements:

- `testDir: './tests/e2e'`
- `timeout: 60000` per test unless a specific smoke needs a higher local timeout.
- `use.baseURL: 'http://localhost:8080'`
- Projects:
  - `chromium` with `devices['Desktop Chrome']`
  - `webkit-ipad` with `devices['iPad Pro 11']`
- No `webServer` block. Nginx and FastAPI are started explicitly by the acceptance procedure.

Acceptance:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --list
```

The command lists Nginx-targeted tests without starting Vite.

### A2. Add npm Script

Update `package.json`:

```json
"test:e2e:nginx": "playwright test --config=playwright.nginx.config.ts"
```

Keep existing `test:e2e` unchanged so regression tests can still use the Vite runner.

Acceptance:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --help
```

The command invokes Playwright and does not start Vite.

### A3. Add Local Nginx Wrapper Helper

Prefer a generated `.tmp` wrapper over committing machine-specific Nginx config.

Create a reusable script if automation is desired:

- `deploy/scripts/write-local-nginx-wrapper.ps1`

The script should:

- Create `.tmp\logs` and `.tmp\temp`
- Write `.tmp\nginx-animal-adventure-wrapper.conf`
- Include `D:/nginx/conf/mime.types`
- Set `error_log`, `access_log`, `pid`, and temp paths under `D:/Animal_Adventure/.tmp`
- Include `D:/Animal_Adventure/deploy/nginx/animal-adventure.nginx.conf`

Acceptance:

```powershell
& 'D:\nginx\nginx.exe' -t -p 'D:\Animal_Adventure\.tmp' -c 'D:\Animal_Adventure\.tmp\nginx-animal-adventure-wrapper.conf'
```

Expected output includes:

- `syntax is ok`
- `test is successful`

### A4. Add Service Cleanup Procedure

Document or script service cleanup before and after tests:

```powershell
if (Test-Path 'D:\Animal_Adventure\.tmp\nginx.pid') {
  & 'D:\nginx\nginx.exe' -p 'D:\Animal_Adventure\.tmp' -c 'D:\Animal_Adventure\.tmp\nginx-animal-adventure-wrapper.conf' -s stop
}
```

For backend cleanup, stop the terminal running uvicorn or terminate the registered process if a helper script is added.

Acceptance:

- Ports `8000` and `8080` are free after cleanup.

## Phase B — Nginx-Served Test Coverage

### B1. Add Route And Asset Test

Create `tests/e2e/phase16-smoke.spec.ts` or `tests/e2e/e2e-nginx-routing.spec.ts`.

Coverage:

- `GET /` returns the built frontend.
- `GET /health` returns HTTP 200 through Nginx.
- `GET /ready` returns HTTP 200 through Nginx.
- `/assets/images/MapTiles/map_tile_0_0.png` returns HTTP 200.
- `/assets/images/Items/game_map_full.png` returns HTTP 200.
- No JS/CSS/image response has a 404 or MIME error.

Acceptance:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep "nginx|assets|@phase16-smoke" --project=chromium
```

### B2. Add Canvas Integrity Test

Coverage:

- Load `http://localhost:8080/`.
- Complete login if needed.
- Assert Phaser canvas is visible.
- Assert canvas/screenshot pixels are nonblank.
- Capture screenshot on failure.

Acceptance:

- Test fails on hidden/blank canvas.
- Test passes when current game renders normally.

### B3. Add Browser Error Monitor

All Phase 16 browser tests must register:

- `page.on('console', ...)`
- `page.on('pageerror', ...)`
- response watcher for failed JS/CSS/assets/API calls

Failure policy:

- Fail on `pageerror`.
- Fail on critical console errors.
- Fail on 404 JS/CSS/assets.
- Fail on failed `/api`, `/health`, `/ready`, or `/ws` setup routes unless the test intentionally simulates failure.

Acceptance:

- A synthetic broken asset or page error causes the test to fail with readable evidence.

### B4. Add Full MVP L3 Test Through Nginx

Reuse the stable selectors and readiness helpers from existing Phase 14 e2e tests, but run against `baseURL: http://localhost:8080`.

Coverage:

- Name-only login creates or resumes a player.
- Quest accept.
- Item pickup.
- Quest turn-in.
- Coin reward visible.
- Potion purchase.
- Potion use.
- Second quest completion.
- Player reaches L3.
- Reload restores visible state.

Acceptance:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep "L3|@phase16-smoke" --project=chromium
```

### B5. Add Reconnect Test Through Nginx

Coverage:

- Establish gameplay WebSocket through `ws://localhost:8080/ws/{player_id}`.
- Force disconnect.
- Verify reconnect.
- Verify `state_sync` restores durable quest/player state.

Acceptance:

- Test passes in chromium.
- If WebKit is included in the smoke, test either passes in `webkit-ipad` or failure is recorded with browser-specific evidence.

### B6. Add Duplicate Session Test Through Nginx

Coverage:

- Browser A logs in as a player.
- Browser B logs in/resumes the same player.
- Browser A receives `duplicate_session` or otherwise transitions to the duplicate-session UI/error path.
- Browser B receives `state_sync`.
- There are not two active gameplay sessions for the same `player_id`.

Acceptance:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep "duplicate|@phase16-smoke"
```

### B7. Add Optional Soak Test

Create a soak test that is always skipped unless explicitly enabled:

```ts
test.skip(process.env.HARNESS_SOAK !== '1', '30-minute soak is opt-in');
```

Coverage:

- Keep the game alive for approximately 30 minutes.
- Perform periodic movement/reconnect/light interactions.
- Fail on critical console errors, page errors, failed API calls, or backend traceback evidence.

Rules:

- Do not tag the soak as `@phase16-smoke`.
- Do not run it through the harness default regression path.

Acceptance:

```powershell
$env:HARNESS_SOAK='1'
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep soak_30_min --project=chromium
Remove-Item Env:HARNESS_SOAK
```

## Phase C — Manual Runtime Procedure

### C1. Preflight

Run:

```powershell
cd D:\Animal_Adventure
& 'C:\Program Files\nodejs\npm.CMD' --version
& 'C:\Program Files\nodejs\node.exe' --version
& 'D:\nginx\nginx.exe' -v
& 'C:\Users\OEM\AppData\Local\Python\bin\python.exe' --version
Get-NetTCPConnection -LocalPort 8000,8080,5173 -ErrorAction SilentlyContinue
```

Pass criteria:

- Tools print versions.
- `8000` and `8080` are free before startup.
- `5173` may be free or unused; Nginx acceptance must not depend on it.

### C2. Build

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run build
```

Pass criteria:

- Build exits 0.
- `dist/index.html` exists.
- `dist/assets` exists.

### C3. Start FastAPI

Start backend in a dedicated terminal:

```powershell
cd D:\Animal_Adventure
& 'C:\Users\OEM\AppData\Local\Python\bin\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verify in another terminal:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/ready
```

Pass criteria:

- Both endpoints return HTTP 200.

### C4. Start Nginx

Generate or refresh the wrapper config, then run:

```powershell
& 'D:\nginx\nginx.exe' -t -p 'D:\Animal_Adventure\.tmp' -c 'D:\Animal_Adventure\.tmp\nginx-animal-adventure-wrapper.conf'
& 'D:\nginx\nginx.exe' -p 'D:\Animal_Adventure\.tmp' -c 'D:\Animal_Adventure\.tmp\nginx-animal-adventure-wrapper.conf'
```

Verify:

```powershell
Invoke-WebRequest http://localhost:8080/
Invoke-WebRequest http://localhost:8080/health
Invoke-WebRequest http://localhost:8080/ready
Invoke-WebRequest http://localhost:8080/assets/images/MapTiles/map_tile_0_0.png
Invoke-WebRequest http://localhost:8080/assets/images/Items/game_map_full.png
```

Pass criteria:

- All route checks return HTTP 200.
- Nginx listens on `8080`.

## Phase D — Execution Order

Run in this order:

1. `npm run typecheck`
2. `npm test`
3. `npm run build`
4. Start FastAPI.
5. Start Nginx through wrapper config.
6. Route checks.
7. `npm run test:e2e:nginx -- --grep @phase16-smoke --project=chromium`
8. `npm run test:e2e:nginx -- --grep @phase16-smoke --project=webkit-ipad`
9. `npm run test:e2e:nginx` if the smoke is stable.
10. Optional `HARNESS_SOAK=1` soak only after all prior checks pass.

Use explicit PowerShell npm command:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run typecheck
& 'C:\Program Files\nodejs\npm.CMD' test
& 'C:\Program Files\nodejs\npm.CMD' run build
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep @phase16-smoke --project=chromium
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep @phase16-smoke --project=webkit-ipad
```

## Phase E — Evidence Collection

For every run, record:

- Command
- Exit code
- Start/end time
- stdout/stderr tail
- Browser project
- Screenshots for browser failures
- Nginx access/error log tail from `.tmp`
- Backend traceback/log evidence if present

Recommended evidence paths:

- `workspace/final-acceptance/phase16-command-log.md`
- `workspace/final-acceptance/screenshots/`
- `workspace/final-acceptance/nginx-access-tail.log`
- `workspace/final-acceptance/nginx-error-tail.log`
- `workspace/final-acceptance/backend-log-tail.log`

## Phase F — Failure Handling

### F1. Environment Failure

Examples:

- Nginx missing.
- Port occupied.
- PowerShell execution policy blocks `npm.ps1`.
- WindowsApps Python shim fails.

Action:

- Fix command/path/environment.
- Do not classify as product failure.
- Re-run from the failed preflight step.

### F2. Nginx Config Failure

Examples:

- Passing bare `server {}` block to `nginx.exe -c`.
- Cannot write to `D:\nginx\logs`.
- Missing `mime.types` include.

Action:

- Use workspace wrapper config.
- Keep pid/log/temp under `.tmp`.
- Re-test `nginx.exe -t`.

### F3. Browser/Test Flake

Examples:

- WebKit-only timing failure.
- Strict locator issue.
- Reconnect wait too short.

Action:

- Reproduce targeted project only.
- Prefer readiness waits over fixed sleep.
- Fix selectors/readiness helpers.
- Re-run targeted test, then full smoke.

### F4. Product Failure

Examples:

- Login fails through Nginx.
- API route points to wrong origin.
- WebSocket does not connect through `/ws/`.
- Quest/L3 loop fails after correct environment setup.

Action:

- Create focused failing test or improve existing Phase 16 test.
- Fix product code.
- Run targeted test.
- Run full Nginx smoke.
- Run standard regression if the fix touches shared behavior.

## Phase G — Completion Criteria

Final acceptance is complete when:

- `npm run typecheck` passes.
- `npm test` passes.
- `npm run build` passes.
- FastAPI `/health` and `/ready` pass on `127.0.0.1:8000`.
- Nginx route checks pass on `http://localhost:8080`.
- `@phase16-smoke` passes in chromium.
- `@phase16-smoke` either passes in `webkit-ipad` or any failure is explicitly documented as browser-specific with a decision to fix or defer.
- Full Nginx e2e passes, or skipped tests have explicit environment reasons.
- Optional soak is either not requested or passes with `HARNESS_SOAK=1`.
- No critical console/page errors, asset 404s, API route failures, or backend tracebacks remain.
