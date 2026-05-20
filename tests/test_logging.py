import json
import logging
import logging.handlers
from pathlib import Path
from collections.abc import Generator

import pytest

from app.logging_config import (
    APP_LOG_BACKUP_COUNT,
    ERROR_LOG_BACKUP_COUNT,
    PLAYER_EVENTS_LOG_BACKUP_COUNT,
    RESOURCE_LOG_BACKUP_COUNT,
    build_log_record,
    configure_logging,
)

REQUIRED_FIELDS = [
    "timestamp",
    "level",
    "service",
    "event_type",
    "request_id",
    "connection_id",
    "player_id",
    "session_id",
    "message",
    "context",
    "duration_ms",
    "error_type",
    "stack_trace",
    "resource_snapshot",
]

NULLABLE_FIELDS = [
    "event_type",
    "request_id",
    "connection_id",
    "player_id",
    "session_id",
    "context",
    "duration_ms",
    "error_type",
    "stack_trace",
    "resource_snapshot",
]


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def handlers(log_dir: Path) -> Generator[list[logging.Handler], None, None]:
    result = configure_logging(log_dir)
    yield result
    logger = logging.getLogger("animal_adventure")
    for h in result:
        logger.removeHandler(h)
        h.close()


# --- build_log_record: required fields ---


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_build_log_record_contains_required_field(field: str) -> None:
    record = build_log_record(message="startup complete")
    assert field in record, f"Missing required field: '{field}'"


@pytest.mark.parametrize("field", NULLABLE_FIELDS)
def test_build_log_record_nullable_field_defaults_to_none(field: str) -> None:
    record = build_log_record(message="startup complete")
    assert record[field] is None, (
        f"Field '{field}' should default to None when not supplied"
    )


def test_build_log_record_sets_message() -> None:
    record = build_log_record(message="database ready")
    assert record["message"] == "database ready"


def test_build_log_record_sets_event_type() -> None:
    record = build_log_record(message="startup", event_type="startup")
    assert record["event_type"] == "startup"


def test_build_log_record_sets_player_id() -> None:
    record = build_log_record(message="move accepted", player_id="player_42")
    assert record["player_id"] == "player_42"


def test_build_log_record_sets_request_id() -> None:
    record = build_log_record(message="rest request", request_id="req-abc")
    assert record["request_id"] == "req-abc"


def test_build_log_record_sets_connection_id() -> None:
    record = build_log_record(message="ws connect", connection_id="conn-001")
    assert record["connection_id"] == "conn-001"


def test_build_log_record_sets_session_id() -> None:
    record = build_log_record(message="session replaced", session_id="sess-999")
    assert record["session_id"] == "sess-999"


def test_build_log_record_sets_duration_ms() -> None:
    record = build_log_record(message="db write", duration_ms=12.5)
    assert record["duration_ms"] == 12.5


def test_build_log_record_sets_error_type() -> None:
    record = build_log_record(message="quest fail", error_type="QuestExpiredError")
    assert record["error_type"] == "QuestExpiredError"


def test_build_log_record_sets_stack_trace() -> None:
    record = build_log_record(message="error", stack_trace="Traceback ...")
    assert record["stack_trace"] == "Traceback ..."


def test_build_log_record_sets_context() -> None:
    ctx = {"quest_id": "quest_hopper_blanket", "coins": 25}
    record = build_log_record(message="quest complete", context=ctx)
    assert record["context"] == ctx


def test_build_log_record_sets_resource_snapshot() -> None:
    snap = {"memory_mb": 128, "db_latency_ms": 5.2}
    record = build_log_record(message="memory warning", resource_snapshot=snap)
    assert record["resource_snapshot"] == snap


def test_build_log_record_timestamp_is_non_empty_string() -> None:
    record = build_log_record(message="ok")
    assert isinstance(record["timestamp"], str)
    assert len(record["timestamp"]) > 0


def test_build_log_record_service_is_non_empty_string() -> None:
    record = build_log_record(message="ok")
    assert isinstance(record["service"], str)
    assert len(record["service"]) > 0


