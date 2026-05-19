from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.cleanup import run_cleanup

_NOW = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


def _write_log(log_dir: Path, name: str) -> Path:
    p = log_dir / name
    p.write_text("log entry\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Dry-run reports old files as candidates
# ---------------------------------------------------------------------------


def test_old_app_log_is_candidate(log_dir: Path) -> None:
    # 15 days old — exceeds 14-day retention
    _write_log(log_dir, "app.log.2024-05-31")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert any("app.log.2024-05-31" in p.name for p in report.candidates)


def test_old_player_events_log_is_candidate(log_dir: Path) -> None:
    # 31 days old — exceeds 30-day retention
    _write_log(log_dir, "player-events.log.2024-05-15")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert any("player-events.log.2024-05-15" in p.name for p in report.candidates)


def test_old_error_log_is_candidate(log_dir: Path) -> None:
    # 31 days old — exceeds 30-day retention
    _write_log(log_dir, "error.log.2024-05-15")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert any("error.log.2024-05-15" in p.name for p in report.candidates)


def test_old_resource_log_is_candidate(log_dir: Path) -> None:
    # 31 days old — exceeds 30-day retention
    _write_log(log_dir, "resource.log.2024-05-15")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert any("resource.log.2024-05-15" in p.name for p in report.candidates)


# ---------------------------------------------------------------------------
# Dry-run preserves recent files (within retention window)
# ---------------------------------------------------------------------------


def test_recent_app_log_not_candidate(log_dir: Path) -> None:
    # 13 days old — within 14-day retention
    _write_log(log_dir, "app.log.2024-06-02")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert not any("app.log.2024-06-02" in p.name for p in report.candidates)


def test_recent_player_events_log_not_candidate(log_dir: Path) -> None:
    # 14 days old — within 30-day retention
    _write_log(log_dir, "player-events.log.2024-06-01")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert not any("player-events.log.2024-06-01" in p.name for p in report.candidates)


# ---------------------------------------------------------------------------
# Dry-run never deletes files
# ---------------------------------------------------------------------------


def test_dry_run_does_not_delete_old_file(log_dir: Path) -> None:
    p = _write_log(log_dir, "app.log.2024-05-01")
    run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert p.exists()


def test_dry_run_deleted_list_is_empty(log_dir: Path) -> None:
    _write_log(log_dir, "app.log.2024-05-01")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert report.deleted == []
    assert report.dry_run is True


# ---------------------------------------------------------------------------
# Retention boundary conditions
# ---------------------------------------------------------------------------


def test_app_log_at_retention_boundary_is_preserved(log_dir: Path) -> None:
    # Exactly 14 days old — at boundary, not past it
    _write_log(log_dir, "app.log.2024-06-01")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert not any("app.log.2024-06-01" in p.name for p in report.candidates)


def test_app_log_one_day_past_retention_is_candidate(log_dir: Path) -> None:
    # 15 days old — one day past 14-day retention
    _write_log(log_dir, "app.log.2024-05-31")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert any("app.log.2024-05-31" in p.name for p in report.candidates)


def test_player_events_log_at_retention_boundary_is_preserved(log_dir: Path) -> None:
    # Exactly 30 days old — at boundary, not past it
    _write_log(log_dir, "player-events.log.2024-05-16")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert not any("player-events.log.2024-05-16" in p.name for p in report.candidates)


def test_player_events_log_one_day_past_retention_is_candidate(log_dir: Path) -> None:
    # 31 days old — one day past 30-day retention
    _write_log(log_dir, "player-events.log.2024-05-15")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert any("player-events.log.2024-05-15" in p.name for p in report.candidates)


# ---------------------------------------------------------------------------
# Mixed ages and edge cases
# ---------------------------------------------------------------------------


def test_only_old_files_are_candidates_in_mixed_log_dir(log_dir: Path) -> None:
    _write_log(log_dir, "app.log.2024-05-01")  # 45 days old
    _write_log(log_dir, "app.log.2024-06-14")  # 1 day old
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    names = {p.name for p in report.candidates}
    assert "app.log.2024-05-01" in names
    assert "app.log.2024-06-14" not in names


def test_empty_log_dir_returns_empty_report(log_dir: Path) -> None:
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert report.candidates == []
    assert report.deleted == []


def test_missing_log_dir_returns_empty_report(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_logs"
    report = run_cleanup(log_dir=missing, dry_run=True, now=_NOW)
    assert report.candidates == []


def test_active_log_file_without_date_suffix_is_ignored(log_dir: Path) -> None:
    _write_log(log_dir, "app.log")  # active log, no date suffix
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert report.candidates == []


def test_cleanup_report_has_dry_run_flag(log_dir: Path) -> None:
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    assert report.dry_run is True


def test_multiple_old_logs_all_reported(log_dir: Path) -> None:
    _write_log(log_dir, "app.log.2024-05-01")
    _write_log(log_dir, "error.log.2024-05-01")
    _write_log(log_dir, "player-events.log.2024-05-01")
    report = run_cleanup(log_dir=log_dir, dry_run=True, now=_NOW)
    names = {p.name for p in report.candidates}
    assert "app.log.2024-05-01" in names
    assert "error.log.2024-05-01" in names
    assert "player-events.log.2024-05-01" in names
