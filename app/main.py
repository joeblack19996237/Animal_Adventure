from pathlib import Path

from fastapi import FastAPI

from app.routes.players import router as players_router
from app.settings import Settings
from app.ws_handler import router as ws_router

app = FastAPI(title="Animal Adventure API")
app.include_router(players_router)
app.include_router(ws_router)

_settings = Settings()

_REQUIRED_CONFIG_FILES = [
    "assets.json",
    "characters.json",
    "map_tiles.json",
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    database_status = _check_database()
    config_status = _check_config()
    websocket_status = "ok"

    all_ok = all(s == "ok" for s in [database_status, config_status, websocket_status])
    overall = "ready" if all_ok else "degraded"

    return {
        "status": overall,
        "database": database_status,
        "config": config_status,
        "websocket": websocket_status,
    }


def _check_database() -> str:
    try:
        db_path = _settings.database_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return "ok"
    except OSError:
        return "error"


def _check_config() -> str:
    config_dir = Path("config")
    try:
        for name in _REQUIRED_CONFIG_FILES:
            if not (config_dir / name).exists():
                return "error"
        return "ok"
    except OSError:
        return "error"
