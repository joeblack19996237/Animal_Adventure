# Animal Adventure L3 MVP Data Model

## SQLite Tables

### players

Stores the durable player profile and current map position.

- `id` TEXT PRIMARY KEY
- `name` TEXT NOT NULL
- `normalized_name` TEXT NOT NULL UNIQUE
- `character_id` TEXT NOT NULL
- `x` REAL NOT NULL
- `y` REAL NOT NULL
- `direction` TEXT NOT NULL
- `level` INTEGER NOT NULL DEFAULT 0
- `coins` INTEGER NOT NULL DEFAULT 25
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL
- `last_seen_at` TEXT

### player_progress

Stores L3 progression and map unlocks.

- `player_id` TEXT PRIMARY KEY REFERENCES players(id)
- `completed_quest_count` INTEGER NOT NULL DEFAULT 0
- `unique_completed_quest_ids_json` TEXT NOT NULL DEFAULT '[]'
- `used_potion_count` INTEGER NOT NULL DEFAULT 0
- `unlocked_level` INTEGER NOT NULL DEFAULT 0
- `unlocked_regions_json` TEXT NOT NULL DEFAULT '["spawn"]'

### player_inventory

Stores both limited inventory and equipment inventory.

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `player_id` TEXT NOT NULL REFERENCES players(id)
- `item_id` TEXT NOT NULL
- `quantity` INTEGER NOT NULL DEFAULT 1
- `slot_type` TEXT NOT NULL CHECK (`slot_type` IN ('inventory', 'equipment'))
- `slot_index` INTEGER

Rules:

- `inventory` is capped at 20 slots.
- `equipment` is not capped for MVP.
- Potion and stackable items can share one slot by `item_id`.
- NPC reward accessories go to `equipment`.
- Add a unique index on `(player_id, item_id, slot_type)` for stackable items in MVP, or enforce stack merging in `InventoryService` before insert.

### player_quests

Stores active, completed, failed, and cooldown timestamps per player.

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `player_id` TEXT NOT NULL REFERENCES players(id)
- `npc_id` TEXT NOT NULL
- `quest_id` TEXT NOT NULL
- `status` TEXT NOT NULL CHECK (`status` IN ('available', 'active', 'completed', 'failed'))
- `started_at` TEXT
- `expires_at` TEXT
- `cooldown_until` TEXT
- `progress_json` TEXT NOT NULL DEFAULT '{}'
- `rewards_granted_json` TEXT NOT NULL DEFAULT '[]'

Rules:

- A player can have at most one active quest at a time in MVP.
- A player can have at most one active row per `(player_id, quest_id)`.
- Repeated turn-in for a completed quest must not grant duplicate rewards; reward ids already granted are stored in `rewards_granted_json`.
- `completed` and `failed` rows may have `cooldown_until`; after that timestamp, the quest is offerable again for that player.
- `active -> failed` conversion must be idempotent. If another path has already changed the row to `completed` or `failed`, the expiry scanner must not overwrite the terminal state.

### quest_locks

Stores the global active lock for each NPC quest so only one player can run that quest at a time.

- `npc_id` TEXT PRIMARY KEY
- `quest_id` TEXT NOT NULL
- `quest_instance_id` INTEGER NOT NULL REFERENCES player_quests(id) ON DELETE CASCADE
- `player_id` TEXT NOT NULL REFERENCES players(id)
- `expires_at` TEXT NOT NULL
- `created_at` TEXT NOT NULL

Rules:

- A row exists only while the quest is active.
- `npc_id` primary key guarantees at most one active lock per NPC quest.
- The lock owner is the only player who can see, pick up, and turn in the spawned quest item instances.
- Completion or failure must delete the lock in the same transaction that updates the quest terminal state and expires world item instances.
- If the backend restarts and finds an expired lock, it must mark the matching quest failed, expire its item instances, start the owner's failure cooldown, and delete the lock.
- The 30-second quest expiry scanner, lazy expiry checks during pickup/turn-in, and backend restart recovery must all use the same failure transition: mark the active quest failed, expire its item instances, start failure cooldown, and delete the lock in one short transaction.
- Backend startup recovery must defensively delete orphan locks whose `quest_instance_id` no longer exists in `player_quests`, then log the cleanup. Normal schema should prevent this via `ON DELETE CASCADE`, but the startup cleanup protects against legacy data, interrupted migrations, or manual database edits.

### world_item_instances

Stores spawned quest items.

