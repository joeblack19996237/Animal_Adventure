from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from events import emit_event
from subprocess_runner import run_command


@dataclass
class SmokeResult:
    status: str
    cmd: list[str] | None = None
    reason: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("passed", "skipped")


def should_run_game_smoke(state: dict, phase_id: int, config: dict) -> bool:
    return (
        state.get("app_type") == "game"
        and phase_id in config.get("game_quick_smoke_phase_ids", [])
    )


def run_game_smoke(state: dict, phase_id: int, config: dict) -> SmokeResult:
    if not should_run_game_smoke(state, phase_id, config):
        return SmokeResult(status="skipped", reason="phase not configured for smoke")
    if not _playwright_config_exists():
        return _skip(phase_id, "playwright config not found")
    tag = f"@phase{phase_id}-smoke"
    if not _smoke_test_exists(tag):
        return _skip(phase_id, f"no smoke test found for {tag}")
    cmd = ["npm", "run", "test:e2e", "--", "--grep", tag]
    run_cmd, result = run_command(cmd, capture_output=True, text=True)
    status = "passed" if result.returncode == 0 else "failed"
    emit_event(
        "game_smoke",
        phase_id=phase_id,
        status=status,
        cmd=run_cmd,
        returncode=result.returncode,
    )
    return SmokeResult(
        status=status,
        cmd=run_cmd,
        stdout_tail=result.stdout[-500:],
        stderr_tail=result.stderr[-500:],
    )


def _playwright_config_exists() -> bool:
    return any(Path(".").glob("playwright.config.*"))


def _smoke_test_exists(tag: str) -> bool:
    for root in (Path("tests/e2e"), Path("e2e")):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in (".ts", ".tsx", ".js", ".mjs"):
                try:
                    if tag in path.read_text(encoding="utf-8"):
                        return True
                except UnicodeDecodeError:
                    continue
    return False


def _skip(phase_id: int, reason: str) -> SmokeResult:
    emit_event("game_smoke", phase_id=phase_id, status="skipped", reason=reason)
    return SmokeResult(status="skipped", reason=reason)
