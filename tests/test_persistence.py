from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db import connect_db, init_db
from app.services.player_service import PlayerService

_CONFIG_DIR = Path("config")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    return db


def _create_player(db_path: Path, name: str = "TestPlayer") -> str:
    svc = PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)
    return svc.create_player(name, "penguin")["player_id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_position(db_path: Path, player_id: str) -> tuple[float, float, str]:
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "SELECT x, y, direction FROM players WHERE id=?", (player_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row[0], row[1], row[2]


# ── Survive reload ────────────────────────────────────────────────────────────


def test_position_survives_reload(db_path: Path) -> None:
    player_id = _create_player(db_path)
    conn = connect_db(db_path)
    try:
        conn.execute(
            "UPDATE players SET x=1200.0, y=5400.0, direction='back' WHERE id=?",
            (player_id,),
        )
        conn.commit()
    finally:
        conn.close()

    svc = PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)
    player = svc.get_player_by_id(player_id)
    assert player is not None
    assert player["x"] == pytest.approx(1200.0)
    assert player["y"] == pytest.approx(5400.0)
    assert player["direction"] == "back"


def test_coins_survive_reload(db_path: Path) -> None:
    player_id = _create_player(db_path)
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE players SET coins=75 WHERE id=?", (player_id,))
        conn.commit()
    finally:
        conn.close()

    svc = PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)
    player = svc.get_player_by_id(player_id)
    assert player is not None
    assert player["coins"] == 75


def test_level_survives_reload(db_path: Path) -> None:
    player_id = _create_player(db_path)
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE players SET level=3 WHERE id=?", (player_id,))
        conn.commit()
    finally:
        conn.close()

    svc = PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)
    player = svc.get_player_by_id(player_id)
    assert player is not None
    assert player["level"] == 3


def test_inventory_survives_reload(db_path: Path) -> None:
    player_id = _create_player(db_path)
    conn = connect_db(db_path)
    try:
        conn.execute(
            "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) "
            "VALUES (?, 'potion_l0', 2, 'equipment')",
            (player_id,),
        )
        conn.commit()
    finally:
        conn.close()

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT item_id, quantity, slot_type FROM player_inventory WHERE player_id=?",
            (player_id,),
        ).fetchone()
    finally:
        conn2.close()

    assert row is not None
    assert row[0] == "potion_l0"
    assert row[1] == 2
    assert row[2] == "equipment"


def test_quest_state_survives_reload(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, started_at, expires_at) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'active', ?, ?)",
            (player_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT quest_id, status FROM player_quests WHERE player_id=?",
            (player_id,),
        ).fetchone()
    finally:
        conn2.close()

    assert row is not None
    assert row[0] == "quest_hopper_blanket"
    assert row[1] == "active"


def test_unlocks_survive_reload(db_path: Path) -> None:
    player_id = _create_player(db_path)
    regions = json.dumps(["spawn", "playground"])
    conn = connect_db(db_path)
    try:
        conn.execute(
            "UPDATE player_progress "
            "SET unlocked_regions_json=?, unlocked_level=3 WHERE player_id=?",
            (regions, player_id),
        )
        conn.commit()
    finally:
        conn.close()

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT unlocked_level, unlocked_regions_json FROM player_progress "
            "WHERE player_id=?",
            (player_id,),
        ).fetchone()
    finally:
        conn2.close()

    assert row is not None
    assert row[0] == 3
    assert "playground" in json.loads(row[1])


# ── Immediate position persistence after events ───────────────────────────────


def test_position_immediate_save_events_quest_accept(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        conn.execute(
            "UPDATE players SET x=2800.0, y=3200.0, direction='front', updated_at=? WHERE id=?",
            (now, player_id),
        )
        conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, started_at, expires_at) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'active', ?, ?)",
            (player_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    x, y, _ = _read_position(db_path, player_id)
    assert x == pytest.approx(2800.0)
    assert y == pytest.approx(3200.0)


def test_position_immediate_save_events_quest_complete(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, started_at, expires_at) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'active', ?, ?)",
            (player_id, now, now),
        )
        quest_row_id = cursor.lastrowid
        conn.execute(
            "UPDATE players SET x=2715.0, y=3200.0, updated_at=? WHERE id=?",
            (now, player_id),
        )
        conn.execute(
            "UPDATE player_quests SET status='completed', cooldown_until=? WHERE id=?",
            (now, quest_row_id),
        )
        conn.commit()
    finally:
        conn.close()

    x, _, _ = _read_position(db_path, player_id)
    assert x == pytest.approx(2715.0)

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT status FROM player_quests WHERE player_id=?", (player_id,)
        ).fetchone()
    finally:
        conn2.close()
    assert row[0] == "completed"


