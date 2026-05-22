from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COLLISION_CONFIG_PATH = ROOT / "config" / "collision_zones.json"
NPC_CONFIG_PATH = ROOT / "config" / "npcs.json"
NPC_BLOCKER_RADIUS = 42.0


@lru_cache(maxsize=1)
def _collision_config() -> dict[str, Any]:
    return json.loads(COLLISION_CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _npc_blockers() -> list[dict[str, float]]:
    npcs = json.loads(NPC_CONFIG_PATH.read_text(encoding="utf-8"))
    return [
        {"x": float(npc["x"]), "y": float(npc["y"]), "radius": NPC_BLOCKER_RADIUS}
        for npc in npcs
    ]


def is_world_collision_blocked(x: float, y: float, player_radius: float = 0.0) -> bool:
    config = _collision_config()
    bounds = config["bounds"]
    if _outside_bounds(x, y, player_radius, bounds):
        return True
    if any(
        _circle_intersects_rect(x, y, player_radius, bridge)
        for bridge in config.get("bridges", [])
    ):
        return False
    if any(_circle_intersects_rect(x, y, player_radius, rect) for rect in config["rects"]):
        return True
    if any(_circle_intersects_circle(x, y, player_radius, circle) for circle in config["circles"]):
        return True
    if any(_circle_intersects_polygon(x, y, player_radius, poly) for poly in config["polygons"]):
        return True
    return any(_circle_intersects_circle(x, y, player_radius, npc) for npc in _npc_blockers())


def _outside_bounds(x: float, y: float, radius: float, bounds: dict[str, float]) -> bool:
    return (
        x - radius < float(bounds["x"])
        or y - radius < float(bounds["y"])
        or x + radius > float(bounds["x"]) + float(bounds["width"])
        or y + radius > float(bounds["y"]) + float(bounds["height"])
    )


def _circle_intersects_rect(
    x: float, y: float, radius: float, rect: dict[str, float]
) -> bool:
    nearest_x = _clamp(x, float(rect["x"]), float(rect["x"]) + float(rect["width"]))
    nearest_y = _clamp(y, float(rect["y"]), float(rect["y"]) + float(rect["height"]))
    return _distance_squared(x, y, nearest_x, nearest_y) <= radius * radius


def _circle_intersects_circle(
    x: float, y: float, radius: float, circle: dict[str, float]
) -> bool:
    combined_radius = radius + float(circle["radius"])
    return _distance_squared(x, y, float(circle["x"]), float(circle["y"])) <= (
        combined_radius * combined_radius
    )


def _circle_intersects_polygon(
    x: float, y: float, radius: float, polygon: dict[str, Any]
) -> bool:
    points = [(float(px), float(py)) for px, py in polygon["points"]]
    if _point_in_polygon(x, y, points):
        return True
    return any(
        _distance_to_segment_squared(x, y, x1, y1, x2, y2) <= radius * radius
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )


def _point_in_polygon(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(points) - 1
    for i, (xi, yi) in enumerate(points):
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < ((xj - xi) * (y - yi)) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _distance_to_segment_squared(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return _distance_squared(px, py, x1, y1)
    t = _clamp(((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy), 0, 1)
    return _distance_squared(px, py, x1 + t * dx, y1 + t * dy)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _distance_squared(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    return dx * dx + dy * dy
