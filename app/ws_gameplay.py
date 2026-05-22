from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import WebSocket

from app.db import connect_db
from app.services.inventory_service import InventoryService
from app.services.progression_service import ProgressionService
from app.services.quest_service import QuestService
from app.services.shop_service import ShopService
from app.services.world_service import MoveStatus, WorldService

BroadcastStateUpdate = Callable[[str, dict, int], Awaitable[None]]


def _fetch_inventory(conn: sqlite3.Connection, player_id: str) -> tuple[list, list]:
    inventory = conn.execute(
        "SELECT item_id, quantity FROM player_inventory "
        "WHERE player_id = ? AND slot_type = 'inventory'",
        (player_id,),
    ).fetchall()
    equipment = conn.execute(
        "SELECT item_id, quantity FROM player_inventory "
        "WHERE player_id = ? AND slot_type = 'equipment'",
        (player_id,),
    ).fetchall()
    return inventory, equipment


def _inventory_update_message(db_path: Path, player_id: str) -> dict:
    conn = connect_db(db_path)
    try:
        inventory_rows, equipment_rows = _fetch_inventory(conn, player_id)
    finally:
        conn.close()
    return {
        "type": "inventory_updated",
        "inventory": [
            {"item_id": r[0], "quantity": r[1], "slot_type": "inventory"}
            for r in inventory_rows
        ],
        "equipment": [
            {"item_id": r[0], "quantity": r[1], "slot_type": "equipment"}
            for r in equipment_rows
        ],
    }


