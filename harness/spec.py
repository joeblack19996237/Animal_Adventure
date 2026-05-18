import json
import re
import sys
from pathlib import Path

from state import save_state

_PHASE_HEADER_RE = re.compile(r"^##\s+Phase\s+(\d+)\s*[:\-—]\s*(.+)$", re.MULTILINE)
_REF_LINE_RE = re.compile(r"\*\*Ref:\*\*\s*(.+)$", re.MULTILINE)
_BACKTICK_PATH_RE = re.compile(r"`([^`]+)`")


def _extract_phase_refs(description: str) -> list[str]:
    """Return unique file paths from all **Ref:** lines in a phase section, preserving order."""
    seen: set[str] = set()
    refs: list[str] = []
    for ref_match in _REF_LINE_RE.finditer(description):
        for path_match in _BACKTICK_PATH_RE.finditer(ref_match.group(1)):
            path = path_match.group(1).strip()
            if path not in seen:
                seen.add(path)
                refs.append(path)
    return refs


def _detect_phase_type(phase_id: int, title: str, keywords: dict) -> str:
    if phase_id == 1:
        return "setup"
    title_lower = title.lower()
    for kw in keywords.get("e2e", []):
        if kw in title_lower:
            return "e2e"
    for kw in keywords.get("integration", []):
        if kw in title_lower:
            return "integration"
    return "development"


def parse_spec(spec_path: str, state: dict, *, write_phases: bool) -> tuple[list, str]:
    """Return (phases, context). phases = [{id, title, language, phase_type, description}]."""
    path = Path(spec_path)

    _config_path = Path(__file__).parent / "spec_validation.json"
    language_types: list[str] = []
    phase_type_keywords: dict = {}
    if _config_path.exists():
        config_data = json.loads(_config_path.read_text(encoding="utf-8"))
        language_types = config_data.get("language_types", [])
        phase_type_keywords = config_data.get("phase_type_keywords", {})

    if path.is_dir():
        md_files = sorted(path.glob("*.md"))
        build_plan_files = [
            f for f in md_files if re.search(r"build.?plan", f.name, re.IGNORECASE)
        ]
        if build_plan_files:
            plan_text = "\n\n".join(
                f.read_text(encoding="utf-8") for f in build_plan_files
            )
            phases = _extract_phases(plan_text, language_types, phase_type_keywords)
        else:
            all_text = "\n\n".join(f.read_text(encoding="utf-8") for f in md_files)
            phases = _extract_phases(all_text, language_types, phase_type_keywords)
        context = ""
    else:
        text = path.read_text(encoding="utf-8")
        phases = _extract_phases(text, language_types, phase_type_keywords)
        context = ""

    if write_phases:
        state["phases"] = [
            {
                "id": p["id"],
                "title": p["title"],
                "language": p["language"],
                "phase_type": p["phase_type"],
                "status": "pending",
                "tasks": [],
                "review": {
                    "status": "pending",
                    "verdict": None,
                    "sha_at_review": None,
                    "issues": [],
                },
            }
            for p in phases
        ]
        state["total_phases"] = len(phases)
        save_state(state)

    return phases, context


def _extract_phases(
    text: str,
    language_types: list[str] | None = None,
    phase_type_keywords: dict | None = None,
) -> list:
    matches = list(_PHASE_HEADER_RE.finditer(text))
    phases = []
    for i, m in enumerate(matches):
        phase_id = int(m.group(1))
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        description = text[body_start:body_end].strip()
        language: str | None = None
        languages: list[str] = []
        if language_types:
            title_lower = title.lower()
            for lang in language_types:
                if lang in title_lower:
                    languages.append(lang)
            if languages:
                language = languages[0]
        phase_type = _detect_phase_type(phase_id, title, phase_type_keywords or {})
        phases.append(
            {
                "id": phase_id,
                "title": title,
                "language": language,
                "languages": languages,
                "phase_type": phase_type,
                "description": description,
                "refs": _extract_phase_refs(description),
            }
        )
    return phases


def validate_spec(phases: list) -> None:
    if not phases:
        print("[ERROR] No phases found in spec. Use '## Phase N: Title' headers.")
        sys.exit(1)
    for i, phase in enumerate(phases, start=1):
        if not phase["title"]:
            print(f"[ERROR] Phase {phase['id']} has no title.")
            sys.exit(1)
        if phase["id"] != i:
            print(
                f"[ERROR] Phase IDs must be sequential starting at 1. "
                f"Found {phase['id']} at position {i}."
            )
            sys.exit(1)