- `id` TEXT PRIMARY KEY
- `quest_instance_id` INTEGER NOT NULL REFERENCES player_quests(id)
- `item_id` TEXT NOT NULL
- `x` REAL NOT NULL
- `y` REAL NOT NULL
- `status` TEXT NOT NULL CHECK (`status` IN ('spawned', 'picked_up', 'expired'))

Rules:

- Quest item instances are owned by a specific quest instance and player through `quest_instance_id`.
- Reconnect must reuse existing spawned item instances for the active quest.
- Failed or completed quests expire their item instances.

### player_events

Stores player behavior and important diagnostic events.

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `player_id` TEXT
- `event_type` TEXT NOT NULL
- `event_payload_json` TEXT NOT NULL
- `created_at` TEXT NOT NULL

Required indexes:

- `idx_player_events_created_at` on `created_at`
- `idx_player_events_player_id_created_at` on `(player_id, created_at)`

## Required SQLite Constraints And Indexes

- `players.id` primary key.
- `players.normalized_name` unique index.
- `player_progress.player_id` primary key and foreign key to `players.id`.
- `player_inventory.player_id` indexed.
- `player_quests.player_id` indexed.
- `player_quests.quest_id` indexed.
- `quest_locks.npc_id` primary key.
- `quest_locks.quest_instance_id` unique index with `ON DELETE CASCADE` to `player_quests(id)`.
- `world_item_instances.quest_instance_id` indexed.
- `player_events.created_at` indexed for cleanup.
- Use `PRAGMA journal_mode=WAL`.
- Use `PRAGMA foreign_keys=ON`.
- Use `PRAGMA busy_timeout=5000`.

## SQLite Write Rules

- Keep online movement state in memory; do not write one SQLite transaction per `player_move`.
- Persist player position on a 30-second throttle and immediately after `quest_accept`, `quest_completed`, `quest_failed`, `shop_buy`, `use_item`, `level_up`, and WebSocket disconnect.
- Use short transactions for gameplay mutations. Do not hold a SQLite transaction while waiting on WebSocket sends, timers, asset loading, or client input.
- Use a single-writer queue or equivalent serialized write path for concurrent gameplay mutations when multiple local clients are connected.
- The quest expiry scanner runs every 30 seconds and must use short transactions through the same serialized write path. It may process expired quests in small batches or one row at a time, and must never hold a transaction while sending WebSocket messages.
- Reward-granting operations must be idempotent. In particular, `quest_turn_in` must check quest status, lock ownership, expiry, requirements, and prior reward state in the same transaction that grants rewards, writes cooldown, expires world item instances, and deletes the quest lock.
- Shop purchases must atomically check coin balance, deduct coins, and add the item. Potion use must atomically consume Potion, increment `used_potion_count`, and apply any resulting level-up.

## JSON Config Files

### config/map.json

Contains:

- map source image id/path
- map tile manifest path
- width and height
- spawn coordinate
- world bounds
- `interaction_regions` such as the MVP Spawn-area interaction region
- `hotspots` for explicit coordinate triggers. MVP must keep this empty because all Portals are non-interactive scenery until V2.
- region unlock metadata

MVP example:

```json
{
  "map": {
    "asset_id": "map_full",
    "tile_manifest": "config/map_tiles.json",
    "width": 5430,
    "height": 7240,
    "spawn": { "x": 2715, "y": 3620 },
    "bounds": { "x": 0, "y": 0, "width": 5430, "height": 7240 }
  },
  "interaction_regions": [
    {
      "id": "spawn_area",
      "type": "mvp_interaction_region",
      "x": 2715,
      "y": 3620,
      "radius": 900
    }
  ],
  "hotspots": [],
  "regions": {
    "spawn": { "unlock_level": 0 },
    "playground": { "unlock_level": 3, "mvp_behavior": "persist_and_notify_only" }
  }
}
```

### config/map_tiles.json

Contains prepared background tile metadata for rendering the full map without loading `game_map_full.png` as one WebGL texture.

- `tile_width`: default tile width, `1024`
- `tile_height`: default tile height, `1024`
- `map_width`: full world width, `5430`
- `map_height`: full world height, `7240`
- `columns`: `6`
- `rows`: `8`
- `tiles`: 48 tile records with `id`, relative `path`, `x`, `y`, `width`, and `height`

Rules:

