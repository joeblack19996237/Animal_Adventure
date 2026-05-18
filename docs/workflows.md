# Animal Adventure L3 MVP Workflows

## New Player

1. Browser opens the Nginx entrypoint.
2. Login screen explains that the same normalized name loads the same local save and that name-only login is intended for MVP local/family-network use.
3. Player enters `name` only.
4. Frontend normalizes name for lookup by trimming surrounding whitespace and comparing case-insensitively through the backend.
5. Frontend calls `POST /api/v1/players` with `name`.
6. Backend computes `normalized_name`.
7. If `normalized_name` does not exist and no `character_id` is provided, backend returns `character_required` without creating a player row.
8. New player chooses one of 3 MVP characters.
9. Frontend calls `POST /api/v1/players` again with `name` and `character_id`.
10. Backend creates a new durable player row, generates a unique internal `player_id`, and persists initial coins, spawn position, character, and progression.
11. Frontend loads bootstrap config.
12. If bootstrap config fails, frontend shows a blocking error page or overlay and does not enter the game world or open the gameplay WebSocket.
13. WebSocket connects to `/ws/{player_id}` using the backend-returned id and receives `state_sync`.
14. Player spawns near the map center. The full map can be toured, but only Spawn-area gameplay interactions are enabled in MVP.

## Returning Player

1. Browser opens the game.
2. Login screen shows the same-name same-save warning.
3. Player enters `name` only.
4. Backend normalizes the name with the same case-insensitive matching rules.
5. If a matching `normalized_name` exists, backend loads the existing player and returns its internal `player_id`.
6. Returning player does not choose a character again in MVP.
7. Frontend loads bootstrap config.
8. If bootstrap config fails, frontend shows a blocking error page or overlay and does not enter the game world or open the gameplay WebSocket.
9. WebSocket connects to `/ws/{player_id}` and receives `state_sync`.
10. Frontend restores position, level, coins, inventory, quest state, and unlocked map state.

## Movement

1. Player uses keyboard or touch controls.
2. Client predicts movement locally.
3. Client sends `player_move` at no more than 20Hz.
4. Server identifies the player from the WebSocket connection, ignoring or verifying any body `player_id`.
5. Server validates map bounds.
6. Server allows movement within the full map rectangle and updates authoritative in-memory position state.
7. If movement messages exceed allowed server limits, the server may return `rate_limited` or safely drop non-critical movement updates without writing SQLite.
8. Server broadcasts minimal `state_update` snapshots at 10Hz for rendering remote players.
9. Server persists position to SQLite on a 30-second throttle and after important gameplay events, not for every movement message.
10. Client reconciles local and remote player positions.

## NPC Quest

1. Player enters NPC interaction radius.
2. Client sends `npc_interact_request`.
3. Server checks whether the player already has an active quest, whether this NPC quest is on player-specific cooldown, and whether another player currently owns the NPC quest lock.
4. If the player already has an active quest, server returns `quest_already_active`; no `quest_offer` is sent.
5. If another player owns the lock, server returns `quest_locked`; no item is spawned.
6. If checks pass, server sends `quest_offer`.
7. Player accepts the quest.
8. Server creates a `player_quests` row and acquires the NPC quest lock in the same transaction.
9. Server starts the authoritative quest timer immediately at accept time by setting `started_at` and `expires_at`.
10. Server spawns the required item for the lock owner's quest instance only.
11. Server sends `quest_started` with `expires_at`; frontend starts the visible countdown from server time.
12. Player touches the item.
13. Client sends `item_pickup_request`.
14. Server validates lock ownership, item ownership, pickup radius, inventory capacity, and status using the server-authoritative player position.
15. If inventory is full, server returns `inventory_full`; the quest remains active, the timer continues, and the player may free inventory space and retry before `expires_at`.
16. Server checks server UTC time against `expires_at`; if expired, it fails the quest before applying pickup.
17. Server updates quest progress and inventory.
18. Player returns to the NPC.
19. Client sends `quest_turn_in`.
20. Server checks server UTC time against `expires_at` and validates active status, lock ownership, collected requirements, and prior reward state.
21. In one transaction, server grants rewards, updates `unique_completed_quest_ids_json`, writes `rewards_granted_json`, sets the player's completion cooldown, expires the item instances, releases the NPC quest lock, persists state, and marks the reward as granted.
22. Server sends `quest_completed`.
23. `quest_completed` includes both `coins_awarded` and `coins_balance`; rewards must be idempotent if the client retries `quest_turn_in`.

