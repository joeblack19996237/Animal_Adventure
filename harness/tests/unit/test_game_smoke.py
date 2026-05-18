from pathlib import Path

import game_smoke


def test_smoke_skips_when_playwright_config_missing(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    state = {"app_type": "game"}
    config = {"game_quick_smoke_phase_ids": [5]}

    result = game_smoke.run_game_smoke(state, 5, config)

    assert result.status == "skipped"
    assert "playwright config" in result.reason


def test_smoke_skips_when_phase_smoke_tests_missing(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    Path("playwright.config.ts").write_text("export default {}", encoding="utf-8")
    state = {"app_type": "game"}
    config = {"game_quick_smoke_phase_ids": [5]}

    result = game_smoke.run_game_smoke(state, 5, config)

    assert result.status == "skipped"
    assert "@phase5-smoke" in result.reason


def test_smoke_runs_phase_specific_grep(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    Path("playwright.config.ts").write_text("export default {}", encoding="utf-8")
    test_dir = Path("tests/e2e")
    test_dir.mkdir(parents=True)
    (test_dir / "smoke.spec.ts").write_text("test('@phase8-smoke works')", encoding="utf-8")
    calls = []

    def mock_run_command(cmd, **kwargs):
        calls.append(cmd)
        return cmd, type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(game_smoke, "run_command", mock_run_command)

    result = game_smoke.run_game_smoke(
        {"app_type": "game"}, 8, {"game_quick_smoke_phase_ids": [8]}
    )

    assert result.status == "passed"
    assert calls == [["npm", "run", "test:e2e", "--", "--grep", "@phase8-smoke"]]


def test_smoke_not_run_for_non_game_app():
    assert not game_smoke.should_run_game_smoke(
        {"app_type": "web"}, 5, {"game_quick_smoke_phase_ids": [5]}
    )


def test_smoke_failure_result_contains_output_tail(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    Path("playwright.config.ts").write_text("export default {}", encoding="utf-8")
    test_dir = Path("tests/e2e")
    test_dir.mkdir(parents=True)
    (test_dir / "smoke.spec.ts").write_text("test('@phase5-smoke fails')", encoding="utf-8")

    def mock_run_command(cmd, **kwargs):
        return cmd, type(
            "Result",
            (),
            {"returncode": 1, "stdout": "x" * 600, "stderr": "y" * 600},
        )()

    monkeypatch.setattr(game_smoke, "run_command", mock_run_command)

    result = game_smoke.run_game_smoke(
        {"app_type": "game"}, 5, {"game_quick_smoke_phase_ids": [5]}
    )

    assert result.status == "failed"
    assert result.stdout_tail == "x" * 500
    assert result.stderr_tail == "y" * 500
