from __future__ import annotations

import subprocess
from pathlib import Path

_IGNORED_DIR_PREFIXES = (
    "workspace/",
    "coverage/",
    "test-results/",
    "playwright-report/",
    "node_modules/",
    ".venv/",
    ".pytest_cache/",
    ".ruff_cache/",
)
_IGNORED_DIR_PARTS = {"__pycache__"}


def capture_snapshot() -> set[str]:
    return set(capture_status_snapshot())


def capture_status_snapshot() -> dict[str, str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    return _parse_porcelain_z(result.stdout)


def changed_files_since_snapshot(pre_snapshot: set[str] | None) -> list[str]:
    if pre_snapshot is None:
        return []
    changed = capture_snapshot() - pre_snapshot
    return sorted(f for f in changed if not _is_ignored_generated_path(f))


def new_untracked_files_since(
    pre_snapshot: dict[str, str] | None, *, ignore_control_plane: bool = False
) -> list[str]:
    if pre_snapshot is None:
        return []
    before = set(pre_snapshot)
    current = capture_status_snapshot()
    return sorted(
        path
        for path, status in current.items()
        if path not in before
        and status == "??"
        and not _is_ignored_generated_path(path)
        and not (ignore_control_plane and _is_control_plane_local_path(path))
        and not _is_user_owned_local_path(path)
    )


def tracked_dirty_files_since(
    pre_snapshot: dict[str, str] | None, *, ignore_control_plane: bool = False
) -> list[str]:
    if pre_snapshot is None:
        return []
    before = set(pre_snapshot)
    current = capture_status_snapshot()
    return sorted(
        path
        for path, status in current.items()
        if path not in before
        and status != "??"
        and not _is_ignored_generated_path(path)
        and not (ignore_control_plane and _is_control_plane_local_path(path))
    )


def _is_ignored_generated_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    if not normalized:
        return True
    if any(
        normalized == p.rstrip("/") or normalized.startswith(p)
        for p in _IGNORED_DIR_PREFIXES
    ):
        return True
    return any(part in _IGNORED_DIR_PARTS for part in normalized.split("/"))


def _is_user_owned_local_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return normalized == ".claude/settings.local.json" or normalized.startswith(
        ".claude/skills/"
    )


def _is_control_plane_local_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return normalized in {".claude", "harness"} or normalized.startswith(
        (".claude/", "harness/")
    )


def _parse_porcelain_z(raw: str) -> dict[str, str]:
    files: dict[str, str] = {}
    parts = [p for p in raw.split("\0") if p]
    i = 0
    while i < len(parts):
        item = parts[i]
        if len(item) < 4:
            i += 1
            continue
        status = item[:2]
        path = item[3:].replace("\\", "/").strip("/")
        if status.startswith("R") or status.startswith("C"):
            i += 1
        if path:
            files[path] = status
        i += 1
    return files


def safe_changed_signal_files(
    pre_snapshot: set[str] | None,
    signal_files: list[str],
    *,
    root: Path | None = None,
    include_preexisting_signal_files: bool = False,
) -> list[str]:
    root = (root or Path(".")).resolve()
    before = pre_snapshot or set()
    after = capture_snapshot()
    changed_after = after - before if pre_snapshot is not None else after
    safe: list[str] = []
    seen: set[str] = set()
    for file_name in signal_files:
        normalized = file_name.replace("\\", "/").strip("/")
        if not normalized or normalized in seen:
            continue
        try:
            resolved = (root / normalized).resolve()
            if not resolved.is_relative_to(root):
                continue
        except ValueError:
            continue
        if (
            normalized in changed_after
            or (pre_snapshot is None and normalized in after)
            or (include_preexisting_signal_files and normalized in after)
        ):
            safe.append(normalized)
            seen.add(normalized)
    return safe


def commit_files(files: list[str], message: str) -> bool:
    if not files:
        return False
    add = subprocess.run(["git", "add"] + files, capture_output=True, text=True)
    if add.returncode != 0:
        return False
    commit = subprocess.run(
        ["git", "commit", "-m", message.strip().replace("\n", " ")],
        capture_output=True,
        text=True,
    )
    return commit.returncode == 0
