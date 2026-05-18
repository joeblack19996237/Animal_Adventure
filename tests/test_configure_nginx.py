from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = PROJECT_ROOT / "deploy" / "scripts" / "configure-nginx.ps1"
TEMPLATE_PATH = (
    PROJECT_ROOT / "deploy" / "nginx" / "animal-adventure.nginx.conf.template"
)
REQUIRED_ROUTES = ["/", "/assets/", "/api/", "/health", "/ready", "/ws/"]


def test_configure_nginx_script_exists() -> None:
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"


def test_configure_nginx_generates_project_paths(tmp_path: Path) -> None:
    nginx_dir = tmp_path / "deploy" / "nginx"
    nginx_dir.mkdir(parents=True)
    template_content = TEMPLATE_PATH.read_text(encoding="utf-8")
    (nginx_dir / "animal-adventure.nginx.conf.template").write_text(
        template_content, encoding="utf-8"
    )

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PATH),
            "-ProjectRoot",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Script failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    output_path = nginx_dir / "animal-adventure.nginx.conf"
    assert output_path.exists(), f"Output not found: {output_path}"
    content = output_path.read_text(encoding="utf-8")
    normalized_root = str(tmp_path).replace("\\", "/")

    assert "{{PROJECT_ROOT}}" not in content, "Unresolved placeholder found in output"
    assert normalized_root in content, (
        f"Expected '{normalized_root}' in generated config"
    )
    for route in REQUIRED_ROUTES:
        assert route in content, f"Route '{route}' missing from generated config"
