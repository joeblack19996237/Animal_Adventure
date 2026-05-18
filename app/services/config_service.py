from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_CONFIG_FILES = [
    "map.json",
    "map_tiles.json",
    "npcs.json",
    "quests.json",
    "items.json",
    "shop.json",
    "characters.json",
    "preset_phrases.json",
    "progression.json",
    "assets.json",
]

_FILE_TO_KEY: dict[str, str] = {
    "map.json": "map",
    "map_tiles.json": "map_tiles",
    "npcs.json": "npcs",
    "quests.json": "quests",
    "items.json": "items",
    "shop.json": "shop",
    "characters.json": "characters",
    "preset_phrases.json": "preset_phrases",
    "progression.json": "progression",
    "assets.json": "assets",
}


class ConfigValidationError(Exception):
    pass


class ConfigService:
    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir

    def get_bootstrap(self) -> dict:
        configs = self._load_all()
        self._validate(configs)
        return configs

    def _load_all(self) -> dict:
        result: dict = {}
        for filename, key in _FILE_TO_KEY.items():
            path = self._config_dir / filename
            if not path.exists():
                raise FileNotFoundError(f"Required config file missing: {filename}")
            content = path.read_text(encoding="utf-8")
            try:
                result[key] = json.loads(content)
            except json.JSONDecodeError as e:
                raise ConfigValidationError(f"Malformed JSON in {filename}: {e}") from e
        return result

    def _validate(self, configs: dict) -> None:
        asset_ids: set[str] = set(configs["assets"].keys())
        npc_ids: set[str] = {npc["id"] for npc in configs["npcs"]}
        item_ids: set[str] = {item["id"] for item in configs["items"]}
        self._validate_npc_assets(configs["npcs"], asset_ids)
        self._validate_item_assets(configs["items"], asset_ids)
        self._validate_character_assets(configs["characters"], asset_ids)
        self._validate_quest_references(configs["quests"], npc_ids, item_ids)

    def _validate_npc_assets(self, npcs: list, asset_ids: set[str]) -> None:
        for npc in npcs:
            asset_id = npc.get("asset_id", "")
            if asset_id not in asset_ids:
                raise ConfigValidationError(
                    f"NPC '{npc['id']}' references unknown asset id '{asset_id}'"
                )

    def _validate_item_assets(self, items: list, asset_ids: set[str]) -> None:
        for item in items:
            asset_id = item.get("asset_id", "")
            if asset_id not in asset_ids:
                raise ConfigValidationError(
                    f"Item '{item['id']}' references unknown asset id '{asset_id}'"
                )

    def _validate_character_assets(self, characters: list, asset_ids: set[str]) -> None:
        for character in characters:
            states = character.get("states", {})
            for state_name, state_data in states.items():
                for direction, ref in state_data.items():
                    if direction == "right_mirror":
                        continue
                    if isinstance(ref, str) and ref not in asset_ids:
                        raise ConfigValidationError(
                            f"Character '{character['id']}' state '{state_name}.{direction}' "
                            f"references unknown asset id '{ref}'"
                        )

    def _validate_quest_references(
        self, quests: list, npc_ids: set[str], item_ids: set[str]
    ) -> None:
        for quest in quests:
            npc_id = quest.get("npc_id", "")
            if npc_id not in npc_ids:
                raise ConfigValidationError(
                    f"Quest '{quest['id']}' references unknown NPC id '{npc_id}'"
                )
            for item_id in quest.get("required_items", []):
                if item_id not in item_ids:
                    raise ConfigValidationError(
                        f"Quest '{quest['id']}' references unknown item id '{item_id}'"
                    )
