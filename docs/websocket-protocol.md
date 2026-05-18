# Animal Adventure L3 MVP WebSocket Protocol

## Connection

Client connects through the same origin that served the page after `POST /api/v1/players` returns the backend-generated internal `player_id`. If the page is opened at `http://localhost:8080/`, the WebSocket URL is:

```text
ws://localhost:8080/ws/{player_id}
```

Nginx proxies to FastAPI:

```text
ws://127.0.0.1:8000/ws/{player_id}
```

On connect, the server sends `state_sync`. On disconnect, remaining players receive `player_left`.

Only one active WebSocket connection is allowed per `player_id`. If a new connection for the same `player_id` succeeds, the server sends `error` with code `duplicate_session` to the previous connection, closes the previous connection, and then sends `state_sync` to the new connection.

The client must derive the URL from `window.location.origin` unless an explicit `VITE_WS_URL` is configured. URL derivation maps `http://` to `ws://` and `https://` to `wss://`; any unsupported origin protocol is a client configuration error and must block connection rather than guessing.

## Connection Identity

The server treats `/ws/{player_id}` as the authoritative identity for the connection. Client messages may include `player_id` for debugging or backward-compatible payload shape, but the server must either ignore it or verify that it matches the connection identity. If the body `player_id` attempts to act as another player, the server returns `identity_mismatch` and must not apply the message.

Movement broadcasts must contain only the minimal state needed for other clients to render remote players, such as position and direction. Durable state such as coins, inventory, quest progress, and equipment is synchronized through `state_sync` and specific gameplay result messages.

## Client To Server Messages

### player_join

```json
{ "type": "player_join", "player_id": "p1" }
```

Deprecated for MVP gameplay. The server must not require this message because connection establishment already identifies the internally generated player id by `/ws/{player_id}` and triggers `state_sync`. If received, the server may treat it as a no-op join acknowledgement.

### player_move

```json
{
  "type": "player_move",
  "player_id": "p1",
  "x": 2715,
  "y": 3620,
  "direction": "down",
  "client_tick": 12
}
```

The client must send `player_move` at no more than 20Hz. The server remains authoritative and may return `rate_limited` or safely drop non-critical over-frequency movement messages, but must not write one SQLite transaction per movement message.

### npc_interact_request

```json
{ "type": "npc_interact_request", "player_id": "p1", "npc_id": "hopper" }
```

### quest_accept

```json
{ "type": "quest_accept", "player_id": "p1", "quest_id": "quest_hopper_blanket" }
```

### item_pickup_request

```json
{ "type": "item_pickup_request", "player_id": "p1", "item_instance_id": "wi_123" }
```

### quest_turn_in

```json
{ "type": "quest_turn_in", "player_id": "p1", "quest_id": "quest_hopper_blanket" }
```

Clients may retry `quest_turn_in` with the same `quest_id` only if the request times out or the WebSocket disconnects before any terminal response is received. After reconnect, clients must process `state_sync` before replaying pending turn-ins; if `state_sync` already shows the quest as completed or otherwise terminal, the pending retry is canceled. Repeated turn-in after a completed transaction returns a `quest_completed` message built from the current completed snapshot and persisted `rewards_granted_json`; it must not grant rewards again and does not require an active quest lock. Clients must stop retrying after `quest_completed`, `quest_failed`, `quest_expired`, or `quest_not_active`.

### shop_buy

```json
{ "type": "shop_buy", "player_id": "p1", "item_id": "potion_l0" }
```

### use_item

```json
{ "type": "use_item", "player_id": "p1", "item_id": "potion_l0" }
```

### preset_chat

```json
{ "type": "preset_chat", "player_id": "p1", "phrase_id": "hello" }
```

### ping

```json
{ "type": "ping", "client_time": 1710000000000 }
```

## Server To Client Messages

### state_sync

