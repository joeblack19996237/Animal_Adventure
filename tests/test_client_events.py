from __future__ import annotations

import json

import pytest

from app.ws_handler import MAX_CLIENT_EVENT_BYTES, validate_client_event

_VALID_PAYLOADS = [
    '{"type": "player_move", "player_id": "p1", "x": 100, "y": 200, "direction": "right", "client_tick": 5}',
    '{"type": "quest_accept", "player_id": "p1", "quest_id": "quest_hopper_blanket"}',
    '{"type": "ping", "client_time": 1710000000000}',
    '{"type": "shop_buy", "player_id": "p1", "item_id": "potion_l0"}',
    '{"type": "player_join", "player_id": "p1"}',
    '{"type": "use_item", "player_id": "p1", "item_id": "potion_l0"}',
    "{}",
]

_MALFORMED_PAYLOADS = [
    ("not json at all", "invalid_message"),
    ("{not valid json}", "invalid_message"),
    ('"just a string"', "invalid_message"),
    ("[1, 2, 3]", "invalid_message"),
    ("null", "invalid_message"),
    ("", "invalid_message"),
    ("42", "invalid_message"),
]


@pytest.mark.parametrize("raw", _VALID_PAYLOADS)
def test_valid_bounded_event_accepted(raw: str) -> None:
    msg, error_code = validate_client_event(raw)
    assert error_code is None
    assert isinstance(msg, dict)


@pytest.mark.parametrize("raw,expected_error", _MALFORMED_PAYLOADS)
def test_malformed_event_returns_invalid_message(raw: str, expected_error: str) -> None:
    msg, error_code = validate_client_event(raw)
    assert error_code == expected_error
    assert msg is None


def test_oversized_payload_rejected() -> None:
    oversized = json.dumps(
        {"type": "player_move", "data": "x" * (MAX_CLIENT_EVENT_BYTES + 1)}
    )
    assert len(oversized.encode("utf-8")) > MAX_CLIENT_EVENT_BYTES
    msg, error_code = validate_client_event(oversized)
    assert error_code == "payload_too_large"
    assert msg is None


def test_payload_at_exact_limit_accepted() -> None:
    prefix = '{"type":"ping","pad":"'
    suffix = '"}'
    pad_len = (
        MAX_CLIENT_EVENT_BYTES
        - len(prefix.encode("utf-8"))
        - len(suffix.encode("utf-8"))
    )
    raw = prefix + "a" * pad_len + suffix
    assert len(raw.encode("utf-8")) == MAX_CLIENT_EVENT_BYTES
    msg, error_code = validate_client_event(raw)
    assert error_code is None
    assert isinstance(msg, dict)


def test_payload_one_byte_over_limit_rejected() -> None:
    prefix = '{"type":"ping","pad":"'
    suffix = '"}'
    pad_len = (
        MAX_CLIENT_EVENT_BYTES
        - len(prefix.encode("utf-8"))
        - len(suffix.encode("utf-8"))
        + 1
    )
    raw = prefix + "a" * pad_len + suffix
    assert len(raw.encode("utf-8")) == MAX_CLIENT_EVENT_BYTES + 1
    msg, error_code = validate_client_event(raw)
    assert error_code == "payload_too_large"
    assert msg is None


def test_player_move_fields_parsed_correctly() -> None:
    raw = (
        '{"type": "player_move", "player_id": "p1", '
        '"x": 2715, "y": 3620, "direction": "down", "client_tick": 12}'
    )
    msg, error_code = validate_client_event(raw)
    assert error_code is None
    assert msg is not None
    assert msg["type"] == "player_move"
    assert msg["x"] == 2715
    assert msg["direction"] == "down"
    assert msg["client_tick"] == 12


def test_non_dict_json_array_rejected() -> None:
    msg, error_code = validate_client_event("[1, 2, 3]")
    assert error_code == "invalid_message"
    assert msg is None


def test_returns_tuple_of_none_and_code_on_error() -> None:
    msg, error_code = validate_client_event("bad input")
    assert msg is None
    assert isinstance(error_code, str)


def test_returns_tuple_of_dict_and_none_on_success() -> None:
    msg, error_code = validate_client_event('{"type": "ping"}')
    assert isinstance(msg, dict)
    assert error_code is None


def test_max_client_event_bytes_is_positive_integer() -> None:
    assert isinstance(MAX_CLIENT_EVENT_BYTES, int)
    assert MAX_CLIENT_EVENT_BYTES > 0
