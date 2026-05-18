"""Tests for quest config validation.

Validates config/quests.json: MVP quest ids, required fields, NPC cross-references,
item spawn proximity to Spawn area, and absence of quest items in V2-only zones.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parent.parent
QUESTS_JSON = REPO_ROOT / "config" / "quests.json"
ITEMS_JSON = REPO_ROOT / "config" / "items.json"
NPCS_JSON = REPO_ROOT / "config" / "npcs.json"
MAP_JSON = REPO_ROOT / "config" / "map.json"

MVP_QUEST_IDS = [
    "quest_hopper_blanket",
    "quest_copper_bagpipe",
    "quest_elisa_dance_shoes",
]

EXPECTED_QUEST_ITEMS: dict[str, list[str]] = {
    "quest_hopper_blanket": ["item_blanket"],
    "quest_copper_bagpipe": ["item_bagpipe"],
    "quest_elisa_dance_shoes": ["item_dance_shoes"],
}

EXPECTED_NPC_BY_QUEST: dict[str, str] = {
    "quest_hopper_blanket": "hopper",
    "quest_copper_bagpipe": "copper",
    "quest_elisa_dance_shoes": "elisa",
}

REQUIRED_QUEST_FIELDS = {
    "id",
    "npc_id",
    "title",
    "time_limit_seconds",
    "required_items",
    "item_spawn",
    "rewards",
    "completion_cooldown_seconds",
    "failure_cooldown_seconds",
}

QUEST_TIME_LIMIT_SECONDS = 300
COMPLETION_COOLDOWN_SECONDS = 3600
FAILURE_COOLDOWN_SECONDS = 1800


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


@pytest.fixture
def quests() -> list[dict[str, Any]]:
    return json.loads(QUESTS_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def quest_by_id(quests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {q["id"]: q for q in quests}


@pytest.fixture
def items_by_id() -> dict[str, dict[str, Any]]:
    items = json.loads(ITEMS_JSON.read_text(encoding="utf-8"))
    return {item["id"]: item for item in items}


@pytest.fixture
def npcs_by_id() -> dict[str, dict[str, Any]]:
    npcs = json.loads(NPCS_JSON.read_text(encoding="utf-8"))
    return {npc["id"]: npc for npc in npcs}


@pytest.fixture
def map_config() -> dict[str, Any]:
    return json.loads(MAP_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def spawn_area(map_config: dict[str, Any]) -> dict[str, Any]:
    for region in map_config.get("interaction_regions", []):
        if region.get("id") == "spawn_area":
            return region
    pytest.fail("spawn_area interaction region not found in config/map.json")


class TestQuestConfigStructure:
    def test_quests_json_exists(self) -> None:
        assert QUESTS_JSON.exists(), "config/quests.json must exist"

    def test_quests_json_is_valid_json(self) -> None:
        data = json.loads(QUESTS_JSON.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_all_mvp_quest_ids_present(
        self, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        missing = [qid for qid in MVP_QUEST_IDS if qid not in quest_by_id]
        assert not missing, f"Missing MVP quest ids in config/quests.json: {missing}"

    def test_no_non_mvp_quest_ids_present(
        self, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        extra = [qid for qid in quest_by_id if qid not in MVP_QUEST_IDS]
        assert not extra, f"Non-MVP quest ids found in config/quests.json: {extra}"

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_quest_has_required_fields(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        missing = REQUIRED_QUEST_FIELDS - set(quest_by_id[quest_id].keys())
        assert not missing, f"Quest {quest_id!r} missing required fields: {missing}"

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_quest_id_field_matches_key(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        assert quest_by_id[quest_id]["id"] == quest_id

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_quest_has_non_empty_title(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        title = quest_by_id[quest_id]["title"]
        assert isinstance(title, str) and title.strip(), (
            f"Quest {quest_id!r} must have a non-empty title"
        )


class TestQuestNpcReferences:
    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_quest_npc_id_matches_expected(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        expected = EXPECTED_NPC_BY_QUEST[quest_id]
        actual = quest_by_id[quest_id]["npc_id"]
        assert actual == expected, (
            f"Quest {quest_id!r}: npc_id={actual!r}, expected {expected!r}"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_quest_npc_id_exists_in_npcs_config(
        self,
        quest_id: str,
        quest_by_id: dict[str, dict[str, Any]],
        npcs_by_id: dict[str, dict[str, Any]],
    ) -> None:
        npc_id = quest_by_id[quest_id]["npc_id"]
        assert npc_id in npcs_by_id, (
            f"Quest {quest_id!r} references npc_id={npc_id!r} not in config/npcs.json"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_npc_back_references_quest(
        self,
        quest_id: str,
        quest_by_id: dict[str, dict[str, Any]],
        npcs_by_id: dict[str, dict[str, Any]],
    ) -> None:
        npc_id = quest_by_id[quest_id]["npc_id"]
        npc_quest_id = npcs_by_id[npc_id].get("quest_id")
        assert npc_quest_id == quest_id, (
            f"NPC {npc_id!r}.quest_id={npc_quest_id!r} does not match {quest_id!r}"
        )


class TestQuestItemConfig:
    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_required_items_match_spec(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        actual = quest_by_id[quest_id]["required_items"]
        expected = EXPECTED_QUEST_ITEMS[quest_id]
        assert actual == expected, (
            f"Quest {quest_id!r}: required_items={actual!r}, expected {expected!r}"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_required_items_exist_in_items_config(
        self,
        quest_id: str,
        quest_by_id: dict[str, dict[str, Any]],
        items_by_id: dict[str, dict[str, Any]],
    ) -> None:
        missing = [
            iid
            for iid in quest_by_id[quest_id]["required_items"]
            if iid not in items_by_id
        ]
        assert not missing, (
            f"Quest {quest_id!r}: item ids not in config/items.json: {missing}"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_required_items_have_quest_type(
        self,
        quest_id: str,
        quest_by_id: dict[str, dict[str, Any]],
        items_by_id: dict[str, dict[str, Any]],
    ) -> None:
        for item_id in quest_by_id[quest_id]["required_items"]:
            item_type = items_by_id[item_id]["type"]
            assert item_type == "quest_item", (
                f"Quest {quest_id!r}: item {item_id!r} type={item_type!r}, expected 'quest_item'"
            )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_item_spawn_has_required_fields(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        spawn = quest_by_id[quest_id]["item_spawn"]
        for field in ("mode", "x", "y", "pickup_radius"):
            assert field in spawn, (
                f"Quest {quest_id!r} item_spawn missing field {field!r}"
            )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_item_spawn_mode_is_fixed(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        mode = quest_by_id[quest_id]["item_spawn"]["mode"]
        assert mode == "fixed", (
            f"Quest {quest_id!r}: item_spawn.mode={mode!r}, expected 'fixed'"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_item_spawn_pickup_radius_is_positive(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        radius = quest_by_id[quest_id]["item_spawn"]["pickup_radius"]
        assert radius > 0, (
            f"Quest {quest_id!r}: item_spawn.pickup_radius must be positive, got {radius}"
        )


class TestQuestItemSpawnProximity:
    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_item_spawn_is_within_spawn_area(
        self,
        quest_id: str,
        quest_by_id: dict[str, dict[str, Any]],
        spawn_area: dict[str, Any],
    ) -> None:
        spawn = quest_by_id[quest_id]["item_spawn"]
        dist = _distance(spawn_area["x"], spawn_area["y"], spawn["x"], spawn["y"])
        assert dist <= spawn_area["radius"], (
            f"Quest {quest_id!r}: item spawn ({spawn['x']}, {spawn['y']}) is {dist:.1f}px "
            f"from Spawn center, exceeds radius {spawn_area['radius']}px — "
            f"quest items must be in Spawn area, not V2-only zones"
        )

    def test_no_mvp_quest_item_outside_spawn_area(
        self,
        quest_by_id: dict[str, dict[str, Any]],
        spawn_area: dict[str, Any],
    ) -> None:
        violations: list[str] = []
        for quest_id in MVP_QUEST_IDS:
            if quest_id not in quest_by_id:
                continue
            spawn = quest_by_id[quest_id]["item_spawn"]
            dist = _distance(spawn_area["x"], spawn_area["y"], spawn["x"], spawn["y"])
            if dist > spawn_area["radius"]:
                violations.append(
                    f"{quest_id}: ({spawn['x']}, {spawn['y']}) dist={dist:.1f} "
                    f"> radius {spawn_area['radius']}"
                )
        assert not violations, (
            "MVP quest items placed in V2-only zones (outside Spawn area):\n"
            + "\n".join(violations)
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_item_spawn_coordinates_within_map_bounds(
        self,
        quest_id: str,
        quest_by_id: dict[str, dict[str, Any]],
        map_config: dict[str, Any],
    ) -> None:
        spawn = quest_by_id[quest_id]["item_spawn"]
        bounds = map_config["map"]["bounds"]
        assert bounds["x"] <= spawn["x"] <= bounds["x"] + bounds["width"], (
            f"Quest {quest_id!r}: item_spawn.x={spawn['x']} outside map x bounds"
        )
        assert bounds["y"] <= spawn["y"] <= bounds["y"] + bounds["height"], (
            f"Quest {quest_id!r}: item_spawn.y={spawn['y']} outside map y bounds"
        )


class TestQuestTimersAndCooldowns:
    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_time_limit_is_300_seconds(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        actual = quest_by_id[quest_id]["time_limit_seconds"]
        assert actual == QUEST_TIME_LIMIT_SECONDS, (
            f"Quest {quest_id!r}: time_limit_seconds={actual}, expected {QUEST_TIME_LIMIT_SECONDS}"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_completion_cooldown_is_3600_seconds(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        actual = quest_by_id[quest_id]["completion_cooldown_seconds"]
        assert actual == COMPLETION_COOLDOWN_SECONDS, (
            f"Quest {quest_id!r}: completion_cooldown_seconds={actual}, "
            f"expected {COMPLETION_COOLDOWN_SECONDS}"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_failure_cooldown_is_1800_seconds(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        actual = quest_by_id[quest_id]["failure_cooldown_seconds"]
        assert actual == FAILURE_COOLDOWN_SECONDS, (
            f"Quest {quest_id!r}: failure_cooldown_seconds={actual}, "
            f"expected {FAILURE_COOLDOWN_SECONDS}"
        )


class TestQuestRewards:
    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_rewards_is_non_empty_list(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        rewards = quest_by_id[quest_id]["rewards"]
        assert isinstance(rewards, list) and len(rewards) > 0, (
            f"Quest {quest_id!r}: rewards must be a non-empty list"
        )

    @pytest.mark.parametrize("quest_id", MVP_QUEST_IDS)
    def test_rewards_include_exactly_25_coins(
        self, quest_id: str, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        rewards = quest_by_id[quest_id]["rewards"]
        coin_rewards = [r for r in rewards if r.get("type") == "coins"]
        assert len(coin_rewards) == 1, (
            f"Quest {quest_id!r}: must have exactly one coins reward"
        )
        assert coin_rewards[0]["amount"] == 25, (
            f"Quest {quest_id!r}: coins reward amount must be 25, got {coin_rewards[0]['amount']}"
        )

    def test_hopper_quest_rewards_include_accessory_sleepy_hat(
        self, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        rewards = quest_by_id["quest_hopper_blanket"]["rewards"]
        equipment_rewards = [r for r in rewards if r.get("type") == "equipment"]
        assert len(equipment_rewards) == 1, (
            "quest_hopper_blanket must have exactly one equipment reward"
        )
        assert equipment_rewards[0]["item_id"] == "accessory_sleepy_hat", (
            f"quest_hopper_blanket equipment reward must be 'accessory_sleepy_hat', "
            f"got {equipment_rewards[0]['item_id']!r}"
        )

    def test_copper_quest_rewards_coins_only(
        self, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        rewards = quest_by_id["quest_copper_bagpipe"]["rewards"]
        non_coin = [r for r in rewards if r.get("type") != "coins"]
        assert not non_coin, (
            f"quest_copper_bagpipe must have only coin rewards, got: {non_coin}"
        )

    def test_elisa_quest_rewards_coins_only(
        self, quest_by_id: dict[str, dict[str, Any]]
    ) -> None:
        rewards = quest_by_id["quest_elisa_dance_shoes"]["rewards"]
        non_coin = [r for r in rewards if r.get("type") != "coins"]
        assert not non_coin, (
            f"quest_elisa_dance_shoes must have only coin rewards, got: {non_coin}"
        )
