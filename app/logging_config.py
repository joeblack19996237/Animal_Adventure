from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

_JSON_DUMPS = json.dumps

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


def emit_lifecycle_log(
    app_logger: logging.Logger,
    event_type: str,
    message: str,
    context: dict | None = None,
) -> dict:
    record = build_log_record(message=message, event_type=event_type, context=context)
    app_logger.info(_JSON_DUMPS(record))
    return record


def emit_startup(app_logger: logging.Logger) -> dict:
    return emit_lifecycle_log(
        app_logger, event_type="startup", message="application startup"
    )


def emit_ready(app_logger: logging.Logger, context: dict | None = None) -> dict:
    return emit_lifecycle_log(
        app_logger, event_type="ready", message="application ready", context=context
    )


def emit_shutdown(app_logger: logging.Logger) -> dict:
    return emit_lifecycle_log(
        app_logger, event_type="shutdown", message="application shutdown"
    )


def emit_functional_log(
    app_logger: logging.Logger,
    event_type: str,
    message: str,
    level: str = "INFO",
    player_id: str | None = None,
    connection_id: str | None = None,
    session_id: str | None = None,
    error_type: str | None = None,
    context: dict | None = None,
) -> dict:
    record = build_log_record(
        message=message,
        level=level,
        event_type=event_type,
        player_id=player_id,
        connection_id=connection_id,
        session_id=session_id,
        error_type=error_type,
        context=context,
    )
    log_method = getattr(app_logger, level.lower(), app_logger.info)
    log_method(_JSON_DUMPS(record))
    return record


def emit_quest_complete(
    app_logger: logging.Logger,
    player_id: str,
    quest_id: str,
    quest_instance_id: int,
    coins_awarded: int = 0,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="quest_complete",
        message=f"Quest completed player={player_id} quest_id={quest_id} instance={quest_instance_id}",
        player_id=player_id,
        context={
            "quest_id": quest_id,
            "quest_instance_id": quest_instance_id,
            "coins_awarded": coins_awarded,
        },
    )


def emit_quest_auto_fail(
    app_logger: logging.Logger,
    player_id: str,
    quest_id: str,
    quest_instance_id: int,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="quest_auto_fail",
        message=(
            f"Expiry scanner failed quest {quest_instance_id} "
            f"player={player_id} quest_id={quest_id}"
        ),
        player_id=player_id,
        context={"quest_id": quest_id, "quest_instance_id": quest_instance_id},
    )


def emit_duplicate_session(
    app_logger: logging.Logger,
    player_id: str,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="duplicate_session",
        message=f"Duplicate session replaced for player={player_id}",
        player_id=player_id,
        context={"player_id": player_id},
    )


def emit_movement_rate_limit(
    app_logger: logging.Logger,
    player_id: str,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="movement_rate_limit",
        message=f"Movement rate limit exceeded for player={player_id}",
        player_id=player_id,
        context={"player_id": player_id},
    )


def emit_bootstrap_failure(
    app_logger: logging.Logger,
    player_id: str | None = None,
    error: str | None = None,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="bootstrap_failure",
        level="ERROR",
        message=f"Bootstrap load failure player={player_id}: {error}",
        player_id=player_id,
        error_type="bootstrap_failure",
        context={"error": error},
    )


def emit_shop_purchase(
    app_logger: logging.Logger,
    player_id: str,
    item_id: str,
    price: int,
    new_balance: int,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="shop_purchase",
        message=f"Shop purchase player={player_id} item={item_id} price={price}",
        player_id=player_id,
        context={"item_id": item_id, "price": price, "new_balance": new_balance},
    )


def emit_reconnect(
    app_logger: logging.Logger,
    player_id: str,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="reconnect",
        message=f"Player reconnected player={player_id}",
        player_id=player_id,
        context={"player_id": player_id},
    )


def emit_reconnect_timeout(
    app_logger: logging.Logger,
    player_id: str,
) -> dict:
    return emit_functional_log(
        app_logger,
        event_type="reconnect_timeout",
        message=f"Reconnect timeout for player={player_id}",
        player_id=player_id,
        context={"player_id": player_id},
    )


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
