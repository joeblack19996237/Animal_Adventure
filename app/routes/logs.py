from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import connect_db
from app.settings import Settings

router = APIRouter(prefix="/api/v1")

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_MAX_EVENT_PAYLOAD_BYTES = 4096


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class ClientEventRequest(BaseModel):
    event_type: str = Field(min_length=2, max_length=64)
    player_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/logs/client-config")
def get_client_logging_config() -> dict[str, object]:
    return {
        "enabled": True,
        "sample_rate": 1.0,
        "endpoint": "/api/v1/client-events",
    }


@router.post("/client-events")
def post_client_event(
    body: ClientEventRequest, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    if _EVENT_TYPE_RE.fullmatch(body.event_type) is None:
        raise HTTPException(status_code=422, detail="Invalid event_type")

    payload_json = json.dumps(body.payload, separators=(",", ":"), sort_keys=True)
    if len(payload_json.encode("utf-8")) > _MAX_EVENT_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Event payload too large")

    conn = connect_db(settings.database_path)
    try:
        conn.execute(
            "INSERT INTO player_events (player_id, event_type, event_payload_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                body.player_id,
                body.event_type,
                payload_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "accepted"}
