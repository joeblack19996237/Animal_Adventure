from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.logging_config import (
    APP_LOG_BACKUP_COUNT,
    ERROR_LOG_BACKUP_COUNT,
    PLAYER_EVENTS_LOG_BACKUP_COUNT,
    RESOURCE_LOG_BACKUP_COUNT,
)

LOG_DIR = Path("logs")

_RETENTION_DAYS: dict[str, int] = {
    "app.log": APP_LOG_BACKUP_COUNT,
    "error.log": ERROR_LOG_BACKUP_COUNT,
    "player-events.log": PLAYER_EVENTS_LOG_BACKUP_COUNT,
    "resource.log": RESOURCE_LOG_BACKUP_COUNT,
}

_DATE_SUFFIX_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2})$")


@dataclass
class CleanupReport:
    dry_run: bool
    candidates: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)


def _parse_file_date(name: str) -> datetime | None:
    m = _DATE_SUFFIX_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _base_log_name(name: str) -> str:
    m = _DATE_SUFFIX_RE.search(name)
    return name[: m.start()] if m else name


def _retention_for(name: str) -> int:
    base = _base_log_name(name)
    return _RETENTION_DAYS.get(base, APP_LOG_BACKUP_COUNT)


def run_cleanup(
    log_dir: Path = LOG_DIR,
    dry_run: bool = True,
    now: datetime | None = None,
) -> CleanupReport:
    if now is None:
        now = datetime.now(tz=timezone.utc)

    report = CleanupReport(dry_run=dry_run)

    if not log_dir.exists():
        return report

    for path in sorted(log_dir.iterdir()):
        if path.is_dir():
            continue
        file_date = _parse_file_date(path.name)
        if file_date is None:
            continue
        age_days = (now - file_date).days
        retention = _retention_for(path.name)
        if age_days > retention:
            report.candidates.append(path)
            if not dry_run:
                path.unlink()
                report.deleted.append(path)

    return report
