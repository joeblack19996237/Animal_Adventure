import json
from pathlib import Path

import events


def test_event_log_line_is_valid_json(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    events.emit_event("thing_happened", answer=42)
    line = Path("workspace/events.jsonl").read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["event"] == "thing_happened"
    assert entry["answer"] == 42


def test_harness_log_created(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    events.log_line("hello")
    assert "hello" in Path("workspace/harness.log").read_text(encoding="utf-8")


def test_event_log_creates_workspace_if_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    events.emit_event("created")
    assert Path("workspace/events.jsonl").exists()


def test_event_log_appends_without_overwriting(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    events.emit_event("first")
    events.emit_event("second")
    lines = Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["first", "second"]


def test_emit_event_rotates_large_events_file(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(events, "MAX_EVENTS_BYTES", 5)
    Path("workspace").mkdir(exist_ok=True)
    Path("workspace/events.jsonl").write_text("123456", encoding="utf-8")

    events.emit_event("after_rotation")

    assert Path("workspace/events.jsonl.1").read_text(encoding="utf-8") == "123456"


def test_emit_event_preserves_current_event_after_rotation(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    monkeypatch.setattr(events, "MAX_EVENTS_BYTES", 5)
    Path("workspace").mkdir(exist_ok=True)
    Path("workspace/events.jsonl").write_text("123456", encoding="utf-8")

    events.emit_event("after_rotation")
    line = Path("workspace/events.jsonl").read_text(encoding="utf-8").strip()

    assert json.loads(line)["event"] == "after_rotation"


def test_emit_event_rate_limits_duplicate_state_transitions(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    events._LAST_TRANSITION_KEY = None
    events._LAST_TRANSITION_COUNT = 0
    for _ in range(3):
        events.emit_event("state_transition", state="EXECUTING", phase_id=1)

    lines = Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1


def test_emit_event_does_not_rate_limit_different_transition(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    events._LAST_TRANSITION_KEY = None
    events._LAST_TRANSITION_COUNT = 0
    events.emit_event("state_transition", state="EXECUTING", phase_id=1)
    events.emit_event("state_transition", state="REVIEWING", phase_id=1)

    lines = Path("workspace/events.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
