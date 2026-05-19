from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.db import connect_db
from app.logging_config import emit_bootstrap_failure as _emit_bootstrap_failure
from app.logging_config import emit_duplicate_session as _emit_duplicate_session
from app.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter()

_active_sessions: dict[str, WebSocket] = {}

MAX_CLIENT_EVENT_BYTES = 4096


def validate_client_event(raw: str) -> tuple[dict | None, str | None]:
    """Validate a raw WebSocket message string. Returns (msg, error_code)."""
    if len(raw.encode("utf-8")) > MAX_CLIENT_EVENT_BYTES:
        return None, "payload_too_large"
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid_message"
    if not isinstance(msg, dict):
        return None, "invalid_message"
    return msg, None


def get_ws_db_path() -> Path:
    return Settings().database_path


def get_ws_config_dir() -> Path:
    return Path("config")


def _load_preset_phrases(config_dir: Path) -> dict[str, str]:
    path = config_dir / "preset_phrases.json"
    phrases: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    return {p["id"]: p["text"] for p in phrases}


async def _broadcast_chat(player_id: str, phrase_id: str, message: str) -> None:
    msg = json.dumps(
        {
            "type": "chat_message",
            "player_id": player_id,
            "phrase_id": phrase_id,
            "message": message,
        }
    )
    for ws in list(_active_sessions.values()):
        try:
            await ws.send_text(msg)
        except Exception as exc:
            logger.debug("Could not broadcast chat_message to player: %s", exc)


async def _broadcast_state_update(
    player_id: str, x: float, y: float, direction: str, client_tick: int
) -> None:
    msg = json.dumps(
        {
            "type": "state_update",
            "tick": client_tick,
            "players": {player_id: {"x": x, "y": y, "direction": direction}},
        }
    )
    for pid, ws in list(_active_sessions.items()):
        if pid != player_id:
            try:
                await ws.send_text(msg)
            except Exception as exc:
                logger.debug(
                    "Could not broadcast state_update to player_id=%s: %s", pid, exc
                )


async def _broadcast_player_left(player_id: str) -> None:
    msg = json.dumps({"type": "player_left", "player_id": player_id})
    for pid, ws in list(_active_sessions.items()):
        if pid != player_id:
            try:
                await ws.send_text(msg)
            except Exception as exc:
                logger.debug(
                    "Could not broadcast player_left to player_id=%s: %s", pid, exc
                )


async def _evict_existing_session(player_id: str) -> None:
    existing = _active_sessions.pop(player_id, None)
    if existing is None:
        return
    _emit_duplicate_session(logger, player_id)
    try:
        await existing.send_text(
            json.dumps(
                {
                    "type": "error",
                    "code": "duplicate_session",
                    "message": "A new session has connected for your player.",
                }
            )
        )
        await existing.close()
    except Exception as exc:
        logger.debug(
            "Could not cleanly close old session for player_id=%s: %s", player_id, exc
        )


def _fetch_player(conn: sqlite3.Connection, player_id: str) -> tuple | None:
    return conn.execute(
        "SELECT id, name, normalized_name, character_id, x, y, direction, level, coins "
        "FROM players WHERE id = ?",
        (player_id,),
    ).fetchone()


def _fetch_progress(conn: sqlite3.Connection, player_id: str) -> tuple | None:
    return conn.execute(
        "SELECT completed_quest_count, unique_completed_quest_ids_json, "
        "used_potion_count, unlocked_level, unlocked_regions_json "
        "FROM player_progress WHERE player_id = ?",
        (player_id,),
    ).fetchone()


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


def _fetch_quests_and_world_items(
    conn: sqlite3.Connection, player_id: str
) -> tuple[list, list]:
    quest_rows = conn.execute(
        "SELECT id, npc_id, quest_id, status, expires_at, cooldown_until, "
        "progress_json, rewards_granted_json "
        "FROM player_quests WHERE player_id = ?",
        (player_id,),
    ).fetchall()
    world_items: list[dict] = []
    for q in quest_rows:
        if q[3] == "active":
            wi_rows = conn.execute(
                "SELECT id, item_id, x, y FROM world_item_instances "
                "WHERE quest_instance_id = ? AND status = 'spawned'",
                (q[0],),
            ).fetchall()
            for wi in wi_rows:
                world_items.append(
                    {"id": wi[0], "item_id": wi[1], "x": wi[2], "y": wi[3]}
                )
    return quest_rows, world_items


