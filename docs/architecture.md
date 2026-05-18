# Animal Adventure L3 MVP Architecture

## Stack

- Frontend: TypeScript + Phaser + Vite.
- Backend: Python + FastAPI + WebSocket.
- Database: SQLite + WAL.
- Config: JSON.
- Static hosting: Nginx.
- Local ops: PowerShell/Bash scripts.

## Runtime Topology

Default browser entrypoint:

```text
http://localhost:8080/
```

Nginx responsibilities:

- `/` -> frontend `dist/`
- `/assets/` -> static assets by Nginx `alias` to the project `assets/` directory
- `/api/` -> FastAPI `127.0.0.1:8000`
- `/health` -> FastAPI
- `/ready` -> FastAPI
- `/ws/` -> FastAPI WebSocket

FastAPI responsibilities:

- REST API.
- WebSocket.
- SQLite persistence.
- Server-authoritative game state.
- Logs and player behavior events.

## Authority Model

- Server decides quest state, rewards, inventory, coins, leveling, and whether a quest item can be picked up.
- Server owns NPC quest locks. A quest lock prevents more than one active instance and one spawned item set for the same NPC quest at a time.
- The backend runs a quest expiry scanner every 30 seconds. Expiry handling must use the same failure transition as pickup/turn-in expiry checks and backend restart recovery.
- Client may predict local movement, but the server periodically corrects position.
- MVP broadcasts minimal multiplayer render state at 10Hz.
- The frontend throttles outbound `player_move` messages to at most 20Hz. The server still defensively handles over-frequency movement with `rate_limited` responses or safe drops.
- Online player positions are kept in memory for active sessions. Movement updates validate map bounds and update memory first; they do not write to SQLite per message.
- Position is autosaved to SQLite every 30 seconds at most and immediately after quest accept, quest completion, quest failure, shop purchase, Potion use, level-up, and WebSocket disconnect.
- After reconnect, the client replaces local state with server `state_sync`.
- WebSocket connection identity comes from `/ws/{player_id}`. The server must ignore or verify any `player_id` included in message bodies and must reject impersonation attempts.
- The WebSocket session registry allows only one active connection per `player_id`. A new connection for the same `player_id` is accepted, the previous connection receives an `error` message with code `duplicate_session`, the previous connection is closed, and the new connection receives `state_sync`.
- The frontend must derive REST and WebSocket URLs from `window.location.origin` unless explicit environment variables are provided. WebSocket URL derivation maps `http://` to `ws://` and `https://` to `wss://`. This keeps `localhost:8080`, optional `localhost:80`, and any future TLS local proxy consistent.
- NPC interaction radius and item pickup radius are validated by the server using the authoritative in-memory player position from the WebSocket session. The server must not trust client-supplied coordinates for interaction or pickup distance checks.

## Static Resource Rules

- Source assets remain under `assets/`.
- MVP uses Nginx `alias` to serve the existing project `assets/` directory directly. Do not use symlinks by default because Windows may require elevated permissions.
- A later packaging step may copy assets into a release directory, but MVP local deployment must not require copying hundreds of image files.
- Frontend loads PNG/audio/map/UI only through `/assets/...`.
- The full map source image remains at `/assets/images/Items/game_map_full.png`, but the client must render the prepared map tiles from `/assets/images/MapTiles/` instead of loading the full map as a single Phaser texture.
- `config/map_tiles.json` stores tile metadata. Tile `path` values are relative to `/assets/images/`; for example `MapTiles/map_tile_0_0.png` resolves to `/assets/images/MapTiles/map_tile_0_0.png`.
- Backend and frontend store/use logical asset ids, not file blobs or hardcoded gameplay references to raw filenames.
- `config/assets.json` is the single asset manifest for logical id -> `/assets/...` path resolution.
- `config/characters.json` is the single source for selectable character ids, direction/state asset mappings, scale, anchor, and collision radius. Current MVP character assets are split PNG files, not uniform 64-frame sprite sheets.
- FastAPI must not implement a static files endpoint.

## Suggested Module Boundaries

### Backend Services

- `PlayerService`: create, load, save players.
- `WorldService`: online players, movement validation, broadcast.
- `QuestService`: quest offer, global quest lock acquire/release, quest accept, quest item instances, completion, failure, cooldown.
- `QuestExpiryWorker`: asyncio background task or equivalent scheduler that scans every 30 seconds for expired active quests and applies the authoritative failure transition.
- `InventoryService`: inventory, equipment, reward items.
- `ShopService`: Potion purchase.
- `ProgressionService`: L3 condition checks and level-up.
- `ConfigService`: JSON config loading and validation.
- `LogService`: app logs, error logs, player behavior logs.

### Frontend Systems

- Boot/Preload: critical asset and config loading.
- Login/CharacterSelect: player id/name and MVP character selection.
- GameScene: Phaser rendering, world background, player/NPC/item sprites.
- UIScene or UI layer: HUD, dialogs, shop, inventory, reconnect overlay.
- Network client: REST bootstrap + WebSocket auto reconnect. Bootstrap config must succeed before `GameScene` is created or the gameplay WebSocket is opened.
- Game state: local state snapshot and server message application.

## REST API Contracts

### GET /health

Response:

```json
{ "status": "ok" }
```

### GET /ready

Response:

```json
{ "status": "ready", "database": "ok", "config": "ok", "websocket": "ok" }
```

### POST /api/v1/players

Request:

```json
{ "name": "Kitty", "character_id": "arctic_fox" }
```

For name lookup before character selection, the frontend may call:

```json
{ "name": "Kitty" }
```

