# Animal Adventure L3 MVP Consolidated Build Plan

All programming tasks that write code must follow TDD: write the test case, implement, then perform the test. Implementation phases are split by language so the harness can choose the correct builder, reviewer, and verification commands.

## Phase 1 — Project Setup And Dependency Bootstrap [python]
**Ref:** `docs/requirements.md`, `docs/architecture.md`, `docs/logging-and-ops.md`

1. Write scaffold validation tests in `tests/test_project_scaffold.py`.
   - Required paths: `app/`, `src/`, `tests/`, `config/`, `docs/`, `deploy/nginx/`, `deploy/scripts/`, `data/`, `logs/`.
   - Empty scaffold directories must contain `.gitkeep`.
2. Write dependency checker tests in `tests/test_dependency_checker.py`.
   - Cases: Python, Node, npm, Nginx, SQLite module, Playwright Chromium, and Playwright WebKit found/missing.
   - Implement `deploy/scripts/check-deps.ps1`; optional cross-platform equivalent `deploy/scripts/check-deps.sh`.
3. Write Python import smoke test in `tests/test_python_dependencies.py`.
   - Ensure `requirements.txt` includes `fastapi`, `uvicorn[standard]`, `aiosqlite`, `pytest`, `pytest-asyncio`, `httpx`, `websockets`.
4. Write Nginx config syntax test in `tests/test_nginx_config.py`.
   - Implement `deploy/nginx/animal-adventure.nginx.conf.template` with `{{PROJECT_ROOT}}` placeholders and generate `deploy/nginx/animal-adventure.nginx.conf`.
   - Use port `8080` by default.
   - Use a generated `alias <project-root>/assets/;` for `/assets/`.
   - Proxy `/api/`, `/health`, `/ready`, and `/ws/` to FastAPI.
5. Write Nginx configuration script tests in `tests/test_configure_nginx.py`.
   - Implement `deploy/scripts/configure-nginx.ps1 -ProjectRoot <path>` to replace `{{PROJECT_ROOT}}` with a normalized slash path and write the generated config.
6. Write backend environment config tests in `tests/test_settings.py`.
   - Implement `.env.example` and `app/settings.py`.

## Phase 2 — Frontend Tooling And Browser Bootstrap [typescript]
**Ref:** `docs/requirements.md`, `docs/architecture.md`, `docs/test-plan.md`

1. Write Node package smoke test in `tests/node/package-config.test.ts`.
   - Update root `package.json` scripts and dependencies for Phaser, Vite, TypeScript, Vitest, Playwright, ESLint, and Prettier.
   - Pass criteria: `npm install`, `npm run typecheck`, and `npx vitest --version` succeed.
2. Write Playwright browser smoke test in `tests/e2e/browser-launch.spec.ts`.
   - Preflight Chromium availability; do not install browsers inside the harness run.
   - Preflight WebKit availability; missing WebKit is reported as a preflight failure (covers `browser_launches_webkit_ipad`).
   - Configure `playwright.config.ts` projects array with two entries: `{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }` and `{ name: 'webkit-ipad', use: { ...devices['iPad Pro 11'] } }`. Existing tests continue to run on `chromium`; new WebKit tests target `webkit-ipad`.
3. Write client environment config test in `tests/node/client-config.test.ts`.
   - Implement `src/config/clientConfig.ts` defaults for API URL, WS URL, and asset base path.
   - Cover `http://` origins mapping to `ws://`, `https://` origins mapping to `wss://`, and explicit `VITE_WS_URL` override.

## Phase 3 — Asset Manifest And Static Asset Validation [python]
**Ref:** `docs/requirements.md`, `docs/data-model.md`, `docs/architecture.md`

1. Write static asset manifest validation in `tests/test_asset_paths.py`.
   - Implement MVP static asset references in `config/assets.json`.
   - Every MVP asset path maps to an existing file under `assets/`.
2. Write map tile manifest validation in `tests/test_map_tiles.py`.
   - Validate `config/map_tiles.json` records and image dimensions under `assets/images/MapTiles/`.
   - Validate tile coordinates stay within `map_width`/`map_height`, cover the full map without gaps or overlap, and use MVP edge dimensions of `310px` for the last column and `72px` for the last row.
