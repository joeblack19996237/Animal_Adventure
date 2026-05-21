# Animal Adventure Code Review Report

Review of `D:\Animal_Adventure` (excluding `harness/`), checked against Python review standards (`.claude/rules/python/python-review-standards.md`) and TypeScript review standards (`.claude/rules/typescript/typescript-review-standards.md`). Reviewed across 4 dimensions: Functionality → Security → Performance → Design/Quality.

---

## 1 [CRITICAL] — Functionality
**File:** [app/ws_handler.py](app/ws_handler.py):296-332
**Issue:** WebSocket message handler only dispatches `player_move` and `preset_chat`. Does **not** handle `npc_interact_request`, `quest_accept`, `item_pickup_request`, `quest_turn_in`, `shop_buy`, or `use_item` — all of which the frontend [GameScene.ts](src/scenes/GameScene.ts) sends. The `QuestService`, `ShopService`, `InventoryService`, and `ProgressionService` are fully implemented and tested, but **none are wired to the WebSocket handler**. The `ws_handler.py` imports only `is_in_world_bounds` from `world_service` — it imports none of the gameplay services.
**Fix:** Add message dispatch in `_handle_messages()` for each gameplay message type, calling the corresponding service method. Wire `QuestService`, `ShopService`, `InventoryService`, and `ProgressionService` into the WebSocket endpoint. Each handler must validate connection identity, then call the service and send the response back over the WebSocket.

---

## 2 [CRITICAL] — Functionality
**File:** [app/routes/players.py](app/routes/players.py):49
**Issue:** `POST /api/v1/players` returns HTTP 200 with `{"status": "character_required"}` when `character_id` is missing for a new player. The spec ([architecture.md](docs/architecture.md):128) requires **HTTP 409** with `code: "character_required"`.
**Fix:** Change to `raise HTTPException(status_code=409, detail=...)` or return `JSONResponse(status_code=409, content={"code": "character_required", ...})`.

---

## 3 [CRITICAL] — Functionality
**File:** [src/scenes/GameScene.ts](src/scenes/GameScene.ts):925-943
**Issue:** `update()` only handles joystick movement. Keyboard movement (WASD / arrow keys) is required by the spec ([architecture.md](docs/architecture.md):192) and the input state module ([src/state/input.ts](src/state/input.ts)) exists, but keyboard input is never read in the game loop. The `InputState` is created but not consumed by `GameScene.update()`.
**Fix:** Read keyboard state in `update()` via `createInputState()`, `getMovementVector()`, and apply keyboard-driven movement alongside joystick. The input module's pure functions are already tested — only the integration in `update()` is missing.

---

## 4 [HIGH] — Security
**File:** [app/ws_handler.py](app/ws_handler.py):337-343
**Issue:** No authentication on WebSocket connections. Any client who knows a player's UUID can connect via `/ws/{player_id}` and receive that player's full `state_sync` (inventory, coins, quest state, progress). While UUIDs are hard to guess, the connection has no token, session secret, or additional verification.
**Fix:** For MVP local deployment this is acceptable risk given the name-only login model. Document as a known limitation for V2+ with stronger identity. No code change required for MVP, but flag for awareness.

---

## 5 [HIGH] — Security
**File:** [app/routes/players.py](app/routes/players.py):36-59, [app/routes/config.py](app/routes/config.py):13-20, [app/routes/logs.py](app/routes/logs.py):26-60
**Issue:** No rate limiting on any HTTP endpoint. `POST /api/v1/players` could be spammed to create many players; `POST /api/v1/client-events` accepts unbounded inserts into `player_events` table.
**Fix:** For MVP local deployment this is low risk, but note for V2+. No code change required for MVP.

---

## 6 [HIGH] — Design/Quality
**File:** [src/scenes/GameScene.ts](src/scenes/GameScene.ts):1-975 (entire file)
**Issue:** `GameScene` is 975 lines with **50+ private fields** and **30+ methods**, directly managing DOM elements, WebSocket messages, quest state machine, shop, inventory, quest timer, joystick, bootstrap loading, and coin/level display. This violates the Phaser rule in [typescript-standards.md](.claude/rules/typescript/typescript-standards.md): "Scene classes are thin rendering layers — no business logic." The `update()` method contains `if/else` logic at lines 925-943 (joystick active checks, speed calculation, direction resolution), also violating the Phaser rule: "`Scene.update(time, delta)` must only call entity/state methods; never contain `if/else` game logic."
**Fix:** Extract business logic into dedicated manager classes (e.g., `QuestManager`, `ShopManager`, `InventoryManager`, `BootstrapManager`). Move DOM panel management out of the scene. Delegate movement input to the `InputState` module already present.

