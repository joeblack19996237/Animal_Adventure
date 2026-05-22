"""Tests for character config validation.

Validates config/characters.json: MVP character ids, direction/state mappings,
numeric field bounds, and asset id references against config/assets.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parent.parent
CHARACTERS_JSON = REPO_ROOT / "config" / "characters.json"
ASSETS_JSON = REPO_ROOT / "config" / "assets.json"

MVP_CHARACTER_IDS = ["penguin", "arctic_fox", "cat_snowman"]

REQUIRED_CHARACTER_FIELDS = {
    "id",
    "display_name",
    "enabled_in_mvp",
    "scale",
    "anchor",
    "collision_radius",
    "states",
}

STAND_REQUIRED_DIRECTIONS = {"front", "back"}
WALK_REQUIRED_DIRECTIONS = {"front", "back", "left", "right"}

SCALE_MIN = 0.0
SCALE_MAX = 2.0
ANCHOR_MIN = 0.0
ANCHOR_MAX = 1.0
COLLISION_RADIUS_MIN = 1
COLLISION_RADIUS_MAX = 200


@pytest.fixture
def characters() -> list[dict[str, Any]]:
    return json.loads(CHARACTERS_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def assets_manifest() -> dict[str, str]:
    return json.loads(ASSETS_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def character_by_id(characters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {ch["id"]: ch for ch in characters}


class TestCharacterConfigStructure:
    def test_characters_json_exists(self) -> None:
        assert CHARACTERS_JSON.exists(), "config/characters.json must exist"

    def test_characters_json_is_valid_json(self) -> None:
        content = CHARACTERS_JSON.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, list)

    def test_characters_json_is_non_empty_list(
        self, characters: list[dict[str, Any]]
    ) -> None:
        assert len(characters) > 0, "config/characters.json must not be empty"

    def test_all_mvp_character_ids_present(
        self, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        missing = [cid for cid in MVP_CHARACTER_IDS if cid not in character_by_id]
        assert not missing, (
            f"Missing MVP character ids in config/characters.json: {missing}"
        )

    def test_no_extra_character_ids_beyond_mvp(
        self, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        extra = [cid for cid in character_by_id if cid not in MVP_CHARACTER_IDS]
        assert not extra, (
            f"Extra non-MVP character ids found in config/characters.json: {extra}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_has_required_fields(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        missing = REQUIRED_CHARACTER_FIELDS - set(ch.keys())
        assert not missing, f"Character {char_id!r} missing required fields: {missing}"

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_is_enabled_in_mvp(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        assert ch["enabled_in_mvp"] is True, (
            f"Character {char_id!r} must have enabled_in_mvp=true"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_id_field_matches_key(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        assert ch["id"] == char_id, (
            f"Character id field {ch['id']!r} does not match expected {char_id!r}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_has_non_empty_display_name(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        assert isinstance(ch["display_name"], str) and ch["display_name"].strip(), (
            f"Character {char_id!r} must have a non-empty display_name string"
        )


class TestCharacterStateMappings:
    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_states_is_dict(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        assert isinstance(ch["states"], dict), (
            f"Character {char_id!r}: states must be a dict"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_has_stand_state(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        assert "stand" in ch["states"], (
            f"Character {char_id!r}: states must include 'stand'"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_stand_state_has_front_and_back(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        stand = character_by_id[char_id]["states"]["stand"]
        missing = STAND_REQUIRED_DIRECTIONS - set(stand.keys())
        assert not missing, (
            f"Character {char_id!r} stand state missing directions: {missing}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_stand_direction_values_are_strings(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        stand = character_by_id[char_id]["states"]["stand"]
        for direction in STAND_REQUIRED_DIRECTIONS:
            value = stand[direction]
            assert isinstance(value, str) and value.strip(), (
                f"Character {char_id!r} stand.{direction} must be a non-empty string"
            )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_character_has_walk_state(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        ch = character_by_id[char_id]
        assert "walk" in ch["states"], (
            f"Character {char_id!r}: states must include 'walk'"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_walk_state_has_front_back_left_right(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        walk = character_by_id[char_id]["states"]["walk"]
        missing = WALK_REQUIRED_DIRECTIONS - set(walk.keys())
        assert not missing, (
            f"Character {char_id!r} walk state missing directions: {missing}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_walk_direction_values_are_strings_or_frame_lists(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        walk = character_by_id[char_id]["states"]["walk"]
        for direction in WALK_REQUIRED_DIRECTIONS:
            value = walk[direction]
            if isinstance(value, str):
                assert value.strip(), (
                    f"Character {char_id!r} walk.{direction} must be a non-empty string"
                )
            else:
                assert isinstance(value, list) and value, (
                    f"Character {char_id!r} walk.{direction} must be a non-empty string "
                    "or a non-empty list of frame asset ids"
                )
                assert all(isinstance(frame, str) and frame.strip() for frame in value), (
                    f"Character {char_id!r} walk.{direction} frame list must contain "
                    "only non-empty strings"
                )


class TestCharacterNumericFields:
    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_scale_is_float_or_int(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        scale = character_by_id[char_id]["scale"]
        assert isinstance(scale, (int, float)), (
            f"Character {char_id!r}: scale must be numeric, got {type(scale).__name__}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_scale_is_above_zero(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        scale = character_by_id[char_id]["scale"]
        assert scale > SCALE_MIN, (
            f"Character {char_id!r}: scale must be > {SCALE_MIN}, got {scale}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_scale_does_not_exceed_maximum(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        scale = character_by_id[char_id]["scale"]
        assert scale <= SCALE_MAX, (
            f"Character {char_id!r}: scale must be <= {SCALE_MAX}, got {scale}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_anchor_is_dict_with_x_and_y(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        anchor = character_by_id[char_id]["anchor"]
        assert isinstance(anchor, dict), f"Character {char_id!r}: anchor must be a dict"
        assert "x" in anchor and "y" in anchor, (
            f"Character {char_id!r}: anchor must have 'x' and 'y' keys"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_anchor_x_is_numeric_within_unit_range(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        anchor_x = character_by_id[char_id]["anchor"]["x"]
        assert isinstance(anchor_x, (int, float)), (
            f"Character {char_id!r}: anchor.x must be numeric"
        )
        assert ANCHOR_MIN <= anchor_x <= ANCHOR_MAX, (
            f"Character {char_id!r}: anchor.x must be in [{ANCHOR_MIN}, {ANCHOR_MAX}], "
            f"got {anchor_x}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_anchor_y_is_numeric_within_unit_range(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        anchor_y = character_by_id[char_id]["anchor"]["y"]
        assert isinstance(anchor_y, (int, float)), (
            f"Character {char_id!r}: anchor.y must be numeric"
        )
        assert ANCHOR_MIN <= anchor_y <= ANCHOR_MAX, (
            f"Character {char_id!r}: anchor.y must be in [{ANCHOR_MIN}, {ANCHOR_MAX}], "
            f"got {anchor_y}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_collision_radius_is_numeric(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        radius = character_by_id[char_id]["collision_radius"]
        assert isinstance(radius, (int, float)), (
            f"Character {char_id!r}: collision_radius must be numeric, "
            f"got {type(radius).__name__}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_collision_radius_is_positive(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        radius = character_by_id[char_id]["collision_radius"]
        assert radius >= COLLISION_RADIUS_MIN, (
            f"Character {char_id!r}: collision_radius must be >= {COLLISION_RADIUS_MIN}, "
            f"got {radius}"
        )

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_collision_radius_within_reasonable_bound(
        self, char_id: str, character_by_id: dict[str, dict[str, Any]]
    ) -> None:
        radius = character_by_id[char_id]["collision_radius"]
        assert radius <= COLLISION_RADIUS_MAX, (
            f"Character {char_id!r}: collision_radius must be <= {COLLISION_RADIUS_MAX}, "
            f"got {radius}"
        )


class TestCharacterAssetReferences:
    def _collect_asset_ids(self, states: dict[str, Any]) -> list[str]:
        """Return all string asset id values from a states dict."""
        asset_ids: list[str] = []
        for state_mapping in states.values():
            if not isinstance(state_mapping, dict):
                continue
            for value in state_mapping.values():
                if isinstance(value, str):
                    asset_ids.append(value)
                elif isinstance(value, list):
                    asset_ids.extend(
                        frame for frame in value if isinstance(frame, str)
                    )
        return asset_ids

    @pytest.mark.parametrize("char_id", MVP_CHARACTER_IDS)
    def test_all_state_asset_ids_exist_in_assets_json(
        self,
        char_id: str,
        character_by_id: dict[str, dict[str, Any]],
        assets_manifest: dict[str, str],
    ) -> None:
        states = character_by_id[char_id]["states"]
        asset_ids = self._collect_asset_ids(states)
        missing = [aid for aid in asset_ids if aid not in assets_manifest]
        assert not missing, (
            f"Character {char_id!r}: state asset ids not found in config/assets.json: "
            f"{missing}"
        )

    def test_all_characters_asset_references_valid(
        self,
        characters: list[dict[str, Any]],
        assets_manifest: dict[str, str],
    ) -> None:
        errors: list[str] = []
        for ch in characters:
            char_id = ch.get("id", "?")
            states = ch.get("states", {})
            for state_name, state_mapping in states.items():
                if not isinstance(state_mapping, dict):
                    continue
                for direction, value in state_mapping.items():
                    if isinstance(value, str) and value not in assets_manifest:
                        errors.append(
                            f"{char_id}.states.{state_name}.{direction}={value!r}"
                        )
                    elif isinstance(value, list):
                        for frame in value:
                            if isinstance(frame, str) and frame not in assets_manifest:
                                errors.append(
                                    f"{char_id}.states.{state_name}.{direction}={frame!r}"
                                )
        assert not errors, (
            "Character state asset ids missing from config/assets.json:\n"
            + "\n".join(errors)
        )

    def test_assets_json_exists_for_reference_check(self) -> None:
        assert ASSETS_JSON.exists(), (
            "config/assets.json must exist for reference checks"
        )
