"""
Unit tests for check_spec_completeness() — Layer 1 (heading keyword search)
and Layer 2 (Phase 1 title structural check).
"""

from pathlib import Path


from spec import check_spec_completeness

CONFIG_PATH = Path(__file__).parent.parent.parent / "spec_validation.json"

# Minimal headings that satisfy all common requirements for CLI apps
_COMMON_HEADINGS = """\
## Architecture
## Workflow
## Requirements
## Verification Plan
## Test Plan
## Phase 1: Project Foundation
"""

# All headings needed for a passing web app spec
_WEB_HEADINGS = """\
## Architecture
## Workflow
## Requirements
## Verification Plan
## Test Plan
## API
## Database
## Data Model
## Frontend
## Log Design
## Phase 1: Project Foundation
"""

_GAME_HEADINGS = """\
## Architecture
## Workflow
## Requirements
## Verification Plan
## Test Plan
## Build Plan
## Phaser Client
## Asset Manifest
## Map And Characters
## Input And Responsive Controls
## WebSocket Multiplayer Reconnect
## Persistence And Backend Restart
## Quests Inventory Shop Progression L3
## E2E Browser Acceptance
## Logs Deployment Nginx
## Phase 1: Project Foundation
"""


def _write_spec(tmp_path: Path, content: str) -> str:
    spec = tmp_path / "spec.md"
    spec.write_text(content, encoding="utf-8")
    return str(spec)


# ---------------------------------------------------------------------------
# Layer 1: keyword in headings
# ---------------------------------------------------------------------------


def test_heading_match_passes(tmp_path):
    spec = _write_spec(tmp_path, "## System Architecture\n## Phase 1: Bootstrap\n")
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert "architecture" not in result


def test_body_text_only_does_not_pass(tmp_path):
    spec = _write_spec(
        tmp_path,
        "The architecture of this system is layered.\n## Phase 1: Bootstrap\n",
    )
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert "architecture" in result


def test_bold_text_does_not_pass(tmp_path):
    spec = _write_spec(
        tmp_path,
        "**Requirements:** must support 100 users.\n## Phase 1: Bootstrap\n",
    )
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert "requirements" in result


def test_required_section_missing(tmp_path):
    # Spec has all common sections except workflow
    spec = _write_spec(
        tmp_path,
        "## Architecture\n## Requirements\n## Verification Plan\n## Phase 1: Bootstrap\n",
    )
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert "workflow" in result


def test_all_common_sections_present_passes(tmp_path):
    spec = _write_spec(tmp_path, _COMMON_HEADINGS)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert result == []


def test_web_app_missing_log_design(tmp_path):
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## API\n## Database\n## Data Model\n## Frontend\n## Phase 1: Project Foundation\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "web", CONFIG_PATH)
    assert "log design" in result


def test_web_app_all_sections_present(tmp_path):
    spec = _write_spec(tmp_path, _WEB_HEADINGS)
    result = check_spec_completeness(spec, "web", CONFIG_PATH)
    assert result == []


def test_game_app_all_sections_present(tmp_path):
    spec = _write_spec(tmp_path, _GAME_HEADINGS)
    result = check_spec_completeness(spec, "game", CONFIG_PATH)
    assert result == []


def test_game_app_missing_websocket_reconnect(tmp_path):
    spec = _write_spec(
        tmp_path,
        _GAME_HEADINGS.replace("## WebSocket Multiplayer Reconnect\n", ""),
    )
    result = check_spec_completeness(spec, "game", CONFIG_PATH)
    assert "WebSocket multiplayer / reconnect" in result


def test_game_app_missing_asset_manifest(tmp_path):
    spec = _write_spec(tmp_path, _GAME_HEADINGS.replace("## Asset Manifest\n", ""))
    result = check_spec_completeness(spec, "game", CONFIG_PATH)
    assert "asset manifest" in result


def test_phase_title_heading_counts_as_section(tmp_path):
    # "api" keyword in a phase title heading counts for Layer 1
    content = _COMMON_HEADINGS + "## Phase 2: REST Lobby API [python]\n"
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert "api / service" not in result


def test_cli_data_model_not_triggered_without_data_heading(tmp_path):
    # CLI spec with no database/schema/model heading — conditional not triggered
    spec = _write_spec(tmp_path, _COMMON_HEADINGS)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert "data model" not in result


def test_cli_data_model_warns_when_data_heading_present(tmp_path, capsys):
    # CLI spec has a database-related heading (triggers condition) but no data model heading
    content = _COMMON_HEADINGS + "## Postgres Database\n"
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    assert "data model" not in result  # conditional → warn only, not in error list