def _build_state_sync(conn: sqlite3.Connection, player_id: str) -> dict | None:
    player_row = _fetch_player(conn, player_id)
    if player_row is None:
        return None

    progress_row = _fetch_progress(conn, player_id)
    inventory_rows, equipment_rows = _fetch_inventory(conn, player_id)
    quest_rows, world_items = _fetch_quests_and_world_items(conn, player_id)

    progress = (
        {
            "completed_quest_count": progress_row[0],
            "unique_completed_quest_ids": json.loads(progress_row[1]),
            "used_potion_count": progress_row[2],
            "unlocked_level": progress_row[3],
            "unlocked_regions": json.loads(progress_row[4]),
        }
        if progress_row is not None
        else {
            "completed_quest_count": 0,
            "unique_completed_quest_ids": [],
            "used_potion_count": 0,
            "unlocked_level": 0,
            "unlocked_regions": ["spawn"],
        }
    )

    quests = [
        {
            "quest_instance_id": q[0],
            "npc_id": q[1],
            "quest_id": q[2],
            "status": q[3],
            "expires_at": q[4],
            "cooldown_until": q[5],
            "progress": json.loads(q[6]) if q[6] else {},
            "rewards_granted_json": json.loads(q[7]) if q[7] else [],
        }
        for q in quest_rows
    ]

    return {
        "type": "state_sync",
        "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "player": {
            "id": player_row[0],
            "name": player_row[1],
            "normalized_name": player_row[2],
            "character_id": player_row[3],
            "x": player_row[4],
            "y": player_row[5],
            "direction": player_row[6],
            "level": player_row[7],
            "coins": player_row[8],
        },
        "progress": progress,
        "inventory": [{"item_id": r[0], "quantity": r[1]} for r in inventory_rows],
        "equipment": [{"item_id": r[0], "quantity": r[1]} for r in equipment_rows],
        "quests": quests,
        "online_players": {},
        "world_items": world_items,
    }


def _load_state_sync(db_path: Path, player_id: str) -> dict | None:
    conn = connect_db(db_path)
    try:
        return _build_state_sync(conn, player_id)
    finally:
        conn.close()


async def _handle_messages(
    websocket: WebSocket, player_id: str, phrase_lookup: dict[str, str]
) -> None:
    try:
        while True:
            raw = await websocket.receive_text()
            msg, error_code = validate_client_event(raw)
            if error_code == "payload_too_large":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "payload_too_large",
                            "message": "Payload exceeds maximum allowed size.",
                        }
                    )
                )
                continue
            if error_code == "invalid_message":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "Message must be a valid JSON object.",
                        }
                    )
                )
                continue

            assert msg is not None  # error_code is None means msg is a valid dict

            body_player_id = msg.get("player_id")
            if body_player_id is not None and body_player_id != player_id:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "identity_mismatch",
                            "message": "Message player_id does not match connection identity.",
                        }
                    )
                )
                continue

            if msg.get("type") == "player_move":
                await _broadcast_state_update(
                    player_id,
                    float(msg.get("x", 0.0)),
                    float(msg.get("y", 0.0)),
                    str(msg.get("direction", "down")),
                    int(msg.get("client_tick", 0)),
                )
            elif msg.get("type") == "preset_chat":
                phrase_id = msg.get("phrase_id")
                if not isinstance(phrase_id, str) or phrase_id not in phrase_lookup:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "code": "invalid_message",
                                "message": "Unknown or missing phrase_id.",
                            }
                        )
                    )
                else:
                    await _broadcast_chat(
                        player_id, phrase_id, phrase_lookup[phrase_id]
                    )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected player_id=%s", player_id)


@router.websocket("/ws/{player_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    player_id: str,
    db_path: Path = Depends(get_ws_db_path),
    config_dir: Path = Depends(get_ws_config_dir),
) -> None:
    await websocket.accept()
    await _evict_existing_session(player_id)
    _active_sessions[player_id] = websocket

    try:
        try:
            state_sync = await asyncio.to_thread(_load_state_sync, db_path, player_id)
        except Exception as exc:
            _emit_bootstrap_failure(logger, player_id=player_id, error=str(exc))
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "code": "internal_error",
                        "message": "Internal server error.",
                    }
                )
            )
            return

        if state_sync is None:
            _emit_bootstrap_failure(
                logger, player_id=player_id, error="player_not_found"
            )
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "code": "player_not_found",
                        "message": "Player not found.",
                    }
                )
            )
            await websocket.close()
            return

        phrase_lookup = _load_preset_phrases(config_dir)
        await websocket.send_text(json.dumps(state_sync))
        await _handle_messages(websocket, player_id, phrase_lookup)
    finally:
        if _active_sessions.get(player_id) is websocket:
            _active_sessions.pop(player_id, None)
            await _broadcast_player_left(player_id)
