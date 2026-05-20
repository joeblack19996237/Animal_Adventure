from __future__ import annotations

import threading
import time
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


@pytest.mark.integration
def test_two_clients_receive_movement(client: TestClient) -> None:
    """Two connected players each receive the other's state_update on player_move."""
    player1_id = _create_player(client, "Alpha")
    player2_id = _create_player(client, "Beta")

    p2_messages: list[dict] = []
    p2_errors: list[Exception] = []
    p2_ready = threading.Event()
    p2_done = threading.Event()

    def run_player2() -> None:
        try:
            with client.websocket_connect(f"/ws/{player2_id}") as ws2:
                ws2.receive_json()  # consume state_sync
                p2_ready.set()
                msg = ws2.receive_json()  # expect state_update
                p2_messages.append(msg)
        except Exception as exc:
            p2_errors.append(exc)
        finally:
            if not p2_ready.is_set():
                p2_ready.set()
            p2_done.set()

    thread = threading.Thread(target=run_player2, daemon=True)
    thread.start()
    p2_ready.wait(timeout=5)
    # Give p2 time to reach the blocking receive_json call
    time.sleep(0.05)

    with client.websocket_connect(f"/ws/{player1_id}") as ws1:
        ws1.receive_json()  # consume state_sync
        ws1.send_json(
            {
                "type": "player_move",
                "player_id": player1_id,
                "x": 2720.0,
                "y": 3625.0,
                "direction": "right",
                "client_tick": 1,
            }
        )
        time.sleep(0.2)  # allow broadcast to propagate to p2

    p2_done.wait(timeout=5)
    thread.join(timeout=5)
    if p2_errors:
        raise p2_errors[0]

    assert len(p2_messages) >= 1, (
        f"Player 2 received no messages after state_sync: {p2_messages}"
    )
    state_update = p2_messages[0]
    assert state_update["type"] == "state_update", (
        f"Expected state_update, got: {state_update}"
    )
    assert player1_id in state_update["players"], (
        f"player1 not in state_update players: {state_update}"
    )
    p1_state = state_update["players"][player1_id]
    assert p1_state["x"] == 2720.0
    assert p1_state["y"] == 3625.0
    assert p1_state["direction"] == "right"


@pytest.mark.integration
def test_player_left_broadcast(client: TestClient) -> None:
    """Remaining client receives player_left when the other player disconnects."""
    player1_id = _create_player(client, "Leaver")
    player2_id = _create_player(client, "Waiter")

    p2_messages: list[dict] = []
    p2_errors: list[Exception] = []
    p2_ready = threading.Event()
    p2_done = threading.Event()

    def run_player2() -> None:
        try:
            with client.websocket_connect(f"/ws/{player2_id}") as ws2:
                ws2.receive_json()  # consume state_sync
                p2_ready.set()
                msg = ws2.receive_json()  # expect player_left
                p2_messages.append(msg)
        except Exception as exc:
            p2_errors.append(exc)
        finally:
            if not p2_ready.is_set():
                p2_ready.set()
            p2_done.set()

    thread = threading.Thread(target=run_player2, daemon=True)
    thread.start()
    p2_ready.wait(timeout=5)
    time.sleep(0.05)

    with client.websocket_connect(f"/ws/{player1_id}") as ws1:
        ws1.receive_json()  # consume state_sync
    # player1 context exits here — triggers disconnect and player_left broadcast

    p2_done.wait(timeout=5)
    thread.join(timeout=5)
    if p2_errors:
        raise p2_errors[0]

    assert len(p2_messages) >= 1, (
        f"Player 2 received no player_left message: {p2_messages}"
    )
    player_left = p2_messages[0]
    assert player_left["type"] == "player_left", (
        f"Expected player_left, got: {player_left}"
    )
    assert player_left["player_id"] == player1_id


@pytest.mark.integration
def test_ws_reconnect_recovery(client: TestClient) -> None:
    """Forced disconnect followed by reconnect delivers a fresh state_sync."""
    player_id = _create_player(client, "Reconnector")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        first_sync = ws.receive_json()

    assert first_sync["type"] == "state_sync"
    assert first_sync["player"]["id"] == player_id

    # Reconnect — simulates a forced disconnect followed by automatic reconnect
    with client.websocket_connect(f"/ws/{player_id}") as ws:
        reconnect_sync = ws.receive_json()

    assert reconnect_sync["type"] == "state_sync"
    assert reconnect_sync["player"]["id"] == player_id
    assert "server_time" in reconnect_sync
    assert "progress" in reconnect_sync
    assert "inventory" in reconnect_sync
    assert "quests" in reconnect_sync
    assert "world_items" in reconnect_sync
