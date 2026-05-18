from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db import connect_db

logger = logging.getLogger(__name__)

_SPAWN_X = 2715.0
_SPAWN_Y = 3620.0
_SPAWN_DIRECTION = "front"
_INITIAL_COINS = 25


class PlayerServiceError(Exception):
    pass


class InvalidNameError(PlayerServiceError):
    pass


class InvalidCharacterError(PlayerServiceError):
    pass


class PlayerService:
    def __init__(self, db_path: Path, config_dir: Path) -> None:
        self._db_path = db_path
        self._characters = self._load_characters(config_dir)

    def _load_characters(self, config_dir: Path) -> dict[str, dict]:
        path = config_dir / "characters.json"
        chars: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        return {c["id"]: c for c in chars}

    def _normalize_name(self, name: str) -> str:
        return name.strip().lower()

    def _insert_player_row(
        self,
        conn: sqlite3.Connection,
        player_id: str,
        stripped_name: str,
        normalized_name: str,
        character_id: str,
        now: str,
    ) -> None:
        conn.execute(
            "INSERT INTO players "
            "(id, name, normalized_name, character_id, x, y, direction, level, coins, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                player_id,
                stripped_name,
                normalized_name,
                character_id,
                _SPAWN_X,
                _SPAWN_Y,
                _SPAWN_DIRECTION,
                0,
                _INITIAL_COINS,
                now,
                now,
            ),
        )
        conn.execute("INSERT INTO player_progress (player_id) VALUES (?)", (player_id,))

    def create_player(self, name: str, character_id: str) -> dict:
        if not name or not name.strip():
            raise InvalidNameError("Player name must not be blank")
        if not character_id:
            raise InvalidCharacterError(
                "character_id is required to create a new player"
            )
        char = self._characters.get(character_id)
        if char is None or not char.get("enabled_in_mvp", False):
            raise InvalidCharacterError(
                f"Invalid or disabled character_id: {character_id!r}"
            )

        stripped_name = name.strip()
        normalized_name = stripped_name.lower()
        player_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = connect_db(self._db_path)
        try:
            self._insert_player_row(
                conn, player_id, stripped_name, normalized_name, character_id, now
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Created player player_id=%s name=%r", player_id, stripped_name)
        return {
            "player_id": player_id,
            "name": stripped_name,
            "normalized_name": normalized_name,
            "character_id": character_id,
            "x": _SPAWN_X,
            "y": _SPAWN_Y,
            "direction": _SPAWN_DIRECTION,
            "level": 0,
            "coins": _INITIAL_COINS,
        }

    def load_player(self, name: str) -> dict | None:
        if not name or not name.strip():
            raise InvalidNameError("Player name must not be blank")

        normalized_name = self._normalize_name(name)
        conn = connect_db(self._db_path)
        try:
            row = conn.execute(
                "SELECT id, name, normalized_name, character_id, x, y, direction, level, coins "
                "FROM players WHERE normalized_name = ?",
                (normalized_name,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        logger.debug("Loaded player player_id=%s", row[0])
        return {
            "player_id": row[0],
            "name": row[1],
            "normalized_name": row[2],
            "character_id": row[3],
            "x": row[4],
            "y": row[5],
            "direction": row[6],
            "level": row[7],
            "coins": row[8],
        }

    def get_player_by_id(self, player_id: str) -> dict | None:
        conn = connect_db(self._db_path)
        try:
            row = conn.execute(
                "SELECT id, name, normalized_name, character_id, x, y, direction, level, coins "
                "FROM players WHERE id = ?",
                (player_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        logger.debug("Fetched player by id player_id=%s", row[0])
        return {
            "player_id": row[0],
            "name": row[1],
            "normalized_name": row[2],
            "character_id": row[3],
            "x": row[4],
            "y": row[5],
            "direction": row[6],
            "level": row[7],
            "coins": row[8],
        }