def test_spec_directory_reads_all_md_files(tmp_path):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "a.md").write_text(
        "## Architecture\n## Workflow\n## Test Plan\n## Phase 1: Project Foundation\n",
        encoding="utf-8",
    )
    (spec_dir / "b.md").write_text(
        "## Requirements\n## Verification Plan\n", encoding="utf-8"
    )
    result = check_spec_completeness(str(spec_dir), "cli", CONFIG_PATH)
    assert result == []


def test_unknown_app_type_returns_only_common_requirements(tmp_path):
    # Unknown app_type → no KeyError, only common section failures checked
    spec = _write_spec(tmp_path, "## Phase 1: Bootstrap\n")
    result = check_spec_completeness(spec, "unknown_type", CONFIG_PATH)
    labels = [r for r in result if not r.startswith("Phase 1")]
    assert "architecture" in labels
    assert "api / service" not in labels  # web-only section not checked


# ---------------------------------------------------------------------------
# Layer 2: Phase 1 title structural check
# ---------------------------------------------------------------------------


def test_phase1_project_foundation_passes(tmp_path):
    spec = _write_spec(tmp_path, _COMMON_HEADINGS)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert phase1_errors == []


def test_phase1_bootstrap_passes(tmp_path):
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: Bootstrap\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert phase1_errors == []


def test_phase1_project_setup_passes(tmp_path):
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: Project Setup\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert phase1_errors == []


def test_phase1_game_foundation_passes(tmp_path):
    # "game" is NOT a domain disqualifier
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: Game Foundation\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert phase1_errors == []


def test_phase1_database_foundation_fails(tmp_path):
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: Database Foundation\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert len(phase1_errors) == 1


def test_phase1_frontend_scaffold_fails(tmp_path):
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: Frontend Scaffold\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert len(phase1_errors) == 1


def test_phase1_game_logic_fails(tmp_path):
    # No setup keyword at all
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: Game Logic\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert len(phase1_errors) == 1


def test_phase1_title_check_case_insensitive(tmp_path):
    content = (
        "## Architecture\n## Workflow\n## Requirements\n## Verification Plan\n"
        "## Phase 1: PROJECT INITIALIZATION\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert phase1_errors == []


def test_no_phases_in_spec_skips_phase1_check(tmp_path):
    # No Phase headers → _extract_phases returns [] → Layer 2 skipped gracefully
    spec = _write_spec(tmp_path, "Some content without any phase headers.\n")
    # Should not raise IndexError
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    phase1_errors = [r for r in result if r.startswith("Phase 1")]
    assert phase1_errors == []


# ---------------------------------------------------------------------------
# Layer 3: per-phase language identifier check
# ---------------------------------------------------------------------------


def test_phase_missing_language_fails(tmp_path):
    content = _COMMON_HEADINGS + "## Phase 2: Data Storage\nBuild the DB.\n"
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    lang_errors = [r for r in result if "Phase 2" in r and "language" in r.lower()]
    assert len(lang_errors) == 1


def test_all_phases_have_language_passes_layer3(tmp_path):
    content = (
        _COMMON_HEADINGS
        + "## Phase 2: Backend API [python]\nBuild API.\n"
        + "## Phase 3: Frontend UI [typescript]\nBuild UI.\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    lang_errors = [r for r in result if "language" in r.lower()]
    assert lang_errors == []


def test_mixed_language_implementation_phase_fails(tmp_path):
    content = (
        _COMMON_HEADINGS
        + "## Phase 2: Player Flow [python] [typescript]\nBuild mixed work.\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert any("multiple language identifiers" in r for r in result)


def test_mixed_language_integration_phase_is_exempt(tmp_path):
    content = (
        _COMMON_HEADINGS
        + "## Phase 2: Player Integration [python] [typescript]\nTest mixed work.\n"
    )
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    assert not any("multiple language identifiers" in r for r in result)


def test_language_identifier_case_insensitive(tmp_path):
    content = _COMMON_HEADINGS + "## Phase 2: Backend [Python]\nBuild.\n"
    spec = _write_spec(tmp_path, content)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    lang_errors = [r for r in result if "Phase 2" in r and "language" in r.lower()]
    assert lang_errors == []


def test_phase1_exempt_from_language_check(tmp_path):
    # Phase 1 without a language identifier must NOT trigger Layer 3 error
    spec = _write_spec(tmp_path, _COMMON_HEADINGS)
    result = check_spec_completeness(spec, "cli", CONFIG_PATH)
    lang_errors = [r for r in result if "Phase 1" in r and "language" in r.lower()]
    assert lang_errors == []
