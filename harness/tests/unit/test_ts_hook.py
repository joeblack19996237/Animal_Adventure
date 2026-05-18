import json
import importlib.util
import io
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace

HOOKS_DIR = Path(__file__).parent.parent.parent.parent / ".claude" / "hooks"
PYTHON = sys.executable
_SCRIPTS_DIR = sysconfig.get_path("scripts")


def run_hook(hook_name: str, stdin_data: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HOOKS_DIR)
    env["HARNESS_MODE"] = "1"
    if _SCRIPTS_DIR:
        env["PATH"] = _SCRIPTS_DIR + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [PYTHON, str(HOOKS_DIR / hook_name)],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        env=env,
    )


def load_hook_module(hook_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, HOOKS_DIR / hook_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- skip behaviour for non-TypeScript files ---


def test_skips_python_file(tmp_path):
    result = run_hook(
        "post_ts_lint_format.py",
        {"tool_input": {"file_path": str(tmp_path / "module.py")}},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_text_file(tmp_path):
    result = run_hook(
        "post_ts_lint_format.py",
        {"tool_input": {"file_path": str(tmp_path / "readme.txt")}},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_json_file(tmp_path):
    result = run_hook(
        "post_ts_lint_format.py",
        {"tool_input": {"file_path": str(tmp_path / "config.json")}},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_empty_file_path():
    result = run_hook("post_ts_lint_format.py", {"tool_input": {"file_path": ""}})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_missing_tool_input_key():
    result = run_hook("post_ts_lint_format.py", {})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# --- TypeScript files are processed and hook always exits 0 ---


def test_ts_file_exits_zero(tmp_path):
    f = tmp_path / "component.ts"
    f.write_text("const x: number = 1;\n", encoding="utf-8")
    result = run_hook("post_ts_lint_format.py", {"tool_input": {"file_path": str(f)}})
    assert result.returncode == 0


def test_tsx_file_exits_zero(tmp_path):
    f = tmp_path / "component.tsx"
    f.write_text("export const App = (): null => null;\n", encoding="utf-8")
    result = run_hook("post_ts_lint_format.py", {"tool_input": {"file_path": str(f)}})
    assert result.returncode == 0


def test_ts_file_missing_from_disk_exits_zero(tmp_path):
    # Hook should not crash if the file was already deleted or path is wrong
    result = run_hook(
        "post_ts_lint_format.py",
        {"tool_input": {"file_path": str(tmp_path / "nonexistent.ts")}},
    )
    assert result.returncode == 0


def test_ts_hook_invokes_npx_no_install_with_timeout(monkeypatch):
    module = load_hook_module("post_ts_lint_format.py", "post_ts_timeout_arg_test")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"tool_input": {"file_path": "component.ts"}})),
    )
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(module.subprocess, "run", mock_run)

    assert module.main() == 0
    assert len(calls) == 3
    assert all(cmd[:2] == ["npx", "--no-install"] for cmd, _ in calls)
    assert all(kwargs.get("timeout") == module.TOOL_TIMEOUT for _, kwargs in calls)


def test_ts_hook_timeout_exits_zero(monkeypatch, capsys):
    module = load_hook_module("post_ts_lint_format.py", "post_ts_timeout_test")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"tool_input": {"file_path": "component.ts"}})),
    )

    def mock_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(module.subprocess, "run", mock_run)

    assert module.main() == 0
    assert "timed out" in capsys.readouterr().out


def test_ts_hook_missing_npx_exits_zero(monkeypatch, capsys):
    module = load_hook_module("post_ts_lint_format.py", "post_ts_missing_npx_test")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"tool_input": {"file_path": "component.ts"}})),
    )

    def mock_run(*args, **kwargs):
        raise FileNotFoundError("npx")

    monkeypatch.setattr(module.subprocess, "run", mock_run)

    assert module.main() == 0
    assert "npx is not available" in capsys.readouterr().out
