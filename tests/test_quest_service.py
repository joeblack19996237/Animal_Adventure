"""Tests for QuestService: offer, accept, lock, pickup, turn-in, cooldowns, and radius checks.

TDD contract tests define the expected QuestService interface before implementation.
All scenarios use a real SQLite database via init_db and real config files from config/.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db import connect_db, init_db
from app.services.player_service import PlayerService
from app.services.quest_service import QuestService

_CONFIG_DIR = Path("config")

# NPC positions from config/npcs.json defaults
HOPPER_X, HOPPER_Y = 2715.0, 3200.0
COPPER_X, COPPER_Y = 3150.0, 3620.0
ELISA_X, ELISA_Y = 2715.0, 4050.0
NPC_INTERACTION_RADIUS = 160.0

# Item spawn positions from config/quests.json defaults
BLANKET_X, BLANKET_Y = 2600.0, 3100.0
BAGPIPE_X, BAGPIPE_Y = 3330.0, 3500.0
DANCE_SHOES_X, DANCE_SHOES_Y = 2830.0, 4250.0
ITEM_PICKUP_RADIUS = 96.0

INVENTORY_CAP = 20


# ── helpers ──────────────────────────────────────────────────────────────────


def _past_utc(seconds: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _future_utc(seconds: int = 300) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _expire_quest(db_path: Path, quest_instance_id: int, npc_id: str) -> None:
    """Backdate quest and lock expires_at so the quest appears expired."""
    past = _past_utc(10)
    conn = connect_db(db_path)
    conn.execute(
        "UPDATE player_quests SET expires_at=? WHERE id=?", (past, quest_instance_id)
    )
    conn.execute("UPDATE quest_locks SET expires_at=? WHERE npc_id=?", (past, npc_id))
    conn.commit()
    conn.close()


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def quest_service(db_path: Path) -> QuestService:
    return QuestService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player_service(db_path: Path) -> PlayerService:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player_a(player_service: PlayerService) -> dict:
    return player_service.create_player("Alice", "penguin")


@pytest.fixture
def player_b(player_service: PlayerService) -> dict:
    return player_service.create_player("Bob", "arctic_fox")


# ── quest offer ───────────────────────────────────────────────────────────────


class TestQuestOffer:
    def test_offer_returns_quest_offer_when_available(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_offer"
        assert result["quest_id"] == "quest_hopper_blanket"

    def test_offer_returns_quest_already_active_when_player_has_active_quest(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="copper",
            player_x=COPPER_X,
            player_y=COPPER_Y,
        )
        assert result["type"] == "quest_already_active"

    def test_offer_returns_quest_locked_when_another_player_holds_lock(
        self, quest_service: QuestService, player_a: dict, player_b: dict
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        result = quest_service.offer_quest(
            player_id=player_b["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_locked"

    def test_offer_returns_npc_out_of_range_when_player_too_far(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X + NPC_INTERACTION_RADIUS + 1,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "npc_out_of_range"

    def test_offer_returns_quest_on_cooldown_during_completion_cooldown(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        conn = connect_db(db_path)
        conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, cooldown_until) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'completed', ?)",
            (player_a["player_id"], _future_utc(3600)),
        )
        conn.commit()
        conn.close()
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_on_cooldown"
        assert "cooldown_until" in result

    def test_offer_returns_quest_on_cooldown_during_failure_cooldown(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        conn = connect_db(db_path)
        conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, cooldown_until) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'failed', ?)",
            (player_a["player_id"], _future_utc(1800)),
        )
        conn.commit()
        conn.close()
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_on_cooldown"

    def test_offer_succeeds_after_cooldown_expires(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        conn = connect_db(db_path)
        conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, cooldown_until) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'completed', ?)",
            (player_a["player_id"], _past_utc(1)),
        )
        conn.commit()
        conn.close()
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_offer"


# ── quest accept ──────────────────────────────────────────────────────────────


class TestQuestAccept:
    def test_accept_creates_active_quest_row(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "active"

    def test_accept_acquires_global_npc_lock(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        conn = connect_db(db_path)
        lock = conn.execute(
            "SELECT player_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert lock is not None
        assert lock[0] == player_a["player_id"]

    def test_accept_sets_utc_expires_at_from_time_limit(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        before = datetime.now(timezone.utc)
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT expires_at FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        conn.close()
        expires_at = datetime.fromisoformat(row[0])
        # time_limit_seconds=300; allow ±10s for test latency
        delta = (expires_at - before).total_seconds()
        assert 290 <= delta <= 310, (
            f"expires_at delta {delta:.1f}s not within [290, 310]"
        )

    def test_accept_spawns_world_item_instance_with_correct_item_id(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        result = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        conn = connect_db(db_path)
        items = conn.execute(
            "SELECT item_id, status FROM world_item_instances WHERE quest_instance_id=?",
            (result["quest_instance_id"],),
        ).fetchall()
        conn.close()
        assert len(items) == 1
        assert items[0][0] == "item_blanket"
        assert items[0][1] == "spawned"

    def test_accept_returns_quest_started_with_world_items(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        result = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        assert result["type"] == "quest_started"
        assert "expires_at" in result
        assert "quest_instance_id" in result
        assert "world_items" in result
        assert len(result["world_items"]) == 1
        item = result["world_items"][0]
        assert "id" in item
        assert item["item_id"] == "item_blanket"
        assert item["status"] == "spawned"

    def test_accept_returns_quest_already_active_when_player_has_active_quest(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        result = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="copper"
        )
        assert result["type"] == "quest_already_active"

    def test_accept_returns_quest_locked_when_another_player_holds_lock(
        self, quest_service: QuestService, player_a: dict, player_b: dict
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        result = quest_service.accept_quest(
            player_id=player_b["player_id"], npc_id="hopper"
        )
        assert result["type"] == "quest_locked"


# ── item pickup ───────────────────────────────────────────────────────────────


class TestItemPickup:
    def _accept_hopper(self, quest_service: QuestService, player_id: str) -> dict:
        return quest_service.accept_quest(player_id=player_id, npc_id="hopper")

    def test_pickup_succeeds_within_pickup_radius(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        item_instance_id = accepted["world_items"][0]["id"]
        result = quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        assert result["type"] == "item_picked_up"

    def test_pickup_rejected_outside_pickup_radius(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        item_instance_id = accepted["world_items"][0]["id"]
        result = quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X + ITEM_PICKUP_RADIUS + 1,
            player_y=BLANKET_Y,
        )
        assert result["type"] == "item_out_of_range"

    def test_pickup_marks_world_item_instance_picked_up(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        item_instance_id = accepted["world_items"][0]["id"]
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM world_item_instances WHERE id=?", (item_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "picked_up"

    def test_pickup_returns_inventory_full_when_inventory_at_cap(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        item_instance_id = accepted["world_items"][0]["id"]
        conn = connect_db(db_path)
        for i in range(INVENTORY_CAP):
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) "
                "VALUES (?, ?, 1, 'inventory')",
                (player_a["player_id"], f"dummy_item_{i}"),
            )
        conn.commit()
        conn.close()
        result = quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        assert result["type"] == "inventory_full"

    def test_inventory_full_does_not_fail_quest_or_expire_item(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        item_instance_id = accepted["world_items"][0]["id"]
        conn = connect_db(db_path)
        for i in range(INVENTORY_CAP):
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) "
                "VALUES (?, ?, 1, 'inventory')",
                (player_a["player_id"], f"dummy_item_{i}"),
            )
        conn.commit()
        conn.close()
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        # Quest must remain active and item must remain spawned
        conn = connect_db(db_path)
        quest_row = conn.execute(
            "SELECT status FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        item_row = conn.execute(
            "SELECT status FROM world_item_instances WHERE id=?", (item_instance_id,)
        ).fetchone()
        conn.close()
        assert quest_row[0] == "active"
        assert item_row[0] == "spawned"

    def test_pickup_fails_quest_when_expired(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        item_instance_id = accepted["world_items"][0]["id"]
        result = quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        assert result["type"] == "quest_failed"

    def test_pickup_by_non_owner_rejected(
        self, quest_service: QuestService, player_a: dict, player_b: dict
    ) -> None:
        accepted = self._accept_hopper(quest_service, player_a["player_id"])
        item_instance_id = accepted["world_items"][0]["id"]
        result = quest_service.pickup_item(
            player_id=player_b["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        assert result["type"] in ("quest_not_active", "item_not_found")


# ── quest turn-in ─────────────────────────────────────────────────────────────


def _accept_and_pickup_hopper(quest_service: QuestService, player_id: str) -> dict:
    accepted = quest_service.accept_quest(player_id=player_id, npc_id="hopper")
    quest_service.pickup_item(
        player_id=player_id,
        item_instance_id=accepted["world_items"][0]["id"],
        player_x=BLANKET_X,
        player_y=BLANKET_Y,
    )
    return accepted


class TestQuestTurnIn:
    def test_turn_in_returns_quest_completed(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        result = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_completed"

    def test_turn_in_grants_coins_and_updates_balance(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        result = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["coins_awarded"] == 25
        assert "coins_balance" in result
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT coins FROM players WHERE id=?", (player_a["player_id"],)
        ).fetchone()
        conn.close()
        assert row[0] == player_a["coins"] + 25

    def test_turn_in_grants_equipment_reward_for_hopper_quest(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT item_id FROM player_inventory "
            "WHERE player_id=? AND slot_type='equipment'",
            (player_a["player_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "accessory_sleepy_hat"

    def test_turn_in_sets_quest_status_to_completed(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        conn.close()
        assert row[0] == "completed"

    def test_turn_in_starts_60_minute_completion_cooldown(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        before = datetime.now(timezone.utc)
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT cooldown_until FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        conn.close()
        assert row[0] is not None
        cooldown_until = datetime.fromisoformat(row[0])
        # completion_cooldown_seconds=3600; allow ±10s for test latency
        delta = (cooldown_until - before).total_seconds()
        assert 3590 <= delta <= 3610, (
            f"completion cooldown delta {delta:.1f}s not ~3600s"
        )

    def test_turn_in_releases_npc_quest_lock(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        lock = conn.execute(
            "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert lock is None

    def test_turn_in_expires_world_item_instances(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        item_instance_id = accepted["world_items"][0]["id"]
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM world_item_instances WHERE id=?", (item_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "expired"

    def test_turn_in_updates_unique_completed_quest_ids(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT unique_completed_quest_ids_json FROM player_progress WHERE player_id=?",
            (player_a["player_id"],),
        ).fetchone()
        conn.close()
        unique_ids = json.loads(row[0])
        assert "quest_hopper_blanket" in unique_ids

    def test_turn_in_rejected_when_npc_too_far(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        result = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X + NPC_INTERACTION_RADIUS + 1,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "npc_out_of_range"

    def test_turn_in_fails_quest_when_expired(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        result = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_failed"

    def test_turn_in_fails_quest_when_expired_and_writes_failure_cooldown(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        before = datetime.now(timezone.utc)
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT cooldown_until FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        conn.close()
        assert row[0] is not None
        cooldown_until = datetime.fromisoformat(row[0])
        delta = (cooldown_until - before).total_seconds()
        # failure_cooldown_seconds=1800; allow ±10s
        assert 1790 <= delta <= 1810, f"failure cooldown delta {delta:.1f}s not ~1800s"


# ── idempotent turn-in replay ─────────────────────────────────────────────────


class TestQuestTurnInReplay:
    def test_turn_in_replay_returns_quest_completed_without_duplicate_rewards(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        first = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert first["type"] == "quest_completed"
        coins_after_first = (
            connect_db(db_path)
            .execute("SELECT coins FROM players WHERE id=?", (player_a["player_id"],))
            .fetchone()[0]
        )

        second = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert second["type"] == "quest_completed"
        coins_after_second = (
            connect_db(db_path)
            .execute("SELECT coins FROM players WHERE id=?", (player_a["player_id"],))
            .fetchone()[0]
        )
        assert coins_after_second == coins_after_first

    def test_turn_in_replay_returns_persisted_rewards_granted_json(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        first = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert "rewards_granted_json" in first
        assert len(first["rewards_granted_json"]) > 0

        second = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert second["rewards_granted_json"] == first["rewards_granted_json"]

    def test_turn_in_replay_works_without_active_lock(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        # Verify lock was released by first turn-in
        lock = (
            connect_db(db_path)
            .execute("SELECT npc_id FROM quest_locks WHERE npc_id='hopper'")
            .fetchone()
        )
        assert lock is None
        # Replay: completed quest row exists, no active lock — must still return completed
        replay = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert replay["type"] == "quest_completed"


# ── unique completed quest tracking ──────────────────────────────────────────


class TestUniqueCompletedQuestTracking:
    def _complete_quest(
        self,
        quest_service: QuestService,
        player_id: str,
        npc_id: str,
        item_x: float,
        item_y: float,
        npc_x: float,
        npc_y: float,
    ) -> None:
        accepted = quest_service.accept_quest(player_id=player_id, npc_id=npc_id)
        quest_service.pickup_item(
            player_id=player_id,
            item_instance_id=accepted["world_items"][0]["id"],
            player_x=item_x,
            player_y=item_y,
        )
        quest_service.turn_in_quest(
            player_id=player_id, npc_id=npc_id, player_x=npc_x, player_y=npc_y
        )

    def test_two_unique_quests_are_tracked_separately(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        self._complete_quest(
            quest_service,
            player_a["player_id"],
            "hopper",
            BLANKET_X,
            BLANKET_Y,
            HOPPER_X,
            HOPPER_Y,
        )
        self._complete_quest(
            quest_service,
            player_a["player_id"],
            "copper",
            BAGPIPE_X,
            BAGPIPE_Y,
            COPPER_X,
            COPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT unique_completed_quest_ids_json FROM player_progress WHERE player_id=?",
            (player_a["player_id"],),
        ).fetchone()
        conn.close()
        unique_ids = json.loads(row[0])
        assert "quest_hopper_blanket" in unique_ids
        assert "quest_copper_bagpipe" in unique_ids
        assert len(unique_ids) == 2

    def test_same_quest_completed_twice_does_not_duplicate_unique_id(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        self._complete_quest(
            quest_service,
            player_a["player_id"],
            "hopper",
            BLANKET_X,
            BLANKET_Y,
            HOPPER_X,
            HOPPER_Y,
        )
        # Force cooldown to expire so player can accept again
        conn = connect_db(db_path)
        conn.execute(
            "UPDATE player_quests SET cooldown_until=? WHERE player_id=? AND quest_id=?",
            (_past_utc(7200), player_a["player_id"], "quest_hopper_blanket"),
        )
        conn.commit()
        conn.close()
        self._complete_quest(
            quest_service,
            player_a["player_id"],
            "hopper",
            BLANKET_X,
            BLANKET_Y,
            HOPPER_X,
            HOPPER_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT unique_completed_quest_ids_json FROM player_progress WHERE player_id=?",
            (player_a["player_id"],),
        ).fetchone()
        conn.close()
        unique_ids = json.loads(row[0])
        assert unique_ids.count("quest_hopper_blanket") == 1


# ── cooldowns ─────────────────────────────────────────────────────────────────


class TestQuestCooldowns:
    def test_failure_via_pickup_starts_30_minute_failure_cooldown(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        before = datetime.now(timezone.utc)
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=accepted["world_items"][0]["id"],
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT cooldown_until FROM player_quests WHERE player_id=? AND quest_id=?",
            (player_a["player_id"], "quest_hopper_blanket"),
        ).fetchone()
        conn.close()
        assert row[0] is not None
        cooldown_until = datetime.fromisoformat(row[0])
        delta = (cooldown_until - before).total_seconds()
        assert 1790 <= delta <= 1810, f"failure cooldown delta {delta:.1f}s not ~1800s"

    def test_completion_cooldown_blocks_re_offer(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_on_cooldown"

    def test_failure_cooldown_blocks_re_offer(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=accepted["world_items"][0]["id"],
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_on_cooldown"

    def test_failure_via_pickup_expires_world_item_instances(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        item_instance_id = accepted["world_items"][0]["id"]
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM world_item_instances WHERE id=?", (item_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "expired"

    def test_failure_via_pickup_releases_quest_lock(
        self, quest_service: QuestService, player_a: dict, db_path: Path
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        _expire_quest(db_path, accepted["quest_instance_id"], "hopper")
        quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=accepted["world_items"][0]["id"],
            player_x=BLANKET_X,
            player_y=BLANKET_Y,
        )
        conn = connect_db(db_path)
        lock = conn.execute(
            "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert lock is None


# ── active-quest conflict ─────────────────────────────────────────────────────


class TestActiveQuestConflict:
    def test_offer_returns_quest_already_active_for_different_npc(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="copper",
            player_x=COPPER_X,
            player_y=COPPER_Y,
        )
        assert result["type"] == "quest_already_active"

    def test_second_player_sees_quest_locked_while_first_player_active(
        self, quest_service: QuestService, player_a: dict, player_b: dict
    ) -> None:
        quest_service.accept_quest(player_id=player_a["player_id"], npc_id="hopper")
        result = quest_service.offer_quest(
            player_id=player_b["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_locked"

    def test_lock_released_after_completion_allows_second_player_to_accept(
        self, quest_service: QuestService, player_a: dict, player_b: dict
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        result = quest_service.offer_quest(
            player_id=player_b["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "quest_offer"


# ── server-authoritative radius checks ───────────────────────────────────────


class TestServerAuthoritativeRadiusChecks:
    def test_npc_offer_rejects_player_position_beyond_interaction_radius(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X + NPC_INTERACTION_RADIUS + 50,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "npc_out_of_range"

    def test_npc_turn_in_rejects_player_position_beyond_interaction_radius(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        _accept_and_pickup_hopper(quest_service, player_a["player_id"])
        result = quest_service.turn_in_quest(
            player_id=player_a["player_id"],
            npc_id="hopper",
            player_x=HOPPER_X + NPC_INTERACTION_RADIUS + 50,
            player_y=HOPPER_Y,
        )
        assert result["type"] == "npc_out_of_range"

    def test_item_pickup_rejects_player_position_beyond_pickup_radius(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        item_instance_id = accepted["world_items"][0]["id"]
        result = quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X + ITEM_PICKUP_RADIUS + 50,
            player_y=BLANKET_Y,
        )
        assert result["type"] == "item_out_of_range"

    @pytest.mark.parametrize(
        "npc_id,npc_x,npc_y",
        [
            ("hopper", HOPPER_X, HOPPER_Y),
            ("copper", COPPER_X, COPPER_Y),
            ("elisa", ELISA_X, ELISA_Y),
        ],
    )
    def test_all_mvp_npcs_enforce_interaction_radius(
        self,
        quest_service: QuestService,
        player_a: dict,
        npc_id: str,
        npc_x: float,
        npc_y: float,
    ) -> None:
        result = quest_service.offer_quest(
            player_id=player_a["player_id"],
            npc_id=npc_id,
            player_x=npc_x + NPC_INTERACTION_RADIUS + 1,
            player_y=npc_y,
        )
        assert result["type"] == "npc_out_of_range"

    def test_pickup_succeeds_at_exact_pickup_radius_boundary(
        self, quest_service: QuestService, player_a: dict
    ) -> None:
        accepted = quest_service.accept_quest(
            player_id=player_a["player_id"], npc_id="hopper"
        )
        item_instance_id = accepted["world_items"][0]["id"]
        result = quest_service.pickup_item(
            player_id=player_a["player_id"],
            item_instance_id=item_instance_id,
            player_x=BLANKET_X + ITEM_PICKUP_RADIUS,
            player_y=BLANKET_Y,
        )
        assert result["type"] == "item_picked_up"
