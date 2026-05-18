"""Tests for QuestExpiryWorker: expiry scan, startup recovery, and concurrent safety."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db import clean_orphan_quest_locks, connect_db, init_db
from app.services.player_service import PlayerService
from app.services.quest_expiry_worker import QuestExpiryWorker

_CONFIG_DIR = Path("config")


def _past_utc(seconds: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _future_utc(seconds: int = 300) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def expiry_worker(db_path: Path) -> QuestExpiryWorker:
    return QuestExpiryWorker(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player_service(db_path: Path) -> PlayerService:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player_a(player_service: PlayerService) -> dict:
    return player_service.create_player("Alice", "penguin")


@pytest.fixture
def player_b(player_service: PlayerService) -> dict:
    return player_service.create_player("Bob", "arctic_fox")


# ── helpers ───────────────────────────────────────────────────────────────────


def _insert_active_quest(
    db_path: Path,
    player_id: str,
    npc_id: str = "hopper",
    quest_id: str = "quest_hopper_blanket",
    item_id: str = "item_blanket",
    expires_at: str | None = None,
) -> tuple[int, str]:
    """Insert active quest with world item and lock. Returns (quest_instance_id, world_item_id)."""
    if expires_at is None:
        expires_at = _past_utc(10)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect_db(db_path)
    cursor = conn.execute(
        "INSERT INTO player_quests (player_id, npc_id, quest_id, status, started_at, expires_at) "
        "VALUES (?, ?, ?, 'active', ?, ?)",
        (player_id, npc_id, quest_id, now, expires_at),
    )
    assert cursor.lastrowid is not None
    quest_instance_id: int = cursor.lastrowid
    world_item_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO world_item_instances (id, quest_instance_id, item_id, x, y, status) "
        "VALUES (?, ?, ?, 2600.0, 3100.0, 'spawned')",
        (world_item_id, quest_instance_id, item_id),
    )
    conn.execute(
        "INSERT INTO quest_locks "
        "(npc_id, quest_id, quest_instance_id, player_id, expires_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (npc_id, quest_id, quest_instance_id, player_id, expires_at, now),
    )
    conn.commit()
    conn.close()
    return quest_instance_id, world_item_id


# ── core expiry scan ──────────────────────────────────────────────────────────


class TestQuestExpiryScan:
    def test_marks_expired_active_quest_as_failed(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(db_path, player_a["player_id"])
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "failed"

    def test_writes_failure_cooldown(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(db_path, player_a["player_id"])
        before = datetime.now(timezone.utc)
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT cooldown_until FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] is not None
        delta = (datetime.fromisoformat(row[0]) - before).total_seconds()
        assert 1790 <= delta <= 1810, f"failure cooldown delta {delta:.1f}s not ~1800s"

    def test_expires_world_item_instances(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        _, world_item_id = _insert_active_quest(db_path, player_a["player_id"])
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM world_item_instances WHERE id=?", (world_item_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "expired"

    def test_releases_npc_quest_lock(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        _insert_active_quest(db_path, player_a["player_id"], npc_id="hopper")
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        lock = conn.execute(
            "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert lock is None

    def test_preserves_completed_terminal_state(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(5)
        )
        conn = connect_db(db_path)
        conn.execute(
            "UPDATE player_quests SET status='completed' WHERE id=?",
            (quest_instance_id,),
        )
        conn.execute("DELETE FROM quest_locks WHERE npc_id='hopper'")
        conn.commit()
        conn.close()

        expiry_worker.scan_expired_quests()

        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "completed"

    def test_preserves_already_failed_terminal_state(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(5)
        )
        conn = connect_db(db_path)
        conn.execute(
            "UPDATE player_quests SET status='failed', cooldown_until=? WHERE id=?",
            (_future_utc(1800), quest_instance_id),
        )
        conn.execute("DELETE FROM quest_locks WHERE npc_id='hopper'")
        conn.commit()
        conn.close()

        expiry_worker.scan_expired_quests()

        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "failed"

    def test_ignores_active_quests_not_yet_expired(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_future_utc(300)
        )
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "active"

    def test_returns_list_of_failed_quest_descriptors(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(db_path, player_a["player_id"])
        results = expiry_worker.scan_expired_quests()
        assert len(results) == 1
        assert results[0]["quest_instance_id"] == quest_instance_id
        assert results[0]["player_id"] == player_a["player_id"]


# ── startup scan ──────────────────────────────────────────────────────────────


class TestQuestExpiryStartupScan:
    def test_fails_quest_that_expired_before_restart(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(900)
        )
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "failed"

    def test_orphan_lock_cleanup_deletes_locks_without_matching_quest_row(
        self, player_a: dict, db_path: Path
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = connect_db(db_path)
        cursor = conn.execute(
            "INSERT INTO player_quests "
            "(player_id, npc_id, quest_id, status, started_at, expires_at) "
            "VALUES (?, 'hopper', 'quest_hopper_blanket', 'active', ?, ?)",
            (player_a["player_id"], now, _past_utc(10)),
        )
        assert cursor.lastrowid is not None
        quest_instance_id: int = cursor.lastrowid
        conn.execute(
            "INSERT INTO quest_locks "
            "(npc_id, quest_id, quest_instance_id, player_id, expires_at, created_at) "
            "VALUES ('hopper', 'quest_hopper_blanket', ?, ?, ?, ?)",
            (quest_instance_id, player_a["player_id"], _past_utc(10), now),
        )
        conn.commit()
        # Disable FK to simulate legacy/corrupt state where CASCADE didn't fire
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM player_quests WHERE id=?", (quest_instance_id,))
        conn.commit()
        conn.close()

        deleted = clean_orphan_quest_locks(db_path)

        assert deleted >= 1
        conn = connect_db(db_path)
        lock = conn.execute(
            "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert lock is None

    def test_valid_active_quest_lock_not_deleted_by_orphan_cleanup(
        self, player_a: dict, db_path: Path
    ) -> None:
        _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_future_utc(300)
        )
        clean_orphan_quest_locks(db_path)
        conn = connect_db(db_path)
        lock = conn.execute(
            "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert lock is not None


# ── concurrent scanner + turn-in ─────────────────────────────────────────────


class TestQuestExpiryConcurrentTurnIn:
    def test_scanner_does_not_overwrite_completed_state_after_turn_in(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(1)
        )
        # Simulate turn-in path completing the quest before the scanner runs
        conn = connect_db(db_path)
        conn.execute(
            "UPDATE player_quests SET status='completed', cooldown_until=? "
            "WHERE id=? AND status='active'",
            (_future_utc(3600), quest_instance_id),
        )
        conn.execute(
            "UPDATE world_item_instances SET status='expired' WHERE quest_instance_id=?",
            (quest_instance_id,),
        )
        conn.execute("DELETE FROM quest_locks WHERE npc_id='hopper'")
        conn.commit()
        conn.close()

        expiry_worker.scan_expired_quests()

        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "completed"

    def test_scanner_failure_transition_is_idempotent(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(db_path, player_a["player_id"])
        expiry_worker.scan_expired_quests()
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "failed"

    def test_two_players_with_different_expired_quests_are_both_failed(
        self,
        expiry_worker: QuestExpiryWorker,
        player_a: dict,
        player_b: dict,
        db_path: Path,
    ) -> None:
        qid_a, _ = _insert_active_quest(
            db_path,
            player_a["player_id"],
            npc_id="hopper",
            quest_id="quest_hopper_blanket",
            expires_at=_past_utc(5),
        )
        qid_b, _ = _insert_active_quest(
            db_path,
            player_b["player_id"],
            npc_id="copper",
            quest_id="quest_copper_bagpipe",
            item_id="item_bagpipe",
            expires_at=_past_utc(5),
        )

        expiry_worker.scan_expired_quests()

        conn = connect_db(db_path)
        row_a = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (qid_a,)
        ).fetchone()
        row_b = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (qid_b,)
        ).fetchone()
        conn.close()
        assert row_a[0] == "failed"
        assert row_b[0] == "failed"
