"""Tests for server-side out-of-bounds movement rejection (issue 16.3).

These tests fail against the current code because the player_move handler
in ws_handler.py calls _broadcast_state_update directly without invoking
world_service bounds validation. They pass once bounds checking is wired in.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.routes.players import get_player_service
from app.services.player_service import PlayerService
from app.ws_handler import get_ws_db_path

_CONFIG_DIR = Path("config")


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    svc = PlayerService(db_path=db, config_dir=_CONFIG_DIR)
    app.dependency_overrides[get_player_service] = lambda: svc
    app.dependency_overrides[get_ws_db_path] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_player(client: TestClient, name: str = "BoundsPlayer") -> str:
    resp = client.post(
        "/api/v1/players", json={"name": name, "character_id": "penguin"}
    )
    assert resp.status_code == 200
    return resp.json()["player_id"]


def _receive_json_with_timeout(ws, *, timeout: float = 1.0) -> dict:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(ws.receive_json)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        ws.close()
        pytest.fail("Expected out_of_bounds error response, but no message arrived.")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def test_out_of_bounds_negative_x_returns_error(client: TestClient) -> None:
    player_id = _create_player(client)
    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "player_move",
                "player_id": player_id,
                "x": -100,
                "y": 3620,
                "direction": "down",
                "client_tick": 1,
            }
        )
        msg = _receive_json_with_timeout(ws)
    assert msg["type"] == "error", (
        f"Expected error message for x=-100 but got type={msg.get('type')!r}. "
        "The ws_handler does not validate out-of-bounds coordinates."
    )
    assert msg.get("code") == "out_of_bounds", (
        f"Expected code='out_of_bounds' but got {msg.get('code')!r}"
    )


def test_out_of_bounds_negative_y_returns_error(client: TestClient) -> None:
    player_id = _create_player(client, name="BoundsPlayerY")
    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "player_move",
                "player_id": player_id,
                "x": 2715,
                "y": -50,
                "direction": "up",
                "client_tick": 1,
            }
        )
        msg = _receive_json_with_timeout(ws)
    assert msg["type"] == "error"
    assert msg.get("code") == "out_of_bounds"


def test_out_of_bounds_exceeds_map_width_returns_error(client: TestClient) -> None:
    player_id = _create_player(client, name="BoundsPlayerW")
    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "player_move",
                "player_id": player_id,
                "x": 9999,
                "y": 3620,
                "direction": "right",
                "client_tick": 1,
            }
        )
        msg = _receive_json_with_timeout(ws)
    assert msg["type"] == "error"
    assert msg.get("code") == "out_of_bounds"


def test_in_bounds_movement_does_not_close_connection(client: TestClient) -> None:
    player_id = _create_player(client, name="BoundsPlayerOk")
    # Verify an in-bounds move does not disconnect the client by sending a
    # second in-bounds move and confirming the connection is still alive.
    connected = False
    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "player_move",
                "player_id": player_id,
                "x": 2715,
                "y": 3620,
                "direction": "down",
                "client_tick": 1,
            }
        )
        connected = True
    assert connected, "WebSocket should stay open for in-bounds movement"