- Tile `path` values are relative to `/assets/images/`. Example: `MapTiles/map_tile_0_0.png` resolves to `/assets/images/MapTiles/map_tile_0_0.png`.
- Tile records must fully cover `0..5430` by `0..7240` without gaps or overlap.
- Config validation must reject tile records that extend outside `map_width`/`map_height`, leave gaps, overlap, or have inconsistent row/column ordering. For the MVP map, the last column width is `310` and the last row height is `72`.
- Most tiles are `1024 x 1024`; the last column is `310px` wide and the last row is `72px` high.
- World coordinates, NPC positions, item positions, hotspots, map bounds, and camera bounds remain in the full `5430 x 7240` coordinate system.
- Collision remains map-bounds only for MVP; tiled rendering does not imply tilemap collision.
- Players can tour the full map in MVP. Only Spawn-area NPCs/items and global UI controls are interactive.

MVP example shape:

```json
{
  "tile_width": 1024,
  "tile_height": 1024,
  "map_width": 5430,
  "map_height": 7240,
  "columns": 6,
  "rows": 8,
  "tiles": [
    { "id": "map_tile_0_0", "path": "MapTiles/map_tile_0_0.png", "x": 0, "y": 0, "width": 1024, "height": 1024 },
    { "id": "map_tile_5_7", "path": "MapTiles/map_tile_5_7.png", "x": 5120, "y": 7168, "width": 310, "height": 72 }
  ]
}
```

### config/foreground_tiles.json

Contains sparse foreground occlusion tile metadata for transparent overlays that render above world sprites. This config is frontend-rendering metadata only; it does not change collision, hotspots, NPC/item coordinates, or backend gameplay state.

- `tiles`: sparse list of foreground tile records.
- Each record has `tile_id`, matching an `id` in `config/map_tiles.json`.
- Each record has `path`, relative to `/assets/images/`. Example: `ForegroundTiles/map_foreground_tile_0_0.png` resolves to `/assets/images/ForegroundTiles/map_foreground_tile_0_0.png`.

Rules:

- Foreground tile entries are optional per map tile. Missing entries are valid and must not trigger asset requests.
- Every foreground PNG must exist on disk, have an alpha channel, and have the exact same `width` and `height` as the corresponding base map tile.
- Non-occlusion pixels must be transparent. Tests enforce that most pixels remain transparent so accidental full-background exports are rejected.
- Foreground tiles use the corresponding base tile's world `x`, `y`, `width`, and `height`; they do not define independent coordinates.
- Foreground tiles are not logical gameplay assets in `config/assets.json`; they are render-layer assets tied to `config/map_tiles.json`.

MVP example shape:

```json
{
  "tiles": [
    {
      "tile_id": "map_tile_0_0",
      "path": "ForegroundTiles/map_foreground_tile_0_0.png"
    }
  ]
}
```

### config/npcs.json

Contains:

- NPC id
- display name
- asset id
- position
- interaction radius
- quest id

MVP NPC ids:

- `hopper`
- `copper`
- `elisa`

MVP example:

```json
[
  { "id": "hopper", "name": "Hopper", "asset_id": "npc_hopper", "x": 2715, "y": 3200, "interaction_radius": 160, "quest_id": "quest_hopper_blanket" },
  { "id": "copper", "name": "Copper", "asset_id": "npc_copper", "x": 3150, "y": 3620, "interaction_radius": 160, "quest_id": "quest_copper_bagpipe" },
  { "id": "elisa", "name": "Elisa", "asset_id": "npc_elisa", "x": 2715, "y": 4050, "interaction_radius": 160, "quest_id": "quest_elisa_dance_shoes" }
]
```

### config/quests.json

Contains:

- quest id
- npc id
- title
- time limit
- required item ids
- item spawn zone
- item pickup radius and logical coordinates
- rewards
- completion cooldown
- failure cooldown

MVP quest ids:

- `quest_hopper_blanket`
- `quest_copper_bagpipe`
- `quest_elisa_dance_shoes`

MVP example:

