from __future__ import annotations

import json
import logging

import pytest

from app.logging_config import (
    emit_bootstrap_failure,
    emit_duplicate_session,
    emit_movement_rate_limit,
    emit_quest_auto_fail,
    emit_quest_complete,
    emit_reconnect,
    emit_reconnect_timeout,
    emit_shop_purchase,
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

_FUNCTIONAL_EVENTS = [
    ("quest_complete", lambda log: emit_quest_complete(log, "p1", "q1", 1)),
    ("quest_auto_fail", lambda log: emit_quest_auto_fail(log, "p1", "q1", 1)),
    ("duplicate_session", lambda log: emit_duplicate_session(log, "p1")),
    ("movement_rate_limit", lambda log: emit_movement_rate_limit(log, "p1")),
    ("bootstrap_failure", lambda log: emit_bootstrap_failure(log, "p1")),
    ("shop_purchase", lambda log: emit_shop_purchase(log, "p1", "item1", 50, 150)),
    ("reconnect", lambda log: emit_reconnect(log, "p1")),
    ("reconnect_timeout", lambda log: emit_reconnect_timeout(log, "p1")),
]


@pytest.fixture
def app_logger() -> logging.Logger:
    return logging.getLogger("animal_adventure")


@pytest.mark.parametrize("event_type,emit_fn", _FUNCTIONAL_EVENTS)
def test_functional_log_contains_required_fields(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    for field in REQUIRED_FIELDS:
        assert field in record, f"Missing field '{field}' in {event_type} log"


@pytest.mark.parametrize("event_type,emit_fn", _FUNCTIONAL_EVENTS)
def test_functional_log_event_type_matches(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert record["event_type"] == event_type


@pytest.mark.parametrize("event_type,emit_fn", _FUNCTIONAL_EVENTS)
def test_functional_log_is_json_serializable(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    parsed = json.loads(json.dumps(record))
    assert parsed["event_type"] == event_type


@pytest.mark.parametrize("event_type,emit_fn", _FUNCTIONAL_EVENTS)
def test_functional_log_timestamp_is_non_empty_string(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert isinstance(record["timestamp"], str) and record["timestamp"]


@pytest.mark.parametrize("event_type,emit_fn", _FUNCTIONAL_EVENTS)
def test_functional_log_service_is_non_empty_string(
    app_logger: logging.Logger, event_type: str, emit_fn
) -> None:
    record = emit_fn(app_logger)
    assert isinstance(record["service"], str) and record["service"]


def test_quest_complete_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_quest_complete(
        app_logger, player_id="p42", quest_id="q1", quest_instance_id=7
    )
    assert record["player_id"] == "p42"


def test_quest_complete_log_context_contains_quest_id(
    app_logger: logging.Logger,
) -> None:
    record = emit_quest_complete(
        app_logger, player_id="p1", quest_id="quest_collect", quest_instance_id=3
    )
    assert record["context"]["quest_id"] == "quest_collect"


def test_quest_complete_log_context_contains_coins(app_logger: logging.Logger) -> None:
    record = emit_quest_complete(
        app_logger, player_id="p1", quest_id="q1", quest_instance_id=3, coins_awarded=25
    )
    assert record["context"]["coins_awarded"] == 25


def test_quest_auto_fail_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_quest_auto_fail(
        app_logger, player_id="p99", quest_id="q1", quest_instance_id=2
    )
    assert record["player_id"] == "p99"


def test_quest_auto_fail_log_context_contains_instance_id(
    app_logger: logging.Logger,
) -> None:
    record = emit_quest_auto_fail(
        app_logger, player_id="p1", quest_id="q1", quest_instance_id=5
    )
    assert record["context"]["quest_instance_id"] == 5


def test_duplicate_session_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_duplicate_session(app_logger, player_id="p55")
    assert record["player_id"] == "p55"


def test_movement_rate_limit_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_movement_rate_limit(app_logger, player_id="p7")
    assert record["player_id"] == "p7"


def test_bootstrap_failure_log_level_is_error(app_logger: logging.Logger) -> None:
    record = emit_bootstrap_failure(app_logger, player_id="p1", error="DB read failed")
    assert record["level"] == "ERROR"


def test_bootstrap_failure_log_error_type_is_set(app_logger: logging.Logger) -> None:
    record = emit_bootstrap_failure(app_logger, player_id="p1", error="DB read failed")
    assert record["error_type"] is not None


def test_bootstrap_failure_log_context_contains_error(
    app_logger: logging.Logger,
) -> None:
    record = emit_bootstrap_failure(app_logger, player_id="p1", error="timeout")
    assert record["context"]["error"] == "timeout"


def test_shop_purchase_log_context_contains_item_and_price(
    app_logger: logging.Logger,
) -> None:
    record = emit_shop_purchase(
        app_logger, player_id="p1", item_id="potion", price=10, new_balance=90
    )
    assert record["context"]["item_id"] == "potion"
    assert record["context"]["price"] == 10
    assert record["context"]["new_balance"] == 90


def test_shop_purchase_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_shop_purchase(
        app_logger, player_id="p22", item_id="sword", price=5, new_balance=45
    )
    assert record["player_id"] == "p22"


def test_reconnect_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_reconnect(app_logger, player_id="p3")
    assert record["player_id"] == "p3"


def test_reconnect_timeout_log_sets_player_id(app_logger: logging.Logger) -> None:
    record = emit_reconnect_timeout(app_logger, player_id="p8")
    assert record["player_id"] == "p8"


def test_quest_complete_emitted_to_logger(
    app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="animal_adventure"):
        emit_quest_complete(
            app_logger, player_id="p1", quest_id="q1", quest_instance_id=1
        )
    assert any("quest_complete" in msg for msg in caplog.messages)


def test_quest_auto_fail_emitted_to_logger(
    app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="animal_adventure"):
        emit_quest_auto_fail(
            app_logger, player_id="p1", quest_id="q1", quest_instance_id=1
        )
    assert any("quest_auto_fail" in msg for msg in caplog.messages)


def test_shop_purchase_emitted_to_logger(
    app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="animal_adventure"):
        emit_shop_purchase(
            app_logger, player_id="p1", item_id="potion", price=10, new_balance=90
        )
    assert any("shop_purchase" in msg for msg in caplog.messages)


def test_bootstrap_failure_emitted_to_logger(
    app_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="animal_adventure"):
        emit_bootstrap_failure(app_logger, player_id="p1", error="missing config")
    assert any("bootstrap_failure" in msg for msg in caplog.messages)
