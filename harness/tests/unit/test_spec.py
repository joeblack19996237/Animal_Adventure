import pytest

import state as state_mod
from pathlib import Path
from spec import _detect_phase_type, _extract_phases, parse_spec, validate_spec

_KW = {"integration": ["integration"], "e2e": ["e2e", "end-to-end", "end to end"]}


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def test_parse_spec_single_file(tmp_workspace):
    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Phase 1: Bootstrap\nDo the setup.\n\n## Phase 2: Build\nBuild it.",
        encoding="utf-8",
    )
    phases, _ = parse_spec(str(spec), {}, write_phases=False)
    assert len(phases) == 2
    assert phases[0]["id"] == 1
    assert phases[0]["title"] == "Bootstrap"
    assert phases[1]["id"] == 2


def test_parse_spec_directory(tmp_workspace):
    spec_dir = tmp_workspace / "spec_dir"
    spec_dir.mkdir()
    (spec_dir / "a.md").write_text("## Phase 1: Alpha\nDo alpha.", encoding="utf-8")
    (spec_dir / "b.md").write_text("## Phase 2: Beta\nDo beta.", encoding="utf-8")
    phases, context = parse_spec(str(spec_dir), {}, write_phases=False)
    assert len(phases) == 2
    assert context == ""
    assert phases[0]["title"] == "Alpha"
    assert phases[1]["title"] == "Beta"


def test_extract_phases_multiple():
    text = "## Phase 1: One\nfoo\n\n## Phase 2: Two\nbar\n\n## Phase 3: Three\nbaz"
    phases = _extract_phases(text)
    assert len(phases) == 3
    assert phases[2]["id"] == 3
    assert phases[2]["title"] == "Three"
    assert "baz" in phases[2]["description"]


def test_extract_phases_python_tag():
    text = "## Phase 1: Foundation [python]\nDo setup.\n"
    phases = _extract_phases(text, ["python", "typescript"])
    assert phases[0]["language"] == "python"
    assert phases[0]["title"] == "Foundation [python]"


def test_extract_phases_typescript_tag():
    text = "## Phase 2: UI [typescript]\nBuild the UI.\n"
    phases = _extract_phases(text, ["python", "typescript"])
    assert phases[0]["language"] == "typescript"


def test_extract_phases_no_matching_language_is_none():
    text = "## Phase 1: Bootstrap\nDo setup.\n"
    phases = _extract_phases(text, ["python", "typescript"])
    assert phases[0]["language"] is None


def test_parse_spec_writes_language_to_state(tmp_workspace):
    spec = tmp_workspace / "spec.md"
    spec.write_text("## Phase 1: Foundation [python]\nDo setup.\n", encoding="utf-8")
    state: dict = {}
    phases, _ = parse_spec(str(spec), state, write_phases=True)
    assert phases[0]["language"] == "python"
    assert state["phases"][0]["language"] == "python"


def test_parse_spec_extracts_phase_ref_lines(tmp_workspace):
    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Phase 1: Bootstrap [python]\n"
        "**Ref:** `docs/requirements.md`, `docs/architecture.md`\n"
        "Do setup.\n",
        encoding="utf-8",
    )

    phases, _ = parse_spec(str(spec), {}, write_phases=False)

    assert phases[0]["refs"] == ["docs/requirements.md", "docs/architecture.md"]


def test_validate_spec_empty():
    with pytest.raises(SystemExit):
        validate_spec([])


def test_validate_spec_missing_title():
    with pytest.raises(SystemExit):
        validate_spec([{"id": 1, "title": ""}])


def test_validate_spec_non_sequential():
    with pytest.raises(SystemExit):
        validate_spec([{"id": 1, "title": "A"}, {"id": 3, "title": "B"}])


# --- Gate 2: phase_type detection ---


def test_phase_type_is_setup_for_phase_1():
    assert _detect_phase_type(1, "Bootstrap", _KW) == "setup"


def test_phase_type_integration_for_title_with_integration_keyword():
    assert _detect_phase_type(2, "Integration Testing [python]", _KW) == "integration"


def test_phase_type_e2e_for_title_with_e2e_keyword():
    assert _detect_phase_type(3, "E2E Testing", _KW) == "e2e"


def test_phase_type_e2e_for_end_to_end_title():
    assert _detect_phase_type(3, "End-to-End Verification", _KW) == "e2e"


def test_phase_type_development_for_regular_non_setup_phase():
    assert _detect_phase_type(2, "Backend [python]", _KW) == "development"


def test_parse_spec_writes_phase_type_to_state_json_shell(tmp_workspace):
    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Phase 1: Bootstrap\nSetup.\n\n## Phase 2: Integration Testing\nIntegrate.",
        encoding="utf-8",
    )
    state: dict = {}
    parse_spec(str(spec), state, write_phases=True)
    assert state["phases"][0]["phase_type"] == "setup"
    assert state["phases"][1]["phase_type"] == "integration"


