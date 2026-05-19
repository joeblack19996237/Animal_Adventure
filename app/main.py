import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.logging_config import emit_ready, emit_shutdown, emit_startup
from app.routes.players import router as players_router
from app.services.quest_expiry_worker import SCAN_INTERVAL_SECONDS, QuestExpiryWorker
from app.settings import Settings
from app.ws_handler import router as ws_router

logger = logging.getLogger(__name__)

_settings = Settings()

_REQUIRED_CONFIG_FILES = [
    "assets.json",
    "characters.json",
    "map_tiles.json",
]


async def _expiry_scan_loop(worker: QuestExpiryWorker) -> None:
    while True:
        try:
            failed = worker.scan_expired_quests()
            if failed:
                logger.info("Expiry scan failed %d quests", len(failed))
        except Exception:
            logger.exception("Expiry scan error")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    emit_startup(logger)
    worker = QuestExpiryWorker(
        db_path=_settings.database_path,
        config_dir=Path("config"),
    )
    try:
        worker.scan_expired_quests()
    except Exception:
        logger.exception("Startup expiry scan error")
    emit_ready(logger)
    task = asyncio.create_task(_expiry_scan_loop(worker))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    emit_shutdown(logger)


app = FastAPI(title="Animal Adventure API", lifespan=_lifespan)
app.include_router(players_router)
app.include_router(ws_router)


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