```json
{
  "type": "state_sync",
  "server_time": "2026-05-10T11:58:30Z",
  "player": {
    "id": "p1",
    "name": "Kitty",
    "normalized_name": "kitty",
    "character_id": "arctic_fox",
    "x": 2715,
    "y": 3620,
    "direction": "down",
    "level": 0,
    "coins": 25
  },
  "progress": {
    "completed_quest_count": 0,
    "unique_completed_quest_ids": [],
    "used_potion_count": 0,
    "unlocked_level": 0,
    "unlocked_regions": ["spawn"]
  },
  "inventory": [],
  "equipment": [],
  "quests": [
    {
      "quest_instance_id": 123,
      "npc_id": "hopper",
      "quest_id": "quest_hopper_blanket",
      "status": "active",
      "expires_at": "2026-05-10T12:03:30Z",
      "cooldown_until": null,
      "progress": { "collected": [] },
      "rewards_granted_json": []
    },
    {
      "quest_instance_id": 99,
      "npc_id": "copper",
      "quest_id": "quest_copper_bagpipe",
      "status": "completed",
      "expires_at": "2026-05-10T11:45:00Z",
      "cooldown_until": "2026-05-10T12:45:00Z",
      "progress": { "collected": ["item_bagpipe"] },
      "rewards_granted_json": ["coins:25"]
    },
    {
      "quest_instance_id": 100,
      "npc_id": "elisa",
      "quest_id": "quest_elisa_dance_shoes",
      "status": "failed",
      "expires_at": "2026-05-10T11:50:00Z",
      "cooldown_until": "2026-05-10T12:20:00Z",
      "progress": { "collected": [] },
      "rewards_granted_json": []
    }
  ],
  "online_players": {},
  "world_items": []
}
```

`state_sync` must include `server_time` on every connect/reconnect so clients can display server-authoritative countdowns. Active quest entries include `expires_at`; completed/failed cooldown snapshots include `cooldown_until`. Active quest `world_items` are also included at top level so reconnect can restore item sprites.

### state_update

```json
{
  "type": "state_update",
  "tick": 100,
  "players": {
    "p1": { "x": 2720, "y": 3624, "direction": "right" }
  }
}
```

### player_joined

```json
{ "type": "player_joined", "player": { "id": "p2", "name": "Bunny", "x": 2700, "y": 3600 } }
```

### player_left

```json
{ "type": "player_left", "player_id": "p2" }
```

### quest_offer

```json
{
  "type": "quest_offer",
  "npc_id": "hopper",
  "quest_id": "quest_hopper_blanket",
  "title": "Find Hopper's Blanket",
  "time_limit_seconds": 300,
  "rewards": [{ "item_id": "coin", "quantity": 25 }, { "item_id": "accessory_sleepy_hat", "quantity": 1 }]
}
```

### quest_started

```json
{
  "type": "quest_started",
  "quest_id": "quest_hopper_blanket",
  "expires_at": "2026-05-10T12:00:00Z",
  "world_items": [{ "id": "wi_123", "item_id": "item_blanket", "x": 2600, "y": 3100 }]
}
```

### quest_progress

```json
{ "type": "quest_progress", "quest_id": "quest_hopper_blanket", "collected": ["item_blanket"] }
```

### quest_completed

```json
{
  "type": "quest_completed",
  "quest_id": "quest_hopper_blanket",
  "coins_awarded": 25,
  "coins_balance": 50,
  "rewards": ["accessory_sleepy_hat"],
  "rewards_granted_json": ["coins:25", "equipment:accessory_sleepy_hat:1"]
}
```

### quest_failed

```json
{ "type": "quest_failed", "quest_id": "quest_hopper_blanket", "cooldown_until": "2026-05-10T12:30:00Z" }
```

### inventory_updated

```json
{ "type": "inventory_updated", "inventory": [], "equipment": [{ "item_id": "potion_l0", "quantity": 1 }] }
```

### shop_result

```json
{ "type": "shop_result", "success": true, "item_id": "potion_l0", "coins_spent": 10, "coins_balance": 15 }
```

### level_up

```json
{ "type": "level_up", "level": 3, "unlocked_regions": ["spawn", "playground"] }
```

### chat_message

```json
{ "type": "chat_message", "player_id": "p1", "phrase_id": "hello", "message": "Hello!" }
```

### error

```json
{ "type": "error", "code": "quest_on_cooldown", "message": "This NPC is cooling down." }
```

If another player currently owns the NPC quest lock:

```json
{ "type": "error", "code": "quest_locked", "message": "This NPC is helping another player. Please try again soon." }
```

Required MVP error codes:

- `invalid_message`
- `identity_mismatch`
- `duplicate_session`
- `player_not_found`
- `out_of_bounds`
- `npc_out_of_range`
- `quest_on_cooldown`
- `quest_locked`
- `quest_already_active`
- `quest_not_active`
- `quest_expired`
- `item_out_of_range`
- `item_not_available`
- `inventory_full`
- `insufficient_funds`
- `item_not_owned`
- `rate_limited`
- `internal_error`

### pong

```json
{ "type": "pong", "server_time": "2026-05-10T11:58:30Z" }
```