Rules:

- Player enters name only; the backend creates and owns the internal `player_id`.
- Normalize name by trimming surrounding whitespace and comparing case-insensitively.
- If `normalized_name` does not exist and `character_id` is present and enabled in `config/characters.json`, create a new player and generate a unique `player_id`.
- If `normalized_name` exists, load the existing player.
- For an existing player, ignore incoming `character_id` and return the stored profile.
- If `character_id` is missing for a new player, return HTTP 409 with code `character_required`; no player row is created yet.
- If `character_id` is not present in `config/characters.json` or `enabled_in_mvp` is false, return HTTP 400 with code `invalid_character_id`; no player row is created.

Response:

```json
{
  "player": {
    "id": "generated-player-id",
    "name": "Kitty",
    "normalized_name": "kitty",
    "character_id": "arctic_fox",
    "x": 2715,
    "y": 3620,
    "direction": "down",
    "level": 0,
    "coins": 25
  }
}
```

### GET /api/v1/players/{player_id}

Returns the same durable snapshot shape used in `state_sync`, excluding remote online players.

This endpoint is internal/dev-facing in MVP. Normal player login must use `POST /api/v1/players` with name only.

### GET /api/v1/config/bootstrap

Returns the full validated content of map, map tile, NPC, quest, item, shop, character, preset phrase, progression, and asset configs.

Response shape:

```json
{
  "map": {},
  "map_tiles": {},
  "npcs": [],
  "quests": [],
  "items": [],
  "shop": {},
  "characters": [],
  "preset_phrases": [],
  "progression": {},
  "assets": {}
}
```

Each top-level key is required. Values are the validated parsed contents of the matching config file, not raw file paths or stringified JSON.

### GET /api/v1/logs/client-config

Response:

```json
{ "enabled": true, "sample_rate": 1.0, "endpoint": "/api/v1/client-events" }
```

### POST /api/v1/client-events

Accepts client diagnostics and behavior events. Server must validate size and event type, then write to player behavior logs or `player_events`.

## Frontend Interaction Defaults

- Keyboard movement: arrow keys and WASD.
- Touch movement: on-screen virtual joystick in the lower-left corner.
- Primary interaction: keyboard `E`, gamepad/touch action button, or tapping an interact prompt.
- Shop button: always visible in HUD after login.
- Inventory button: always visible in HUD after login.
- Quest timer: visible at top center only while a quest is active.
- Reconnect overlay: blocks gameplay input until `state_sync` is received.
- Bootstrap failure overlay: full-screen blocking overlay with the message "Configuration failed to load. Please retry or refresh the page." The frontend may retry automatically at most 3 times with a 5-second interval, must include a "Retry" button for manual retry, and must not create `GameScene` or open the gameplay WebSocket until bootstrap succeeds.
- If an NPC interaction returns `quest_already_active`, the UI shows "You already have an active quest." and does not show a `quest_offer`.
- Login screen must tell players that the same name loads the same local save and matching is case-insensitive.
- Login screen must also warn that two people using the same name on the same local deployment will share the same save. MVP is local/family-network only; PIN or formal account authentication is V2+.

## Persistence And Transaction Rules

- SQLite runs with WAL, foreign keys, and `busy_timeout=5000`.
- Use short transactions and keep long-running timers, broadcasts, and asset work outside database transactions.
- Gameplay writes that can race, including quest accept, quest turn-in, shop purchase, Potion use, and level-up, must be atomic.
- The quest expiry scanner must use the same serialized write path or single-writer queue as other gameplay mutations. It processes only active quests whose `expires_at` is at or before server UTC now, marks them failed, writes failure cooldown, expires world item instances, and deletes the quest lock inside a short transaction. Any `quest_failed` WebSocket sends happen after the transaction commits.
- `quest_turn_in` must check quest active status, lock ownership, expiry, collected requirements, and prior reward state in the same transaction that grants rewards, sets cooldown, expires item instances, and releases the quest lock.
- Repeated `quest_turn_in` for a completed quest must not require an active quest lock. The server recognizes the idempotent case from `player_quests.status = 'completed'` and persisted `rewards_granted_json`, then returns the same `quest_completed` snapshot without granting rewards again.
- Shop purchase and Potion use must update coins/inventory/progression atomically and return the post-commit snapshot or balance.
- Reward-granting paths persist `rewards_granted_json` so retries and reconnects cannot duplicate quest rewards.
- A single-writer queue or equivalent serialized write path is recommended for SQLite gameplay mutations when concurrent local clients are active.

## MVP Defaults

- Map source image: `/assets/images/Items/game_map_full.png`
- Map tile manifest: `config/map_tiles.json`
- Map tile directory: `/assets/images/MapTiles/`
- Map tile grid: `6 x 8`, 48 images, default tile size `1024 x 1024`; right edge tiles are `310px` wide and bottom edge tiles are `72px` high.
- Map size: `5430 x 7240`
- Spawn: `{ "x": 2715, "y": 3620 }`
- NPC interaction radius: `160px`
- Item pickup radius: `96px`
- Walk speed: `180px/s`
- World bounds: full map rectangle.
- Collision: map bounds only; no tile collision.
- MVP exploration: players may tour the full map, but only Spawn-area NPCs/items and global UI controls are interactive.
- MVP Portal behavior: all Portal objects are non-interactive scenery. No hotspot, placeholder modal, scene transition, or portal-enter log is implemented in MVP.
- L3 unlock: persist `playground` in `unlocked_regions` and show a level-up notification only; do not implement Playground gameplay in MVP.
