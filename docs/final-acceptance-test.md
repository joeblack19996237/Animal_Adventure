# Final Acceptance Test

Generated for Phase 16 on 2026-05-20.

This document turns `docs/test-plan.md` Phase 16 into an executable final acceptance plan. Values below were verified on this workstation before writing the file. The goal is to run Phase 16 under direct Codex/manual control instead of the harness default timeout path.

## Verified Local Environment

- Workspace: `D:\Animal_Adventure`
- Git branch at verification time: `main`
- Node executable: `C:\Program Files\nodejs\node.exe`
- Node version: `v24.14.0`
- npm command for PowerShell: `C:\Program Files\nodejs\npm.CMD`
- npm version: `11.9.0`
- `npm` in PowerShell resolves to `C:\Program Files\nodejs\npm.ps1` and is blocked by execution policy on this machine. Use `npm.CMD` in PowerShell, or use `npm` from Git Bash.
- Nginx executable: `D:\nginx\nginx.exe`
- Nginx version: `nginx/1.30.0`
- Example path `C:\nginx\nginx.exe` does not exist on this machine.
- Real Python executable: `C:\Users\OEM\AppData\Local\Python\bin\python.exe`
- Alternate real Python executable: `C:\Users\OEM\AppData\Local\Python\pythoncore-3.14-64\python.exe`
- Python version for both real executables: `Python 3.14.3`
- WindowsApps Python shim: `C:\Users\OEM\AppData\Local\Microsoft\WindowsApps\python.exe`; verified inaccessible, so do not use bare `python` from PowerShell for final acceptance.

## Verified Ports

Checked before writing this document:

- `8000`: free. Intended FastAPI backend port.
- `8080`: free. Intended Nginx browser entrypoint.
- `5173`: free. Current Vite e2e runner port.

If any of these ports are occupied at run time, stop the occupying process or choose a deliberate alternate port and update the commands in this document before testing.

## Verified Paths

- Nginx generated config: `D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf`
- Nginx template: `D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf.template`
- Nginx configure script: `D:\Animal_Adventure\deploy\scripts\configure-nginx.ps1`
- Watchdog script: `D:\Animal_Adventure\deploy\scripts\watchdog.py`
- Built frontend entrypoint: `D:\Animal_Adventure\dist\index.html`
- Built frontend assets directory: `D:\Animal_Adventure\dist\assets`
- Static game assets root: `D:\Animal_Adventure\assets`
- Sample static asset: `D:\Animal_Adventure\assets\images\Items\game_map_full.png`
- Sample tile asset: `D:\Animal_Adventure\assets\images\MapTiles\map_tile_0_0.png`
- Data directory: `D:\Animal_Adventure\data`
- Logs directory: `D:\Animal_Adventure\logs`

## Verified Nginx Configuration Status

The generated Nginx file contains a `server { ... }` block with:

- `listen 8080`
- `root D:/Animal_Adventure/dist`
- `/assets/` aliased to `D:/Animal_Adventure/dist/assets/` for Vite-built JS/CSS
- `/assets/images/` aliased to `D:/Animal_Adventure/assets/images/`
- `/assets/music/` aliased to `D:/Animal_Adventure/assets/music/`
- `/api/`, `/health`, `/ready`, and `/ws/` proxied to `http://127.0.0.1:8000`

Important: running this file directly with:

```powershell
& 'D:\nginx\nginx.exe' -t -c 'D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf'
```

was verified to fail because the file is a `server` block, not a full top-level `nginx.conf`. Phase 16 must either include this file from `D:\nginx\conf\nginx.conf` inside the `http {}` block, or use a temporary full wrapper config for acceptance testing.

## Verified Environment Variables

Currently unset in the running shell:

- `HARNESS_SOAK`
- `E2E_BASE_URL`
- `PLAYWRIGHT_NO_VITE`
- `DATABASE_PATH`
- `PYTHON`
- `PYTHON_EXE`

Currently supported by frontend code:

- `VITE_WS_URL`: optional build-time override for WebSocket URL. Leave unset for Nginx acceptance so the client derives `ws://localhost:8080` from `window.location.origin`.

Currently not implemented by the e2e runner:

- `E2E_BASE_URL`
- `PLAYWRIGHT_NO_VITE`

Before Nginx-specific Playwright automation is added, `npm run test:e2e` still starts or reuses Vite on `http://localhost:5173` and Playwright still uses `baseURL: http://localhost:5173`.

## Acceptance Scope

Phase 16 covers the following tests from `docs/test-plan.md`:

- `e2e_app_loads_through_nginx`
- `e2e_canvas_visible_nonblank`
- `e2e_assets_no_404`
- `e2e_nginx_routing`
- `e2e_full_mvp_loop`
- `e2e_duplicate_session_single_active_connection`
- `e2e_no_console_or_backend_errors`
- `@phase16-smoke`
- `soak_30_min`

For direct Codex/manual execution, split these into two tracks:

- Quick final acceptance: deterministic checks expected to finish in under 10 minutes.
- Optional soak: 30-minute run, only when `HARNESS_SOAK=1`.

## Required Improvements Before Running Automated Phase 16

1. Add a Nginx Playwright mode.

   Current `npm run test:e2e` is Vite-based. Add a separate script such as:

   ```json
   "test:e2e:nginx": "playwright test --config=playwright.nginx.config.ts"
   ```

   The Nginx config should use `baseURL: 'http://localhost:8080'` and must not start Vite.

2. Add `@phase16-smoke`.

   The smoke should cover Nginx routing, assets, login, reconnect, duplicate session, and L3. It must not include the 30-minute soak.