```json
[
  {
    "id": "quest_hopper_blanket",
    "npc_id": "hopper",
    "title": "Find Hopper's Blanket",
    "time_limit_seconds": 300,
    "required_items": ["item_blanket"],
    "item_spawn": { "mode": "fixed", "x": 2600, "y": 3100, "pickup_radius": 96 },
    "rewards": [{ "type": "coins", "amount": 25 }, { "type": "equipment", "item_id": "accessory_sleepy_hat", "quantity": 1 }],
    "completion_cooldown_seconds": 3600,
    "failure_cooldown_seconds": 1800
  },
  {
    "id": "quest_copper_bagpipe",
    "npc_id": "copper",
    "title": "Find Copper's Bagpipe",
    "time_limit_seconds": 300,
    "required_items": ["item_bagpipe"],
    "item_spawn": { "mode": "fixed", "x": 3330, "y": 3500, "pickup_radius": 96 },
    "rewards": [{ "type": "coins", "amount": 25 }],
    "completion_cooldown_seconds": 3600,
    "failure_cooldown_seconds": 1800
  },
  {
    "id": "quest_elisa_dance_shoes",
    "npc_id": "elisa",
    "title": "Find Elisa's Dance Shoes",
    "time_limit_seconds": 300,
    "required_items": ["item_dance_shoes"],
    "item_spawn": { "mode": "fixed", "x": 2830, "y": 4250, "pickup_radius": 96 },
    "rewards": [{ "type": "coins", "amount": 25 }],
    "completion_cooldown_seconds": 3600,
    "failure_cooldown_seconds": 1800
  }
]
```

### config/items.json

Contains:

- item id
- display name
- asset id/path
- stackability
- inventory target
- item type

MVP item ids:

- `item_blanket`
- `item_bagpipe`
- `item_dance_shoes`
- `potion_l0`
- `accessory_sleepy_hat`
- `coin`

MVP example:

```json
[
  { "id": "item_blanket", "name": "Blanket", "asset_id": "item_blanket", "stackable": false, "slot_type": "inventory", "type": "quest_item" },
  { "id": "item_bagpipe", "name": "Bagpipe", "asset_id": "item_bagpipe", "stackable": false, "slot_type": "inventory", "type": "quest_item" },
  { "id": "item_dance_shoes", "name": "Dance Shoes", "asset_id": "item_dance_shoes", "stackable": false, "slot_type": "inventory", "type": "quest_item" },
  { "id": "potion_l0", "name": "Potion", "asset_id": "potion_l0", "stackable": true, "slot_type": "equipment", "type": "consumable" },
  { "id": "accessory_sleepy_hat", "name": "Sleepy Hat", "asset_id": "accessory_sleepy_hat", "stackable": false, "slot_type": "equipment", "type": "accessory" },
  { "id": "coin", "name": "Dollar", "asset_id": "coin", "stackable": true, "slot_type": "none", "type": "currency" }
]
```

### config/shop.json

Contains purchasable items.

MVP:

- `potion_l0`
- price: `$10`
- unlock level: `0`

MVP example:

```json
{
  "items": [
    { "item_id": "potion_l0", "price": 10, "unlock_level": 0 }
  ]
}
```

### config/progression.json

MVP L3 rule:

```json
{
  "levels": {
    "3": {
      "unique_completed_quest_ids": 2,
      "used_potion_count": 2,
      "unlock_regions": ["spawn", "playground"]
    }
  }
}
```

The player starts with `25` coins and MVP Potion costs `$10`, so the initial balance can buy the 2 required Potions. L3 still requires `unique_completed_quest_ids >= 2`, so completing at least 2 different quests is mandatory and quest rewards are not the gate for Potion affordability.

### config/assets.json

Maps logical asset ids to Nginx-served paths.

Example:

```json
{
  "map_full": "/assets/images/Items/game_map_full.png",
  "npc_hopper": "/assets/images/NPC/NPC_1_Hopper.png",
  "npc_copper": "/assets/images/NPC/NPC_A_Copper.png",
  "npc_elisa": "/assets/images/NPC/NPC_B_Elisa.png",
  "item_blanket": "/assets/images/Items/item_blanket.png",
  "item_bagpipe": "/assets/images/Items/item_bagpipe.png",
  "item_dance_shoes": "/assets/images/Items/item_dance_shoes.png",
  "potion_l0": "/assets/images/Items/item_magic_potion_1.png",
  "accessory_sleepy_hat": "/assets/images/Items/accessory_sleepy_hat.png",
  "coin": "/assets/images/UI/ui_currency_icon.png",
  "bgm_1": "/assets/music/bgm-1.m4a",
  "bgm_2": "/assets/music/bgm-2.m4a",
  "bgm_3": "/assets/music/bgm-3.m4a",
  "bgm_4": "/assets/music/bgm-4.m4a",
  "character_penguin_stand_front": "/assets/images/penguin_sprite_sheet/penguin_stand_front.png",
  "character_penguin_stand_back": "/assets/images/penguin_sprite_sheet/penguin_stand_back.png",
  "character_penguin_walk_front": "/assets/images/penguin_sprite_sheet/penguin_walk_front.png",
  "character_penguin_walk_side": "/assets/images/penguin_sprite_sheet/penguin_walk_side.png",
  "character_arctic_fox_stand_front": "/assets/images/arctic_fox_sprite_sheet/arctic_fox_stand_front.png",
  "character_arctic_fox_walk_front": "/assets/images/arctic_fox_sprite_sheet/arctic_fox_walk_front.png",
  "character_arctic_fox_walk_back": "/assets/images/arctic_fox_sprite_sheet/arctic_fox_walk_back.png",
  "character_arctic_fox_walk_side": "/assets/images/arctic_fox_sprite_sheet/arctic_fox_walk_side.png",
  "character_cat_snowman_stand_front": "/assets/images/cat_snowman_sprite_sheet/cat-front-stand.png",
  "character_cat_snowman_stand_back": "/assets/images/cat_snowman_sprite_sheet/cat-back-stand.png",
  "character_cat_snowman_walk_front": "/assets/images/cat_snowman_sprite_sheet/cat-front-walk.png",
  "character_cat_snowman_walk_side": "/assets/images/cat_snowman_sprite_sheet/cat-side-walk.png"
}
```

