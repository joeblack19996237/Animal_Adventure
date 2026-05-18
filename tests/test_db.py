import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from app.db import clean_orphan_quest_locks, connect_db, init_db

REQUIRED_TABLES = [
    "players",
    "player_progress",
    "player_inventory",
    "player_quests",
    "quest_locks",
    "world_item_instances",
    "player_events",
]

_PLAYER_ROW = (
    "INSERT INTO players "
    "(id, name, normalized_name, character_id, x, y, direction, level, coins, created_at, updated_at) "
    "VALUES (?, ?, ?, 'penguin', 0.0, 0.0, 'down', 0, 25, '2024-01-01T00:00:00', '2024-01-01T00:00:00')"
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    connection = connect_db(db_path)
    yield connection
    connection.close()


@pytest.mark.parametrize("table", REQUIRED_TABLES)
def test_required_table_exists(conn: sqlite3.Connection, table: str) -> None:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    assert cursor.fetchone() is not None, f"Table '{table}' not found in schema"


def test_pragma_journal_mode_wal(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0] == "wal"


def test_pragma_foreign_keys_enabled(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1


def test_pragma_busy_timeout(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA busy_timeout")
    assert cursor.fetchone()[0] == 5000


def test_quest_locks_cascade_on_delete(db_path: Path) -> None:
    conn = connect_db(db_path)

    conn.execute(_PLAYER_ROW, ("p1", "Test", "test"))
    conn.execute(
        "INSERT INTO player_quests "
        "(player_id, npc_id, quest_id, status, progress_json, rewards_granted_json) "
        "VALUES ('p1', 'hopper', 'quest_hopper_blanket', 'active', '{}', '[]')"
    )
    quest_instance_id = conn.execute(
        "SELECT id FROM player_quests WHERE player_id='p1'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO quest_locks "
        "(npc_id, quest_id, quest_instance_id, player_id, expires_at, created_at) "
        "VALUES ('hopper', 'quest_hopper_blanket', ?, 'p1', '2024-01-01T01:00:00', '2024-01-01T00:00:00')",
        (quest_instance_id,),
    )
    conn.commit()

    lock_before = conn.execute(
        "SELECT * FROM quest_locks WHERE npc_id='hopper'"
    ).fetchone()
    assert lock_before is not None, "Lock must exist before parent deletion"

    conn.execute("DELETE FROM player_quests WHERE id=?", (quest_instance_id,))
    conn.commit()

    lock_after = conn.execute(
        "SELECT * FROM quest_locks WHERE npc_id='hopper'"
    ).fetchone()
    assert lock_after is None, "quest_locks row must be removed via ON DELETE CASCADE"
    conn.close()


def test_startup_cleans_orphan_quest_locks(db_path: Path) -> None:
    conn = connect_db(db_path)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(_PLAYER_ROW, ("p2", "Ghost", "ghost"))
    conn.execute(
        "INSERT INTO quest_locks "
        "(npc_id, quest_id, quest_instance_id, player_id, expires_at, created_at) "
        "VALUES ('copper', 'quest_copper_bagpipe', 9999, 'p2', '2024-01-01T01:00:00', '2024-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    deleted_count = clean_orphan_quest_locks(db_path)

    conn2 = connect_db(db_path)
    orphan = conn2.execute("SELECT * FROM quest_locks WHERE npc_id='copper'").fetchone()
    conn2.close()

    assert orphan is None, "Orphan quest lock must be deleted by startup recovery"
    assert deleted_count >= 1
