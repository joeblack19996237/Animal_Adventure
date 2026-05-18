from pathlib import Path

from spec_context import (
    build_evaluation_spec_context,
    build_phase_spec_context,
    build_spec_manifest,
    list_spec_files,
)


def _write_docs(root: Path) -> Path:
    docs = root / "docs"
    docs.mkdir()
    (docs / "requirements.md").write_text("## Requirements\nGame loop.\n", encoding="utf-8")
    (docs / "architecture.md").write_text("## Architecture\nPhaser client.\n", encoding="utf-8")
    (docs / "data-model.md").write_text("## Data Model\nPlayers.\n", encoding="utf-8")
    (docs / "workflows.md").write_text("## Workflows\nReconnect.\n", encoding="utf-8")
    (docs / "websocket-protocol.md").write_text("## WebSocket\nstate_sync.\n", encoding="utf-8")
    (docs / "logging-and-ops.md").write_text("## Nginx\nDeployment.\n", encoding="utf-8")
    (docs / "build-plan.md").write_text(
        "## Phase 1 — Setup [python]\nDo setup.\n\n"
        "## Phase 2 — WebSocket Backend [python]\nBuild ws.\n",
        encoding="utf-8",
    )
    (docs / "test-plan.md").write_text(
        "## Phase 1 Tests — Setup\nTest setup.\n\n"
        "## Phase 2 Tests — WebSocket Backend\nTest ws.\n",
        encoding="utf-8",
    )
    return docs


def test_list_spec_files_sorted(tmp_path):
    docs = _write_docs(tmp_path)
    files = list_spec_files(str(docs))
    assert files == sorted(files)
    assert files[0].endswith("architecture.md")


def test_spec_manifest_lists_docs(tmp_path):
    docs = _write_docs(tmp_path)
    manifest = build_spec_manifest(str(docs))
    assert "Spec manifest" in manifest
    assert "requirements.md" in manifest


def test_phase_context_includes_current_build_and_test_excerpts(tmp_path):
    docs = _write_docs(tmp_path)
    context = build_phase_spec_context(str(docs), {"id": 2, "title": "WebSocket Backend"})
    assert "Build ws." in context
    assert "Test ws." in context
    assert "Do setup." not in context


def test_websocket_phase_includes_protocol_doc(tmp_path):
    docs = _write_docs(tmp_path)
    context = build_phase_spec_context(str(docs), {"id": 2, "title": "WebSocket Backend"})
    assert "websocket-protocol.md" in context


def test_ops_phase_includes_logging_ops_doc(tmp_path):
    docs = _write_docs(tmp_path)
    context = build_phase_spec_context(str(docs), {"id": 3, "title": "Nginx Deployment"})
    assert "logging-and-ops.md" in context


def test_l3_phase_includes_data_model_and_workflows(tmp_path):
    docs = _write_docs(tmp_path)
    context = build_phase_spec_context(
        str(docs), {"id": 3, "title": "Quest Inventory Shop L3 Backend"}
    )
    assert "data-model.md" in context
    assert "workflows.md" in context


def test_nginx_phase_includes_logging_ops_doc(tmp_path):
    docs = _write_docs(tmp_path)
    context = build_phase_spec_context(str(docs), {"id": 3, "title": "Nginx Ops"})
    assert "logging-and-ops.md" in context


def test_evaluation_context_references_all_docs(tmp_path):
    docs = _write_docs(tmp_path)
    context = build_evaluation_spec_context(str(docs))
    assert "@" in context
    assert "requirements.md" in context
    assert "websocket-protocol.md" in context
