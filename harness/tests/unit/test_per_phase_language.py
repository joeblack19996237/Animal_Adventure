"""
Unit tests for per-phase language switching end-to-end path.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agents
import calibrate as cal_mod
import state as state_mod
from cleanup import _finish, run_cleanup
from lang import get_profile
from spec import parse_spec


@pytest.fixture(autouse=True)
def use_tmp_workspace(tmp_workspace, monkeypatch):
    monkeypatch.chdir(tmp_workspace)
    (tmp_workspace / "workspace").mkdir(exist_ok=True)
    monkeypatch.setattr(state_mod, "STATE_PATH", Path("workspace/state.json"))
    monkeypatch.setattr(state_mod, "STATE_TMP", Path("workspace/state.json.tmp"))


def test_profiles_populated_from_spec(tmp_workspace, sample_config, monkeypatch):
    """Profiles built correctly for each phase from spec language identifiers."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    spec = tmp_workspace / "spec.md"
    spec.write_text(
        "## Phase 1: Bootstrap [python]\nSetup.\n"
        "## Phase 2: Backend [python]\nBuild.\n"
        "## Phase 3: Frontend [typescript]\nUI.\n",
        encoding="utf-8",
    )

    from harness import Harness

    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness._default_language = "python"

    phases, _ = parse_spec(str(spec), harness.state, write_phases=True)
    for p in phases:
        lang = p.get("language") or harness._default_language
        harness.profiles[p["id"]] = get_profile(lang)

    assert harness.profiles[1]["name"] == "python"
    assert harness.profiles[2]["name"] == "python"
    assert harness.profiles[3]["name"] == "typescript"


def test_untagged_phase_falls_back_to_default(
    tmp_workspace, sample_config, monkeypatch
):
    """Phase with no recognized language name uses --language default."""
    monkeypatch.setattr(cal_mod, "load_config", lambda: sample_config)
    spec = tmp_workspace / "spec.md"
    spec.write_text("## Phase 1: Bootstrap\nSetup.\n", encoding="utf-8")

    from harness import Harness

    args = MagicMock()
    args.resume = True
    args.language = "python"
    harness = Harness(args)
    harness._default_language = "python"

    phases, _ = parse_spec(str(spec), harness.state, write_phases=True)
    for p in phases:
        lang = p.get("language") or harness._default_language
        harness.profiles[p["id"]] = get_profile(lang)

    assert harness.profile_for(1)["name"] == "python"


def test_cleanup_groups_issues_by_phase(tmp_workspace, sample_config, monkeypatch):
    """run_cleanup calls fix_issues once per language group with the correct profile."""
    state = {
        "spec_file": "spec.md",
        "language": "python",
        "task_types": [],
        "phases": [
            {
                "id": 2,
                "title": "Backend",
                "language": "python",
                "status": "complete",
                "tasks": [],
                "review": {
                    "status": "fixed",
                    "verdict": "BLOCK",
                    "sha_at_review": "abc",
                    "issues": [
                        {
                            "id": "2.1",
                            "severity": "MEDIUM",
                            "dimension": "Performance",
                            "file": "app.py",
                            "title": "Slow query",
                            "status": "deferred",
                            "attempts": 0,
                            "files_changed": [],
                            "fixed_sha": None,
                            "last_error": [],
                        }
                    ],
                },
            },
            {
                "id": 3,
                "title": "Frontend",
                "language": "typescript",
                "status": "complete",
                "tasks": [],
                "review": {
                    "status": "fixed",
                    "verdict": "BLOCK",
                    "sha_at_review": "def",
                    "issues": [
                        {
                            "id": "3.1",
                            "severity": "MEDIUM",
                            "dimension": "Performance",
                            "file": "App.tsx",
                            "title": "Slow render",
                            "status": "deferred",
                            "attempts": 0,
                            "files_changed": [],
                            "fixed_sha": None,
                            "last_error": [],
                        }
                    ],
                },
            },
        ],
    }
    state_mod.save_state(state)

    debt = tmp_workspace / "workspace" / "tech_debt.jsonl"
    debt.write_text(
        json.dumps(state["phases"][0]["review"]["issues"][0])
        + "\n"
        + json.dumps(state["phases"][1]["review"]["issues"][0])
        + "\n",
        encoding="utf-8",
    )

    python_profile = get_profile("python")
    typescript_profile = get_profile("typescript")

    harness = MagicMock()
    harness.config = sample_config
    harness._default_language = "python"
    harness.profile_for = MagicMock(
        side_effect=lambda pid: python_profile if pid == 2 else typescript_profile
    )

    fix_calls: list[dict] = []

    def mock_fix_issues(
        source_file,
        profile,
        config,
        failure_history=None,
        phase_type="development",
        spec_context="",
    ):
        issues = [
            json.loads(line)
            for line in Path(source_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        fix_calls.append(
            {"profile_name": profile["name"], "issue_ids": [i["id"] for i in issues]}
        )
        return {
            "signal": {
                "fixes": [
                    {"id": i["id"], "status": "fixed", "files_changed": []}
                    for i in issues
                ]
            },
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }

    import cleanup as cleanup_mod

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: MagicMock(stdout="sha\n", returncode=0, stderr=""),
    )
    monkeypatch.setattr(agents, "fix_issues", mock_fix_issues)
    monkeypatch.setattr(cleanup_mod, "_finish", lambda *_, **kw: None)

    def mock_verify_fix(*args, **kwargs):
        state_arg, fixes_arg, phase_id_arg = args[1], args[2], args[3]
        for fix in fixes_arg:
            if fix.get("status") == "fixed":
                for phase in state_arg.get("phases", []):
                    if phase["id"] == phase_id_arg:
                        for issue in phase.get("review", {}).get("issues", []):
                            if issue["id"] == fix["id"]:
                                issue["status"] = "fixed"
        vr = MagicMock()
        vr.harness_blocker = False
        vr.tests_ok = True
        vr.commit_ok = True
        vr.open_fixes = []
        vr.stdout_tail = ""
        vr.stderr_tail = ""
        return vr

    monkeypatch.setattr(cleanup_mod, "verify_fix", mock_verify_fix)

    run_cleanup(harness, state)

    assert len(fix_calls) == 2
    python_call = next(c for c in fix_calls if c["profile_name"] == "python")
    typescript_call = next(c for c in fix_calls if c["profile_name"] == "typescript")
    assert python_call["issue_ids"] == ["2.1"]
    assert typescript_call["issue_ids"] == ["3.1"]


def test_finish_runs_both_test_commands(monkeypatch):
    """_finish executes every test command supplied."""
    called: list[list] = []

    def mock_run(cmd, **kw):
        called.append(list(cmd))
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        return r

    monkeypatch.setattr(subprocess, "run", mock_run)
    _finish([["pytest"], ["npx", "vitest", "run"]])

    assert ["pytest"] in called
    assert ["npx", "vitest", "run"] in called
