import json
from pathlib import Path

import pytest

from app.services.config_service import ConfigService, ConfigValidationError

BOOTSTRAP_REQUIRED_KEYS = [
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
]

CONFIG_DIR = Path(__file__).parent.parent / "config"


@pytest.fixture
def service() -> ConfigService:
    return ConfigService(CONFIG_DIR)


def _copy_configs(tmp_path: Path, overrides: dict[str, object]) -> Path:
    for src in CONFIG_DIR.iterdir():
        if src.suffix == ".json":
            if src.name in overrides:
                (tmp_path / src.name).write_text(
                    json.dumps(overrides[src.name]), encoding="utf-8"
                )
            else:
                (tmp_path / src.name).write_bytes(src.read_bytes())
    return tmp_path


# Bootstrap shape tests


@pytest.mark.parametrize("key", BOOTSTRAP_REQUIRED_KEYS)
def test_bootstrap_contains_required_key(service: ConfigService, key: str) -> None:
    bootstrap = service.get_bootstrap()
    assert key in bootstrap, f"Bootstrap response missing required key: '{key}'"


def test_bootstrap_map_has_nested_map_key(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["map"], dict)
    assert "map" in bootstrap["map"]


def test_bootstrap_map_tiles_has_tiles_list(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["map_tiles"], dict)
    assert "tiles" in bootstrap["map_tiles"]
    assert isinstance(bootstrap["map_tiles"]["tiles"], list)


def test_bootstrap_npcs_is_list_of_three(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["npcs"], list)
    assert len(bootstrap["npcs"]) >= 3


def test_bootstrap_quests_is_list_of_three(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["quests"], list)
    assert len(bootstrap["quests"]) >= 3


def test_bootstrap_items_is_list(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["items"], list)
    assert len(bootstrap["items"]) > 0


def test_bootstrap_shop_has_items_key(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["shop"], dict)
    assert "items" in bootstrap["shop"]


def test_bootstrap_characters_is_list_of_three(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["characters"], list)
    assert len(bootstrap["characters"]) >= 3


def test_bootstrap_preset_phrases_is_list(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["preset_phrases"], list)
    assert len(bootstrap["preset_phrases"]) > 0


def test_bootstrap_progression_has_levels(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["progression"], dict)
    assert "levels" in bootstrap["progression"]


def test_bootstrap_assets_is_dict(service: ConfigService) -> None:
    bootstrap = service.get_bootstrap()
    assert isinstance(bootstrap["assets"], dict)
    assert len(bootstrap["assets"]) > 0


# Validation: cross-reference asset ids


def test_raises_for_npc_with_unknown_asset_id(tmp_path: Path) -> None:
    bad_npcs = [
        {
            "id": "hopper",
            "name": "Hopper",
            "asset_id": "nonexistent_npc_asset",
            "x": 2715,
            "y": 3200,
            "interaction_radius": 160,
            "quest_id": "quest_hopper_blanket",
        }
    ]
    config_dir = _copy_configs(tmp_path, {"npcs.json": bad_npcs})
    with pytest.raises(ConfigValidationError, match="asset"):
        ConfigService(config_dir).get_bootstrap()


def test_raises_for_item_with_unknown_asset_id(tmp_path: Path) -> None:
    bad_items = [
        {
            "id": "item_blanket",
            "name": "Blanket",
            "asset_id": "ghost_item_asset",
            "stackable": False,
            "slot_type": "inventory",
            "type": "quest_item",
        }
    ]
    config_dir = _copy_configs(tmp_path, {"items.json": bad_items})
    with pytest.raises(ConfigValidationError, match="asset"):
        ConfigService(config_dir).get_bootstrap()


def test_raises_for_character_state_with_unknown_asset_id(tmp_path: Path) -> None:
    bad_characters = [
        {
            "id": "penguin",
            "display_name": "Penguin",
            "enabled_in_mvp": True,
            "scale": 0.45,
            "anchor": {"x": 0.5, "y": 0.9},
            "collision_radius": 36,
            "states": {
                "stand": {
                    "front": "missing_asset_id",
                    "back": "character_penguin_stand_back",
                }
            },
        }
    ]
    config_dir = _copy_configs(tmp_path, {"characters.json": bad_characters})
    with pytest.raises(ConfigValidationError, match="asset"):
        ConfigService(config_dir).get_bootstrap()


# Validation: cross-reference logical ids


def test_raises_for_quest_referencing_nonexistent_npc(tmp_path: Path) -> None:
    bad_quests = [
        {
            "id": "quest_ghost",
            "npc_id": "ghost_npc",
            "title": "Ghost Quest",
            "time_limit_seconds": 300,
            "required_items": ["item_blanket"],
            "item_spawn": {"mode": "fixed", "x": 0, "y": 0, "pickup_radius": 96},
            "rewards": [{"type": "coins", "amount": 25}],
            "completion_cooldown_seconds": 3600,
            "failure_cooldown_seconds": 1800,
        }
    ]
    config_dir = _copy_configs(tmp_path, {"quests.json": bad_quests})
    with pytest.raises(ConfigValidationError):
        ConfigService(config_dir).get_bootstrap()


def test_raises_for_quest_referencing_nonexistent_item(tmp_path: Path) -> None:
    bad_quests = [
        {
            "id": "quest_hopper_blanket",
            "npc_id": "hopper",
            "title": "Find Hopper's Blanket",
            "time_limit_seconds": 300,
            "required_items": ["item_nonexistent"],
            "item_spawn": {"mode": "fixed", "x": 2600, "y": 3100, "pickup_radius": 96},
            "rewards": [{"type": "coins", "amount": 25}],
            "completion_cooldown_seconds": 3600,
            "failure_cooldown_seconds": 1800,
        }
    ]
    config_dir = _copy_configs(tmp_path, {"quests.json": bad_quests})
    with pytest.raises(ConfigValidationError):
        ConfigService(config_dir).get_bootstrap()


# Validation: malformed or missing files


def test_raises_for_malformed_json(tmp_path: Path) -> None:
    for src in CONFIG_DIR.iterdir():
        if src.suffix == ".json":
            (tmp_path / src.name).write_bytes(src.read_bytes())
    (tmp_path / "npcs.json").write_text("not valid json{{{", encoding="utf-8")
    with pytest.raises((ConfigValidationError, ValueError)):
        ConfigService(tmp_path).get_bootstrap()


def test_raises_when_required_config_file_is_missing(tmp_path: Path) -> None:
    for src in CONFIG_DIR.iterdir():
        if src.suffix == ".json" and src.name != "npcs.json":
            (tmp_path / src.name).write_bytes(src.read_bytes())
    with pytest.raises((ConfigValidationError, FileNotFoundError)):
        ConfigService(tmp_path).get_bootstrap()