3. Add an explicit soak guard.

   Any 30-minute test must use:

   ```ts
   test.skip(process.env.HARNESS_SOAK !== '1', '30-minute soak is opt-in');
   ```

   The soak test must not be tagged `@phase16-smoke`.

4. Fix or wrap the generated Nginx config for runtime testing.

   Since `animal-adventure.nginx.conf` is a `server` block, use one of these approaches:

   - Include it inside the `http {}` block in `D:\nginx\conf\nginx.conf`.
   - Generate a temporary full config for testing that contains `events {}` and `http { include mime.types; include D:/Animal_Adventure/deploy/nginx/animal-adventure.nginx.conf; }`.

## Quick Final Acceptance Procedure

### 1. Preflight

Run from `D:\Animal_Adventure`.

```powershell
& 'C:\Program Files\nodejs\npm.CMD' --version
& 'C:\Program Files\nodejs\node.exe' --version
& 'D:\nginx\nginx.exe' -v
& 'C:\Users\OEM\AppData\Local\Python\bin\python.exe' --version
```

Check the required ports:

```powershell
Get-NetTCPConnection -LocalPort 8000,8080,5173 -ErrorAction SilentlyContinue
```

Expected result before startup: no listeners on `8000`, `8080`, or `5173`.

### 2. Build

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run build
```

Expected:

- `D:\Animal_Adventure\dist\index.html` exists.
- `D:\Animal_Adventure\dist\assets` exists.

### 3. Start Backend

Use the real Python executable, not WindowsApps `python.exe`.

```powershell
& 'C:\Users\OEM\AppData\Local\Python\bin\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell, verify:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/ready
```

Expected:

- `/health` returns HTTP 200.
- `/ready` returns HTTP 200 and reports ready status.

### 4. Start Nginx

Do not pass `D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf` directly to `-c` unless it has been converted into a full top-level Nginx config.

Preferred acceptance setup:

1. Include `D:/Animal_Adventure/deploy/nginx/animal-adventure.nginx.conf` inside the `http {}` block of `D:\nginx\conf\nginx.conf`, or create a temporary full wrapper config.
2. Validate the effective config:

```powershell
& 'D:\nginx\nginx.exe' -t
```

3. Start Nginx:

```powershell
& 'D:\nginx\nginx.exe'
```

Expected:

- Nginx listens on `8080`.
- No config syntax errors.

### 5. Route Checks

```powershell
Invoke-WebRequest http://localhost:8080/
Invoke-WebRequest http://localhost:8080/health
Invoke-WebRequest http://localhost:8080/ready
Invoke-WebRequest http://localhost:8080/assets/images/MapTiles/map_tile_0_0.png
Invoke-WebRequest http://localhost:8080/assets/images/Items/game_map_full.png
```

Expected:

- `/` returns the built frontend.
- `/health` and `/ready` are proxied to FastAPI.
- Asset URLs return HTTP 200 with image content.
- The frontend derives API URL `http://localhost:8080` and WebSocket URL `ws://localhost:8080`.

### 6. Automated Browser Checks

After adding `test:e2e:nginx`, run:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep @phase16-smoke
```

Expected coverage:

- App loads through `http://localhost:8080/`.
- Canvas is visible and nonblank.
- Assets load without 404 or MIME errors.
- `/api`, `/health`, `/ready`, and `/ws` route through Nginx correctly.
- Name login creates or resumes a player.
- Reload restores state.
- WebSocket reconnect restores progress.
- Second browser with the same player receives `duplicate_session` on the older connection.
- New player can complete the MVP path to L3.
- No critical browser console errors, page errors, or backend tracebacks.

### 7. Full Nginx E2E

After the smoke is stable, run the Nginx project without grep:

```powershell
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx
```

Expected time budget: 10-15 minutes. If this exceeds 15 minutes without progress, stop and inspect the current test rather than letting it run indefinitely.

## Optional 30-Minute Soak

Only run this after quick final acceptance passes.

```powershell
$env:HARNESS_SOAK='1'
& 'C:\Program Files\nodejs\npm.CMD' run test:e2e:nginx -- --grep soak_30_min
Remove-Item Env:HARNESS_SOAK
```

Expected:

- Runtime is approximately 30 minutes.
- No critical console errors.
- No page errors.
- No backend tracebacks.
- Reconnect and state restore remain healthy over time.

Do not run this through the harness default regression path.

## Pass Criteria

Phase 16 passes when all of the following are true:

- Build succeeds.
- Backend health and readiness pass on `127.0.0.1:8000`.
- Nginx serves the app on `http://localhost:8080/`.
- Nginx proxies `/api/`, `/health`, `/ready`, and `/ws/` to FastAPI.
- Static assets under `/assets/` return HTTP 200.
- `@phase16-smoke` passes through the Nginx URL.
- Full Nginx e2e passes or any skipped tests have explicit environment reasons.
- Optional soak passes only when intentionally run with `HARNESS_SOAK=1`.

## Known Current Gaps

- `test:e2e:nginx` does not exist yet.
- `playwright.nginx.config.ts` does not exist yet.
- `E2E_BASE_URL` and `PLAYWRIGHT_NO_VITE` are not implemented by the current e2e runner.
- The generated Nginx config is a `server` block and cannot be used directly as `nginx.exe -c <file>`.
- PowerShell `npm` resolves to a blocked `.ps1`; use `npm.CMD`.
- Bare `python` resolves to an inaccessible WindowsApps shim; use the verified real Python executable.
