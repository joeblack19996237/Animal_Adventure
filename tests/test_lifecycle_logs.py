from __future__ import annotations

import json
import logging

import pytest

from app.logging_config import emit_ready, emit_shutdown, emit_startup

REQUIRED_FIELDS = ["timestamp", "level", "service", "event_type", "message", "context"]

LIFECYCLE_EVENTS = [
    ("startup", emit_startup),
    ("ready", emit_ready),
    ("shutdown", emit_shutdown),
]


@pytest.fixture
def app_logger() -> logging.Logger:
    return logging.getLogger("animal_adventure")


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_contains_required_fields(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    for field in REQUIRED_FIELDS:
        assert field in record, f"Missing field '{field}' in {event_type} log"


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_event_type_matches(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert record["event_type"] == event_type


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_is_json_serializable(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    parsed = json.loads(json.dumps(record))
    for field in REQUIRED_FIELDS:
        assert field in parsed


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_timestamp_is_non_empty_string(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert isinstance(record["timestamp"], str) and record["timestamp"]


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_service_is_non_empty_string(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert isinstance(record["service"], str) and record["service"]


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_level_is_info(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert record["level"] == "INFO"


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_message_is_non_empty_string(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert isinstance(record["message"], str) and record["message"]


@pytest.mark.parametrize("event_type,emit_fn", LIFECYCLE_EVENTS)
def test_lifecycle_log_context_key_exists(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert "context" in record


def test_lifecycle_log_emitted_to_logger(
    app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="animal_adventure"):
        emit_startup(app_logger)
    assert any("startup" in msg for msg in caplog.messages)


def test_ready_log_accepts_context(app_logger: logging.Logger) -> None:
    ctx = {"database": "ok", "config": "ok"}
    record = emit_ready(app_logger, context=ctx)
    assert record["context"] == ctx


def test_shutdown_log_emitted_to_logger(
    app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="animal_adventure"):
        emit_shutdown(app_logger)
    assert any("shutdown" in msg for msg in caplog.messages)