def _current_position(
    db_path: Path, world_service: WorldService, player_id: str
) -> tuple[float, float, str]:
    pos = world_service.get_online_positions().get(player_id)
    if pos is not None:
        return float(pos["x"]), float(pos["y"]), str(pos["direction"])
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "SELECT x, y, direction FROM players WHERE id = ?", (player_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return 0.0, 0.0, "down"
    return float(row[0]), float(row[1]), str(row[2])


def _message_position(
    msg: dict, db_path: Path, world_service: WorldService, player_id: str
) -> tuple[float, float, str]:
    current_x, current_y, current_direction = _current_position(
        db_path, world_service, player_id
    )
    x = float(msg.get("x", current_x))
    y = float(msg.get("y", current_y))
    direction = str(msg.get("direction", current_direction))
    return x, y, direction


def _npc_id_for_player_quest(db_path: Path, player_id: str, quest_id: str) -> str | None:
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "SELECT npc_id FROM player_quests "
            "WHERE player_id = ? AND quest_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (player_id, quest_id),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row is not None else None


def _resolve_item_instance_id(
    db_path: Path, player_id: str, msg: dict
) -> str | None:
    item_instance_id = msg.get("item_instance_id")
    if isinstance(item_instance_id, str) and item_instance_id:
        return item_instance_id
    quest_id = msg.get("quest_id")
    item_id = msg.get("item_id")
    if not isinstance(quest_id, str) or not isinstance(item_id, str):
        return None
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "SELECT wi.id FROM world_item_instances wi "
            "JOIN player_quests pq ON wi.quest_instance_id = pq.id "
            "WHERE pq.player_id = ? AND pq.quest_id = ? AND wi.item_id = ? "
            "AND pq.status = 'active' AND wi.status = 'spawned' "
            "ORDER BY wi.id LIMIT 1",
            (player_id, quest_id, item_id),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row is not None else None


async def send_json(websocket: WebSocket, msg: dict) -> None:
    await websocket.send_text(json.dumps(msg))


async def _send_inventory_update(
    websocket: WebSocket, db_path: Path, player_id: str
) -> None:
    await send_json(websocket, _inventory_update_message(db_path, player_id))


async def _send_progression_if_changed(
    websocket: WebSocket, progression_service: ProgressionService, player_id: str
) -> None:
    result = progression_service.check_and_apply_progression(player_id)
    if result.get("type") != "no_change":
        await send_json(websocket, result)


async def _handle_player_move(
    websocket: WebSocket,
    player_id: str,
    msg: dict,
    db_path: Path,
    world_service: WorldService,
    broadcast_state_update: BroadcastStateUpdate,
) -> None:
    x, y, direction = _message_position(msg, db_path, world_service, player_id)
    status = world_service.apply_move(player_id, x, y, direction)
    if status == MoveStatus.OUT_OF_BOUNDS:
        await send_json(
            websocket,
            {
                "type": "error",
                "code": "out_of_bounds",
                "message": "Movement coordinates are outside the world bounds.",
            },
        )
        return
    if status == MoveStatus.COLLISION_BLOCKED:
        await send_json(
            websocket,
            {
                "type": "error",
                "code": "collision_blocked",
                "message": "Movement coordinates are blocked by world collision.",
            },
        )
        return
    if status == MoveStatus.RATE_LIMITED:
        return
    await broadcast_state_update(
        player_id, world_service.get_snapshot(), int(msg.get("client_tick", 0))
    )


async def handle_gameplay_message(
    websocket: WebSocket,
    player_id: str,
    msg: dict,
    db_path: Path,
    quest_service: QuestService,
    shop_service: ShopService,
    inventory_service: InventoryService,
    progression_service: ProgressionService,
    world_service: WorldService,
    broadcast_state_update: BroadcastStateUpdate,
) -> bool:
    msg_type = msg.get("type")
    if msg_type == "player_move":
        await _handle_player_move(
            websocket, player_id, msg, db_path, world_service, broadcast_state_update
        )
        return True
    if msg_type == "npc_interact_request":
        npc_id = msg.get("npc_id")
        if not isinstance(npc_id, str):
            await send_json(websocket, {"type": "error", "code": "invalid_message"})
            return True
        x, y, _ = _message_position(msg, db_path, world_service, player_id)
        await send_json(websocket, quest_service.offer_quest(player_id, npc_id, x, y))
        return True
    if msg_type == "quest_accept":
        quest_id = msg.get("quest_id")
        if not isinstance(quest_id, str):
            await send_json(websocket, {"type": "error", "code": "invalid_message"})
            return True
        npc_id = quest_service.npc_id_for_quest(quest_id)
        result = (
            {"type": "quest_not_found"}
            if npc_id is None
            else quest_service.accept_quest(player_id, npc_id)
        )
        await send_json(websocket, result)
        return True
    if msg_type == "item_pickup_request":
        item_instance_id = _resolve_item_instance_id(db_path, player_id, msg)
        if item_instance_id is None:
            await send_json(websocket, {"type": "item_not_found"})
            return True
        x, y, _ = _message_position(msg, db_path, world_service, player_id)
        result = quest_service.pickup_item(player_id, item_instance_id, x, y)
        await send_json(websocket, result)
        if result.get("type") == "item_picked_up":
            await _send_inventory_update(websocket, db_path, player_id)
        return True
    if msg_type == "quest_turn_in":
        quest_id = msg.get("quest_id")
        if not isinstance(quest_id, str):
            await send_json(websocket, {"type": "error", "code": "invalid_message"})
            return True
        npc_id = _npc_id_for_player_quest(db_path, player_id, quest_id)
        npc_id = npc_id or quest_service.npc_id_for_quest(quest_id)
        if npc_id is None:
            await send_json(websocket, {"type": "quest_not_found"})
            return True
        x, y, _ = _message_position(msg, db_path, world_service, player_id)
        result = quest_service.turn_in_quest(player_id, npc_id, x, y)
        await send_json(websocket, result)
        if result.get("type") == "quest_completed":
            await _send_inventory_update(websocket, db_path, player_id)
            await _send_progression_if_changed(
                websocket, progression_service, player_id
            )
        return True
    if msg_type == "shop_buy":
        item_id = msg.get("item_id")
        if not isinstance(item_id, str):
            await send_json(websocket, {"type": "error", "code": "invalid_message"})
            return True
        result = shop_service.purchase_item(player_id, item_id)
        if result.get("type") == "purchase_success":
            result = {
                "type": "shop_purchase_ok",
                "item_id": item_id,
                "coins_balance": result["coins_balance"],
            }
        await send_json(websocket, result)
        if result.get("type") == "shop_purchase_ok":
            await _send_inventory_update(websocket, db_path, player_id)
        return True
    if msg_type == "use_item":
        item_id = msg.get("item_id")
        if not isinstance(item_id, str):
            await send_json(websocket, {"type": "error", "code": "invalid_message"})
            return True
        result = inventory_service.use_item(player_id, item_id)
        await send_json(websocket, result)
        if result.get("type") == "item_used":
            await _send_inventory_update(websocket, db_path, player_id)
            await _send_progression_if_changed(
                websocket, progression_service, player_id
            )
        return True
    return False
