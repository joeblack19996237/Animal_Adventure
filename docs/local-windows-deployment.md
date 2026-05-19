# Animal Adventure — Local Windows 10 Deployment Guide

This guide covers deploying the Animal Adventure L3 MVP locally on Windows 10 using Nginx on port 8080.

## Prerequisites

- Windows 10 (64-bit)
- Python 3.10+
- Node.js 18+ and npm
- Git (for cloning)
- PowerShell 5.1+

## Architecture Overview

```
Browser → http://localhost:8080/
              │
              ▼
           Nginx (port 8080)
           ├─ /          → dist/index.html  (frontend SPA)
           ├─ /assets/   → assets/          (static assets)
           ├─ /api/      → 127.0.0.1:8000   (FastAPI)
           ├─ /health    → 127.0.0.1:8000
           ├─ /ready     → 127.0.0.1:8000
           └─ /ws/       → 127.0.0.1:8000   (WebSocket)
```

FastAPI listens only on `127.0.0.1:8000` and is not exposed directly to the browser.

## Step 1 — Install Nginx on Windows 10

1. Download the **stable** Windows zip from the official Nginx download page:
   `https://nginx.org/en/download.html`

2. Extract to a short path **without spaces**:

   ```text
   C:\nginx
   ```

   Avoid paths like `C:\Program Files\nginx` — spaces can break Nginx config on Windows.

3. Verify the install:

   ```powershell
   C:\nginx\nginx.exe -v
   ```

## Step 2 — Install Python and Node Dependencies

```powershell
cd D:\Animal_Adventure
pip install -r requirements.txt
npm install
```

## Step 3 — Build the Frontend

```powershell
cd D:\Animal_Adventure
npm run build
```

The built files land in `dist/`. Nginx serves this directory at `/`.

## Step 4 — Generate the Nginx Config

The template `deploy/nginx/animal-adventure.nginx.conf.template` contains `{{PROJECT_ROOT}}`
placeholders. The installation script resolves these to absolute forward-slash paths and writes
the generated config to `deploy/nginx/animal-adventure.nginx.conf`.

```powershell
cd D:\Animal_Adventure
.\deploy\scripts\configure-nginx.ps1 -ProjectRoot "D:\Animal_Adventure"
```

If your project root differs from `D:\Animal_Adventure`, pass the actual path:

```powershell
.\deploy\scripts\configure-nginx.ps1 -ProjectRoot "C:\Projects\AnimalAdventure"
```

The generated config file: `deploy/nginx/animal-adventure.nginx.conf`

## Step 5 — Nginx Config Reference

The template shape (from `deploy/nginx/animal-adventure.nginx.conf.template`):

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

Port `8080` is the default MVP port. Do not change this to port `80` without reading the risks
section below.

## Step 6 — Validate and Start Nginx

```powershell
cd C:\nginx

# Test the generated config
.\nginx.exe -t -c D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf

# Start Nginx with the project config
.\nginx.exe -c D:\Animal_Adventure\deploy\nginx\animal-adventure.nginx.conf
```

## Step 7 — Start FastAPI

```powershell
cd D:\Animal_Adventure
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Step 8 — Verify Deployment

Open these URLs in Chrome:

| URL | Expected result |
|-----|----------------|
| `http://localhost:8080/` | Game loads in browser |
| `http://localhost:8080/health` | `{"status": "ok"}` or similar |
| `http://localhost:8080/ready` | `{"status": "ready"}` or similar |
| `http://localhost:8080/assets/images/MapTiles/map_tile_0_0.png` | Tile image renders |

## Nginx Restart and Stop Commands

After changing the Nginx config, reload without downtime:

```powershell
cd C:\nginx
.\nginx.exe -s reload
```

Stop Nginx:

```powershell
cd C:\nginx
.\nginx.exe -s stop
```

Nginx is **not** a Windows service by default. Each machine reboot requires a manual restart
unless a Windows Task Scheduler entry or service wrapper is configured (see Restart section below).

## FastAPI Watchdog

The watchdog script (`deploy/scripts/watchdog.py`) checks whether uvicorn is running and
starts it if missing. It will not start a duplicate process if uvicorn is already running.

Run manually:

```powershell
cd D:\Animal_Adventure
python deploy/scripts/watchdog.py
```

The watchdog is a one-shot script, not a daemon. For automatic recovery after a crash, call
it on a schedule using Windows Task Scheduler or a monitoring loop.

## Recovery After Machine Reboot

The MVP does not automatically survive a full machine reboot. After reboot:

1. Start Nginx manually (Step 6 above).
2. Start FastAPI manually (Step 7 above).

To automate startup, create a Windows Task Scheduler entry that triggers on user logon and
runs both commands. This is optional for MVP development.

## Firewall Considerations

When Nginx first starts, Windows Firewall may prompt to allow network access.

- Allow access on **private networks** only for local development.
- Do **not** select "Public networks" unless you intend to expose the game to the local LAN.
- The MVP is not hardened for public internet exposure.

Port `8080` is a high port and typically does not require administrator privileges.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Port `80` requires administrator privileges or is occupied by IIS/Skype | Use port `8080` (the default). Only switch to port `80` if explicitly needed and the port is free. |
| Windows Firewall blocks Nginx on first start | Accept the Windows Firewall prompt; allow private network access only. |
| Paths with spaces break Nginx config | Extract Nginx to `C:\nginx`. Run `configure-nginx.ps1` to normalize project root separators; avoid paths with spaces. |
| Nginx `alias` requires trailing slash on both location and alias target | The generated config from the template always includes trailing slashes on `/assets/`. Do not edit manually without preserving them. |
| Nginx is not a Windows service and does not survive reboot | Document the manual restart procedure. Configure Windows Task Scheduler for automatic restart if needed. |
| Browser caches changed assets and hides updates | Hard refresh with `Ctrl+Shift+R` during development. |
| FastAPI process crashes | Run `python deploy/scripts/watchdog.py` to restart uvicorn, or configure Task Scheduler to call the watchdog on a regular interval. |