def test_check_completeness_no_language_tag_required_for_integration_phase(
    tmp_workspace,
):
    from pathlib import Path as _Path
    from spec import check_spec_completeness

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "# Architecture\n# Workflow\n# Requirements\n# Verification\n# Test Plan\n"
        "# Build Plan\n"
        "## Phase 1: Bootstrap\nSetup.\n"
        "## Phase 2: Integration Testing\nNo language tag.",
        encoding="utf-8",
    )
    config_path = _Path(__file__).parent.parent.parent / "spec_validation.json"
    missing = check_spec_completeness(str(spec), "cli", config_path)
    lang_errors = [m for m in missing if "language identifier" in m and "Phase 2" in m]
    assert not lang_errors, (
        f"Integration phase should not require language tag: {lang_errors}"
    )


def test_check_completeness_no_language_tag_required_for_e2e_phase(tmp_workspace):
    from pathlib import Path as _Path
    from spec import check_spec_completeness

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "# Architecture\n# Workflow\n# Requirements\n# Verification\n# Test Plan\n"
        "# Build Plan\n"
        "## Phase 1: Bootstrap\nSetup.\n"
        "## Phase 2: E2E Testing\nNo language tag.",
        encoding="utf-8",
    )
    config_path = _Path(__file__).parent.parent.parent / "spec_validation.json"
    missing = check_spec_completeness(str(spec), "cli", config_path)
    lang_errors = [m for m in missing if "language identifier" in m and "Phase 2" in m]
    assert not lang_errors, f"E2E phase should not require language tag: {lang_errors}"


# --- extract_spec_sections ---


def test_extracts_requirements_section(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Requirements\nMust do X.\n\n## Other\nIgnore me.\n", encoding="utf-8"
    )
    result = extract_spec_sections(str(spec))
    assert "## Requirements" in result
    assert "Must do X." in result
    assert "Ignore me." not in result


def test_extracts_verification_section(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Verification Plan\nTest all the things.\n\n## Other\nSkip.\n",
        encoding="utf-8",
    )
    result = extract_spec_sections(str(spec))
    assert "## Verification Plan" in result
    assert "Test all the things." in result


def test_extracts_architecture_section(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Architecture\nSystem design here.\n\n## Other\nSkip.\n", encoding="utf-8"
    )
    result = extract_spec_sections(str(spec))
    assert "## Architecture" in result
    assert "System design here." in result


def test_extracts_multiple_sections(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Requirements\nReq content.\n\n## Architecture\nArch content.\n\n## Phase 1\nSkip.\n",
        encoding="utf-8",
    )
    result = extract_spec_sections(str(spec))
    assert "## Requirements" in result
    assert "## Architecture" in result
    assert "## Phase 1" not in result


def test_ignores_non_target_sections(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Phase 1: Setup\nDo setup.\n\n## Requirements\nThe reqs.\n", encoding="utf-8"
    )
    result = extract_spec_sections(str(spec))
    assert "## Requirements" in result
    assert "Phase 1" not in result


def test_returns_empty_string_when_no_sections_match(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text("## Phase 1\nNo targets here.\n", encoding="utf-8")
    result = extract_spec_sections(str(spec))
    assert result == ""


def test_folder_mode_returns_at_paths(tmp_workspace):
    from spec import extract_spec_sections

    folder = tmp_workspace / "specs"
    folder.mkdir()
    (folder / "requirements.md").write_text("req", encoding="utf-8")
    (folder / "architecture.md").write_text("arch", encoding="utf-8")
    result = extract_spec_sections(str(folder))
    lines = result.splitlines()
    assert len(lines) == 2
    assert all(line.startswith("@") for line in lines)


def test_folder_mode_sorted_paths(tmp_workspace):
    from spec import extract_spec_sections

    folder = tmp_workspace / "specs"
    folder.mkdir()
    (folder / "z_last.md").write_text("z", encoding="utf-8")
    (folder / "a_first.md").write_text("a", encoding="utf-8")
    result = extract_spec_sections(str(folder))
    lines = result.splitlines()
    assert "a_first" in lines[0]
    assert "z_last" in lines[1]


def test_folder_mode_skips_non_md_files(tmp_workspace):
    from spec import extract_spec_sections

    folder = tmp_workspace / "specs"
    folder.mkdir()
    (folder / "spec.md").write_text("md content", encoding="utf-8")
    (folder / "readme.txt").write_text("txt content", encoding="utf-8")
    result = extract_spec_sections(str(folder))
    lines = [l for l in result.splitlines() if l.strip()]
    assert len(lines) == 1
    assert "spec.md" in lines[0]


def test_section_ends_at_next_heading(tmp_workspace):
    from spec import extract_spec_sections

    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Requirements\nReq body.\n\n## Architecture\nArch body.\n", encoding="utf-8"
    )
    result = extract_spec_sections(str(spec))
    req_part = result.split("## Architecture")[0]
    assert "Req body." in req_part
    assert "Arch body." not in req_part
