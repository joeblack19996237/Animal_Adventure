from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import connect_db
from app.logging_config import emit_quest_auto_fail as _emit_quest_auto_fail

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 30


class QuestExpiryWorker:
    def __init__(self, db_path: Path, config_dir: Path) -> None:
        self._db_path = db_path
        self._quest_config = self._load_quest_config(config_dir)

    def _load_quest_config(self, config_dir: Path) -> dict[str, dict]:
        path = config_dir / "quests.json"
        quests: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        return {q["id"]: q for q in quests}

    def scan_expired_quests(self) -> list[dict]:
        """Find and fail all currently expired active quests. Returns list of failed quest descriptors."""
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()

        conn = connect_db(self._db_path)
        try:
            expired_rows = conn.execute(
                "SELECT id, player_id, quest_id, npc_id FROM player_quests "
                "WHERE status='active' AND expires_at < ?",
                (now_iso,),
            ).fetchall()
        finally:
            conn.close()

        results = []
        for row in expired_rows:
            quest_instance_id, player_id, quest_id, npc_id = row
            transitioned = self._fail_expired_quest(
                quest_instance_id=quest_instance_id,
                player_id=player_id,
                quest_id=quest_id,
                npc_id=npc_id,
                now_utc=now_utc,
            )
            if transitioned:
                results.append(
                    {
                        "quest_instance_id": quest_instance_id,
                        "player_id": player_id,
                        "quest_id": quest_id,
                        "npc_id": npc_id,
                    }
                )
        return results

    def _fail_expired_quest(
        self,
        quest_instance_id: int,
        player_id: str,
        quest_id: str,
        npc_id: str,
        now_utc: datetime,
    ) -> bool:
        """Apply the failure transition atomically. Returns True if the quest was transitioned."""
        quest_cfg = self._quest_config.get(quest_id, {})
        failure_cooldown = int(quest_cfg.get("failure_cooldown_seconds", 1800))
        cooldown_until = (now_utc + timedelta(seconds=failure_cooldown)).isoformat()

        conn = connect_db(self._db_path)
        try:
            cursor = conn.execute(
                "UPDATE player_quests SET status='failed', cooldown_until=? "
                "WHERE id=? AND status='active'",
                (cooldown_until, quest_instance_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                logger.debug(
                    "Quest %d already in terminal state; skipping expiry",
                    quest_instance_id,
                )
                return False
            conn.execute(
                "UPDATE world_item_instances SET status='expired' "
                "WHERE quest_instance_id=? AND status='spawned'",
                (quest_instance_id,),
            )
            conn.execute(
                "DELETE FROM quest_locks WHERE npc_id=?",
                (npc_id,),
            )
            conn.commit()
            _emit_quest_auto_fail(logger, player_id, quest_id, quest_instance_id)
            return True
        except Exception as e:
            conn.rollback()
            logger.error("Error failing expired quest %d: %s", quest_instance_id, e)
            raise
        finally:
            conn.close()
