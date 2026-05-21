from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_PRODUCTION_FILE_LINES = 500
PRODUCTION_DIRS = ("app", "src")
PRODUCTION_SUFFIXES = {".py", ".ts", ".tsx"}


def _iter_files(root: Path, directories: tuple[str, ...], suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    for directory in directories:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                files.append(path)
    return sorted(files)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _collect_large_files(root: Path) -> list[dict]:
    issues = []
    for path in _iter_files(root, PRODUCTION_DIRS, PRODUCTION_SUFFIXES):
        lines = _line_count(path)
        if lines > MAX_PRODUCTION_FILE_LINES:
            issues.append(
                {
                    "severity": "HIGH",
                    "type": "large_production_file",
                    "file": str(path.relative_to(root)),
                    "message": (
                        f"Production file has {lines} lines, above "
                        f"{MAX_PRODUCTION_FILE_LINES}."
                    ),
                }
            )
    return issues


def _extract_types_from_object_send(text: str, call_name: str) -> set[str]:
    pattern = re.compile(
        rf"\b{re.escape(call_name)}\s*\(\s*\{{(?P<body>.*?)\}}\s*\)",
        flags=re.DOTALL,
    )
    types: set[str] = set()
    for match in pattern.finditer(text):
        type_match = re.search(r"\btype\s*:\s*['\"]([a-z_]+)['\"]", match.group("body"))
        if type_match:
            types.add(type_match.group(1))
    return types


def _collect_client_ws_types(root: Path) -> set[str]:
    client_types: set[str] = set()
    src = root / "src"
    if not src.exists():
        return client_types
    for path in src.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        client_types.update(_extract_types_from_object_send(text, "this.wsClient.send"))
        client_types.update(_extract_types_from_object_send(text, "this.wsClient.sendMove"))
        client_types.update(_extract_types_from_object_send(text, "this.onSend"))
    return client_types


def _collect_server_ws_types(root: Path) -> set[str]:
    server_types: set[str] = set()
    app = root / "app"
    if not app.exists():
        return server_types
    patterns = [
        re.compile(r"\bmsg_type\s*==\s*['\"]([a-z_]+)['\"]"),
        re.compile(r"\bmsg\.get\(['\"]type['\"]\)\s*==\s*['\"]([a-z_]+)['\"]"),
    ]
    for path in app.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            server_types.update(pattern.findall(text))
    return server_types


def _collect_ws_dispatch_issues(root: Path) -> list[dict]:
    client_types = _collect_client_ws_types(root)
    server_types = _collect_server_ws_types(root)
    missing = sorted(client_types - server_types)
    return [
        {
            "severity": "HIGH",
            "type": "missing_ws_dispatch",
            "file": "app/ws_handler.py",
            "message": (
                f"Client sends WebSocket message `{msg_type}`, but no server "
                "dispatch branch was found."
            ),
        }
        for msg_type in missing
    ]


def run_quality_gates(root: Path = Path(".")) -> dict:
    root = root.resolve()
    issues = []
    issues.extend(_collect_large_files(root))
    issues.extend(_collect_ws_dispatch_issues(root))
    return {"pass": not issues, "issues": issues}


def main() -> int:
    result = run_quality_gates(Path("."))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
