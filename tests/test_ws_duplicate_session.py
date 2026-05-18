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


def test_ws_duplicate_session_replaces_old_connection(client: TestClient) -> None:
    player_id = _create_player(client, "Alice")

    old_messages: list[dict] = []
    old_ready = threading.Event()
    old_done = threading.Event()

    def run_old_connection() -> None:
        try:
            with client.websocket_connect(f"/ws/{player_id}") as ws:
                old_messages.append(ws.receive_json())  # state_sync
                old_ready.set()
                try:
                    old_messages.append(ws.receive_json())  # duplicate_session error
                except Exception:
                    # Expected: server closes connection after sending error
                    pass
        except Exception:
            pass
        finally:
            if not old_ready.is_set():
                old_ready.set()
            old_done.set()

    thread = threading.Thread(target=run_old_connection, daemon=True)
    thread.start()

    old_ready.wait(timeout=5)
    # Allow old thread to reach the blocking receive_json call
    time.sleep(0.05)

    with client.websocket_connect(f"/ws/{player_id}") as new_ws:
        new_state_sync = new_ws.receive_json()

    old_done.wait(timeout=5)
    thread.join(timeout=5)

    # Old connection received state_sync initially
    assert len(old_messages) >= 1, f"Old connection got no messages: {old_messages}"
    assert old_messages[0]["type"] == "state_sync"

    # Old connection must have received duplicate_session error before being closed
    assert len(old_messages) == 2, (
        f"Old connection expected [state_sync, duplicate_session_error], got: {old_messages}"
    )
    assert old_messages[1]["type"] == "error"
    assert old_messages[1]["code"] == "duplicate_session"

    # New connection received state_sync
    assert new_state_sync["type"] == "state_sync"
    assert new_state_sync["player"]["id"] == player_id
