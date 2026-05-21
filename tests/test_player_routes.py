from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.routes.players import get_player_service
from app.services.player_service import PlayerService

_CONFIG_DIR = Path("config")


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    svc = PlayerService(db_path=db, config_dir=_CONFIG_DIR)
    app.dependency_overrides[get_player_service] = lambda: svc
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_disabled(tmp_path: Path) -> Generator[TestClient, None, None]:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    cfg = tmp_path / "config"
    cfg.mkdir()
    chars = [
        {"id": "penguin", "enabled_in_mvp": True, "states": {}},
        {"id": "disabled_char", "enabled_in_mvp": False, "states": {}},
    ]
    (cfg / "characters.json").write_text(json.dumps(chars), encoding="utf-8")
    svc = PlayerService(db_path=db, config_dir=cfg)
    app.dependency_overrides[get_player_service] = lambda: svc
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- POST /api/v1/players ---


def test_post_creates_new_player_returns_player_id(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/players", json={"name": "Alice", "character_id": "penguin"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "player_id" in body
    assert body["name"] == "Alice"
    assert body["character_id"] == "penguin"
    assert body["coins"] == 25
    assert body["level"] == 0


def test_post_name_only_loads_existing_player(client: TestClient) -> None:
    create_resp = client.post(
        "/api/v1/players", json={"name": "Bob", "character_id": "arctic_fox"}
    )
    assert create_resp.status_code == 200
    player_id = create_resp.json()["player_id"]

    load_resp = client.post("/api/v1/players", json={"name": "Bob"})
    assert load_resp.status_code == 200
    assert load_resp.json()["player_id"] == player_id


def test_post_name_only_unknown_player_returns_character_required(
    client: TestClient,
) -> None:
    resp = client.post("/api/v1/players", json={"name": "NewPlayer"})
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("code") == "character_required"


def test_post_invalid_character_id_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/players", json={"name": "Alice", "character_id": "dragon"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("code") == "invalid_character_id"


def test_post_disabled_character_id_returns_400(client_disabled: TestClient) -> None:
    resp = client_disabled.post(
        "/api/v1/players", json={"name": "Carol", "character_id": "disabled_char"}
    )
    assert resp.status_code == 400
    assert resp.json().get("code") == "invalid_character_id"


def test_post_existing_player_ignores_character_id(client: TestClient) -> None:
    client.post("/api/v1/players", json={"name": "Dave", "character_id": "penguin"})
    resp = client.post(
        "/api/v1/players", json={"name": "Dave", "character_id": "arctic_fox"}
    )
    assert resp.status_code == 200
    assert resp.json()["character_id"] == "penguin"


# --- GET /api/v1/players/{player_id} ---


def test_get_player_returns_durable_snapshot(client: TestClient) -> None:
    create_resp = client.post(
        "/api/v1/players", json={"name": "Eve", "character_id": "cat_snowman"}
    )
    player_id = create_resp.json()["player_id"]

    resp = client.get(f"/api/v1/players/{player_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["player_id"] == player_id
    assert body["name"] == "Eve"
    assert body["character_id"] == "cat_snowman"
    assert "x" in body
    assert "y" in body
    assert "coins" in body
    assert "level" in body
    assert "direction" in body


def test_get_player_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/players/nonexistent-id")
    assert resp.status_code == 404