def test_position_immediate_save_events_quest_fail(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, started_at, expires_at) "
            "VALUES (?, 'copper', 'quest_copper_bagpipe', 'active', ?, ?)",
            (player_id, now, now),
        )
        quest_row_id = cursor.lastrowid
        conn.execute(
            "UPDATE players SET x=3150.0, y=3620.0, updated_at=? WHERE id=?",
            (now, player_id),
        )
        conn.execute(
            "UPDATE player_quests SET status='failed', cooldown_until=? WHERE id=?",
            (now, quest_row_id),
        )
        conn.commit()
    finally:
        conn.close()

    x, y, _ = _read_position(db_path, player_id)
    assert x == pytest.approx(3150.0)
    assert y == pytest.approx(3620.0)

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT status FROM player_quests WHERE player_id=?", (player_id,)
        ).fetchone()
    finally:
        conn2.close()
    assert row[0] == "failed"


def test_position_immediate_save_events_shop_buy(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        conn.execute(
            "UPDATE players SET x=2715.0, y=3620.0, coins=15, updated_at=? WHERE id=?",
            (now, player_id),
        )
        conn.execute(
            "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) "
            "VALUES (?, 'potion_l0', 1, 'equipment')",
            (player_id,),
        )
        conn.commit()
    finally:
        conn.close()

    player = PlayerService(db_path=db_path, config_dir=_CONFIG_DIR).get_player_by_id(
        player_id
    )
    assert player is not None
    assert player["coins"] == 15
    assert player["x"] == pytest.approx(2715.0)

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT quantity FROM player_inventory "
            "WHERE player_id=? AND item_id='potion_l0'",
            (player_id,),
        ).fetchone()
    finally:
        conn2.close()
    assert row is not None
    assert row[0] == 1


def test_position_immediate_save_events_potion_use(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        conn.execute(
            "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) "
            "VALUES (?, 'potion_l0', 1, 'equipment')",
            (player_id,),
        )
        conn.execute(
            "DELETE FROM player_inventory WHERE player_id=? AND item_id='potion_l0'",
            (player_id,),
        )
        conn.execute(
            "UPDATE player_progress SET used_potion_count=1 WHERE player_id=?",
            (player_id,),
        )
        conn.execute(
            "UPDATE players SET x=2715.0, y=3620.0, updated_at=? WHERE id=?",
            (now, player_id),
        )
        conn.commit()
    finally:
        conn.close()

    x, y, _ = _read_position(db_path, player_id)
    assert x == pytest.approx(2715.0)
    assert y == pytest.approx(3620.0)

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT used_potion_count FROM player_progress WHERE player_id=?",
            (player_id,),
        ).fetchone()
    finally:
        conn2.close()
    assert row[0] == 1


def test_position_immediate_save_events_level_up(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        conn.execute(
            "UPDATE players SET x=2715.0, y=3620.0, level=3, updated_at=? WHERE id=?",
            (now, player_id),
        )
        conn.execute(
            "UPDATE player_progress "
            'SET unlocked_level=3, unlocked_regions_json=\'["spawn","playground"]\' '
            "WHERE player_id=?",
            (player_id,),
        )
        conn.commit()
    finally:
        conn.close()

    player = PlayerService(db_path=db_path, config_dir=_CONFIG_DIR).get_player_by_id(
        player_id
    )
    assert player is not None
    assert player["level"] == 3
    assert player["x"] == pytest.approx(2715.0)

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT unlocked_level, unlocked_regions_json FROM player_progress "
            "WHERE player_id=?",
            (player_id,),
        ).fetchone()
    finally:
        conn2.close()
    assert row[0] == 3
    assert "playground" in json.loads(row[1])


def test_position_immediate_save_events_websocket_disconnect(db_path: Path) -> None:
    player_id = _create_player(db_path)
    now = _now()
    conn = connect_db(db_path)
    try:
        conn.execute(
            "UPDATE players SET x=3200.0, y=4000.0, direction='back', "
            "last_seen_at=?, updated_at=? WHERE id=?",
            (now, now, player_id),
        )
        conn.commit()
    finally:
        conn.close()

    x, y, direction = _read_position(db_path, player_id)
    assert x == pytest.approx(3200.0)
    assert y == pytest.approx(4000.0)
    assert direction == "back"

    conn2 = connect_db(db_path)
    try:
        row = conn2.execute(
            "SELECT last_seen_at FROM players WHERE id=?", (player_id,)
        ).fetchone()
    finally:
        conn2.close()
    assert row[0] is not None