3. Write character config validation in `tests/test_character_config.py`.
   - Validate character direction/state mappings, scale, anchor, and collision radius.

## Phase 4 — Backend Foundation [python]
**Ref:** `docs/requirements.md`, `docs/architecture.md`, `docs/data-model.md`, `docs/logging-and-ops.md`

1. Write health endpoint tests in `tests/test_health_ready.py`.
   - Implement `app/main.py`.
   - `GET /health` returns `{ "status": "ok" }`.
   - `GET /ready` returns database/config/websocket readiness.
2. Write SQLite initialization tests in `tests/test_db.py`.
   - Implement `app/db.py` and `app/schema.sql`.
   - Required tables: `players`, `player_progress`, `player_inventory`, `player_quests`, `quest_locks`, `world_item_instances`, `player_events`.
   - Required pragmas: WAL, foreign keys, `busy_timeout=5000`.
   - `quest_locks.quest_instance_id` uses `ON DELETE CASCADE`, and startup recovery cleans orphan lock rows left by legacy/corrupt data.
3. Write config loader tests in `tests/test_config_service.py`.
   - Implement `app/services/config_service.py`.
   - Validate gameplay config files, logical asset id references, and the required bootstrap response shape.
4. Write structured logging tests in `tests/test_logging.py`.
   - Implement `app/logging_config.py`.

## Phase 5 — Frontend Foundation [typescript]
**Ref:** `docs/requirements.md`, `docs/architecture.md`, `docs/test-plan.md`

1. Write frontend config tests in `tests/node/client-config.test.ts`.
   - REST and WS URLs derive from `window.location.origin` unless explicit env vars exist; `http://` maps to `ws://`, `https://` maps to `wss://`, and unsupported protocols block connection.
2. Write protocol type tests in `tests/node/protocol.test.ts`.
   - Implement `src/net/protocol.ts`.
3. Write Phaser boot test in `tests/node/phaser-boot.test.ts`.
   - Implement `index.html`, `src/main.ts`, `src/scenes/BootScene.ts`, `src/scenes/PreloadScene.ts`.
4. Write responsive layout tests in `tests/node/responsive.test.ts`.
   - Canvas dimensions fit viewport and camera zoom remains within min/max.
5. Write asset loader tests in `tests/node/assets.test.ts`.
   - Client requests only `/assets/...` paths.
   - MVP map rendering loads `config/map_tiles.json` and `/assets/images/MapTiles/...`.
   - Client must not load `/assets/images/Items/game_map_full.png` as a single Phaser texture.
6. Write input and HUD state tests in `tests/node/input-ui.test.ts`.
   - Implement WASD, arrows, touch joystick, interact, shop, inventory, reconnect overlay state.
7. Write `@phase5-smoke` Playwright quick smoke for app boot, nonblank canvas, and asset 404 checks.

## Phase 6 — Player Session And Persistence Backend [python]
**Ref:** `docs/requirements.md`, `docs/data-model.md`, `docs/workflows.md`

1. Write player service tests in `tests/test_player_service.py`.
   - Create/load by name, case-insensitive load, trim whitespace, generated unique `player_id`, missing name, missing character for new player, and invalid or disabled `character_id`.
2. Write player REST tests in `tests/test_player_routes.py`.
   - Implement `app/routes/players.py`.
   - `POST /api/v1/players` accepts `{ "name": "..." }` for lookup and `{ "name": "...", "character_id": "..." }` for creation.
   - Invalid or disabled `character_id` returns HTTP 400 with code `invalid_character_id`.
   - `GET /api/v1/players/{player_id}` returns durable snapshot.
3. Write persistence tests in `tests/test_persistence.py`.
   - Position, coins, level, inventory, quest state, and unlocks survive reload.
   - Position is persisted immediately after quest accept, quest complete, quest fail, shop buy, Potion use, level-up, and WebSocket disconnect.

## Phase 7 — Player Login Frontend [typescript]
**Ref:** `docs/requirements.md`, `docs/workflows.md`, `docs/data-model.md`

