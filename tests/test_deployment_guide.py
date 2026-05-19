from __future__ import annotations

from pathlib import Path

import pytest

_GUIDE_PATH = Path("docs/local-windows-deployment.md")

_REQUIRED_TERMS = [
    "8080",
    "nginx.exe -t",
    "nginx.exe -s reload",
    "nginx.exe -s stop",
    "Firewall",
    "Risks",
]


@pytest.fixture(scope="module")
def guide_text() -> str:
    return _GUIDE_PATH.read_text(encoding="utf-8")


def test_guide_file_exists() -> None:
    assert _GUIDE_PATH.exists(), f"{_GUIDE_PATH} does not exist"


@pytest.mark.parametrize("term", _REQUIRED_TERMS)
def test_guide_contains_required_term(guide_text: str, term: str) -> None:
    assert term in guide_text, f"Deployment guide missing required term: {term!r}"


def test_guide_contains_port_8080(guide_text: str) -> None:
    assert "8080" in guide_text


def test_guide_contains_nginx_test_command(guide_text: str) -> None:
    assert "nginx.exe -t" in guide_text


def test_guide_contains_nginx_reload_command(guide_text: str) -> None:
    assert "nginx.exe -s reload" in guide_text


def test_guide_contains_nginx_stop_command(guide_text: str) -> None:
    assert "nginx.exe -s stop" in guide_text


def test_guide_contains_firewall_note(guide_text: str) -> None:
    assert "firewall" in guide_text.lower()


def test_guide_contains_risks_section(guide_text: str) -> None:
    assert "Risks" in guide_text or "risks" in guide_text.lower()
