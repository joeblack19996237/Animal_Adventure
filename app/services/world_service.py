from __future__ import annotations

import time
from enum import Enum

from app.services.collision import is_world_collision_blocked

MAP_WIDTH = 5430.0
MAP_HEIGHT = 7240.0
POSITION_SAVE_INTERVAL_SECONDS = 30.0
MIN_MOVE_INTERVAL_SECONDS = 1.0 / 20.0  # 20Hz client max


def is_in_world_bounds(x: float, y: float) -> bool:
    return 0.0 <= x <= MAP_WIDTH and 0.0 <= y <= MAP_HEIGHT


class MoveStatus(str, Enum):
    ACCEPTED = "accepted"
    OUT_OF_BOUNDS = "out_of_bounds"
    RATE_LIMITED = "rate_limited"
    COLLISION_BLOCKED = "collision_blocked"


class WorldService:
    def __init__(self) -> None:
        self._positions: dict[str, dict[str, float | str]] = {}
        self._last_move_time: dict[str, float] = {}
        self._last_save_time: dict[str, float] = {}
        self._tick: int = 0

    def register_player(
        self,
        player_id: str,
        x: float,
        y: float,
        direction: str,
        now: float | None = None,
    ) -> None:
        if now is None:
            now = time.monotonic()
        self._positions[player_id] = {"x": x, "y": y, "direction": direction}
        self._last_save_time[player_id] = now
        self._last_move_time[player_id] = 0.0

    def unregister_player(self, player_id: str) -> None:
        self._positions.pop(player_id, None)
        self._last_move_time.pop(player_id, None)
        self._last_save_time.pop(player_id, None)

    def apply_move(
        self,
        player_id: str,
        x: float,
        y: float,
        direction: str,
        now: float | None = None,
    ) -> MoveStatus:
        if now is None:
            now = time.monotonic()

        last_move = self._last_move_time.get(player_id, 0.0)
        if now - last_move < MIN_MOVE_INTERVAL_SECONDS:
            return MoveStatus.RATE_LIMITED

        if not is_in_world_bounds(x, y):
            return MoveStatus.OUT_OF_BOUNDS

        if is_world_collision_blocked(x, y):
            return MoveStatus.COLLISION_BLOCKED

        self._positions[player_id] = {"x": x, "y": y, "direction": direction}
        self._last_move_time[player_id] = now
        return MoveStatus.ACCEPTED

    def get_snapshot(self) -> dict:
        self._tick += 1
        return {
            "type": "state_update",
            "tick": self._tick,
            "players": {
                pid: {"x": pos["x"], "y": pos["y"], "direction": pos["direction"]}
                for pid, pos in self._positions.items()
            },
        }

    def get_online_positions(self) -> dict[str, dict]:
        return dict(self._positions)

    def needs_position_save(self, player_id: str, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        last_save = self._last_save_time.get(player_id, 0.0)
        return now - last_save >= POSITION_SAVE_INTERVAL_SECONDS

    def mark_position_saved(self, player_id: str, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        self._last_save_time[player_id] = now