### config/characters.json

Contains the MVP selectable character ids and their asset references. Returning players keep their stored `character_id`.

Rules:

- Character configs use logical asset ids from `config/assets.json`; gameplay code must not depend directly on raw file paths.
- MVP character assets are split PNG files. Missing left/right frames may use mirrored side images; missing run frames must fall back to walk/stand because running is V2+.
- Each character entry defines `scale`, `anchor`, and `collision_radius` so rendering, interaction distance, and hit checks are stable despite different PNG dimensions.

MVP character ids:

- `penguin`
- `arctic_fox`
- `cat_snowman`

MVP example:

```json
[
  {
    "id": "penguin",
    "display_name": "Penguin",
    "enabled_in_mvp": true,
    "scale": 0.45,
    "anchor": { "x": 0.5, "y": 0.9 },
    "collision_radius": 36,
    "states": {
      "stand": { "front": "character_penguin_stand_front", "back": "character_penguin_stand_back" },
      "walk": { "front": "character_penguin_walk_front", "back": "character_penguin_stand_back", "left": "character_penguin_walk_side", "right": "character_penguin_walk_side", "right_mirror": true }
    }
  },
  {
    "id": "arctic_fox",
    "display_name": "Arctic Fox",
    "enabled_in_mvp": true,
    "scale": 0.5,
    "anchor": { "x": 0.5, "y": 0.9 },
    "collision_radius": 34,
    "states": {
      "stand": { "front": "character_arctic_fox_stand_front", "back": "character_arctic_fox_walk_back" },
      "walk": { "front": "character_arctic_fox_walk_front", "back": "character_arctic_fox_walk_back", "left": "character_arctic_fox_walk_side", "right": "character_arctic_fox_walk_side", "right_mirror": true }
    }
  },
  {
    "id": "cat_snowman",
    "display_name": "Snowman Cat",
    "enabled_in_mvp": true,
    "scale": 0.5,
    "anchor": { "x": 0.5, "y": 0.9 },
    "collision_radius": 34,
    "states": {
      "stand": { "front": "character_cat_snowman_stand_front", "back": "character_cat_snowman_stand_back" },
      "walk": { "front": "character_cat_snowman_walk_front", "back": "character_cat_snowman_stand_back", "left": "character_cat_snowman_walk_side", "right": "character_cat_snowman_walk_side", "right_mirror": true }
    }
  }
]
```

### config/preset_phrases.json

Contains preset chat phrase ids and display text. Free text is out of scope for MVP.

MVP example:

```json
[
  { "id": "hello", "text": "Hello!" },
  { "id": "thanks", "text": "Thanks!" },
  { "id": "lets_go", "text": "Let's go!" }
]
```

## MVP Coordinates

- Spawn: `{ "x": 2715, "y": 3620 }`
- Hopper: `{ "x": 2715, "y": 3200 }`
- Copper: `{ "x": 3150, "y": 3620 }`
- Elisa: `{ "x": 2715, "y": 4050 }`
- Hopper blanket: `{ "x": 2600, "y": 3100 }`
- Copper bagpipe: `{ "x": 3330, "y": 3500 }`
- Elisa dance shoes: `{ "x": 2830, "y": 4250 }`

These are config defaults and may be tuned without code changes.
