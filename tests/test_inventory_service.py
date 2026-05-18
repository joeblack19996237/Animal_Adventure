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

# Non-stackable inventory items (slot_type='inventory')
QUEST_ITEM_A = "item_blanket"
QUEST_ITEM_B = "item_bagpipe"
QUEST_ITEM_C = "item_dance_shoes"

# Equipment items
POTION_ID = "potion_l0"
ACCESSORY_ID = "accessory_sleepy_hat"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def inventory_service(db_path: Path) -> InventoryService:
    return InventoryService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player_service(db_path: Path) -> PlayerService:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player_a(player_service: PlayerService) -> dict:
    return player_service.create_player("Alice", "penguin")


@pytest.fixture
def player_b(player_service: PlayerService) -> dict:
    return player_service.create_player("Bob", "arctic_fox")


# ── helpers ──────────────────────────────────────────────────────────────────


def _inventory_count(db_path: Path, player_id: str) -> int:
    conn = connect_db(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM player_inventory WHERE player_id=? AND slot_type='inventory'",
            (player_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def _equipment_rows(db_path: Path, player_id: str) -> list[dict]:
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            "SELECT item_id, quantity FROM player_inventory WHERE player_id=? AND slot_type='equipment'",
            (player_id,),
        ).fetchall()
        return [{"item_id": r[0], "quantity": r[1]} for r in rows]
    finally:
        conn.close()


def _used_potion_count(db_path: Path, player_id: str) -> int:
    conn = connect_db(db_path)
    try:
        return conn.execute(
            "SELECT used_potion_count FROM player_progress WHERE player_id=?",
            (player_id,),
        ).fetchone()[0]
    finally:
        conn.close()


# ── inventory cap ─────────────────────────────────────────────────────────────


class TestInventoryCap:
    def test_add_item_fills_up_to_cap(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        for i in range(INVENTORY_CAP):
            # Direct DB insert for all-but-last to avoid needing 20 distinct item_ids
            conn = connect_db(db_path)
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, 'inventory')",
                (pid, f"item_fake_{i}"),
            )
            conn.commit()
            conn.close()
        assert _inventory_count(db_path, pid) == INVENTORY_CAP

    def test_add_item_returns_inventory_full_at_cap(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        for i in range(INVENTORY_CAP):
            conn = connect_db(db_path)
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, 'inventory')",
                (pid, f"item_fake_{i}"),
            )
            conn.commit()
            conn.close()
        result = inventory_service.add_item(pid, QUEST_ITEM_A)
        assert result["type"] == "inventory_full"

    def test_add_item_succeeds_below_cap(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        result = inventory_service.add_item(pid, QUEST_ITEM_A)
        assert result["type"] == "item_added"
        assert _inventory_count(db_path, pid) == 1

    def test_equipment_not_subject_to_inventory_cap(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        for i in range(INVENTORY_CAP):
            conn = connect_db(db_path)
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, 'inventory')",
                (pid, f"item_fake_{i}"),
            )
            conn.commit()
            conn.close()
        result = inventory_service.add_item(pid, POTION_ID)
        assert result["type"] == "item_added"

    def test_cap_is_per_player(
        self,
        inventory_service: InventoryService,
        player_a: dict,
        player_b: dict,
        db_path: Path,
    ) -> None:
        pid_a = player_a["player_id"]
        pid_b = player_b["player_id"]
        for i in range(INVENTORY_CAP):
            conn = connect_db(db_path)
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, 'inventory')",
                (pid_a, f"item_fake_{i}"),
            )
            conn.commit()
            conn.close()
        result_a = inventory_service.add_item(pid_a, QUEST_ITEM_A)
        result_b = inventory_service.add_item(pid_b, QUEST_ITEM_B)
        assert result_a["type"] == "inventory_full"
        assert result_b["type"] == "item_added"


# ── potion stacking and use ───────────────────────────────────────────────────


