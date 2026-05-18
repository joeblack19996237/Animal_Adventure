from __future__ import annotations

import json
import logging
from pathlib import Path

from app.db import connect_db

logger = logging.getLogger(__name__)

INVENTORY_CAP = 20


class InventoryService:
    def __init__(self, db_path: Path, config_dir: Path) -> None:
        self._db_path = db_path
        self._items = self._load_items(config_dir)

    def _load_items(self, config_dir: Path) -> dict[str, dict]:
        data: list[dict] = json.loads(
            (config_dir / "items.json").read_text(encoding="utf-8")
        )
        return {i["id"]: i for i in data}

    def _item_meta(self, item_id: str) -> tuple[str, bool, str]:
        """Return (slot_type, stackable, item_type); defaults for unknown items."""
        cfg = self._items.get(item_id)
        if cfg is None:
            return "inventory", False, "unknown"
        return (
            cfg.get("slot_type", "inventory"),
            bool(cfg.get("stackable", False)),
            cfg.get("type", "unknown"),
        )

    def add_item(self, player_id: str, item_id: str, quantity: int = 1) -> dict:
        slot_type, stackable, _ = self._item_meta(item_id)
        if slot_type == "none":
            return {"type": "item_added"}

        conn = connect_db(self._db_path)
        conn.isolation_level = None  # manual transaction control
        try:
            conn.execute("BEGIN IMMEDIATE")
            if slot_type == "inventory":
                count = conn.execute(
                    "SELECT COUNT(*) FROM player_inventory "
                    "WHERE player_id=? AND slot_type='inventory'",
                    (player_id,),
                ).fetchone()[0]
                if count >= INVENTORY_CAP:
                    conn.execute("ROLLBACK")
                    return {"type": "inventory_full"}

            if stackable:
                cursor = conn.execute(
                    "UPDATE player_inventory SET quantity = quantity + ? "
                    "WHERE player_id=? AND item_id=? AND slot_type=?",
                    (quantity, player_id, item_id, slot_type),
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        "INSERT INTO player_inventory "
                        "(player_id, item_id, quantity, slot_type) VALUES (?, ?, ?, ?)",
                        (player_id, item_id, quantity, slot_type),
                    )
            else:
                conn.execute(
                    "INSERT INTO player_inventory "
                    "(player_id, item_id, quantity, slot_type) VALUES (?, ?, ?, ?)",
                    (player_id, item_id, quantity, slot_type),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        return {"type": "item_added"}

    def use_item(self, player_id: str, item_id: str) -> dict:
        _, _, item_type = self._item_meta(item_id)
        is_consumable = item_type == "consumable"

        conn = connect_db(self._db_path)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, quantity FROM player_inventory "
                "WHERE player_id=? AND item_id=?",
                (player_id, item_id),
            ).fetchone()
            if row is None or row[1] <= 0:
                conn.execute("ROLLBACK")
                return {"type": "item_not_found"}

            row_id, qty = row
            if qty == 1:
                conn.execute("DELETE FROM player_inventory WHERE id=?", (row_id,))
            else:
                conn.execute(
                    "UPDATE player_inventory SET quantity = quantity - 1 WHERE id=?",
                    (row_id,),
                )

            if is_consumable:
                conn.execute(
                    "UPDATE player_progress "
                    "SET used_potion_count = used_potion_count + 1 "
                    "WHERE player_id=?",
                    (player_id,),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        return {"type": "item_used"}

    def list_inventory(self, player_id: str) -> list[dict]:
        conn = connect_db(self._db_path)
        try:
            rows = conn.execute(
                "SELECT item_id, quantity, slot_index FROM player_inventory "
                "WHERE player_id=? AND slot_type='inventory'",
                (player_id,),
            ).fetchall()
            return [
                {"item_id": r[0], "quantity": r[1], "slot_index": r[2]} for r in rows
            ]
        finally:
            conn.close()

    def list_equipment(self, player_id: str) -> list[dict]:
        conn = connect_db(self._db_path)
        try:
            rows = conn.execute(
                "SELECT item_id, quantity, slot_index FROM player_inventory "
                "WHERE player_id=? AND slot_type='equipment'",
                (player_id,),
            ).fetchall()
            return [
                {"item_id": r[0], "quantity": r[1], "slot_index": r[2]} for r in rows
            ]
        finally:
            conn.close()
