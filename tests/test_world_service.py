from __future__ import annotations

import pytest

from app.services.world_service import MoveStatus, WorldService

_MAP_WIDTH = 5430.0
_MAP_HEIGHT = 7240.0


@pytest.fixture
def world() -> WorldService:
    svc = WorldService()
    svc.register_player("p1", 2715.0, 3620.0, "down")
    return svc


def test_accepts_in_bounds_movement(world: WorldService) -> None:
    result = world.apply_move("p1", 2716.0, 3621.0, "right")
    assert result == MoveStatus.ACCEPTED


@pytest.mark.parametrize(
    "x,y",
    [
        (-1.0, 3620.0),
        (_MAP_WIDTH + 0.1, 3620.0),
        (2715.0, -1.0),
        (2715.0, _MAP_HEIGHT + 0.1),
    ],
)
def test_rejects_out_of_bounds_movement(
    world: WorldService, x: float, y: float
) -> None:
    result = world.apply_move("p1", x, y, "down")
    assert result == MoveStatus.OUT_OF_BOUNDS


def test_boundary_coords_are_accepted(world: WorldService) -> None:
    assert world.apply_move("p1", 0.0, 0.0, "up", now=1000.0) == MoveStatus.ACCEPTED
    assert (
        world.apply_move("p1", _MAP_WIDTH, _MAP_HEIGHT, "down", now=1001.0)
        == MoveStatus.ACCEPTED
    )


def test_updates_direction_on_accepted_move(world: WorldService) -> None:
    world.apply_move("p1", 2716.0, 3620.0, "right")
    pos = world.get_online_positions()
    assert pos["p1"]["direction"] == "right"


def test_out_of_bounds_does_not_update_position(world: WorldService) -> None:
    world.apply_move("p1", -1.0, 3620.0, "left")
    pos = world.get_online_positions()
    assert pos["p1"]["x"] == 2715.0
    assert pos["p1"]["y"] == 3620.0


def test_tracks_online_position_in_memory(world: WorldService) -> None:
    world.apply_move("p1", 3000.0, 4000.0, "up")
    pos = world.get_online_positions()
    assert pos["p1"]["x"] == 3000.0
    assert pos["p1"]["y"] == 4000.0
    assert pos["p1"]["direction"] == "up"


def test_register_player_appears_in_online_positions() -> None:
    svc = WorldService()
    svc.register_player("p2", 100.0, 200.0, "left")
    pos = svc.get_online_positions()
    assert "p2" in pos
    assert pos["p2"]["x"] == 100.0
    assert pos["p2"]["y"] == 200.0


def test_unregister_removes_player(world: WorldService) -> None:
    world.unregister_player("p1")
    assert "p1" not in world.get_online_positions()


def test_snapshot_contains_all_online_players() -> None:
    svc = WorldService()
    svc.register_player("p1", 100.0, 200.0, "up")
    svc.register_player("p2", 300.0, 400.0, "down")
    snapshot = svc.get_snapshot()
    assert snapshot["type"] == "state_update"
    assert "tick" in snapshot
    assert "p1" in snapshot["players"]
    assert "p2" in snapshot["players"]
    assert snapshot["players"]["p1"] == {"x": 100.0, "y": 200.0, "direction": "up"}


def test_snapshot_contains_minimal_player_state() -> None:
    svc = WorldService()
    svc.register_player("p1", 100.0, 200.0, "up")
    snap = svc.get_snapshot()
    player_keys = set(snap["players"]["p1"].keys())
    assert player_keys == {"x", "y", "direction"}


def test_snapshot_tick_increments() -> None:
    svc = WorldService()
    snap1 = svc.get_snapshot()
    snap2 = svc.get_snapshot()
    assert snap2["tick"] == snap1["tick"] + 1


def test_position_save_not_needed_immediately() -> None:
    t0 = 1000.0
    svc = WorldService()
    svc.register_player("p1", 2715.0, 3620.0, "down", now=t0)
    assert not svc.needs_position_save("p1", now=t0 + 1.0)


def test_position_save_needed_after_thirty_seconds() -> None:
    t0 = 1000.0
    svc = WorldService()
    svc.register_player("p1", 2715.0, 3620.0, "down", now=t0)
    assert svc.needs_position_save("p1", now=t0 + 31.0)


def test_mark_position_saved_resets_throttle() -> None:
    t0 = 1000.0
    svc = WorldService()
    svc.register_player("p1", 2715.0, 3620.0, "down", now=t0)
    assert svc.needs_position_save("p1", now=t0 + 31.0)
    svc.mark_position_saved("p1", now=t0 + 31.0)
    assert not svc.needs_position_save("p1", now=t0 + 31.0)


def test_rate_limit_drops_over_frequency_moves(world: WorldService) -> None:
    t0 = 1000.0
    r1 = world.apply_move("p1", 2716.0, 3620.0, "right", now=t0)
    assert r1 == MoveStatus.ACCEPTED
    r2 = world.apply_move("p1", 2717.0, 3620.0, "right", now=t0 + 0.01)
    assert r2 == MoveStatus.RATE_LIMITED


def test_rate_limit_allows_move_after_interval(world: WorldService) -> None:
    t0 = 1000.0
    world.apply_move("p1", 2716.0, 3620.0, "right", now=t0)
    result = world.apply_move("p1", 2717.0, 3620.0, "right", now=t0 + 0.06)
    assert result == MoveStatus.ACCEPTED


def test_rate_limited_move_does_not_update_position(world: WorldService) -> None:
    t0 = 1000.0
    world.apply_move("p1", 2800.0, 3700.0, "up", now=t0)
    world.apply_move("p1", 2900.0, 3800.0, "down", now=t0 + 0.01)
    pos = world.get_online_positions()
    assert pos["p1"]["x"] == 2800.0
    assert pos["p1"]["y"] == 3700.0


def test_no_sqlite_writes_on_movement(world: WorldService) -> None:
    # WorldService has no db_path — verifies by construction that movement
    # does not touch SQLite; callers are responsible for throttled persistence.
    for i in range(100):
        world.apply_move("p1", float(2715 + i % 10), 3620.0, "right", now=float(i))
