from __future__ import annotations

from unittest.mock import patch

import check_deps

REQUIRED_TOOL_NAMES = {
    "python",
    "node",
    "npm",
    "nginx",
    "sqlite3",
    "playwright-chromium",
    "playwright-webkit",
}


def test_check_deps_reports_required_tools() -> None:
    results = check_deps.check_all()
    reported_names = {r.name for r in results}
    assert reported_names == REQUIRED_TOOL_NAMES


# --- python ---


def test_python_found_when_on_path() -> None:
    with patch("check_deps.shutil.which", return_value="/usr/bin/python"):
        result = check_deps.check_python()
    assert result.found is True
    assert result.name == "python"
    assert result.detail == "/usr/bin/python"


def test_python_missing_when_not_on_path() -> None:
    with patch("check_deps.shutil.which", return_value=None):
        result = check_deps.check_python()
    assert result.found is False
    assert result.name == "python"
    assert "not found" in result.detail


# --- node ---


def test_node_found_when_on_path() -> None:
    with patch("check_deps.shutil.which", return_value="/usr/bin/node"):
        result = check_deps.check_node()
    assert result.found is True
    assert result.name == "node"
    assert result.detail == "/usr/bin/node"


def test_node_missing_when_not_on_path() -> None:
    with patch("check_deps.shutil.which", return_value=None):
        result = check_deps.check_node()
    assert result.found is False
    assert result.name == "node"


# --- npm ---


def test_npm_found_when_on_path() -> None:
    with patch("check_deps.shutil.which", return_value="/usr/bin/npm"):
        result = check_deps.check_npm()
    assert result.found is True
    assert result.name == "npm"
    assert result.detail == "/usr/bin/npm"


def test_npm_missing_when_not_on_path() -> None:
    with patch("check_deps.shutil.which", return_value=None):
        result = check_deps.check_npm()
    assert result.found is False
    assert result.name == "npm"


# --- nginx ---


def test_nginx_found_when_on_path() -> None:
    with patch("check_deps.shutil.which", return_value="/usr/sbin/nginx"):
        result = check_deps.check_nginx()
    assert result.found is True
    assert result.name == "nginx"
    assert result.detail == "/usr/sbin/nginx"


def test_nginx_missing_when_not_on_path() -> None:
    with patch("check_deps.shutil.which", return_value=None):
        result = check_deps.check_nginx()
    assert result.found is False
    assert result.name == "nginx"


# --- sqlite3 ---


def test_sqlite_found_when_module_available() -> None:
    with patch("check_deps._sqlite_connect"):
        result = check_deps.check_sqlite()
    assert result.found is True
    assert result.name == "sqlite3"
    assert "available" in result.detail


def test_sqlite_missing_when_connect_raises() -> None:
    with patch(
        "check_deps._sqlite_connect", side_effect=Exception("sqlite3 unavailable")
    ):
        result = check_deps.check_sqlite()
    assert result.found is False
    assert result.name == "sqlite3"
    assert "sqlite3 unavailable" in result.detail


# --- playwright-chromium ---


def test_playwright_chromium_found_when_installed() -> None:
    with patch(
        "check_deps._playwright_browser_installed",
        return_value=(True, "/path/to/chromium"),
    ):
        result = check_deps.check_playwright_chromium()
    assert result.found is True
    assert result.name == "playwright-chromium"
    assert result.detail == "/path/to/chromium"


def test_playwright_chromium_missing_when_not_installed() -> None:
    with patch(
        "check_deps._playwright_browser_installed",
        return_value=(False, "not installed at /path/to/chromium"),
    ):
        result = check_deps.check_playwright_chromium()
    assert result.found is False
    assert result.name == "playwright-chromium"
    assert "not installed" in result.detail


# --- playwright-webkit ---


def test_playwright_webkit_found_when_installed() -> None:
    with patch(
        "check_deps._playwright_browser_installed",
        return_value=(True, "/path/to/webkit"),
    ):
        result = check_deps.check_playwright_webkit()
    assert result.found is True
    assert result.name == "playwright-webkit"
    assert result.detail == "/path/to/webkit"


def test_playwright_webkit_missing_when_not_installed() -> None:
    with patch(
        "check_deps._playwright_browser_installed",
        return_value=(False, "not installed at /path/to/webkit"),
    ):
        result = check_deps.check_playwright_webkit()
    assert result.found is False
    assert result.name == "playwright-webkit"
    assert "not installed" in result.detail
