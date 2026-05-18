from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn = connect_db(path)
    try:
        conn.executescript(schema_sql)
    finally:
        conn.close()


def clean_orphan_quest_locks(path: Path) -> int:
    conn = connect_db(path)
    try:
        cursor = conn.execute(
            "DELETE FROM quest_locks "
            "WHERE quest_instance_id NOT IN (SELECT id FROM player_quests)"
        )
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            logger.warning(
                "Startup recovery deleted %d orphan quest_locks row(s)", deleted_count
            )
        return deleted_count
    finally:
        conn.close()
