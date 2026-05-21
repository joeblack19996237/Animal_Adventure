from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.player_service import (
    InvalidCharacterError,
    InvalidNameError,
    PlayerService,
)
from app.settings import Settings

router = APIRouter(prefix="/api/v1")


@lru_cache(maxsize=1)
def _cached_player_service() -> PlayerService:
    settings = Settings()
    return PlayerService(db_path=settings.database_path, config_dir=Path("config"))


def get_player_service() -> PlayerService:
    return _cached_player_service()


class PlayerRequest(BaseModel):
    name: str
    character_id: str | None = None


@router.post("/players", response_model=None)
def post_players(
    body: PlayerRequest, service: PlayerService = Depends(get_player_service)
) -> Any:
    try:
        existing = service.load_player(body.name)
    except InvalidNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if existing is not None:
        return existing

    if body.character_id is None:
        return JSONResponse(
            status_code=409,
            content={
                "code": "character_required",
                "message": "character_id is required to create a new player",
            },
        )

    try:
        return service.create_player(body.name, body.character_id)
    except InvalidCharacterError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "invalid_character_id", "message": str(exc)},
        )
    except InvalidNameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/players/{player_id}")
def get_player(
    player_id: str, service: PlayerService = Depends(get_player_service)
) -> dict[str, Any]:
    player = service.get_player_by_id(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player
