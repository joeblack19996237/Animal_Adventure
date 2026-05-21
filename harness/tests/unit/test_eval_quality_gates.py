from pathlib import Path

from eval_quality_gates import run_quality_gates


def test_quality_gate_reports_large_production_file(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "LargeScene.ts").write_text("\n".join(["x"] * 501), encoding="utf-8")

    result = run_quality_gates(tmp_path)

    assert result["pass"] is False
    assert result["issues"][0]["type"] == "large_production_file"
    assert result["issues"][0]["file"] == str(Path("src") / "LargeScene.ts")


def test_quality_gate_allows_file_at_line_limit(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Scene.ts").write_text("\n".join(["x"] * 500), encoding="utf-8")

    result = run_quality_gates(tmp_path)

    assert result["pass"] is True
    assert result["issues"] == []


def test_quality_gate_reports_client_ws_message_without_server_dispatch(tmp_path):
    src = tmp_path / "src"
    app = tmp_path / "app"
    src.mkdir()
    app.mkdir()
    (src / "GameScene.ts").write_text(
        "this.wsClient.send({ type: 'quest_accept', quest_id: 'q1' });\n",
        encoding="utf-8",
    )
    (app / "ws_handler.py").write_text(
        "if msg.get('type') == 'preset_chat':\n    pass\n",
        encoding="utf-8",
    )

    result = run_quality_gates(tmp_path)

    assert result["pass"] is False
    assert result["issues"][0]["type"] == "missing_ws_dispatch"
    assert "`quest_accept`" in result["issues"][0]["message"]


def test_quality_gate_accepts_client_ws_message_with_server_dispatch(tmp_path):
    src = tmp_path / "src"
    app = tmp_path / "app"
    src.mkdir()
    app.mkdir()
    (src / "GameScene.ts").write_text(
        "this.wsClient.send({ type: 'quest_accept', quest_id: 'q1' });\n",
        encoding="utf-8",
    )
    (app / "ws_gameplay.py").write_text(
        "msg_type = msg.get('type')\nif msg_type == 'quest_accept':\n    pass\n",
        encoding="utf-8",
    )

    result = run_quality_gates(tmp_path)

    assert result["pass"] is True
    assert result["issues"] == []
