from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).parent.parent
    / "deploy"
    / "nginx"
    / "animal-adventure.nginx.conf.template"
)
GENERATED_PATH = (
    Path(__file__).parent.parent / "deploy" / "nginx" / "animal-adventure.nginx.conf"
)

REQUIRED_ROUTES = [
    "/",
    "/assets/",
    "/assets/images/",
    "/assets/music/",
    "/api/",
    "/health",
    "/ready",
    "/ws/",
]


def test_nginx_template_exists() -> None:
    assert TEMPLATE_PATH.exists(), f"Template not found: {TEMPLATE_PATH}"


def test_nginx_config_contains_required_routes() -> None:
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    for route in REQUIRED_ROUTES:
        assert route in content, f"Route '{route}' missing from Nginx config template"


def test_nginx_template_uses_project_root_placeholder() -> None:
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{{PROJECT_ROOT}}" in content, (
        "Template must use {{PROJECT_ROOT}} placeholder"
    )


def test_nginx_template_listens_on_port_8080() -> None:
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "listen 8080" in content, "Nginx config must listen on port 8080 by default"


def test_nginx_template_splits_built_and_game_assets() -> None:
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "alias {{PROJECT_ROOT}}/dist/assets/;" in content, (
        "Vite-built JS/CSS assets under /assets/ must be served from dist/assets"
    )
    assert "alias {{PROJECT_ROOT}}/assets/images/;" in content, (
        "Game images under /assets/images/ must be served from source assets/images"
    )
    assert "alias {{PROJECT_ROOT}}/assets/music/;" in content, (
        "Game music under /assets/music/ must be served from source assets/music"
    )


def test_nginx_generated_config_exists() -> None:
    assert GENERATED_PATH.exists(), (
        f"Generated config not found: {GENERATED_PATH}. "
        "Run deploy/scripts/configure-nginx.ps1 to generate it."
    )


def test_nginx_generated_config_has_no_unresolved_placeholders() -> None:
    assert GENERATED_PATH.exists(), f"Generated config not found: {GENERATED_PATH}"
    content = GENERATED_PATH.read_text(encoding="utf-8")
    assert "{{PROJECT_ROOT}}" not in content, (
        "Generated config must not contain unresolved {{PROJECT_ROOT}} placeholders"
    )


def test_nginx_generated_config_contains_required_routes() -> None:
    assert GENERATED_PATH.exists(), f"Generated config not found: {GENERATED_PATH}"
    content = GENERATED_PATH.read_text(encoding="utf-8")
    for route in REQUIRED_ROUTES:
        assert route in content, f"Route '{route}' missing from generated Nginx config"


def test_nginx_generated_config_splits_built_and_game_assets() -> None:
    assert GENERATED_PATH.exists(), f"Generated config not found: {GENERATED_PATH}"
    content = GENERATED_PATH.read_text(encoding="utf-8")
    assert "/dist/assets/;" in content, (
        "Generated config must serve Vite-built JS/CSS assets from dist/assets"
    )
    assert "/assets/images/;" in content, (
        "Generated config must serve game images from source assets/images"
    )
    assert "/assets/music/;" in content, (
        "Generated config must serve game music from source assets/music"
    )
