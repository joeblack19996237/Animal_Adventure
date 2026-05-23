# Animal Adventure L3 MVP Test Plan

This plan mirrors `docs/build-plan.md` so the harness can inject phase-specific tests with the matching implementation phase.

## Verification Plan

The MVP is verified through backend unit/integration tests, frontend Vitest tests,
Playwright browser E2E, and final Nginx-served acceptance checks.

## Input And Responsive Controls

Keyboard, touch, interaction, shop, inventory, and reconnect controls must remain
usable across laptop, tablet, and small browser viewports.

## Phase 1 Tests — Project Setup And Dependency Bootstrap

- `test_project_scaffold_required_dirs`: setup creates `app/`, `src/`, `tests/`, `config/`, `deploy/nginx/`, `deploy/scripts/`, `data/`, `logs/`.
- `test_check_deps_reports_required_tools`: dependency checker reports Python, Node, npm, Nginx, SQLite, Playwright Chromium, and Playwright WebKit.
- `test_python_dependencies_import`: FastAPI, uvicorn, aiosqlite, httpx, and websockets import successfully.
- `test_nginx_config_contains_required_routes`: Nginx config serves `/`, `/assets/`, `/api/`, `/health`, `/ready`, `/ws/`.
- `test_configure_nginx_generates_project_paths`: Nginx config generation replaces `{{PROJECT_ROOT}}` with the provided project path and preserves required routes.
- `test_backend_settings_defaults`: API, SQLite, and log paths resolve from defaults.

## Phase 2 Tests — Frontend Tooling And Browser Bootstrap

- `package_config_has_root_scripts`: root `package.json` exposes `typecheck`, `test`, `build`, and `test:e2e`.
- `tooling_config_files_exist`: `tsconfig.json`, `vite.config.ts`, `playwright.config.ts`, ESLint config, and Prettier config exist.
- `client_config_defaults`: REST, WS, and asset base path derive from browser origin.
- `client_config_https_ws_url`: HTTPS origins derive `wss://` WebSocket URLs, HTTP origins derive `ws://`, and explicit `VITE_WS_URL` wins.
- `browser_launches_chromium`: Playwright Chromium opens a blank page if already installed; missing Chromium is reported as a preflight failure.
- `browser_launches_webkit_ipad`: Playwright WebKit-iPad project opens a blank page if already installed; missing WebKit is reported as a preflight failure.

## Phase 3 Tests — Asset Manifest And Static Asset Validation

- `test_asset_manifest_paths_exist`: every MVP logical asset path maps to an existing file under `assets/`.
- `test_map_tiles_manifest_matches_files`: `config/map_tiles.json` covers prepared map tiles under `assets/images/MapTiles/`.
- `test_map_tiles_coordinate_coverage`: tile coordinates stay within the map, cover `0..5430` by `0..7240` without gaps or overlap, and use MVP edge dimensions of `310px` by `72px`.
- `foreground tile asset contract`: every `config/foreground_tiles.json` entry references an existing base map tile, points at an existing PNG under `assets/images/ForegroundTiles/`, matches the base tile dimensions, has an alpha channel, and remains mostly transparent.
- `test_character_config_mappings`: character direction/state mappings, scale, anchor, and collision radius validate.

## Phase 4 Tests — Backend Foundation

- `test_health_ready`: `/health` and `/ready` return HTTP 200 with expected JSON.
- `test_db_schema_and_pragmas`: required tables, SQLite pragmas, and `quest_locks.quest_instance_id ON DELETE CASCADE` exist.
- `test_startup_cleans_orphan_quest_locks`: startup recovery deletes orphan lock rows left by legacy/corrupt data.
- `test_config_service_validates_gameplay_config`: invalid gameplay configs raise actionable errors.
- `test_bootstrap_config_shape`: bootstrap config exposes required top-level keys for map, map tiles, NPCs, quests, items, shop, characters, preset phrases, progression, and assets.
- `test_structured_logging_fields`: log records include required fields and rotate by policy.

## Phase 5 Tests — Frontend Foundation

- `client_config_origin_8080`, `client_config_origin_80`, and `client_config_https`: API/WS URLs derive from `window.location.origin`, mapping HTTP to WS and HTTPS to WSS.
- `protocol_type_guards`: REST/WS message guards reject malformed messages.
- `phaser_boot_has_required_scenes`: Boot, Preload, Game, and UI scenes are registered.
- `responsive_canvas_fits_viewport`: laptop, iPad, and small browser dimensions fit.
- `asset_manifest_uses_map_tiles`: map rendering resolves `/assets/images/MapTiles/...` and does not request `/assets/images/Items/game_map_full.png` as a single texture.
- `asset_manifest_uses_map_tiles`: foreground tile load entries resolve `/assets/images/ForegroundTiles/...`, use `foreground_` texture keys, and support sparse manifests without requiring all 48 map tiles.
- `game_scene_movement_structure`: `GameScene` preloads initial foreground tiles and passes the foreground manifest to `MapTileRenderer`.
- `visual_asset_integration`: Phaser uses pixel-friendly map compositing settings: `pixelArt`, `roundPixels`, and `antialias: false`.
- `input_ui_state`: keyboard, touch, interact, shop, inventory, and reconnect state are testable without a live Phaser canvas.
- `@phase5-smoke`: Vite-served app loads, canvas is nonblank, and core assets do not 404.

