from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import init_db
from app.services.player_service import (
    InvalidCharacterError,
    InvalidNameError,
    PlayerService,
)

_REAL_CONFIG = Path("config")


@pytest.fixture
def service(tmp_path: Path) -> PlayerService:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    return PlayerService(db_path=db, config_dir=_REAL_CONFIG)


@pytest.fixture
def service_with_disabled(tmp_path: Path) -> PlayerService:
    db = tmp_path / "test.sqlite3"
    init_db(db)
    cfg = tmp_path / "config"
    cfg.mkdir()
    chars = [
        {"id": "penguin", "enabled_in_mvp": True, "states": {}},
        {"id": "disabled_char", "enabled_in_mvp": False, "states": {}},
    ]
    (cfg / "characters.json").write_text(json.dumps(chars), encoding="utf-8")
    return PlayerService(db_path=db, config_dir=cfg)


# --- create_player ---


def test_create_player_returns_snapshot_with_id(service: PlayerService) -> None:
    player = service.create_player("Alice", "penguin")
    assert player["player_id"]
    assert player["name"] == "Alice"
    assert player["character_id"] == "penguin"
    assert player["x"] == 2715.0
    assert player["y"] == 3620.0
    assert player["coins"] == 25
    assert player["level"] == 0
    assert player["direction"] == "front"


def test_create_player_trims_name_whitespace(service: PlayerService) -> None:
    player = service.create_player("  Bob  ", "arctic_fox")
    assert player["name"] == "Bob"
    assert player["normalized_name"] == "bob"


def test_create_player_generates_unique_player_ids(service: PlayerService) -> None:
    p1 = service.create_player("Alice", "penguin")
    p2 = service.create_player("Bob", "arctic_fox")
    assert p1["player_id"] != p2["player_id"]


def test_create_player_stores_normalized_name(service: PlayerService) -> None:
    player = service.create_player("  CAROL  ", "cat_snowman")
    assert player["normalized_name"] == "carol"


def test_create_player_raises_for_blank_name(service: PlayerService) -> None:
    with pytest.raises(InvalidNameError):
        service.create_player("   ", "penguin")


def test_create_player_raises_for_empty_name(service: PlayerService) -> None:
    with pytest.raises(InvalidNameError):
        service.create_player("", "penguin")


def test_create_player_raises_for_empty_character_id(service: PlayerService) -> None:
    with pytest.raises(InvalidCharacterError):
        service.create_player("Dave", "")


def test_create_player_raises_for_invalid_character_id(service: PlayerService) -> None:
    with pytest.raises(InvalidCharacterError):
        service.create_player("Eve", "dragon")


def test_create_player_raises_for_disabled_character(
    service_with_disabled: PlayerService,
) -> None:
    with pytest.raises(InvalidCharacterError):
        service_with_disabled.create_player("Frank", "disabled_char")


def test_create_player_accepts_all_mvp_characters(service: PlayerService) -> None:
    for i, char_id in enumerate(("penguin", "arctic_fox", "cat_snowman")):
        player = service.create_player(f"Player{i}", char_id)
        assert player["character_id"] == char_id


# --- load_player ---


def test_load_player_returns_existing_player(service: PlayerService) -> None:
    service.create_player("Grace", "penguin")
    player = service.load_player("Grace")
    assert player is not None
    assert player["name"] == "Grace"
    assert player["character_id"] == "penguin"


def test_load_player_case_insensitive(service: PlayerService) -> None:
    service.create_player("Hank", "arctic_fox")
    player = service.load_player("HANK")
    assert player is not None
    assert player["name"] == "Hank"


def test_load_player_trims_whitespace(service: PlayerService) -> None:
    service.create_player("Iris", "cat_snowman")
    player = service.load_player("  Iris  ")
    assert player is not None
    assert player["name"] == "Iris"


def test_load_player_returns_none_when_not_found(service: PlayerService) -> None:
    result = service.load_player("NoSuchPlayer")
    assert result is None


def test_load_player_raises_for_blank_name(service: PlayerService) -> None:
    with pytest.raises(InvalidNameError):
        service.load_player("   ")


def test_load_player_raises_for_empty_name(service: PlayerService) -> None:
    with pytest.raises(InvalidNameError):
        service.load_player("")


def test_load_player_includes_player_id(service: PlayerService) -> None:
    created = service.create_player("Jake", "penguin")
    loaded = service.load_player("Jake")
    assert loaded is not None
    assert loaded["player_id"] == created["player_id"]