## Quest Failure

1. Server tracks quest expiry time with server UTC `expires_at`.
2. Expiry can be detected by `item_pickup_request`, `quest_turn_in`, the 30-second quest expiry scanner, or backend restart recovery.
3. If server time passes `expires_at` before completion, server marks the active quest as failed using the same authoritative failure transition for every trigger.
4. Server removes/invalidates spawned quest items.
5. Server starts 30-minute player-specific cooldown.
6. Server releases the NPC quest lock.
7. Server persists the failed quest state and sends `quest_failed` after the transaction commits when the owner is connected.

## Quest State Machine

- No row or expired cooldown -> quest is available.
- `available -> active` when the player accepts a quest and the server acquires the NPC quest lock.
- `active -> completed` when all requirements are met and turn-in succeeds.
- `active -> failed` when server time passes `expires_at`.
- `completed` starts a 60-minute player-specific cooldown.
- `failed` starts a 30-minute player-specific cooldown.
- While the NPC quest lock exists, other players receive `quest_locked`.
- Completion or failure releases the NPC quest lock immediately.
- After `cooldown_until`, the same player can receive the quest again and a new quest instance is created.
- Repeated `quest_turn_in` for an already completed quest returns a `quest_completed` message built from the current completed snapshot and must not grant rewards again. Idempotency is based on persisted `rewards_granted_json`; an active quest lock is not required for this repeated response.
- Client may retry `quest_turn_in` only when the request times out or the WebSocket disconnects before any terminal response is received. After reconnect, the client must first process `state_sync`; if that snapshot shows the quest is `completed`, `failed`, expired, or no longer active, it cancels the pending retry. After receiving `quest_completed`, `quest_failed`, `quest_expired`, or `quest_not_active`, the client must stop retrying that turn-in.
- All quest expiry decisions use server UTC time. The frontend countdown is display-only.

## Potion And L3 Progression

1. Player opens shop.
2. Player buys Potion.
3. Server validates coins, deducts coins, and adds Potion to equipment inventory atomically.
4. Player uses Potion.
5. Server atomically consumes Potion and increments `used_potion_count`.
6. `ProgressionService` checks L3 conditions.
7. If `unique_completed_quest_ids >= 2` and used potions >= 2, server upgrades player to L3 in the same mutation path.
8. Server persists progression and sends `level_up`.

## Disconnect And Reconnect

1. Network drops or browser loses WebSocket connection.
2. Frontend shows reconnect overlay.
3. `WSClient` retries with exponential backoff for up to 120 seconds.
4. On reconnect, server sends `state_sync`.
5. `state_sync` includes `server_time`, durable quest `expires_at` values, relevant `cooldown_until` values, and active world items so countdowns and quest progress resume from server state.
6. Frontend replaces local state with server state.
7. Player continues from persisted/latest authoritative progress.
8. If reconnect does not succeed within 120 seconds, `WSClient` stops automatic retries and shows "Server is temporarily unavailable. Please refresh the page." A manual refresh restarts login/bootstrap/connect recovery.

## Duplicate Session

1. A second browser or reconnect attempt opens `/ws/{player_id}` while an older connection for that player is still registered.
2. Server accepts the new connection because it is the freshest user intent and best supports reconnect recovery.
3. Server sends `error` with code `duplicate_session` to the older connection and closes it.
4. The older client shows a duplicate session message and does not auto-reconnect.
5. The new connection receives `state_sync` and becomes the only active WebSocket session for that `player_id`.

## Backend Restart

1. Uvicorn process exits unexpectedly.
2. Local watchdog restarts FastAPI.
3. Frontend reconnect attempts continue.
4. Backend reloads config and SQLite state.
5. Backend scans active quests and quest locks. Any quest whose `expires_at` is already in the past is marked failed, its items are expired, the owner receives failure cooldown, and the lock is released.
6. Reconnected clients receive `state_sync`.

## Player-To-Player

- Online players appear through `state_update` broadcasts.
- Preset chat uses phrase ids validated by the server.
- Friend request and trade workflows are reserved for V2.

## MVP Portal Scenery

1. Portal art may appear on the full map as scenery.
2. MVP does not define Portal hotspots.
3. Frontend must not show a Coming Soon modal for Portal proximity.
4. Backend does not define or log a Portal-enter event in MVP.
5. Portal interaction, scene transition, and Portal gameplay begin in V2 after the L3 MVP loop.
