from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.routes.players import get_player_service
from app.services.player_service import PlayerService
from app.ws_handler import get_ws_config_dir, get_ws_db_path

_CONFIG_DIR = Path("config")


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    svc = PlayerService(db_path=db, config_dir=_CONFIG_DIR)
    app.dependency_overrides[get_player_service] = lambda: svc
    app.dependency_overrides[get_ws_db_path] = lambda: db
    app.dependency_overrides[get_ws_config_dir] = lambda: _CONFIG_DIR
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_player(client: TestClient, name: str = "GameplayPlayer") -> str:
    resp = client.post(
        "/api/v1/players", json={"name": name, "character_id": "penguin"}
    )
    assert resp.status_code == 200
    return resp.json()["player_id"]


def _connect(client: TestClient, player_id: str):
    ws = client.websocket_connect(f"/ws/{player_id}")
    session = ws.__enter__()
    state_sync = session.receive_json()
    assert state_sync["type"] == "state_sync"
    return ws, session


def test_ws_dispatches_quest_offer_and_accept(client: TestClient) -> None:
    player_id = _create_player(client)
    manager, ws = _connect(client, player_id)
    try:
        ws.send_json(
            {
                "type": "player_move",
                "player_id": player_id,
                "x": 2715,
                "y": 3105,
                "direction": "up",
                "client_tick": 1,
            }
        )
        ws.send_json(
            {"type": "npc_interact_request", "player_id": player_id, "npc_id": "hopper"}
        )
        offer = ws.receive_json()
        assert offer["type"] == "quest_offer"
        assert offer["npc_id"] == "hopper"
        assert offer["quest_id"] == "quest_hopper_blanket"
        assert offer["title"] == "Find Hopper's Blanket"

        ws.send_json(
            {
                "type": "quest_accept",
                "player_id": player_id,
                "quest_id": "quest_hopper_blanket",
            }
        )
        started = ws.receive_json()
        assert started["type"] == "quest_started"
        assert started["quest_id"] == "quest_hopper_blanket"
        assert started["world_items"][0]["item_id"] == "item_blanket"
    finally:
        manager.__exit__(None, None, None)


def test_ws_rejects_collision_blocked_movement(client: TestClient) -> None:
    player_id = _create_player(client, "CollisionPlayer")
    manager, ws = _connect(client, player_id)
    try:
        ws.send_json(
            {
                "type": "player_move",
                "player_id": player_id,
                "x": 520,
                "y": 3200,
                "direction": "left",
                "client_tick": 1,
            }
        )
        response = ws.receive_json()
        assert response["type"] == "error"
        assert response["code"] == "collision_blocked"
    finally:
        manager.__exit__(None, None, None)


def test_ws_dispatches_pickup_and_turn_in(client: TestClient) -> None:
    player_id = _create_player(client, "TurnInPlayer")
    manager, ws = _connect(client, player_id)
    try:
        ws.send_json(
            {
                "type": "quest_accept",
                "player_id": player_id,
                "quest_id": "quest_hopper_blanket",
            }
        )
        started = ws.receive_json()
        item_instance_id = started["world_items"][0]["id"]

        ws.send_json(
            {
                "type": "item_pickup_request",
                "player_id": player_id,
                "item_instance_id": item_instance_id,
                "x": 2600,
                "y": 3100,
            }
        )
        picked = ws.receive_json()
        assert picked["type"] == "item_picked_up"
        assert picked["quest_id"] == "quest_hopper_blanket"
        inventory = ws.receive_json()
        assert inventory["type"] == "inventory_updated"
        assert inventory["inventory"][0]["item_id"] == "item_blanket"

        ws.send_json(
            {
                "type": "quest_turn_in",
                "player_id": player_id,
                "quest_id": "quest_hopper_blanket",
                "x": 2715,
                "y": 3200,
            }
        )
        completed = ws.receive_json()
        assert completed["type"] == "quest_completed"
        assert completed["quest_id"] == "quest_hopper_blanket"
        assert completed["coins_balance"] == 50
    finally:
        manager.__exit__(None, None, None)


def test_ws_dispatches_shop_buy_and_use_item_with_level_up(client: TestClient) -> None:
    player_id = _create_player(client, "ShopPlayer")
    manager, ws = _connect(client, player_id)
    try:
        ws.send_json(
            {"type": "shop_buy", "player_id": player_id, "item_id": "potion_l0"}
        )
        shop = ws.receive_json()
        assert shop["type"] == "shop_purchase_ok"
        assert shop["coins_balance"] == 15
        inventory = ws.receive_json()
        assert inventory["type"] == "inventory_updated"
        assert inventory["equipment"][0]["item_id"] == "potion_l0"

        ws.send_json(
            {"type": "use_item", "player_id": player_id, "item_id": "potion_l0"}
        )
        used = ws.receive_json()
        assert used["type"] == "item_used"
        updated = ws.receive_json()
        assert updated["type"] == "inventory_updated"
    finally:
        manager.__exit__(None, None, None)
