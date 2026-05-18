# Animal Adventure L3 MVP Logging And Ops

## Logging Goals

Logs must support local diagnosis of application lifecycle, gameplay workflows, data flow, resource issues, and exceptions. Logs should be structured JSON lines where possible.

## Required Log Fields

- `timestamp`
- `level`
- `service`
- `event_type`
- `request_id`
- `connection_id`
- `player_id`
- `session_id`
- `message`
- `context`
- `duration_ms`
- `error_type`
- `stack_trace`
- `resource_snapshot`

Fields that do not apply to a given event may be null, but the key should be present for structured logs.

## Required Log Categories

### Application Lifecycle

- startup
- config loaded
- database ready
- websocket ready
- shutdown

### Functional Paths

- player create/load
- websocket connect/disconnect/reconnect
- duplicate session replacement
- reconnect timeout
- movement accepted/rejected
- movement rate limit
- bootstrap load failure
- quest offer/start/pickup/complete/fail
- quest expiry scanner run
- quest auto-fail
- shop buy success/fail
- item use
- level up

### Data Flow

- REST request/response
- WebSocket receive/send
- database read/write
- config load

### Resource Utilization

- memory warning
- DB write latency warning
- WebSocket queue backlog
- abnormal reconnect frequency
- quest expiry scanner duration
- expired quest count
- rate-limited movement count

### Errors

Error logs must include:

- operation
- player id when available
- input summary
- stack trace
- recovery action

## Retention And Cleanup

- app logs: rotate daily, keep 14 days.
- player behavior logs: rotate daily, keep 30 days.
- error logs: rotate daily, keep 30 days.
- stale task/world item records cleaned by scheduled cleanup command.
- SQLite uses WAL checkpoint and periodic vacuum policy.

## Log File Targets

- `logs/app.log`: application lifecycle, readiness, normal service events.
- `logs/error.log`: exceptions, failed requests, failed WebSocket operations.
- `logs/player-events.log`: player behavior and gameplay events.
- `logs/resource.log`: resource warnings such as DB latency and queue backlog.

## MVP Local Deployment Requirements

- Nginx installed locally. Default MVP port is `8080`; port `80` is optional when available.
- FastAPI runs on `127.0.0.1:8000`.
- SQLite file stored at `data/animal_adventure.sqlite3`.
- Frontend built by `npm run build`.
- Assets served by Nginx under `/assets/`.
- Browser enters through Nginx URL only.
- FastAPI must not serve static assets.

## MVP Local Deployment Steps

1. Run dependency checker.
2. Install missing Python dependencies.
3. Install missing Node dependencies.
4. Install Playwright Chromium.
5. Build frontend.
6. Generate Nginx config from the project template:

```powershell
.\deploy\scripts\configure-nginx.ps1 -ProjectRoot "D:\Animal_Adventure"
```

7. Prepare Nginx static asset root.
8. Start FastAPI with uvicorn.
9. Start Nginx using the generated project config.
10. Open `http://localhost:8080/` by default, or `http://localhost/` if port `80` is explicitly configured.
11. Verify `/health`, `/ready`, `/assets/...`, and WebSocket connection.

## Windows 10 Nginx Install And Config Steps

Default MVP target is Windows 10 with Nginx listening on `8080`.

1. Download the stable Windows Nginx zip from the official Nginx download page.
2. Extract it to a simple path without spaces, recommended:

```text
C:\nginx
```

3. Generate the project config from the template. Use the actual project root if it is not `D:\Animal_Adventure`:

```powershell
cd D:\Animal_Adventure
.\deploy\scripts\configure-nginx.ps1 -ProjectRoot "D:\Animal_Adventure"
```

4. Copy or reference the generated project config:

```text
D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf
```

5. Either replace `C:\nginx\conf\nginx.conf` with the generated project config or include it from the default config.
6. From PowerShell or Command Prompt:

```powershell
cd C:\nginx
.\nginx.exe -t -c D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf
.\nginx.exe -c D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf
```

7. To reload config after changes:

```powershell
cd C:\nginx
.\nginx.exe -s reload
```

8. To stop Nginx:

```powershell
cd C:\nginx
.\nginx.exe -s stop
```

9. Verify from browser:

```text
http://localhost:8080/
http://localhost:8080/health
http://localhost:8080/ready
http://localhost:8080/assets/images/Items/game_map_full.png
http://localhost:8080/assets/images/MapTiles/map_tile_0_0.png
```

### Windows 10 Nginx Risks And Mitigations

- Risk: port `80` may require administrator privileges or may already be used by IIS/Skype/other software.
  - Mitigation: use port `8080` by default.
- Risk: Windows Firewall may prompt when Nginx starts.
  - Mitigation: allow local/private network access for development; do not expose MVP publicly.
- Risk: paths with spaces can break simple Nginx config.
  - Mitigation: run `deploy/scripts/configure-nginx.ps1 -ProjectRoot <path>` to normalize separators; avoid install paths with spaces for MVP.
- Risk: Nginx `alias` requires a trailing slash on both the location and alias target.
  - Mitigation: generated config must use `location /assets/ { alias <project-root>/assets/; }`.
- Risk: Nginx is not a Windows service by default.
  - Mitigation: document manual start/stop for MVP; use Windows Task Scheduler or a service wrapper only if machine reboot recovery is required.
- Risk: browser caching may hide changed assets.
  - Mitigation: hard refresh during development or add cache-control rules later.

## Automatic Restart

- Provide a local PowerShell/Bash watchdog for uvicorn process crashes.
- The quest expiry scanner starts and stops with the FastAPI application lifecycle. Scanner exceptions must be logged with recovery action and must not terminate the main FastAPI service.
- For recovery after full machine reboot, document an OS-level startup task such as Windows Task Scheduler or systemd. The MVP script does not itself survive a powered-off machine.
- Document Nginx restart command.
- Production alternatives can be documented as notes only; MVP deployment remains local.

## Nginx Routing Requirements

- `/` serves frontend `dist/`.
- `/assets/` serves static assets.
- `/api/`, `/health`, and `/ready` proxy to FastAPI.
- `/ws/` proxies WebSocket traffic to FastAPI and preserves upgrade headers.

## MVP Nginx Config Requirements

- Listen on `8080` by default.
- Serve built frontend from the project `dist/` directory using the generated project root.
- Use `alias` for `/assets/` pointing at the project `assets/` directory using the generated project root.
- Proxy `/api/`, `/health`, and `/ready` to `http://127.0.0.1:8000`.
- Proxy `/ws/` to `http://127.0.0.1:8000` with `Upgrade` and `Connection` headers.
- `deploy/nginx/animal-adventure.nginx.conf.template` uses `{{PROJECT_ROOT}}` placeholders. `deploy/scripts/configure-nginx.ps1 -ProjectRoot <path>` writes `deploy/nginx/animal-adventure.nginx.conf` with normalized forward slashes and no unresolved placeholders.

## MVP Nginx Config Template

Implementation should generate the local config from this template shape:

```nginx
server {
    listen 8080;
    server_name localhost;

    root {{PROJECT_ROOT}}/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /assets/ {
        alias {{PROJECT_ROOT}}/assets/;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000;
    }

    location /ready {
        proxy_pass http://127.0.0.1:8000;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```
