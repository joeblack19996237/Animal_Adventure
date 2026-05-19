"""Quest expiry edge-case tests: post-commit notification, startup recovery, orphan lock
cleanup, and concurrent expiry-scan plus turn-in/pickup serialization."""

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


def _insert_active_quest(
    db_path: Path,
    player_id: str,
    npc_id: str = "hopper",
    quest_id: str = "quest_hopper_blanket",
    item_id: str = "item_blanket",
    expires_at: str | None = None,
) -> tuple[int, str]:
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


class TestNotificationAfterCommit:
    def test_scan_result_contains_quest_only_after_db_transition_committed(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(db_path, player_a["player_id"])
        results = expiry_worker.scan_expired_quests()
        assert any(r["quest_instance_id"] == quest_instance_id for r in results)
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "failed"

    def test_scan_excludes_already_terminal_quest_from_notification_results(
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
        results = expiry_worker.scan_expired_quests()
        assert not any(r["quest_instance_id"] == quest_instance_id for r in results)


class TestStartupScanPreRestartExpiry:
    def test_startup_scan_fails_quest_that_expired_during_downtime(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(600)
        )
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        row = conn.execute(
            "SELECT status, cooldown_until FROM player_quests WHERE id=?",
            (quest_instance_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "failed"
        assert row[1] is not None


class TestOrphanLockCleanup:
    def test_orphan_cleanup_deletes_lock_whose_quest_row_is_absent(
        self, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(db_path, player_a["player_id"])
        conn = connect_db(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM player_quests WHERE id=?", (quest_instance_id,))
        conn.commit()
        conn.close()
        deleted = clean_orphan_quest_locks(db_path)
        assert deleted == 1
        conn = connect_db(db_path)
        assert (
            conn.execute(
                "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
            ).fetchone()
            is None
        )
        conn.close()

    def test_orphan_cleanup_preserves_lock_with_existing_quest_row(
        self, player_a: dict, db_path: Path
    ) -> None:
        _insert_active_quest(db_path, player_a["player_id"])
        deleted = clean_orphan_quest_locks(db_path)
        assert deleted == 0
        conn = connect_db(db_path)
        assert (
            conn.execute(
                "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
            ).fetchone()
            is not None
        )
        conn.close()


class TestConcurrentExpiryScanAndTurnIn:
    def test_turn_in_wins_race_scanner_does_not_overwrite_completed(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, _ = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(1)
        )
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
        results = expiry_worker.scan_expired_quests()
        assert not any(r["quest_instance_id"] == quest_instance_id for r in results)
        conn = connect_db(db_path)
        assert (
            conn.execute(
                "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
            ).fetchone()[0]
            == "completed"
        )
        conn.close()

    def test_scanner_wins_race_item_is_expired_and_lock_is_released(
        self, expiry_worker: QuestExpiryWorker, player_a: dict, db_path: Path
    ) -> None:
        quest_instance_id, world_item_id = _insert_active_quest(
            db_path, player_a["player_id"], expires_at=_past_utc(5)
        )
        expiry_worker.scan_expired_quests()
        conn = connect_db(db_path)
        quest_status = conn.execute(
            "SELECT status FROM player_quests WHERE id=?", (quest_instance_id,)
        ).fetchone()[0]
        item_status = conn.execute(
            "SELECT status FROM world_item_instances WHERE id=?", (world_item_id,)
        ).fetchone()[0]
        lock_row = conn.execute(
            "SELECT npc_id FROM quest_locks WHERE npc_id='hopper'"
        ).fetchone()
        conn.close()
        assert quest_status == "failed"
        assert item_status == "expired"
        assert lock_row is None
