"""Tests for ShopService: Potion purchase, insufficient funds, invalid/locked item, concurrency."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.db import connect_db, init_db
from app.services.player_service import PlayerService
from app.services.shop_service import ShopService

_CONFIG_DIR = Path("config")
POTION_ID = "potion_l0"
POTION_PRICE = 10
INITIAL_COINS = 25


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def svc(db_path: Path) -> ShopService:
    return ShopService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player(db_path: Path) -> dict:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR).create_player(
        "Alice", "penguin"
    )


def _get_coins(db_path: Path, player_id: str) -> int:
    conn = connect_db(db_path)
    row = conn.execute("SELECT coins FROM players WHERE id=?", (player_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def _get_equipment_qty(db_path: Path, player_id: str, item_id: str) -> int:
    conn = connect_db(db_path)
    row = conn.execute(
        "SELECT quantity FROM player_inventory "
        "WHERE player_id=? AND item_id=? AND slot_type='equipment'",
        (player_id, item_id),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


class TestPotionPurchaseSuccess:
    def test_purchase_deducts_coins(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        result = svc.purchase_item(player["player_id"], POTION_ID)
        assert result["type"] == "purchase_success"
        assert _get_coins(db_path, player["player_id"]) == INITIAL_COINS - POTION_PRICE

    def test_purchase_adds_potion_to_equipment(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        svc.purchase_item(player["player_id"], POTION_ID)
        assert _get_equipment_qty(db_path, player["player_id"], POTION_ID) == 1

    def test_purchase_returns_updated_coin_balance(
        self, svc: ShopService, player: dict
    ) -> None:
        result = svc.purchase_item(player["player_id"], POTION_ID)
        assert result["coins_balance"] == INITIAL_COINS - POTION_PRICE

    def test_multiple_purchases_stack_potion(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        svc.purchase_item(pid, POTION_ID)
        svc.purchase_item(pid, POTION_ID)
        assert _get_equipment_qty(db_path, pid, POTION_ID) == 2


class TestInsufficientFunds:
    def test_returns_insufficient_funds_when_broke(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        conn = connect_db(db_path)
        conn.execute("UPDATE players SET coins=0 WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        result = svc.purchase_item(pid, POTION_ID)
        assert result["type"] == "insufficient_funds"

    def test_coins_unchanged_after_failed_purchase(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        conn = connect_db(db_path)
        conn.execute("UPDATE players SET coins=5 WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        svc.purchase_item(pid, POTION_ID)
        assert _get_coins(db_path, pid) == 5

    def test_no_item_added_after_failed_purchase(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        conn = connect_db(db_path)
        conn.execute("UPDATE players SET coins=0 WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        svc.purchase_item(pid, POTION_ID)
        assert _get_equipment_qty(db_path, pid, POTION_ID) == 0


class TestInvalidOrLockedItem:
    def test_returns_item_not_found_for_unknown_item(
        self, svc: ShopService, player: dict
    ) -> None:
        result = svc.purchase_item(player["player_id"], "nonexistent_item")
        assert result["type"] == "item_not_found"

    def test_coins_unchanged_for_invalid_item(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        svc.purchase_item(player["player_id"], "nonexistent_item")
        assert _get_coins(db_path, player["player_id"]) == INITIAL_COINS

    def test_returns_item_locked_when_level_too_low(
        self, db_path: Path, tmp_path: Path, player: dict
    ) -> None:
        cfg_dir = tmp_path / "locked_config"
        cfg_dir.mkdir()
        (cfg_dir / "shop.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "item_id": POTION_ID,
                            "price": POTION_PRICE,
                            "unlock_level": 5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (cfg_dir / "items.json").write_text(
            (_CONFIG_DIR / "items.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        locked_svc = ShopService(db_path=db_path, config_dir=cfg_dir)
        result = locked_svc.purchase_item(player["player_id"], POTION_ID)
        assert result["type"] == "item_locked"

    def test_coins_unchanged_for_locked_item(
        self, db_path: Path, tmp_path: Path, player: dict
    ) -> None:
        cfg_dir = tmp_path / "locked_config2"
        cfg_dir.mkdir()
        (cfg_dir / "shop.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "item_id": POTION_ID,
                            "price": POTION_PRICE,
                            "unlock_level": 5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (cfg_dir / "items.json").write_text(
            (_CONFIG_DIR / "items.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        locked_svc = ShopService(db_path=db_path, config_dir=cfg_dir)
        locked_svc.purchase_item(player["player_id"], POTION_ID)
        assert _get_coins(db_path, player["player_id"]) == INITIAL_COINS


class TestConcurrentPurchase:
    def test_concurrent_purchases_do_not_overdraft(
        self, svc: ShopService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        # Player starts with 25 coins; potion costs 10 — only 2 purchases can succeed
        results: list[dict] = []
        lock = threading.Lock()

        def buy() -> None:
            r = svc.purchase_item(pid, POTION_ID)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=buy) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r["type"] == "purchase_success")
        failures = sum(1 for r in results if r["type"] == "insufficient_funds")
        assert successes == 2
        assert failures == 2
        assert _get_coins(db_path, pid) == INITIAL_COINS - (successes * POTION_PRICE)
        assert _get_equipment_qty(db_path, pid, POTION_ID) == successes
