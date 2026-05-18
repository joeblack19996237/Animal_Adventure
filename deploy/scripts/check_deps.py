from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DepResult:
    name: str
    found: bool
    detail: str


def check_python() -> DepResult:
    path = shutil.which("python") or shutil.which("python3")
    return DepResult(
        name="python", found=bool(path), detail=path or "not found in PATH"
    )


def check_node() -> DepResult:
    path = shutil.which("node")
    return DepResult(name="node", found=bool(path), detail=path or "not found in PATH")


def check_npm() -> DepResult:
    path = shutil.which("npm")
    return DepResult(name="npm", found=bool(path), detail=path or "not found in PATH")


def check_nginx() -> DepResult:
    path = shutil.which("nginx")
    return DepResult(name="nginx", found=bool(path), detail=path or "not found in PATH")


def _sqlite_connect() -> None:
    import sqlite3

    sqlite3.connect(":memory:").close()


def check_sqlite() -> DepResult:
    try:
        _sqlite_connect()
        return DepResult(name="sqlite3", found=True, detail="built-in module available")
    except Exception as exc:
        return DepResult(name="sqlite3", found=False, detail=str(exc))


def _playwright_browser_installed(browser: str) -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser_type = getattr(pw, browser)
            exe = browser_type.executable_path
            exists = Path(exe).exists()
            return exists, exe if exists else f"not installed at {exe}"
    except ImportError:
        return False, "playwright package not installed"
    except Exception as exc:
        return False, str(exc)


def check_playwright_chromium() -> DepResult:
    found, detail = _playwright_browser_installed("chromium")
    return DepResult(name="playwright-chromium", found=found, detail=detail)


def check_playwright_webkit() -> DepResult:
    found, detail = _playwright_browser_installed("webkit")
    return DepResult(name="playwright-webkit", found=found, detail=detail)


def check_all() -> list[DepResult]:
    return [
        check_python(),
        check_node(),
        check_npm(),
        check_nginx(),
        check_sqlite(),
        check_playwright_chromium(),
        check_playwright_webkit(),
    ]


if __name__ == "__main__":
    results = check_all()
    all_found = True
    for r in results:
        status = "OK" if r.found else "MISSING"
        print(f"[{status:7s}] {r.name}: {r.detail}")
        if not r.found:
            all_found = False
    sys.exit(0 if all_found else 1)
