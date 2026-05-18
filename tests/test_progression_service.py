"""Tests for ProgressionService: L3 level-up logic, playground unlock, and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import connect_db, init_db
from app.services.player_service import PlayerService
from app.services.progression_service import ProgressionService

_CONFIG_DIR = Path("config")
QUEST_A = "quest_hopper_blanket"
QUEST_B = "quest_copper_bagpipe"
QUEST_C = "quest_elisa_dance_shoes"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    init_db(path)
    return path


@pytest.fixture
def svc(db_path: Path) -> ProgressionService:
    return ProgressionService(db_path=db_path, config_dir=_CONFIG_DIR)


@pytest.fixture
def player(db_path: Path) -> dict:
    return PlayerService(db_path=db_path, config_dir=_CONFIG_DIR).create_player(
        "Alice", "penguin"
    )


def _set_progress(
    db_path: Path,
    player_id: str,
    unique_quest_ids: list[str],
    used_potion_count: int,
) -> None:
    conn = connect_db(db_path)
    conn.execute(
        "UPDATE player_progress "
        "SET unique_completed_quest_ids_json=?, used_potion_count=? WHERE player_id=?",
        (json.dumps(unique_quest_ids), used_potion_count, player_id),
    )
    conn.commit()
    conn.close()


def _get_level(db_path: Path, player_id: str) -> int:
    conn = connect_db(db_path)
    row = conn.execute("SELECT level FROM players WHERE id=?", (player_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def _get_unlocked_regions(db_path: Path, player_id: str) -> list[str]:
    conn = connect_db(db_path)
    row = conn.execute(
        "SELECT unlocked_regions_json FROM player_progress WHERE player_id=?",
        (player_id,),
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row else []


class TestNoLevelUp:
    def test_returns_no_change_when_quests_insufficient(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A], 2)
        result = svc.check_and_apply_progression(player["player_id"])
        assert result["type"] == "no_change"

    def test_returns_no_change_when_potions_insufficient(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B], 1)
        result = svc.check_and_apply_progression(player["player_id"])
        assert result["type"] == "no_change"

    def test_returns_no_change_when_both_insufficient(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [], 0)
        result = svc.check_and_apply_progression(player["player_id"])
        assert result["type"] == "no_change"

    def test_level_unchanged_below_threshold(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A], 1)
        svc.check_and_apply_progression(player["player_id"])
        assert _get_level(db_path, player["player_id"]) == 0


class TestL3LevelUp:
    def test_returns_level_up_when_criteria_met(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B], 2)
        result = svc.check_and_apply_progression(player["player_id"])
        assert result["type"] == "level_up"
        assert result["level"] == 3

    def test_persists_level_3_in_players_table(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B], 2)
        svc.check_and_apply_progression(player["player_id"])
        assert _get_level(db_path, player["player_id"]) == 3

    def test_unlocks_playground_region(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B], 2)
        svc.check_and_apply_progression(player["player_id"])
        regions = _get_unlocked_regions(db_path, player["player_id"])
        assert "playground" in regions

    def test_persists_spawn_and_playground_in_unlocked_regions(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B], 2)
        svc.check_and_apply_progression(player["player_id"])
        regions = _get_unlocked_regions(db_path, player["player_id"])
        assert "spawn" in regions
        assert "playground" in regions

    def test_level_up_is_exactly_once(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        pid = player["player_id"]
        _set_progress(db_path, pid, [QUEST_A, QUEST_B], 2)
        result1 = svc.check_and_apply_progression(pid)
        result2 = svc.check_and_apply_progression(pid)
        assert result1["type"] == "level_up"
        assert result2["type"] == "no_change"
        assert _get_level(db_path, pid) == 3

    def test_criteria_met_with_more_than_minimum(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B, QUEST_C], 5)
        result = svc.check_and_apply_progression(player["player_id"])
        assert result["type"] == "level_up"

    def test_result_includes_unlocked_regions(
        self, svc: ProgressionService, player: dict, db_path: Path
    ) -> None:
        _set_progress(db_path, player["player_id"], [QUEST_A, QUEST_B], 2)
        result = svc.check_and_apply_progression(player["player_id"])
        assert "unlocked_regions" in result
        assert "playground" in result["unlocked_regions"]