## Phase 6 Tests — Player Session And Persistence Backend

- `test_player_service_create_and_load`: create/load by name, trim whitespace, and case-insensitive lookup.
- `test_player_routes`: create/load/error HTTP statuses and schemas, including HTTP 400 `invalid_character_id` for invalid or disabled new-player characters.
- `test_persistence`: position, coins, level, inventory, quest state, and unlocks survive reload.
- `test_position_immediate_save_events`: quest accept, quest complete, quest fail, shop buy, Potion use, level-up, and WebSocket disconnect persist the latest position.

## Phase 7 Tests — Player Login Frontend

- `login_name_only`: UI asks for name only.
- `login_new_player_character_select`: new player selects an MVP character.
- `login_returning_player_skips_character_select`: same name with different casing loads the existing player.

## Phase 8 Tests — Player Session Integration

- `e2e_name_login_creates_player`: browser login creates backend player.
- `e2e_return_login_case_insensitive`: returning login with different casing loads the same player.
- `e2e_reload_restores_session`: reload restores player snapshot.
- `@phase8-smoke`: name login creates/loads a player and reload restores session state.

## Phase 9 Tests — WebSocket Multiplayer Backend

- `test_ws_connect_sends_state_sync`: `/ws/{player_id}` sends `state_sync`.
- `test_ws_unknown_player_errors`: unknown player receives protocol error then close.
- `test_world_service_movement_bounds`: in-bounds accepted and out-of-bounds rejected.
- `test_world_service_snapshot_throttle`: movement broadcasts are minimal and persistence is throttled.
- `test_world_service_movement_rate_limit`: over-frequency movement is rejected or safely dropped without per-message SQLite writes.
- `test_ws_identity`: connection path identity rejects impersonation.
- `test_ws_duplicate_session_replaces_old_connection`: a second connection for the same `player_id` sends an `error` message with code `duplicate_session` to the old connection, closes it, and receives `state_sync` on the new connection.

## Phase 10 Tests — WebSocket Multiplayer Frontend

- `ws_client_connect_state_sync`: client handles `state_sync`.
- `ws_client_reconnect_restores_state`: reconnect ends with `state_sync`.
- `ws_client_reconnect_timeout`: reconnect backoff stops after 120 seconds and shows "Server is temporarily unavailable. Please refresh the page."
- `ws_client_no_duplicate_reconnects`: repeated close events do not create duplicate sockets.
- `ws_client_movement_throttle_20hz`: outbound `player_move` messages are capped at 20Hz.
- `bootstrap_failure_blocks_game_start`: failed bootstrap config shows the blocking error overlay, exercises automatic/manual retry behavior, and does not open the gameplay WebSocket.
- `bootstrap_success_requires_schema`: successful bootstrap must include all required top-level config keys before gameplay starts.
- `game_state_remote_players`: local and remote snapshots render correctly.
- `preset_chat_ui`: configured phrases render and send by id.

## Phase 11 Tests — WebSocket Multiplayer Integration

- `test_two_clients_receive_movement`: two clients receive each other's `state_update`.
- `test_player_left_broadcast`: remaining clients receive `player_left`.
- `e2e_ws_reconnect_recovery`: forced disconnect reconnects and restores `state_sync`.
- `e2e_touch_joystick_moves_player`: simulate touch events on webkit-ipad project; assert player character position changes, verifying virtual joystick `touchstart`/`touchmove` events work in WebKit engine.
- `e2e_safari_ws_reconnect`: on webkit-ipad project, force WebSocket disconnect, wait for auto-reconnect, and verify `state_sync` restores session state.
- `@phase11-smoke`: browser reconnect receives `state_sync` without console errors; webkit-ipad project also runs touch-joystick and WebKit reconnect smoke tests.

## Phase 12 Tests — Quest, Inventory, Shop, And L3 Backend

