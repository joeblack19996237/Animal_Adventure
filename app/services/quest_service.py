from __future__ import annotations

import json
import logging
import math
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import connect_db
from app.logging_config import emit_quest_complete as _emit_quest_complete

logger = logging.getLogger(__name__)

INVENTORY_CAP = 20


class QuestService:
    def __init__(self, db_path: Path, config_dir: Path) -> None:
        self._db_path = db_path
        self._npcs = self._load_npcs(config_dir)
        self._quests = self._load_quests(config_dir)

    def _load_npcs(self, config_dir: Path) -> dict[str, dict]:
        data: list[dict] = json.loads(
            (config_dir / "npcs.json").read_text(encoding="utf-8")
        )
        return {n["id"]: n for n in data}

    def _load_quests(self, config_dir: Path) -> dict[str, dict]:
        data: list[dict] = json.loads(
            (config_dir / "quests.json").read_text(encoding="utf-8")
        )
        return {q["id"]: q for q in data}

    def npc_id_for_quest(self, quest_id: str) -> str | None:
        for npc_id, npc in self._npcs.items():
            if npc.get("quest_id") == quest_id:
                return npc_id
        return None

    @staticmethod
    def _dist(x1: float, y1: float, x2: float, y2: float) -> float:
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def offer_quest(
        self,
        player_id: str,
        npc_id: str,
        player_x: float,
        player_y: float,
    ) -> dict:
        npc = self._npcs.get(npc_id)
        if npc is None:
            return {"type": "npc_not_found"}
        if (
            self._dist(player_x, player_y, float(npc["x"]), float(npc["y"]))
            > npc["interaction_radius"]
        ):
            return {"type": "npc_out_of_range"}
        quest_id = npc["quest_id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = connect_db(self._db_path)
        try:
            active = conn.execute(
                "SELECT id FROM player_quests WHERE player_id=? AND status='active'",
                (player_id,),
            ).fetchone()
            if active:
                return {"type": "quest_already_active"}
            cooldown = conn.execute(
                "SELECT cooldown_until FROM player_quests "
                "WHERE player_id=? AND quest_id=? AND status IN ('completed','failed') "
                "AND cooldown_until > ? ORDER BY id DESC LIMIT 1",
                (player_id, quest_id, now_iso),
            ).fetchone()
            if cooldown:
                return {"type": "quest_on_cooldown", "cooldown_until": cooldown[0]}
            lock = conn.execute(
                "SELECT player_id FROM quest_locks WHERE npc_id=?", (npc_id,)
            ).fetchone()
            if lock and lock[0] != player_id:
                return {"type": "quest_locked"}
        finally:
            conn.close()
        quest_cfg = self._quests.get(quest_id)
        if quest_cfg is None:
            return {"type": "quest_not_found"}
        return {
            "type": "quest_offer",
            "npc_id": npc_id,
            "quest_id": quest_id,
            "title": str(quest_cfg.get("title", quest_id)),
            "time_limit_seconds": int(quest_cfg.get("time_limit_seconds", 0)),
            "rewards": quest_cfg.get("rewards", []),
        }

    def _check_accept_guards(
        self, conn: sqlite3.Connection, player_id: str, npc_id: str
    ) -> dict | None:
        active = conn.execute(
            "SELECT id FROM player_quests WHERE player_id=? AND status='active'",
            (player_id,),
        ).fetchone()
        if active:
            return {"type": "quest_already_active"}
        lock = conn.execute(
            "SELECT player_id FROM quest_locks WHERE npc_id=?", (npc_id,)
        ).fetchone()
        if lock and lock[0] != player_id:
            return {"type": "quest_locked"}
        return None

    def _insert_quest_lock(
        self,
        conn: sqlite3.Connection,
        npc_id: str,
        quest_id: str,
        quest_instance_id: int,
        player_id: str,
        expires_at: str,
        now_iso: str,
    ) -> None:
        conn.execute(
            "INSERT INTO quest_locks "
            "(npc_id, quest_id, quest_instance_id, player_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (npc_id, quest_id, quest_instance_id, player_id, expires_at, now_iso),
        )

    def _spawn_quest_items(
        self, conn: sqlite3.Connection, quest_instance_id: int, quest_cfg: dict
    ) -> list[dict]:
        item_spawn = quest_cfg["item_spawn"]
        world_items = []
        for item_id in quest_cfg["required_items"]:
            wid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO world_item_instances "
                "(id, quest_instance_id, item_id, x, y, status) VALUES (?, ?, ?, ?, ?, 'spawned')",
                (wid, quest_instance_id, item_id, item_spawn["x"], item_spawn["y"]),
            )
            world_items.append(
                {
                    "id": wid,
                    "item_id": item_id,
                    "x": item_spawn["x"],
                    "y": item_spawn["y"],
                    "status": "spawned",
                }
            )
        return world_items

    def accept_quest(self, player_id: str, npc_id: str) -> dict:
        npc = self._npcs.get(npc_id)
        if npc is None:
            return {"type": "npc_not_found"}
        quest_id = npc["quest_id"]
        quest_cfg = self._quests.get(quest_id)
        if quest_cfg is None:
            return {"type": "quest_not_found"}
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        expires_at = (
            now_utc + timedelta(seconds=int(quest_cfg["time_limit_seconds"]))
        ).isoformat()

        conn = connect_db(self._db_path)
        try:
            guard = self._check_accept_guards(conn, player_id, npc_id)
            if guard:
                return guard
            cursor = conn.execute(
                "INSERT INTO player_quests "
                "(player_id, npc_id, quest_id, status, started_at, expires_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (player_id, npc_id, quest_id, now_iso, expires_at),
            )
            quest_instance_id: int = cursor.lastrowid  # type: ignore[assignment]
            self._insert_quest_lock(
                conn,
                npc_id,
                quest_id,
                quest_instance_id,
                player_id,
                expires_at,
                now_iso,
            )
            world_items = self._spawn_quest_items(conn, quest_instance_id, quest_cfg)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        logger.info(
            "Quest accepted player=%s quest_id=%s instance=%d",
            player_id,
            quest_id,
            quest_instance_id,
        )
        return {
            "type": "quest_started",
            "quest_instance_id": quest_instance_id,
            "quest_id": quest_id,
            "expires_at": expires_at,
            "world_items": world_items,
        }

    def _do_pickup_write(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        item_instance_id: str,
        quest_instance_id: int,
        item_id: str,
    ) -> dict | None:
        """Executes pickup DB writes. Returns None on success or an error dict (no writes committed)."""
        count = conn.execute(
            "SELECT COUNT(*) FROM player_inventory WHERE player_id=? AND slot_type='inventory'",
            (player_id,),
        ).fetchone()[0]
        if count >= INVENTORY_CAP:
            return {"type": "inventory_full"}
        cursor = conn.execute(
            "UPDATE world_item_instances SET status='picked_up' WHERE id=? AND status='spawned'",
            (item_instance_id,),
        )
        if cursor.rowcount == 0:
            return {"type": "item_not_found"}
        conn.execute(
            "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) "
            "VALUES (?, ?, 1, 'inventory')",
            (player_id, item_id),
        )
        pq = conn.execute(
            "SELECT progress_json FROM player_quests WHERE id=?",
            (quest_instance_id,),
        ).fetchone()
        progress = json.loads(pq[0])
        collected: list[str] = progress.get("collected_items", [])
        collected.append(item_id)
        progress["collected_items"] = collected
        conn.execute(
            "UPDATE player_quests SET progress_json=? WHERE id=?",
            (json.dumps(progress), quest_instance_id),
        )
        return None

    def pickup_item(
        self, player_id: str, item_instance_id: str, player_x: float, player_y: float
    ) -> dict:
        conn = connect_db(self._db_path)
        try:
            row = conn.execute(
                "SELECT wi.item_id, wi.x, wi.y, wi.status, wi.quest_instance_id, "
                "pq.player_id, pq.quest_id, pq.npc_id, pq.expires_at "
                "FROM world_item_instances wi "
                "JOIN player_quests pq ON wi.quest_instance_id = pq.id "
                "WHERE wi.id=?",
                (item_instance_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None or row[5] != player_id or row[3] != "spawned":
            return {"type": "item_not_found"}
        item_id, item_x, item_y = row[0], float(row[1]), float(row[2])
        quest_instance_id, quest_id, npc_id, expires_at = row[4], row[6], row[7], row[8]
        quest_cfg = self._quests.get(quest_id)
        if quest_cfg is None:
            return {"type": "quest_not_found"}
        if self._dist(player_x, player_y, item_x, item_y) > float(
            quest_cfg["item_spawn"]["pickup_radius"]
        ):
            return {"type": "item_out_of_range"}
        now_utc = datetime.now(timezone.utc)
        if expires_at and now_utc.isoformat() > expires_at:
            return self._apply_failure(
                quest_instance_id, player_id, quest_id, npc_id, now_utc
            )

        conn = connect_db(self._db_path)
        try:
            err = self._do_pickup_write(
                conn, player_id, item_instance_id, quest_instance_id, item_id
            )
            if err is not None:
                conn.rollback()
                return err
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"type": "item_picked_up", "quest_id": quest_id, "item_id": item_id}

    def _apply_failure(
        self,
        quest_instance_id: int,
        player_id: str,
        quest_id: str,
        npc_id: str,
        now_utc: datetime,
    ) -> dict:
        quest_cfg = self._quests.get(quest_id, {})
        cooldown_secs = int(quest_cfg.get("failure_cooldown_seconds", 1800))
        cooldown_until = (now_utc + timedelta(seconds=cooldown_secs)).isoformat()
        conn = connect_db(self._db_path)
        try:
            cursor = conn.execute(
                "UPDATE player_quests SET status='failed', cooldown_until=? WHERE id=? AND status='active'",
                (cooldown_until, quest_instance_id),
            )
            if cursor.rowcount > 0:
                conn.execute(
                    "UPDATE world_item_instances SET status='expired' "
                    "WHERE quest_instance_id=? AND status='spawned'",
                    (quest_instance_id,),
                )
                conn.execute("DELETE FROM quest_locks WHERE npc_id=?", (npc_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        logger.info(
            "Quest failed player=%s quest_id=%s instance=%d",
            player_id,
            quest_id,
            quest_instance_id,
        )
        return {
            "type": "quest_failed",
            "quest_id": quest_id,
            "cooldown_until": cooldown_until,
        }

    def turn_in_quest(
        self, player_id: str, npc_id: str, player_x: float, player_y: float
    ) -> dict:
        npc = self._npcs.get(npc_id)
        if npc is None:
            return {"type": "npc_not_found"}
        if (
            self._dist(player_x, player_y, float(npc["x"]), float(npc["y"]))
            > npc["interaction_radius"]
        ):
            return {"type": "npc_out_of_range"}
        quest_id = npc["quest_id"]
        conn = connect_db(self._db_path)
        try:
            row = conn.execute(
                "SELECT id, status, expires_at, rewards_granted_json FROM player_quests "
                "WHERE player_id=? AND quest_id=? ORDER BY id DESC LIMIT 1",
                (player_id, quest_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"type": "quest_not_active"}
        quest_instance_id, status, expires_at, rewards_str = row
        if status == "completed":
            return {
                "type": "quest_completed",
                "quest_id": quest_id,
                "coins_awarded": 0,
                "rewards_granted_json": json.loads(rewards_str),
            }
        if status != "active":
            return {"type": "quest_not_active"}
        now_utc = datetime.now(timezone.utc)
        if expires_at and now_utc.isoformat() > expires_at:
            return self._apply_failure(
                quest_instance_id, player_id, quest_id, npc_id, now_utc
            )
        return self._complete_quest(
            quest_instance_id, player_id, quest_id, npc_id, now_utc
        )

    def _grant_quest_rewards_in_transaction(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        quest_id: str,
        rewards: list[dict],
        coins_awarded: int,
    ) -> None:
        if coins_awarded > 0:
            conn.execute(
                "UPDATE players SET coins = coins + ? WHERE id=?",
                (coins_awarded, player_id),
            )
        for reward in rewards:
            if reward.get("type") == "equipment":
                conn.execute(
                    "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) VALUES (?, ?, ?, 'equipment')",
                    (player_id, reward["item_id"], int(reward.get("quantity", 1))),
                )
        prog = conn.execute(
            "SELECT unique_completed_quest_ids_json FROM player_progress WHERE player_id=?",
            (player_id,),
        ).fetchone()
        unique_ids: list[str] = json.loads(prog[0])
        if quest_id not in unique_ids:
            unique_ids.append(quest_id)
        conn.execute(
            "UPDATE player_progress SET unique_completed_quest_ids_json=? WHERE player_id=?",
            (json.dumps(unique_ids), player_id),
        )

    def _write_quest_completion(
        self,
        conn: sqlite3.Connection,
        quest_instance_id: int,
        player_id: str,
        quest_id: str,
        npc_id: str,
        cooldown_until: str,
        rewards: list[dict],
        rewards_json: str,
        coins_awarded: int,
    ) -> tuple[int, list[dict] | None]:
        cursor = conn.execute(
            "UPDATE player_quests SET status='completed', cooldown_until=?, rewards_granted_json=? "
            "WHERE id=? AND status='active'",
            (cooldown_until, rewards_json, quest_instance_id),
        )
        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT rewards_granted_json FROM player_quests WHERE id=?",
                (quest_instance_id,),
            ).fetchone()
            return 0, json.loads(row[0]) if row else []
        self._grant_quest_rewards_in_transaction(
            conn, player_id, quest_id, rewards, coins_awarded
        )
        conn.execute(
            "UPDATE world_item_instances SET status='expired' WHERE quest_instance_id=?",
            (quest_instance_id,),
        )
        conn.execute("DELETE FROM quest_locks WHERE npc_id=?", (npc_id,))
        coins_balance: int = conn.execute(
            "SELECT coins FROM players WHERE id=?", (player_id,)
        ).fetchone()[0]
        return coins_balance, None

    def _complete_quest(
        self,
        quest_instance_id: int,
        player_id: str,
        quest_id: str,
        npc_id: str,
        now_utc: datetime,
    ) -> dict:
        quest_cfg = self._quests.get(quest_id)
        if quest_cfg is None:
            return {"type": "quest_not_found"}
        cooldown_secs = int(quest_cfg.get("completion_cooldown_seconds", 3600))
        cooldown_until = (now_utc + timedelta(seconds=cooldown_secs)).isoformat()
        rewards: list[dict] = quest_cfg.get("rewards", [])
        rewards_json = json.dumps(rewards)
        coins_awarded = sum(
            int(r["amount"]) for r in rewards if r.get("type") == "coins"
        )
        conn = connect_db(self._db_path)
        try:
            coins_balance, already_granted = self._write_quest_completion(
                conn,
                quest_instance_id,
                player_id,
                quest_id,
                npc_id,
                cooldown_until,
                rewards,
                rewards_json,
                coins_awarded,
            )
            if already_granted is not None:
                conn.rollback()
                return {
                    "type": "quest_completed",
                    "quest_id": quest_id,
                    "coins_awarded": 0,
                    "rewards_granted_json": already_granted,
                }
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _emit_quest_complete(
            logger, player_id, quest_id, quest_instance_id, coins_awarded
        )
        return {
            "type": "quest_completed",
            "quest_id": quest_id,
            "coins_awarded": coins_awarded,
            "coins_balance": coins_balance,
            "rewards_granted_json": rewards,
        }
