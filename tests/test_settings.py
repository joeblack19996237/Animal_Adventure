import pytest
from pathlib import Path


def test_backend_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "APP_HOST",
        "APP_PORT",
        "APP_DEBUG",
        "DATABASE_PATH",
        "LOG_APP",
        "LOG_ERROR",
        "LOG_PLAYER_EVENTS",
        "LOG_RESOURCE",
        "LOG_LEVEL",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(var, raising=False)

    from app.settings import Settings

    settings = Settings(_env_file=None)

    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.database_path == Path("data/animal_adventure.sqlite3")
    assert settings.log_app == Path("logs/app.log")
    assert settings.log_error == Path("logs/error.log")
    assert settings.log_player_events == Path("logs/player-events.log")
    assert settings.log_resource == Path("logs/resource.log")


def test_backend_settings_app_port_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "9000")

    from app.settings import Settings

    settings = Settings(_env_file=None)

    assert settings.app_port == 9000


def test_backend_settings_database_path_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", "data/custom.sqlite3")

    from app.settings import Settings

    settings = Settings(_env_file=None)

    assert settings.database_path == Path("data/custom.sqlite3")


def test_backend_settings_log_app_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_APP", "logs/custom-app.log")

    from app.settings import Settings

    settings = Settings(_env_file=None)

    assert settings.log_app == Path("logs/custom-app.log")
