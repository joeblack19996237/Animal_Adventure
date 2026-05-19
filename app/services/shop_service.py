from __future__ import annotations

import json
import logging
from pathlib import Path

from app.db import connect_db
from app.logging_config import emit_shop_purchase as _emit_shop_purchase

logger = logging.getLogger(__name__)


class ShopService:
    def __init__(self, db_path: Path, config_dir: Path) -> None:
        self._db_path = db_path
        self._shop_items = self._load_shop(config_dir)
        self._item_meta = self._load_items(config_dir)

    def _load_shop(self, config_dir: Path) -> dict[str, dict]:
        data: dict = json.loads((config_dir / "shop.json").read_text(encoding="utf-8"))
        return {i["item_id"]: i for i in data["items"]}

    def _load_items(self, config_dir: Path) -> dict[str, dict]:
        data: list[dict] = json.loads(
            (config_dir / "items.json").read_text(encoding="utf-8")
        )
        return {i["id"]: i for i in data}

    def purchase_item(self, player_id: str, item_id: str) -> dict:
        shop_entry = self._shop_items.get(item_id)
        if shop_entry is None:
            return {"type": "item_not_found"}

        price = int(shop_entry["price"])
        unlock_level = int(shop_entry.get("unlock_level", 0))
        item_cfg = self._item_meta.get(item_id, {})
        slot_type = item_cfg.get("slot_type", "inventory")
        stackable = bool(item_cfg.get("stackable", False))

        conn = connect_db(self._db_path)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT coins, level FROM players WHERE id=?",
                (player_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {"type": "player_not_found"}

            coins, level = int(row[0]), int(row[1])
            if level < unlock_level:
                conn.execute("ROLLBACK")
                return {"type": "item_locked"}
            if coins < price:
                conn.execute("ROLLBACK")
                return {"type": "insufficient_funds"}

            conn.execute(
                "UPDATE players SET coins = coins - ? WHERE id=?",
                (price, player_id),
            )
            if stackable:
                cursor = conn.execute(
                    "UPDATE player_inventory SET quantity = quantity + 1 "
                    "WHERE player_id=? AND item_id=? AND slot_type=?",
                    (player_id, item_id, slot_type),
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        "INSERT INTO player_inventory "
                        "(player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, ?)",
                        (player_id, item_id, slot_type),
                    )
            else:
                conn.execute(
                    "INSERT INTO player_inventory "
                    "(player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, ?)",
                    (player_id, item_id, slot_type),
                )
            new_coins = coins - price
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        _emit_shop_purchase(logger, player_id, item_id, price, new_coins)
        return {
            "type": "purchase_success",
            "item_id": item_id,
            "coins_balance": new_coins,
        }
