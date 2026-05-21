from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.config_service import ConfigService, ConfigValidationError

router = APIRouter(prefix="/api/v1")


@router.get("/config/bootstrap")
def get_bootstrap_config() -> dict[str, Any]:
    try:
        return ConfigService(Path("config")).get_bootstrap()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
