"""Tests for InventoryService: cap enforcement, Potion stacking/use, accessory equipment, concurrency."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.db import connect_db, init_db
from app.services.inventory_service import InventoryService
from app.services.player_service import PlayerService

_CONFIG_DIR = Path("config")
INVENTORY_CAP = 20
QUEST_ITEM_A = "item_blanket"
QUEST_ITEM_B = "item_bagpipe"
POTION_ID = "potion_l0"
ACCESSORY_ID = "accessory_sleepy_hat"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def svc(db_path: Path) -> InventoryService:
    return InventoryService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player(db_path: Path) -> dict:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR).create_player(
        "Alice", "penguin"
    )


@pytest.fixture
def player_b(db_path: Path) -> dict:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR).create_player(
        "Bob", "arctic_fox"
    )


def _fill_inventory(db_path: Path, player_id: str, n: int = INVENTORY_CAP) -> None:
    conn = connect_db(db_path)
    for i in range(n):
        conn.execute(
            "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type)"
            " VALUES (?, ?, 1, 'inventory')",
            (player_id, f"item_fake_{i}"),
        )
    conn.commit()
    conn.close()


def _equipment_qty(db_path: Path, player_id: str, item_id: str) -> int:
    conn = connect_db(db_path)
    row = conn.execute(
        "SELECT quantity FROM player_inventory"
        " WHERE player_id=? AND item_id=? AND slot_type='equipment'",
        (player_id, item_id),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _used_potion_count(db_path: Path, player_id: str) -> int:
    conn = connect_db(db_path)
    row = conn.execute(
        "SELECT used_potion_count FROM player_progress WHERE player_id=?",
        (player_id,),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


class TestInventoryCap:
    def test_returns_inventory_full_at_cap(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        _fill_inventory(db_path, player["player_id"])
        assert (
            svc.add_item(player["player_id"], QUEST_ITEM_A)["type"] == "inventory_full"
        )

    def test_succeeds_below_cap(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        result = svc.add_item(player["player_id"], QUEST_ITEM_A)
        assert result["type"] == "item_added"

    def test_equipment_bypasses_cap(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        _fill_inventory(db_path, player["player_id"])
        assert svc.add_item(player["player_id"], POTION_ID)["type"] == "item_added"

    def test_cap_is_per_player(
        self, svc: InventoryService, player: dict, player_b: dict, db_path: Path
    ) -> None:
        _fill_inventory(db_path, player["player_id"])
        assert (
            svc.add_item(player["player_id"], QUEST_ITEM_A)["type"] == "inventory_full"
        )
        assert svc.add_item(player_b["player_id"], QUEST_ITEM_B)["type"] == "item_added"


class TestPotionStackAndUse:
    def test_add_potion_goes_to_equipment(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        svc.add_item(player["player_id"], POTION_ID)
        assert _equipment_qty(db_path, player["player_id"], POTION_ID) == 1

    def test_add_potion_twice_merges_stack(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, POTION_ID)
        svc.add_item(pid, POTION_ID)
        assert _equipment_qty(db_path, pid, POTION_ID) == 2

    def test_use_potion_decrements_quantity(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, POTION_ID, quantity=2)
        assert svc.use_item(pid, POTION_ID)["type"] == "item_used"
        assert _equipment_qty(db_path, pid, POTION_ID) == 1

    def test_use_last_potion_removes_row(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, POTION_ID, quantity=1)
        svc.use_item(pid, POTION_ID)
        assert _equipment_qty(db_path, pid, POTION_ID) == 0

    def test_use_potion_increments_used_count(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, POTION_ID, quantity=2)
        svc.use_item(pid, POTION_ID)
        assert _used_potion_count(db_path, pid) == 1
        svc.use_item(pid, POTION_ID)
        assert _used_potion_count(db_path, pid) == 2

    def test_use_returns_not_found_when_empty(
        self, svc: InventoryService, player: dict
    ) -> None:
        assert svc.use_item(player["player_id"], POTION_ID)["type"] == "item_not_found"


class TestAccessoryEquipment:
    def test_accessory_goes_to_equipment_slot(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        svc.add_item(player["player_id"], ACCESSORY_ID)
        assert _equipment_qty(db_path, player["player_id"], ACCESSORY_ID) >= 1

    def test_list_equipment_includes_accessory(
        self, svc: InventoryService, player: dict
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, ACCESSORY_ID)
        assert ACCESSORY_ID in [e["item_id"] for e in svc.list_equipment(pid)]

    def test_list_inventory_excludes_accessory(
        self, svc: InventoryService, player: dict
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, QUEST_ITEM_A)
        svc.add_item(pid, ACCESSORY_ID)
        ids = [e["item_id"] for e in svc.list_inventory(pid)]
        assert ACCESSORY_ID not in ids
        assert QUEST_ITEM_A in ids


class TestConcurrentOperations:
    def test_concurrent_add_within_cap_all_succeed(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        results: list[dict] = []
        lock = threading.Lock()

        def add(i: int) -> None:
            r = svc.add_item(pid, f"item_fake_{i}")
            with lock:
                results.append(r)

        threads = [threading.Thread(target=add, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        conn = connect_db(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM player_inventory WHERE player_id=? AND slot_type='inventory'",
            (pid,),
        ).fetchone()[0]
        conn.close()
        assert count == 5
        assert all(r["type"] == "item_added" for r in results)

    def test_concurrent_potion_stack_merge_is_safe(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]

        def add_potion() -> None:
            svc.add_item(pid, POTION_ID)

        threads = [threading.Thread(target=add_potion) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert _equipment_qty(db_path, pid, POTION_ID) == 4

    def test_concurrent_use_does_not_overdraft(
        self, svc: InventoryService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        svc.add_item(pid, POTION_ID, quantity=2)
        results: list[dict] = []
        lock = threading.Lock()

        def use() -> None:
            r = svc.use_item(pid, POTION_ID)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=use) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(1 for r in results if r["type"] == "item_used") == 2
        assert sum(1 for r in results if r["type"] == "item_not_found") == 2
        assert _equipment_qty(db_path, pid, POTION_ID) == 0
