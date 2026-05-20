"""Tests for GET /api/v1/config/bootstrap route (issue 16.1).

These tests fail against the current code because no route is registered
for /api/v1/config/bootstrap. They pass once a route is added.
"""

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

REQUIRED_BOOTSTRAP_KEYS = {
    "map",
    "map_tiles",
    "npcs",
    "quests",
    "items",
    "shop",
    "characters",
    "preset_phrases",
    "progression",
    "assets",
}


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


def test_bootstrap_route_returns_200(client: TestClient) -> None:
    resp = client.get("/api/v1/config/bootstrap")
    assert resp.status_code == 200, (
        f"Expected 200 but got {resp.status_code}. "
        "The /api/v1/config/bootstrap endpoint is not registered."
    )


def test_bootstrap_route_returns_all_required_keys(client: TestClient) -> None:
    resp = client.get("/api/v1/config/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    missing = REQUIRED_BOOTSTRAP_KEYS - set(body.keys())
    assert not missing, f"Bootstrap response missing required keys: {missing}"


def test_bootstrap_route_map_key_is_dict(client: TestClient) -> None:
    resp = client.get("/api/v1/config/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["map"], dict), "bootstrap.map must be a dict"


def test_bootstrap_route_npcs_key_is_list(client: TestClient) -> None:
    resp = client.get("/api/v1/config/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["npcs"], list), "bootstrap.npcs must be a list"


def test_bootstrap_route_quests_key_is_list(client: TestClient) -> None:
    resp = client.get("/api/v1/config/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["quests"], list), "bootstrap.quests must be a list"
