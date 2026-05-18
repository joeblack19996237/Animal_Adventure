from pathlib import Path

from spec import _extract_phases, validate_spec

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_fixture_specs_parse_successfully():
    for path in FIXTURES.glob("*.md"):
        phases = _extract_phases(_read(path.name), ["python", "typescript"])
        validate_spec(phases)
        assert phases


def test_fixture_specs_have_required_phase_headers():
    for path in FIXTURES.glob("*.md"):
        text = _read(path.name)
        assert "## Phase 1:" in text
        assert "## Phase 2:" in text


def test_mixed_stack_fixture_has_per_phase_language_tags():
    phases = _extract_phases(_read("mixed_stack_spec.md"), ["python", "typescript"])
    assert phases[1]["language"] == "python"
    assert phases[2]["language"] == "typescript"


def test_timeout_fixture_documents_review_timeout_scenario():
    text = _read("review_timeout_spec.md").lower()
    assert "review timeout" in text
    assert "review.status as error" in text


def test_fix_cycle_fixture_documents_block_and_fix_scenario():
    text = _read("fix_cycle_spec.md").lower()
    assert "block" in text
    assert "targeted re-review" in text