def extract_spec_sections(spec_path: str) -> str:
    """Return Requirements, Verification, and Architecture sections as a text block.

    Folder mode: returns @-prefixed paths for the evaluator to Read at runtime.
    Single-file mode: extracts ## sections whose headings match target keywords.
    """
    path = Path(spec_path)
    if path.is_dir():
        lines = []
        for f in sorted(path.iterdir()):
            if f.suffix == ".md":
                lines.append(f"@{f}")
        return "\n".join(lines)

    _cfg = Path(__file__).parent / "spec_validation.json"
    raw_keywords = json.loads(_cfg.read_text(encoding="utf-8")).get(
        "extract_section_keywords", []
    )
    kw_lower = [kw.lower() for kw in raw_keywords]
    content = path.read_text(encoding="utf-8")
    section_re = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(section_re.finditer(content))
    extracted: list[str] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip().lower()
        if any(kw in heading for kw in kw_lower):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            extracted.append(content[start:end].strip())
    return "\n\n".join(extracted)


def check_spec_completeness(
    spec_path: str, app_type: str, config_path: Path
) -> list[str]:
    """
    Return list of missing required section labels. Empty list = all checks passed.

    Layer 1 — keyword in headings: searches only lines starting with '#'.
    Layer 2 — Phase 1 structural check: Phase 1 title must contain a setup keyword
               and must NOT contain a domain-specific qualifier.
    Logs [WARN] for conditional failures without adding to error list.
    """
    path = Path(spec_path)
    if path.is_dir():
        spec_text = "\n\n".join(
            f.read_text(encoding="utf-8") for f in sorted(path.glob("*.md"))
        )
    else:
        spec_text = path.read_text(encoding="utf-8")

    headings_text = "\n".join(
        line for line in spec_text.splitlines() if re.match(r"^#{1,6}\s+", line)
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing: list[str] = []

    def _any_keyword(keywords: list[str]) -> bool:
        pattern = "|".join(re.escape(k) for k in keywords)
        return bool(re.search(pattern, headings_text, re.IGNORECASE))

    for req in config["common_requirements"]:
        if not _any_keyword(req["keywords"]):
            if req["mode"] == "required":
                missing.append(req["label"])

    for req in config["app_type_requirements"].get(app_type, []):
        if req["mode"] == "required":
            if not _any_keyword(req["keywords"]):
                missing.append(req["label"])
        elif req["mode"] == "conditional":
            if _any_keyword(req["condition_keywords"]) and not _any_keyword(
                req["keywords"]
            ):
                print(
                    f"[WARN] Spec has data-related content but no '{req['label']}' section."
                )

    language_types = config.get("language_types", [])
    phase_type_keywords = config.get("phase_type_keywords", {})
    phases = _extract_phases(spec_text, language_types, phase_type_keywords)
    if phases:
        phase1_title = phases[0]["title"].lower()
        setup_kws = config["phase1_setup_keywords"]
        disqualifiers = config["phase1_domain_disqualifiers"]
        has_setup = any(kw in phase1_title for kw in setup_kws)
        has_domain = any(kw in phase1_title for kw in disqualifiers)
        if not has_setup or has_domain:
            missing.append(
                f"Phase 1 title '{phases[0]['title']}' does not indicate a project-level "
                f"setup phase. Phase 1 must contain a setup keyword "
                f"({', '.join(setup_kws)}) without domain-specific qualifiers "
                f"({', '.join(disqualifiers)})."
            )

    if language_types and phases:
        for phase in phases:
            if phase["id"] == 1:
                continue
            if phase.get("phase_type") in ("integration", "e2e"):
                continue
            phase_languages = phase.get("languages") or (
                [phase["language"]] if phase.get("language") else []
            )
            if not phase_languages:
                missing.append(
                    f"Phase {phase['id']} title '{phase['title']}' has no language identifier. "
                    f"Include one of {language_types} in the heading (e.g. [python])."
                )
            elif len(phase_languages) > 1:
                missing.append(
                    f"Phase {phase['id']} title '{phase['title']}' has multiple language identifiers "
                    f"{phase_languages}. Split mixed implementation work into single-language phases, "
                    "or mark the phase as integration/e2e."
                )

    return missing
