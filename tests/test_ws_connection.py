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


def test_ws_connect_sends_state_sync(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/players", json={"name": "TestPlayer", "character_id": "penguin"}
    )
    assert resp.status_code == 200
    player_id = resp.json()["player_id"]

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        msg = ws.receive_json()

    assert msg["type"] == "state_sync"
    assert msg["player"]["id"] == player_id
    assert msg["player"]["name"] == "TestPlayer"
    assert msg["player"]["character_id"] == "penguin"
    assert msg["player"]["coins"] == 25
    assert msg["player"]["level"] == 0
    assert "server_time" in msg
    assert "progress" in msg
    assert msg["progress"]["completed_quest_count"] == 0
    assert msg["progress"]["unique_completed_quest_ids"] == []
    assert msg["progress"]["used_potion_count"] == 0
    assert "spawn" in msg["progress"]["unlocked_regions"]
    assert msg["inventory"] == []
    assert msg["equipment"] == []
    assert msg["quests"] == []
    assert msg["online_players"] == {}
    assert msg["world_items"] == []


def test_ws_unknown_player_errors(client: TestClient) -> None:
    with client.websocket_connect("/ws/nonexistent-player-id") as ws:
        msg = ws.receive_json()

    assert msg["type"] == "error"
    assert msg["code"] == "player_not_found"
    assert "message" in msg
