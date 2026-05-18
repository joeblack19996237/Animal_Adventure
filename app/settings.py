from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_debug: bool = False
    database_path: Path = Path("data/animal_adventure.sqlite3")
    log_app: Path = Path("logs/app.log")
    log_error: Path = Path("logs/error.log")
    log_player_events: Path = Path("logs/player-events.log")
    log_resource: Path = Path("logs/resource.log")
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:8080", "http://127.0.0.1:8080"]
