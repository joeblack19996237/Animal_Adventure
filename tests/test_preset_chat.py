from __future__ import annotations

import sys
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
from app.ws_handler import get_ws_config_dir, get_ws_db_path

_CONFIG_DIR = Path("config")

VALID_PHRASES = [
    ("hello", "Hello!"),
    ("thanks", "Thanks!"),
    ("lets_go", "Let's go!"),
]


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


def _create_player(client: TestClient, name: str) -> str:
    resp = client.post(
        "/api/v1/players", json={"name": name, "character_id": "penguin"}
    )
    assert resp.status_code == 200
    return resp.json()["player_id"]


@pytest.mark.parametrize("phrase_id,expected_text", VALID_PHRASES)
def test_valid_phrase_returns_chat_message(
    client: TestClient, phrase_id: str, expected_text: str
) -> None:
    player_id = _create_player(client, f"Player_{phrase_id}")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {"type": "preset_chat", "player_id": player_id, "phrase_id": phrase_id}
        )
        msg = ws.receive_json()

    assert msg["type"] == "chat_message"
    assert msg["player_id"] == player_id
    assert msg["phrase_id"] == phrase_id
    assert msg["message"] == expected_text


def test_unknown_phrase_id_returns_invalid_message_error(client: TestClient) -> None:
    player_id = _create_player(client, "Alice")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {
                "type": "preset_chat",
                "player_id": player_id,
                "phrase_id": "not_a_real_phrase",
            }
        )
        msg = ws.receive_json()

    assert msg["type"] == "error"
    assert msg["code"] == "invalid_message"


def test_missing_phrase_id_returns_invalid_message_error(client: TestClient) -> None:
    player_id = _create_player(client, "Bob")

    with client.websocket_connect(f"/ws/{player_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json({"type": "preset_chat", "player_id": player_id})
        msg = ws.receive_json()

    assert msg["type"] == "error"
    assert msg["code"] == "invalid_message"


@pytest.mark.integration
def test_chat_message_broadcast_to_other_players(client: TestClient) -> None:
    sender_id = _create_player(client, "Sender")
    receiver_id = _create_player(client, "Receiver")

    receiver_messages: list[dict] = []
    receiver_ready = threading.Event()
    receiver_done = threading.Event()

    def run_receiver() -> None:
        try:
            with client.websocket_connect(f"/ws/{receiver_id}") as ws:
                ws.receive_json()  # consume state_sync
                receiver_ready.set()
                try:
                    msg = ws.receive_json()
                    receiver_messages.append(msg)
                except Exception as exc:
                    print(f"receiver inner error: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"receiver connect error: {exc}", file=sys.stderr)
        finally:
            if not receiver_ready.is_set():
                receiver_ready.set()
            receiver_done.set()

    thread = threading.Thread(target=run_receiver, daemon=True)
    thread.start()
    receiver_ready.wait(timeout=5)
    time.sleep(0.05)

    with client.websocket_connect(f"/ws/{sender_id}") as ws:
        ws.receive_json()  # consume state_sync
        ws.send_json(
            {"type": "preset_chat", "player_id": sender_id, "phrase_id": "hello"}
        )
        sender_msg = ws.receive_json()
        time.sleep(0.2)

    receiver_done.wait(timeout=5)
    thread.join(timeout=5)

    assert sender_msg["type"] == "chat_message"
    assert sender_msg["phrase_id"] == "hello"
    assert sender_msg["player_id"] == sender_id

    assert len(receiver_messages) >= 1, f"Receiver got no messages: {receiver_messages}"
    recv = receiver_messages[0]
    assert recv["type"] == "chat_message"
    assert recv["phrase_id"] == "hello"
    assert recv["player_id"] == sender_id