- `test_quest_config`: Hopper, Copper, Elisa, quest items, and Spawn placement validate.
- `test_quest_service`: accept, lock, expiry, pickup, turn-in, cooldown, active-quest conflict, inventory-full pickup, server-authoritative radius checks, and idempotent rewards.
- `test_quest_turn_in_replay_returns_completed`: repeated turn-in after completed state returns `quest_completed` with persisted `rewards_granted_json` and no duplicate rewards, even without an active lock.
- `test_quest_expiry_scanner`: expired active quests are automatically failed, cooldown is written, world items are expired, locks are released, and existing terminal states are not overwritten.
- `test_quest_expiry_startup_scan`: backend startup scan fails quests that expired before restart and cleans orphan locks.
- `test_quest_expiry_concurrent_turn_in`: concurrent scanner and turn-in/pickup leaves exactly one terminal state and no duplicate rewards.
- `test_inventory_service`: cap, Potion stack/use, accessory equipment.
- `test_shop_service`: purchase success, insufficient funds, invalid/locked item, concurrency.
- `test_progression_service`: two unique completed quests plus two used Potions reaches L3 exactly once.
- `test_preset_chat`: only configured phrase ids can be sent.

## Phase 13 Tests — Quest, Inventory, Shop, And L3 Frontend

- `quest_ui_flow`: NPC prompt, dialog, countdown, item marker, completion/failure notification.
- `quest_already_active_ui`: `quest_already_active` shows "You already have an active quest." and does not render a quest offer.
- `shop_inventory_ui`: Potion purchase/use updates UI from server messages.
- `preset_chat_rendering`: received preset chat messages render for nearby/online players.

## Phase 14 Tests — Quest And L3 End-To-End Acceptance

- `e2e_new_player_reaches_l3`: new player completes MVP loop and reaches L3.
- `e2e_quest_reconnect_restores_timers`: reconnect restores active quest timers and world items.
- `e2e_quest_expires_while_disconnected`: if a quest expires during disconnect, reconnect receives failed quest state with `cooldown_until`.
- `e2e_quest_turn_in_retry_idempotent`: a turn-in retried after a network interruption does not duplicate rewards, and reconnect `state_sync` cancels pending replay when it already shows completed state.
- `e2e_backend_restart_preserves_progression`: backend restart preserves quest/progression state.
- `@phase14-smoke`: new player can complete the short MVP L3 loop.

## Phase 15 Tests — Logs, Ops, Cleanup, And Local Deployment

- `test_lifecycle_logs`: startup, ready, and shutdown logs include required fields.
- `test_gameplay_logs`: quest completion, quest expiry scanner auto-fail, duplicate session, movement rate limit, bootstrap failure, shop purchase, reconnect, and reconnect timeout emit diagnostic events.
- `test_client_events`: bounded payload accepted and oversized payload rejected.
- `test_cleanup`: dry-run reports deletions without deleting recent data.
- `test_watchdog_script`: watchdog starts uvicorn when missing and avoids duplicates.
- `test_deployment_guide`: Windows/Nginx guide includes commands and risks.

## Phase 16 Tests — Final Browser Acceptance

- `e2e_app_loads_through_nginx`: app loads from `http://localhost:8080/`.
- `e2e_canvas_visible_nonblank`: Phaser canvas visible and screenshot pixels non-empty.
- `e2e_assets_no_404`: JS/CSS/assets load without 404 or MIME errors.
- `e2e_nginx_routing`: frontend/assets/API/ws routing is split correctly.
- `e2e_full_mvp_loop`: name login, movement, quest, shop, Potion use, and L3 progression work.
- `e2e_duplicate_session_single_active_connection`: a second browser using the same player replaces the old WebSocket connection and does not leave two active sessions.
- `e2e_no_console_or_backend_errors`: no critical browser console/page errors or backend tracebacks.
- `@phase16-smoke`: Nginx-served browser acceptance covers assets, API/ws routing, login, reconnect, duplicate session, and L3; webkit-ipad project also runs touch-joystick and WebKit reconnect smoke tests.
- `soak_30_min`: 30-minute smoke runs only when `HARNESS_SOAK=1`.

## Phase 16 — Final Browser Acceptance [e2e]
**Ref:** `docs/requirements.md`, `docs/architecture.md`, `docs/data-model.md`, `docs/websocket-protocol.md`, `docs/workflows.md`, `docs/logging-and-ops.md`, `docs/test-plan.md`

1. Run full pytest suite.
2. Run full Vitest suite.
3. Run Playwright E2E through Nginx URL.
4. Verify Nginx serves frontend and assets.
5. Verify FastAPI does not serve static assets.
6. Verify browser-only access.
7. Verify name-only player creation and case-insensitive return login.
8. Verify new player can reach L3.
9. Verify reload restores state.
10. Verify WebSocket reconnect restores progress.
11. Verify a second browser using the same player replaces the old WebSocket connection via `duplicate_session`.
12. Verify backend process restart restores SQLite state.
13. Verify logs rotate and cleanup dry-run works.
14. Verify no critical console errors or backend tracebacks during 30-minute smoke test.
15. Write `@phase16-smoke` Playwright quick smoke for Nginx routing, assets, login, reconnect, duplicate session, and L3. Run the 30-minute soak only when `HARNESS_SOAK=1`.
