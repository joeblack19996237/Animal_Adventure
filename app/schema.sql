CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    character_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    direction TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    coins INTEGER NOT NULL DEFAULT 25,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS player_progress (
    player_id TEXT PRIMARY KEY REFERENCES players(id),
    completed_quest_count INTEGER NOT NULL DEFAULT 0,
    unique_completed_quest_ids_json TEXT NOT NULL DEFAULT '[]',
    used_potion_count INTEGER NOT NULL DEFAULT 0,
    unlocked_level INTEGER NOT NULL DEFAULT 0,
    unlocked_regions_json TEXT NOT NULL DEFAULT '["spawn"]'
);

CREATE TABLE IF NOT EXISTS player_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL REFERENCES players(id),
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    slot_type TEXT NOT NULL CHECK (slot_type IN ('inventory', 'equipment')),
    slot_index INTEGER
);

CREATE TABLE IF NOT EXISTS player_quests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL REFERENCES players(id),
    npc_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available', 'active', 'completed', 'failed')),
    started_at TEXT,
    expires_at TEXT,
    cooldown_until TEXT,
    progress_json TEXT NOT NULL DEFAULT '{}',
    rewards_granted_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS quest_locks (
    npc_id TEXT PRIMARY KEY,
    quest_id TEXT NOT NULL,
    quest_instance_id INTEGER NOT NULL REFERENCES player_quests(id) ON DELETE CASCADE,
    player_id TEXT NOT NULL REFERENCES players(id),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS world_item_instances (
    id TEXT PRIMARY KEY,
    quest_instance_id INTEGER NOT NULL REFERENCES player_quests(id),
    item_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('spawned', 'picked_up', 'expired'))
);

CREATE TABLE IF NOT EXISTS player_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT,
    event_type TEXT NOT NULL,
    event_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_player_inventory_player_id
    ON player_inventory(player_id);

CREATE INDEX IF NOT EXISTS idx_player_quests_player_id
    ON player_quests(player_id);

CREATE INDEX IF NOT EXISTS idx_player_quests_quest_id
    ON player_quests(quest_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quest_locks_quest_instance_id
    ON quest_locks(quest_instance_id);

CREATE INDEX IF NOT EXISTS idx_world_item_instances_quest_instance_id
    ON world_item_instances(quest_instance_id);

CREATE INDEX IF NOT EXISTS idx_player_events_created_at
    ON player_events(created_at);

CREATE INDEX IF NOT EXISTS idx_player_events_player_id_created_at
    ON player_events(player_id, created_at);
