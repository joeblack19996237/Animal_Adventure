from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENTS_PATH = Path("workspace/events.jsonl")
ROTATED_EVENTS_PATH = Path("workspace/events.jsonl.1")
MAX_EVENTS_BYTES = 10 * 1024 * 1024
HARNESS_LOG_PATH = Path("workspace/harness.log")
_LAST_TRANSITION_KEY: tuple | None = None
_LAST_TRANSITION_COUNT = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_event(event_type: str, **fields: Any) -> dict:
    global _LAST_TRANSITION_COUNT, _LAST_TRANSITION_KEY
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _now(), "event": event_type, **fields}
    if event_type == "state_transition":
        key = (fields.get("state"), fields.get("phase_id"))
        if key == _LAST_TRANSITION_KEY:
            _LAST_TRANSITION_COUNT += 1
            if _LAST_TRANSITION_COUNT % 100 != 0:
                return {**entry, "suppressed": True}
            entry["repeat_count"] = _LAST_TRANSITION_COUNT
        else:
            _LAST_TRANSITION_KEY = key
            _LAST_TRANSITION_COUNT = 1
    else:
        _LAST_TRANSITION_KEY = None
        _LAST_TRANSITION_COUNT = 0
    _rotate_events_if_needed()
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def _rotate_events_if_needed() -> None:
    if not EVENTS_PATH.exists():
        return
    try:
        if EVENTS_PATH.stat().st_size <= MAX_EVENTS_BYTES:
            return
    except OSError:
        return
    ROTATED_EVENTS_PATH.unlink(missing_ok=True)
    EVENTS_PATH.replace(ROTATED_EVENTS_PATH)


def log_line(message: str) -> None:
    HARNESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HARNESS_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{_now()} {message}\n")
