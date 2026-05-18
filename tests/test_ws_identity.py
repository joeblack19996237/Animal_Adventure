from __future__ import annotations

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


def _create_player(client: TestClient, name: str) -> str:
    resp = client.post(
        "/api/v1/players", json={"name": name, "character_id": "penguin"}
    )
    assert resp.status_code == 200
    return resp.json()["player_id"]


def test_ws_identity_rejects_impersonation(client: TestClient) -> None:
    player_id = _create_player(client, "Alice")
    other_id = _create_player(client, "Bob")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "player_move",
                "player_id": other_id,
                "x": 2716.0,
                "y": 3620.0,
                "direction": "right",
                "client_tick": 1,
            }
        )
        error = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "identity_mismatch"
    assert "message" in error


def test_ws_identity_connection_stays_open_after_mismatch(client: TestClient) -> None:
    player_id = _create_player(client, "Alice")
    other_id = _create_player(client, "Bob")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "player_move",
                "player_id": other_id,
                "x": 2716.0,
                "y": 3620.0,
                "direction": "right",
                "client_tick": 1,
            }
        )
        error1 = ws.receive_json()
        ws.send_json(
            {
                "type": "player_move",
                "player_id": other_id,
                "x": 2717.0,
                "y": 3620.0,
                "direction": "right",
                "client_tick": 2,
            }
        )
        error2 = ws.receive_json()

    assert error1["type"] == "error"
    assert error1["code"] == "identity_mismatch"
    assert error2["type"] == "error"
    assert error2["code"] == "identity_mismatch"


def test_ws_identity_invalid_json_returns_error(client: TestClient) -> None:
    player_id = _create_player(client, "Alice")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_text("not-valid-json{{{")
        error = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "invalid_message"