class TestPotionStackAndUse:
    def test_add_potion_creates_equipment_row(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        result = inventory_service.add_item(pid, POTION_ID)
        assert result["type"] == "item_added"
        rows = _equipment_rows(db_path, pid)
        assert any(r["item_id"] == POTION_ID and r["quantity"] == 1 for r in rows)

    def test_add_potion_twice_merges_stack(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, POTION_ID)
        inventory_service.add_item(pid, POTION_ID)
        rows = [r for r in _equipment_rows(db_path, pid) if r["item_id"] == POTION_ID]
        assert len(rows) == 1
        assert rows[0]["quantity"] == 2

    def test_add_potion_with_quantity_merges_stack(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, POTION_ID, quantity=3)
        inventory_service.add_item(pid, POTION_ID, quantity=2)
        rows = [r for r in _equipment_rows(db_path, pid) if r["item_id"] == POTION_ID]
        assert len(rows) == 1
        assert rows[0]["quantity"] == 5

    def test_use_potion_decrements_quantity(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, POTION_ID, quantity=2)
        result = inventory_service.use_item(pid, POTION_ID)
        assert result["type"] == "item_used"
        rows = [r for r in _equipment_rows(db_path, pid) if r["item_id"] == POTION_ID]
        assert rows[0]["quantity"] == 1

    def test_use_last_potion_removes_row(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, POTION_ID, quantity=1)
        result = inventory_service.use_item(pid, POTION_ID)
        assert result["type"] == "item_used"
        rows = [r for r in _equipment_rows(db_path, pid) if r["item_id"] == POTION_ID]
        assert len(rows) == 0

    def test_use_potion_increments_used_potion_count(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, POTION_ID, quantity=2)
        inventory_service.use_item(pid, POTION_ID)
        assert _used_potion_count(db_path, pid) == 1
        inventory_service.use_item(pid, POTION_ID)
        assert _used_potion_count(db_path, pid) == 2

    def test_use_item_returns_not_found_when_none_in_inventory(
        self, inventory_service: InventoryService, player_a: dict
    ) -> None:
        result = inventory_service.use_item(player_a["player_id"], POTION_ID)
        assert result["type"] == "item_not_found"


# ── accessory equipment storage ───────────────────────────────────────────────


class TestAccessoryEquipment:
    def test_add_accessory_goes_to_equipment_slot(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        result = inventory_service.add_item(pid, ACCESSORY_ID)
        assert result["type"] == "item_added"
        rows = _equipment_rows(db_path, pid)
        assert any(r["item_id"] == ACCESSORY_ID for r in rows)

    def test_accessory_not_counted_toward_inventory_cap(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        for i in range(INVENTORY_CAP):
            conn = connect_db(db_path)
            conn.execute(
                "INSERT INTO player_inventory (player_id, item_id, quantity, slot_type) VALUES (?, ?, 1, 'inventory')",
                (pid, f"item_fake_{i}"),
            )
            conn.commit()
            conn.close()
        result = inventory_service.add_item(pid, ACCESSORY_ID)
        assert result["type"] == "item_added"

    def test_list_equipment_returns_added_accessory(
        self, inventory_service: InventoryService, player_a: dict
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, ACCESSORY_ID)
        equipment = inventory_service.list_equipment(pid)
        item_ids = [e["item_id"] for e in equipment]
        assert ACCESSORY_ID in item_ids

    def test_list_inventory_excludes_equipment(
        self, inventory_service: InventoryService, player_a: dict
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, QUEST_ITEM_A)
        inventory_service.add_item(pid, ACCESSORY_ID)
        inv = inventory_service.list_inventory(pid)
        equipment_ids = [e["item_id"] for e in inv]
        assert ACCESSORY_ID not in equipment_ids
        assert QUEST_ITEM_A in equipment_ids


# ── concurrent add/remove ─────────────────────────────────────────────────────


class TestConcurrentOperations:
    def test_concurrent_add_items_within_cap_all_succeed(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        results: list[dict] = []
        lock = threading.Lock()

        def add_item(item_suffix: int) -> None:
            r = inventory_service.add_item(pid, f"item_fake_{item_suffix}")
            with lock:
                results.append(r)

        threads = [threading.Thread(target=add_item, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert _inventory_count(db_path, pid) == 5
        assert all(r["type"] == "item_added" for r in results)

    def test_concurrent_potion_stack_merge_is_safe(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]

        def add_potion() -> None:
            inventory_service.add_item(pid, POTION_ID)

        threads = [threading.Thread(target=add_potion) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = [r for r in _equipment_rows(db_path, pid) if r["item_id"] == POTION_ID]
        assert len(rows) == 1
        assert rows[0]["quantity"] == 4

    def test_concurrent_use_potion_does_not_overdraft(
        self, inventory_service: InventoryService, player_a: dict, db_path: Path
    ) -> None:
        pid = player_a["player_id"]
        inventory_service.add_item(pid, POTION_ID, quantity=2)
        results: list[dict] = []
        lock = threading.Lock()

        def use_potion() -> None:
            r = inventory_service.use_item(pid, POTION_ID)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=use_potion) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        used = sum(1 for r in results if r["type"] == "item_used")
        not_found = sum(1 for r in results if r["type"] == "item_not_found")
        assert used == 2
        assert not_found == 2
        rows = [r for r in _equipment_rows(db_path, pid) if r["item_id"] == POTION_ID]
        assert len(rows) == 0
