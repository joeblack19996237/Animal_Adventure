from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

APP_LOG_BACKUP_COUNT = 14
ERROR_LOG_BACKUP_COUNT = 30
PLAYER_EVENTS_LOG_BACKUP_COUNT = 30
RESOURCE_LOG_BACKUP_COUNT = 30

SERVICE_NAME = "animal_adventure"

_LOG_FILES: list[tuple[str, int]] = [
    ("app.log", APP_LOG_BACKUP_COUNT),
    ("error.log", ERROR_LOG_BACKUP_COUNT),
    ("player-events.log", PLAYER_EVENTS_LOG_BACKUP_COUNT),
    ("resource.log", RESOURCE_LOG_BACKUP_COUNT),
]


def build_log_record(
    *,
    message: str,
    level: str = "INFO",
    event_type: str | None = None,
    request_id: str | None = None,
    connection_id: str | None = None,
    player_id: str | None = None,
    session_id: str | None = None,
    duration_ms: float | None = None,
    error_type: str | None = None,
    stack_trace: str | None = None,
    context: dict | None = None,
    resource_snapshot: dict | None = None,
) -> dict:
    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "level": level,
        "service": SERVICE_NAME,
        "event_type": event_type,
        "request_id": request_id,
        "connection_id": connection_id,
        "player_id": player_id,
        "session_id": session_id,
        "message": message,
        "context": context,
        "duration_ms": duration_ms,
        "error_type": error_type,
        "stack_trace": stack_trace,
        "resource_snapshot": resource_snapshot,
    }


def configure_logging(log_dir: Path) -> list[logging.Handler]:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(SERVICE_NAME)
    logger.setLevel(logging.DEBUG)

    handlers: list[logging.Handler] = []
    for filename, backup_count in _LOG_FILES:
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_dir / filename,
            when="midnight",
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        handlers.append(handler)

    return handlers