1. Write frontend login tests in `tests/node/login.test.ts`.
   - Implement `src/scenes/LoginScene.ts`, `src/state/SessionState.ts`, and `src/net/ApiClient.ts`.
   - UI asks for name only.
   - Same name loads same local save case-insensitively.
   - New player includes character selection; returning player skips reselection.

## Phase 8 — Player Session Integration [integration]
**Ref:** `docs/requirements.md`, `docs/workflows.md`, `docs/data-model.md`

1. Verify browser login creates a backend player and stores a durable snapshot.
2. Verify returning login by different name casing loads the same player.
3. Verify reload restores player session state.
4. Write `@phase8-smoke` Playwright quick smoke for name login and reload restore.

## Phase 9 — WebSocket Multiplayer Backend [python]
**Ref:** `docs/requirements.md`, `docs/websocket-protocol.md`, `docs/data-model.md`

1. Write WebSocket connection tests in `tests/test_ws_connection.py`.
   - Implement `app/ws_handler.py`.
   - `/ws/{player_id}` sends `state_sync`; unknown player returns protocol `error` then closes.
2. Write world state tests in `tests/test_world_service.py`.
   - In-bounds movement, out-of-bounds rejection, direction update, in-memory online position, 10Hz snapshot, 30-second position save throttle, and server-side movement rate-limit defense.
3. Write WebSocket identity tests in `tests/test_ws_identity.py`.
   - Server uses `/ws/{player_id}` as connection identity and rejects impersonation.
4. Write duplicate session tests in `tests/test_ws_duplicate_session.py`.
   - A new connection for an existing `player_id` sends an `error` message with code `duplicate_session` to the old connection, closes it, and receives `state_sync` on the new connection.

## Phase 10 — WebSocket Multiplayer Frontend [typescript]
**Ref:** `docs/requirements.md`, `docs/websocket-protocol.md`, `docs/workflows.md`

1. Write frontend WebSocket client tests in `tests/node/ws-client.test.ts`.
   - Connect, state sync, send movement, 20Hz movement throttle, reconnect backoff, 120-second reconnect timeout UI, and duplicate reconnect protection.
2. Write bootstrap failure tests in `tests/node/bootstrap.test.ts`.
   - Failed `GET /api/v1/config/bootstrap` shows a blocking error and prevents `GameScene` creation and gameplay WebSocket connection.
   - Successful bootstrap validates required top-level keys before starting gameplay.
3. Write player rendering tests in `tests/node/game-state.test.ts`.
   - Implement `src/state/GameState.ts`, `src/entities/Player.ts`.
   - Local and remote snapshots apply correctly.
4. Write preset chat UI tests in `tests/node/preset-chat.test.ts`.
   - Implement `src/ui/PresetChatPanel.ts`.

## Phase 11 — WebSocket Multiplayer Integration [integration]
**Ref:** `docs/requirements.md`, `docs/websocket-protocol.md`, `docs/workflows.md`

1. Write multiplayer integration test in `tests/test_ws_multiplayer.py`.
   - Two clients receive each other's position updates and `player_left`.
2. Verify forced WebSocket disconnect reconnects and receives `state_sync`.
3. Write touch-joystick WebKit E2E test in `tests/e2e/touch-joystick.spec.ts` targeting the `webkit-ipad` project.
   - Simulate `touchstart` and `touchmove` events on the virtual joystick; assert player character position changes (covers `e2e_touch_joystick_moves_player`).
4. Write WebKit WebSocket reconnect E2E test in `tests/e2e/safari-ws-reconnect.spec.ts` targeting the `webkit-ipad` project.
   - Force WebSocket disconnect, wait for auto-reconnect, verify `state_sync` restores session state (covers `e2e_safari_ws_reconnect`).
5. Write `@phase11-smoke` Playwright quick smoke for reconnect and `state_sync`; include webkit-ipad project runs for touch-joystick and WebKit reconnect smoke tests.

## Phase 12 — Quest, Inventory, Shop, And L3 Backend [python]
**Ref:** `docs/requirements.md`, `docs/data-model.md`, `docs/workflows.md`