---

## 7 [HIGH] — Design/Quality
**File:** [app/services/quest_service.py](app/services/quest_service.py):48, 139
**Issue:** `offer_quest()` at line 48 uses `self._npcs[npc_id]` without a `.get()` guard — raises `KeyError` (500) if NPC ID does not exist. Same issue at line 139 in `accept_quest()` with `self._quests[quest_id]`. These are user-controlled inputs (npc_id comes from WebSocket messages).
**Fix:** Use `self._npcs.get(npc_id)` and `self._quests.get(quest_id)`, returning `{"type": "npc_not_found"}` / `{"type": "quest_not_found"}` respectively.

---

## 8 [HIGH] — Design/Quality
**File:** [app/ws_handler.py](app/ws_handler.py):48-51
**Issue:** `_load_preset_phrases()` reads `preset_phrases.json` from disk on **every WebSocket connection** with no caching. If the file is missing, malformed, or has unexpected structure, the entire WebSocket endpoint crashes with an unhandled exception — no player can connect.
**Fix:** Load once at module level or cache in `ConfigService` on startup. Add error handling for missing/malformed file.

---

## 9 [HIGH] — Design/Quality
**File:** [app/services/world_service.py](app/services/world_service.py):1-94
**Issue:** `WorldService` class is fully implemented with `apply_move()`, `get_snapshot()`, `needs_position_save()`, etc. and has comprehensive tests at [tests/test_world_service.py](tests/test_world_service.py):161 lines. However, **it is never instantiated or used** by `ws_handler.py`. The WebSocket handler has its own duplicate movement/broadcast logic (`_broadcast_state_update`, hardcoded in `_handle_messages`). This is dead, untested code path in production — the tested `WorldService` rate limiting, bounds checking, and snapshot logic is bypassed.
**Fix:** Either remove `WorldService` or wire it into `ws_handler.py`. Prefer wiring it in, since it provides tested rate limiting and snapshot functionality.

---

## 10 [MEDIUM] — Performance
**File:** [app/ws_handler.py](app/ws_handler.py):164-176
**Issue:** N+1 query in `_fetch_quests_and_world_items()`. Fetches all quests for a player, then loops over each active quest to fetch its world items in separate queries. For a player with 3 active quests, that's 4 queries when 1 JOIN would suffice.
**Fix:** Use a single `SELECT ... FROM world_item_instances WHERE quest_instance_id IN (SELECT id FROM player_quests WHERE player_id=? AND status='active')`.

---

## 11 [MEDIUM] — Performance
**File:** [src/scenes/GameScene.ts](src/scenes/GameScene.ts):726, 751
**Issue:** `updateShopPanel()` and `updateInventoryPanel()` use `innerHTML = ''` to clear and rebuild all DOM elements from scratch on every update. These are called from `handleStateSync()` and `handleInventoryUpdated()`, which fire on every state sync (reconnect) and inventory change. Repeated DOM destruction/recreation causes unnecessary layout thrashing.
**Fix:** Use targeted DOM updates (update text content, add/remove individual rows) rather than full rebuilds.

---

## 12 [MEDIUM] — Design/Quality
**File:** [app/ws_handler.py](app/ws_handler.py):251-335
**Issue:** `_handle_messages()` is **84 lines** and handles multiple message types in a single `if/elif` chain. This violates the 50-line function limit for API/public surface code.
**Fix:** Extract message-type handlers into separate methods or use a message dispatch dict.

---

## 13 [MEDIUM] — Design/Quality
**File:** [app/routes/players.py](app/routes/players.py):21-28
**Issue:** `Settings()` is instantiated with `lru_cache` in `routes/players.py`, but in [routes/logs.py](app/routes/logs.py):44 it is called directly with `Settings()` — each call re-reads `.env`. The pattern is inconsistent.
**Fix:** Use the same `lru_cache` pattern or a shared singleton across all route modules.

---

