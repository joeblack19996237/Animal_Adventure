from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    db = tmp_path / "events.sqlite3"
    init_db(db)
    monkeypatch.setenv("DATABASE_PATH", str(db))
    with TestClient(app) as c:
        yield c


def test_client_logging_config_route(client: TestClient) -> None:
    resp = client.get("/api/v1/logs/client-config")
    assert resp.status_code == 200
    assert resp.json() == {
        "enabled": True,
        "sample_rate": 1.0,
        "endpoint": "/api/v1/client-events",
    }


def test_client_events_route_persists_event(client: TestClient, tmp_path: Path) -> None:
    db = tmp_path / "events.sqlite3"
    resp = client.post(
        "/api/v1/client-events",
        json={
            "event_type": "ui.click",
            "player_id": "player-1",
            "payload": {"button": "shop"},
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT player_id, event_type, event_payload_json FROM player_events"
        ).fetchone()
    finally:
        conn.close()

    expected_payload = json.dumps({"button": "shop"}, separators=(",", ":"), sort_keys=True)
    assert row == ("player-1", "ui.click", expected_payload)


def test_client_events_rejects_invalid_event_type(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/client-events",
        json={"event_type": "bad event", "payload": {}},
    )
    assert resp.status_code == 422