1. Write quest config tests in `tests/test_quest_config.py`.
   - Hopper, Copper, and Elisa configs validate; item coordinates are near Spawn; no MVP quest item is in V2-only interaction areas.
2. Write quest service tests in `tests/test_quest_service.py`.
   - Offer, accept, global lock, timer kickoff, UTC expiry, item spawn, pickup, turn-in, cooldowns, idempotent `quest_completed` replay, unique completed quest tracking, active-quest conflict returning `quest_already_active`, `inventory_full` pickup behavior, and server-authoritative NPC/item radius checks.
3. Write quest expiry scanner tests in `tests/test_quest_expiry_scanner.py`.
   - Implement `QuestExpiryWorker` or equivalent scheduler. Every 30 seconds it fails expired active quests, writes failure cooldown, expires item instances, releases locks, preserves existing terminal states, and sends notifications only after commit.
   - Cover backend startup scan failing quests that expired before restart, orphan lock cleanup, and concurrent expiry scan plus turn-in/pickup through the serialized write path.
4. Write inventory tests in `tests/test_inventory_service.py`.
   - Inventory cap, Potion stack/use, accessory equipment.
5. Write shop tests in `tests/test_shop_service.py`.
   - Potion purchase, insufficient funds, invalid/locked item, concurrent serialization.
6. Write progression tests in `tests/test_progression_service.py`.
   - `unique_completed_quest_ids >= 2` plus 2 used Potions reaches L3 exactly once.
7. Write backend preset phrase validation tests in `tests/test_preset_chat.py`.

## Phase 13 — Quest, Inventory, Shop, And L3 Frontend [typescript]
**Ref:** `docs/requirements.md`, `docs/data-model.md`, `docs/workflows.md`

1. Write frontend quest UI tests in `tests/node/quest-ui.test.ts`.
   - Implement `src/entities/NPC.ts`, `src/entities/WorldItem.ts`, `src/ui/QuestPanel.ts`.
   - `quest_already_active` displays "You already have an active quest." and does not display a `quest_offer`.
2. Write frontend shop/inventory tests in `tests/node/shop-inventory.test.ts`.
   - Implement `src/ui/ShopPanel.ts`, `src/ui/InventoryPanel.ts`.
3. Verify Potion purchase/use flow updates UI from server messages.

## Phase 14 — Quest And L3 End-To-End Acceptance [e2e]
**Ref:** `docs/requirements.md`, `docs/data-model.md`, `docs/workflows.md`, `docs/test-plan.md`

1. Verify a new player accepts a quest, picks up the item, turns it in, receives rewards, buys and uses Potion, and reaches L3.
2. Verify quest timers and cooldowns recover from reconnect using server `state_sync`.
3. Verify quests that expire during disconnect are failed by the scanner and restored with `cooldown_until` on reconnect.
4. Verify `quest_turn_in` retries after network interruption do not duplicate rewards, including the case where reconnect `state_sync` shows the quest already completed before the client replays pending turn-in.
5. Verify reload and backend restart preserve quest and progression state.
6. Write `@phase14-smoke` Playwright quick smoke for the MVP L3 loop.

## Phase 15 — Logs, Ops, Cleanup, And Local Deployment [python]
**Ref:** `docs/requirements.md`, `docs/logging-and-ops.md`

1. Write lifecycle log tests in `tests/test_lifecycle_logs.py`.
   - Startup, ready, and shutdown logs include required fields.
2. Write functional path log tests in `tests/test_gameplay_logs.py`.
   - Quest completion, quest expiry scanner auto-fail, duplicate session, movement rate limit, bootstrap failure, shop purchase, reconnect, and reconnect timeout emit diagnostic events.
3. Write client event tests in `tests/test_client_events.py`.
   - Accept bounded JSON events, reject oversized payloads.
4. Write cleanup tests in `tests/test_cleanup.py`.
   - Dry-run old logs/player events and preserve recent data.
5. Write watchdog script tests in `tests/test_watchdog_script.py`.
   - Starts uvicorn if missing and avoids duplicates.
6. Write Windows 10 deployment guide in `docs/local-windows-deployment.md`.
   - Include Nginx install, config path, port 8080, firewall note, restart commands, and risks.