## 14 [MEDIUM] — Design/Quality
**File:** Project-wide (app/services/*.py, app/ws_handler.py)
**Issue:** Every service method and WebSocket function opens a fresh `sqlite3.connect()` per operation. While SQLite WAL mode handles concurrent readers well, this creates unnecessary connection overhead. No connection pooling or shared connection used.
**Fix:** For MVP local deployment this is acceptable. Consider a connection pool or per-request connection for V2+.

---

## 15 [LOW] — Design/Quality
**File:** [src/net/WSClient.ts](src/net/WSClient.ts):83-84, 112-113
**Issue:** Empty `catch {}` blocks in `sendMove()` and `sendPayload()`. While the comment justifies this as "send is best-effort," silently swallowing exceptions makes debugging connection issues harder.
**Fix:** Log at `debug` level inside the catch, or use a structured debug event.

---

## 16 [LOW] — Design/Quality
**File:** [src/scenes/GameScene.ts](src/scenes/GameScene.ts):848
**Issue:** `(window as unknown as Record<string, unknown>)['__gameStore'] = { ... }` — pollutes the global namespace. Any browser extension or script can read/write game state.
**Fix:** Use a module-scoped variable or a proper state management pattern rather than attaching to `window`.

---

## 17 [LOW] — Design/Quality
**File:** [vite.config.ts](vite.config.ts):24
**Issue:** Path traversal check uses `path.sep` for boundary validation. On Windows this is `\`, on Linux `/`. The string comparison `filePath.startsWith(process.cwd() + path.sep)` is correct per-platform but could be rewritten as `path.resolve(filePath).startsWith(path.resolve(process.cwd()))` for clarity. The `existsSync` guard limits blast radius. This is dev-server only (not production Nginx), so risk is minimal.
**Fix:** Low priority — dev server only.

---

## 18 [LOW] — Design/Quality
**File:** [tests/](tests/) directory
**Issue:** No `conftest.py` in the project-level `tests/` directory. Test fixtures are duplicated across test files (e.g., the `client` fixture in `test_player_routes.py`, `test_ws_identity.py`, etc.). A shared `conftest.py` would centralize common fixtures.
**Fix:** Extract shared fixtures (test DB init, test client, player creation helper) into `tests/conftest.py`.

---

## 19 [LOW] — Security
**File:** [app/ws_handler.py](app/ws_handler.py):22
**Issue:** `_active_sessions` dict has no size limit. A malicious client could open many WebSocket connections with different `player_id` values, exhausting server memory.
**Fix:** Add a `MAX_ACTIVE_SESSIONS` limit or rely on OS-level connection limits for MVP.

---

## Summary

| Severity    | Count |
|-------------|-------|
| CRITICAL    | 3     |
| HIGH        | 6     |
| MEDIUM      | 5     |
| LOW         | 5     |

### CRITICAL Issues Detail

| # | File | Summary |
|---|------|---------|
| 1 | [app/ws_handler.py:296-332](app/ws_handler.py#L296) | Gameplay WS messages not dispatched — quest, shop, inventory, progression services unconnected |
| 2 | [app/routes/players.py:49](app/routes/players.py#L49) | `character_required` returns 200 instead of spec-required 409 |
| 3 | [src/scenes/GameScene.ts:925](src/scenes/GameScene.ts#L925) | Keyboard movement (WASD/arrows) not wired in update loop |

### HIGH Issues Detail

| # | File | Summary |
|---|------|---------|
| 4 | [app/ws_handler.py:337](app/ws_handler.py#L337) | No auth on WebSocket — anyone with UUID can connect |
| 5 | [app/routes/*.py](app/routes/) | No rate limiting on HTTP endpoints |
| 6 | [src/scenes/GameScene.ts](src/scenes/GameScene.ts) | 975-line scene violates Phaser thin-layer rule |
| 7 | [app/services/quest_service.py:48](app/services/quest_service.py#L48) | KeyError on unknown NPC/quest IDs (500 crash) |
| 8 | [app/ws_handler.py:48](app/ws_handler.py#L48) | Preset phrases file read per-connection, no error handling |
| 9 | [app/services/world_service.py](app/services/world_service.py) | Implemented + tested WorldService never instantiated — dead code path |

---

**Verdict: BLOCK** — 3 CRITICAL and 6 HIGH issues must be resolved before proceeding. The most impactful issue is #1: the core gameplay loop cannot function because the WebSocket handler does not dispatch quest, shop, inventory, or progression messages to their respective services.

**Notable strengths:**
- Strong test coverage: 38 Python test files + 17 Vitest test files + 15 Playwright E2E specs
- Clean separation of concerns in services layer — each service is focused and well-tested
- Consistent use of parameterized SQL queries — no SQL injection risk
- Server-authoritative position validation (`is_in_world_bounds`, NPC/item distance checks)
- Atomic transactions with `BEGIN IMMEDIATE` for concurrent-safe gameplay mutations
- Thorough TypeScript type guards for all protocol messages
- Comprehensive structured logging with rotation/cleanup
