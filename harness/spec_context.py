from __future__ import annotations

import re
from pathlib import Path

_PHASE_RE = re.compile(r"^##\s+Phase\s+(\d+)(?:\s+Tests)?\s*[:\-—]\s*(.+)$", re.MULTILINE)

_GLOBAL_DOCS = {
    "requirements.md",
    "architecture.md",
    "build-plan.md",
    "test-plan.md",
}

_KEYWORD_DOCS = [
    (("websocket", "multiplayer", "reconnect"), "websocket-protocol.md"),
    (("log", "ops", "deployment", "nginx", "cleanup"), "logging-and-ops.md"),
    (("player", "quest", "inventory", "shop", "progression", "persistence", "backend", "database"), "data-model.md"),
    (("workflow", "login", "movement", "quest", "reconnect", "restart"), "workflows.md"),
]


def list_spec_files(spec_path: str) -> list[str]:
    path = Path(spec_path)
    if path.is_dir():
        return [str(p).replace("\\", "/") for p in sorted(path.glob("*.md"))]
    if path.exists():
        return [str(path).replace("\\", "/")]
    return []


def build_spec_manifest(spec_path: str) -> str:
    files = list_spec_files(spec_path)
    if not files:
        return "Spec manifest: no spec files found."
    lines = ["Spec manifest (read referenced files when needed):"]
    lines.extend(f"- {p}" for p in files)
    return "\n".join(lines)


def build_phase_spec_context(spec_path: str, phase: dict) -> str:
    path = Path(spec_path)
    phase_id = int(phase.get("id", 0) or 0)
    title = str(phase.get("title", ""))
    parts = [build_spec_manifest(spec_path)]

    if not path.is_dir():
        if path.exists():
            parts.append(f"Primary spec file: {path}")
        return "\n\n".join(parts)

    selected = _select_docs(path, title)
    if selected:
        parts.append("Phase-relevant spec files:\n" + "\n".join(f"- {p}" for p in selected))

    build_plan = path / "build-plan.md"
    test_plan = path / "test-plan.md"
    build_excerpt = _phase_excerpt(build_plan, phase_id)
    test_excerpt = _phase_excerpt(test_plan, phase_id)
    if build_excerpt:
        parts.append("Current build-plan phase excerpt:\n" + build_excerpt)
    if test_excerpt:
        parts.append("Current test-plan phase excerpt:\n" + test_excerpt)
    return "\n\n".join(parts)


def build_evaluation_spec_context(spec_path: str) -> str:
    files = list_spec_files(spec_path)
    if not files:
        return "Spec manifest: no spec files found."
    lines = ["Full evaluation spec context. Read all files before scoring:"]
    lines.extend(f"- @{p}" for p in files)
    return "\n".join(lines)


def _select_docs(spec_dir: Path, title: str) -> list[str]:
    title_lower = title.lower()
    selected: list[Path] = []
    for name in _GLOBAL_DOCS:
        candidate = spec_dir / name
        if candidate.exists():
            selected.append(candidate)
    for keywords, name in _KEYWORD_DOCS:
        if any(keyword in title_lower for keyword in keywords):
            candidate = spec_dir / name
            if candidate.exists() and candidate not in selected:
                selected.append(candidate)
    return [str(p).replace("\\", "/") for p in selected]


def _phase_excerpt(path: Path, phase_id: int) -> str:
    if not path.exists() or phase_id <= 0:
        return ""
    content = path.read_text(encoding="utf-8")
    matches = list(_PHASE_RE.finditer(content))
    for idx, match in enumerate(matches):
        if int(match.group(1)) != phase_id:
            continue
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        return content[start:end].strip()
    return ""