def test_build_log_record_level_is_string() -> None:
    record = build_log_record(message="ok", level="WARNING")
    assert record["level"] == "WARNING"


def test_build_log_record_default_level_is_info() -> None:
    record = build_log_record(message="ok")
    assert record["level"] == "INFO"


def test_build_log_record_is_json_serializable() -> None:
    record = build_log_record(
        message="quest complete",
        event_type="quest_complete",
        player_id="p1",
        duration_ms=42.0,
        context={"quest": "q1"},
    )
    serialized = json.dumps(record)
    parsed = json.loads(serialized)
    for field in REQUIRED_FIELDS:
        assert field in parsed


# --- configure_logging: rotation policy ---


def test_configure_logging_returns_four_handlers(
    handlers: list[logging.Handler],
) -> None:
    rotating = [
        h for h in handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(rotating) == 4


def test_all_four_log_files_are_configured(
    handlers: list[logging.Handler],
) -> None:
    base_names = {
        Path(getattr(h, "baseFilename", "")).name
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    }
    assert "app.log" in base_names
    assert "error.log" in base_names
    assert "player-events.log" in base_names
    assert "resource.log" in base_names


def test_app_log_handler_uses_daily_rotation(
    handlers: list[logging.Handler],
) -> None:
    app_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and "app.log" in str(getattr(h, "baseFilename", ""))
    ]
    assert len(app_handlers) == 1
    assert app_handlers[0].when.lower() in ("midnight", "d")


def test_app_log_handler_retains_14_days(
    handlers: list[logging.Handler],
) -> None:
    app_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and "app.log" in str(getattr(h, "baseFilename", ""))
    ]
    assert len(app_handlers) == 1
    assert APP_LOG_BACKUP_COUNT == 14
    assert app_handlers[0].backupCount == APP_LOG_BACKUP_COUNT


def test_error_log_handler_uses_daily_rotation(
    handlers: list[logging.Handler],
) -> None:
    error_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and "error.log" in str(getattr(h, "baseFilename", ""))
    ]
    assert len(error_handlers) == 1
    assert error_handlers[0].when.lower() in ("midnight", "d")


def test_error_log_handler_retains_30_days(
    handlers: list[logging.Handler],
) -> None:
    error_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and "error.log" in str(getattr(h, "baseFilename", ""))
    ]
    assert len(error_handlers) == 1
    assert ERROR_LOG_BACKUP_COUNT == 30
    assert error_handlers[0].backupCount == ERROR_LOG_BACKUP_COUNT


def test_player_events_log_handler_retains_30_days(
    handlers: list[logging.Handler],
) -> None:
    pe_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and "player-events.log" in str(getattr(h, "baseFilename", ""))
    ]
    assert len(pe_handlers) == 1
    assert PLAYER_EVENTS_LOG_BACKUP_COUNT == 30
    assert pe_handlers[0].backupCount == PLAYER_EVENTS_LOG_BACKUP_COUNT


def test_resource_log_handler_retains_30_days(
    handlers: list[logging.Handler],
) -> None:
    resource_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and "resource.log" in str(getattr(h, "baseFilename", ""))
    ]
    assert len(resource_handlers) == 1
    assert RESOURCE_LOG_BACKUP_COUNT == 30
    assert resource_handlers[0].backupCount == RESOURCE_LOG_BACKUP_COUNT


def test_all_rotating_handlers_use_daily_rotation(
    handlers: list[logging.Handler],
) -> None:
    for h in handlers:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler):
            assert h.when.lower() in (
                "midnight",
                "d",
            ), f"Handler for {getattr(h, 'baseFilename', '?')} does not rotate daily"


def test_log_files_are_created_in_log_dir(
    handlers: list[logging.Handler], log_dir: Path
) -> None:
    for h in handlers:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler):
            base = Path(h.baseFilename)
            assert base.parent.resolve() == log_dir.resolve(), (
                f"Log file {base} is not in log_dir {log_dir}"
            )
