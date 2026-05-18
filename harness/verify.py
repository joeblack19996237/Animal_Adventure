from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from events import emit_event
from calibrate import get_artifact_limits
from git_changes import (
    changed_files_since_snapshot,
    commit_files,
    safe_changed_signal_files,
)
from state import update_state
from subprocess_runner import run_command

if TYPE_CHECKING:
    from harness import Harness

logger = logging.getLogger(__name__)

REVIEW_REPORT_PATH = Path("workspace/review_report.md")
FIX_TEST_FAILURE_LOG_PATH = Path("workspace/fix_test_failure.log")

_TEXT_ARTIFACT_SUFFIXES = {
    ".conf",
    ".example",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".template",
    ".txt",
    ".yaml",
    ".yml",
}
_TEXT_ARTIFACT_NAMES = {"requirements.txt", ".env", ".env.example"}


@dataclass
class VerificationResult(list):
    failed_tasks: list = field(default_factory=list)
    open_fixes: list = field(default_factory=list)
    commit_ok: bool = True
    compile_ok: bool = True
    tests_ok: bool = True
    skipped_reason: str | None = None
    commands: list[list[str]] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    commit_sha: str | None = None
    committed_files: list[str] = field(default_factory=list)
    failure_kind: str | None = None
    harness_blocker: bool = False
    blocker_reason: str | None = None
    failure_artifact: str | None = None

    def __post_init__(self) -> None:
        list.__init__(self, self.failed_tasks or self.open_fixes)


def _select_test_cmd(profile: dict, phase_type: str) -> list[str]:
    if phase_type in ("integration", "e2e"):
        return profile.get("integration_test_cmd", profile["test_cmd"])
    return profile["test_cmd"]


def _verification_profiles(harness: Harness, phase_id: int) -> list[dict]:
    method = getattr(harness, "verification_profiles_for", None)
    if callable(method):
        try:
            profiles = method(phase_id)
            if isinstance(profiles, list) and profiles:
                return profiles
        except (AttributeError, TypeError):
            pass
    return [harness.profile_for(phase_id)]


def _select_test_cmds(
    harness: Harness, phase_id: int, phase_type: str
) -> list[list[str]]:
    cmds: list[list[str]] = []
    for profile in _verification_profiles(harness, phase_id):
        cmd = _select_test_cmd(profile, phase_type)
        if cmd not in cmds:
            cmds.append(cmd)
    return cmds


def _compile_profile_for_file(
    profiles: list[dict], fallback: dict, file_path: str
) -> dict:
    for profile in profiles:
        if any(
            fnmatch.fnmatch(file_path, ext) for ext in profile["compile_extensions"]
        ):
            return profile
    return fallback


_run_command = run_command


def _phase_id_from_batch(batch: list) -> int:
    try:
        return int(batch[0]["id"].split(".")[0])
    except (IndexError, ValueError):
        return 1


def _within_project_root(path: str) -> bool:
    root = Path(".").resolve()
    try:
        return Path(path).resolve().is_relative_to(root)
    except ValueError:
        return False


def _signal_files_tracked_and_clean(signal_files: list[str]) -> bool:
    if not signal_files:
        return True
    root = Path(".").resolve()
    for file_name in signal_files:
        normalized = file_name.replace("\\", "/").strip("/")
        if not normalized:
            return False
        try:
            resolved = (root / normalized).resolve()
            if not resolved.is_relative_to(root):
                return False
        except ValueError:
            return False
        if not resolved.exists():
            return False
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--", normalized],
            capture_output=True,
            text=True,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", normalized],
            capture_output=True,
            text=True,
        )
        if tracked.returncode != 0:
            return False
    return True


def _already_satisfied_noop_note(task_sig: dict) -> bool:
    note = str(task_sig.get("tdd_skipped") or "").lower()
    return "already" in note and "satisf" in note


def _normalize_diff_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _is_text_artifact(path: str) -> bool:
    normalized = _normalize_diff_path(path)
    name = Path(normalized).name.lower()
    return (
        name in _TEXT_ARTIFACT_NAMES
        or Path(normalized).suffix.lower() in _TEXT_ARTIFACT_SUFFIXES
    )


def _validate_requirements_text(path: str, text: str) -> list[str]:
    if Path(path).name.lower() != "requirements.txt":
        return []
    failures = []
    for line_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "--")):
            continue
        if line[0] in "<>=!~,":
            failures.append(f"{path}:{line_no} does not look like a requirement")
    return failures


def _artifact_quality_failures(files: list[str]) -> list[str]:
    failures = []
    for file_name in files:
        normalized = _normalize_diff_path(file_name)
        if not normalized or not _is_text_artifact(normalized):
            continue
        if not _within_project_root(normalized):
            continue
        path = Path(normalized)
        if not path.exists() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError as e:
            failures.append(f"{normalized} could not be read: {e}")
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            failures.append(f"{normalized} has a UTF-8 BOM")
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            failures.append(f"{normalized} has a UTF-16 BOM")
        if b"\x00" in raw:
            failures.append(f"{normalized} contains NUL bytes")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"{normalized} is not UTF-8 text")
            continue
        failures.extend(_validate_requirements_text(normalized, text))
    return failures


def _test_file_size_failures(config: dict, files: list[str]) -> list[str]:
    max_lines = get_artifact_limits(config)["max_new_test_file_lines"]
    if max_lines <= 0:
        return []
    failures = []
    for file_name in files:
        normalized = _normalize_diff_path(file_name)
        if not normalized.startswith("tests/"):
            continue
        if Path(normalized).suffix.lower() not in {".py", ".ts", ".tsx"}:
            continue
        if not _within_project_root(normalized):
            continue
        path = Path(normalized)
        if not path.exists() or not path.is_file():
            continue
        try:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            continue
        if line_count > max_lines:
            failures.append(
                f"{normalized} has {line_count} lines; limit is {max_lines}. "
                "Reduce to representative cases."
            )
    return failures


def _failed_signals_for_artifacts(signal: dict, failures: list[str]) -> list[dict]:
    reason = "artifact quality failed: " + "; ".join(failures[:3])
    return [
        {**task_sig, "status": "failed", "reason": reason}
        for task_sig in signal.get("tasks", [])
        if task_sig.get("status") == "complete"
    ]


def _changed_files_in_commit(pre_sha: str, current_sha: str) -> list[str]:
    if not pre_sha or pre_sha == current_sha:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{pre_sha}..{current_sha}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [
        _normalize_diff_path(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def _allowed_unit_test_support_file(path: str) -> bool:
    normalized = _normalize_diff_path(path)
    name = Path(normalized).name
    if name in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        return True
    if normalized in {"pytest.ini", "pyproject.toml"}:
        return True
    return bool(
        re.fullmatch(r"(vitest|playwright)\.config\.(js|mjs|cjs|ts|mts|cts)", name)
    )


def _verification_temp_dir() -> Path:
    path = Path("workspace") / "verification-tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_pytest_cmd(cmd: list[str]) -> bool:
    if not cmd:
        return False
    executable = Path(cmd[0]).name.lower()
    if executable in {"pytest", "pytest.exe"}:
        return True
    return len(cmd) >= 3 and cmd[1:3] == ["-m", "pytest"]


def _prepare_verification_cmd(cmd: list[str]) -> list[str]:
    prepared = list(cmd)
    if not _is_pytest_cmd(prepared):
        return prepared
    if not any(part == "--ignore=.pytest_cache" for part in prepared):
        prepared.append("--ignore=.pytest_cache")
    if not any(part == "--ignore=.tmp" for part in prepared):
        prepared.append("--ignore=.tmp")
    # Do not add --basetemp: pytest calls ensure_reset_dir() on a user-supplied
    # basetemp, which issues rmtree on Windows where prior-run SQLite/WAL handles
    # are still open, causing PermissionError (WinError 5) at test-setup time.
    # The TMP/TEMP env override in _verification_cmd_kwargs is sufficient to keep
    # pytest's own auto-created temp directories within workspace/verification-tmp.
    return prepared


def _verification_cmd_kwargs(harness: Harness) -> dict:
    temp_dir = _verification_temp_dir()
    env = dict(os.environ)
    env["TMP"] = str(temp_dir.resolve())
    env["TEMP"] = str(temp_dir.resolve())
    kwargs = {"capture_output": True, "text": True, "env": env}
    timeout = harness.config.get("verification_timeout")
    if timeout:
        kwargs["timeout"] = int(timeout)
    return kwargs


def _cleanup_verification_artifacts(
    root: Path | None = None, pre_snapshot: set[str] | None = None
) -> None:
    repo_root = (root or Path(".")).resolve()
    for name in ("coverage", "test-results", "playwright-report"):
        path = (repo_root / name).resolve()
        try:
            if not path.is_relative_to(repo_root):
                continue
        except ValueError:
            continue
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
    coverage_file = repo_root / ".coverage"
    if not coverage_file.exists() or (pre_snapshot and ".coverage" in pre_snapshot):
        return
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--", ".coverage"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or not status.stdout.strip():
        return
    if status.stdout.startswith("??"):
        coverage_file.unlink(missing_ok=True)
    else:
        subprocess.run(
            ["git", "restore", "--", ".coverage"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )


def _is_expected_preflight_report(batch: list, stdout: str, stderr: str) -> bool:
    task_text = " ".join(
        " ".join(str(t.get(k, "")) for k in ("title", "description")).lower()
        for t in batch
    )
    output = f"{stdout}\n{stderr}"
    if "PREFLIGHT FAILURE" not in output:
        return False
    if "preflight" not in task_text and "browser launch" not in task_text:
        return False
    generic_failures = ("SyntaxError", "TypeError", "ReferenceError", "Traceback")
    return not any(marker in output for marker in generic_failures)


def _is_no_tests_selected(
    cmd: list[str], returncode: int, stdout: str, stderr: str
) -> bool:
    if not _is_pytest_cmd(cmd):
        return False
    output = f"{stdout}\n{stderr}".lower()
    return returncode == 5 or "0 selected" in output or "no tests ran" in output


def _fix_failure_archive_path(phase_id: int, fixes: list) -> Path:
    issue_ids = [
        re.sub(r"[^A-Za-z0-9_.-]+", "_", str(fix.get("id", "unknown"))) for fix in fixes
    ] or ["unknown"]
    attempts = []
    for fix in fixes:
        value = fix.get("attempts")
        if isinstance(value, int):
            attempts.append(value)
    attempt = max(attempts, default=0)
    issue_part = "_".join(issue_ids[:5])
    return Path(
        f"workspace/fix-test-failures/phase_{phase_id}_issues_{issue_part}_attempt_{attempt}.log"
    )


def _write_fix_test_failure_log(
    cmd: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    *,
    phase_id: int | None = None,
    fixes: list | None = None,
    failure_kind: str = "test_failed",
    call_id: str | None = None,
) -> None:
    content = "\n".join(
        [
            "FIX test command failed",
            f"cmd: {' '.join(cmd)}",
            f"returncode: {returncode}",
            f"failure_kind: {failure_kind}",
            f"call_id: {call_id or ''}",
            "",
            "stdout tail:",
            stdout[-2000:],
            "",
            "stderr tail:",
            stderr[-2000:],
        ]
    )
    FIX_TEST_FAILURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIX_TEST_FAILURE_LOG_PATH.write_text(content, encoding="utf-8")
    if phase_id is not None and fixes is not None:
        archive_path = _fix_failure_archive_path(phase_id, fixes)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(content, encoding="utf-8")


def _harness_blocker_result(
    *,
    failed_tasks: list | None = None,
    open_fixes: list | None = None,
    reason: str,
    failure_kind: str,
    commands: list[list[str]] | None = None,
    stdout_tail: str = "",
    stderr_tail: str = "",
    failure_artifact: str | None = None,
) -> VerificationResult:
    return VerificationResult(
        failed_tasks=failed_tasks or [],
        open_fixes=open_fixes or [],
        commit_ok=False,
        compile_ok=False,
        tests_ok=False,
        commands=commands or [],
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        failure_kind=failure_kind,
        harness_blocker=True,
        blocker_reason=reason,
        failure_artifact=failure_artifact,
    )


def verify_execution(
    harness: Harness,
    pre_sha: str,
    batch: list,
    signal: dict,
    pre_snapshot: set[str] | None = None,
    call_id: str | None = None,
) -> VerificationResult:
    """Return list of failed task signals (empty = all passed)."""
    phase_id = _phase_id_from_batch(batch)
    profile = harness.profile_for(phase_id)
    verification_profiles = _verification_profiles(harness, phase_id)
    phase_type = harness.phase_type_for(phase_id)
    is_setup_phase = phase_type == "setup"

    # unit_test tasks only run tests and write no code — skip the commit check.
    all_unit_test = bool(batch) and all(t.get("tdd_mode") == "unit_test" for t in batch)
    all_exempt = bool(batch) and all(t.get("tdd_mode") == "exempt" for t in batch)
    all_implementation = bool(batch) and all(
        t.get("tdd_mode") == "implementation"
        for t in batch
        if t.get("status") != "failed"
    )
    all_test_first = bool(batch) and all(
        t.get("tdd_mode") == "test_first" for t in batch if t.get("status") != "failed"
    )
    already_satisfied_noop_files: list[str] = []

    _sha_run = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if _sha_run.returncode != 0:
        logger.error("git rev-parse HEAD failed: %s", _sha_run.stderr[:200].strip())
        failures = [
            {"id": t["id"], "status": "failed", "reason": "git rev-parse HEAD failed"}
            for t in batch
        ]
        return VerificationResult(failed_tasks=failures, commit_ok=False)
    current_sha = _sha_run.stdout.strip()

    if all_unit_test and current_sha == pre_sha:
        dirty_support_files = changed_files_since_snapshot(pre_snapshot)
        if dirty_support_files:
            disallowed = [
                f for f in dirty_support_files if not _allowed_unit_test_support_file(f)
            ]
            if disallowed:
                failures = [
                    {
                        **t,
                        "status": "failed",
                        "reason": "unit_test task changed non-support files: "
                        + ", ".join(disallowed[:5]),
                    }
                    for t in batch
                ]
                return VerificationResult(failed_tasks=failures, commit_ok=False)
            commit_files(
                dirty_support_files,
                f"chore(phase-{phase_id}): update test verification support",
            )
            _fallback_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip()
            if _fallback_sha != pre_sha:
                current_sha = _fallback_sha
            else:
                failures = [
                    {
                        **t,
                        "status": "failed",
                        "reason": "unit_test support files changed but no commit was created",
                    }
                    for t in batch
                ]
                return VerificationResult(failed_tasks=failures, commit_ok=False)

    if not all_unit_test and current_sha == pre_sha:
        # Hook didn't commit — try to commit the files from the signal directly
        # before falling back to a full Claude retry.
        signal_files = [
            f
            for task_sig in signal.get("tasks", [])
            if task_sig.get("status") == "complete"
            for f in task_sig.get("files_changed", [])
        ]
        completed_signals = [
            t for t in signal.get("tasks", []) if t.get("status") == "complete"
        ]
        _hook_files = (
            safe_changed_signal_files(
                pre_snapshot,
                signal_files,
                include_preexisting_signal_files=True,
            )
            if signal_files
            else []
        )
        for file_name in changed_files_since_snapshot(pre_snapshot):
            if file_name not in _hook_files:
                _hook_files.append(file_name)
        missing_claimed = [
            f
            for f in signal_files
            if f and _within_project_root(f) and not Path(f).exists()
        ]
        can_accept_existing_implementation = (
            all_implementation
            and signal_files
            and completed_signals
            and all(_already_satisfied_noop_note(t) for t in completed_signals)
        )
        if (
            can_accept_existing_implementation
            and not _hook_files
            and _signal_files_tracked_and_clean(signal_files)
            and not missing_claimed
        ):
            logger.info(
                "[VERIFY] Implementation task completed by existing tracked files; "
                "running normal verification without requiring a new commit."
            )
            already_satisfied_noop_files = signal_files
        else:
            can_accept_noop = (
                is_setup_phase or all_exempt or (all_test_first and signal_files)
            )
            if (
                can_accept_noop
                and completed_signals
                and not _hook_files
                and _signal_files_tracked_and_clean(signal_files)
                and not missing_claimed
            ):
                logger.info(
                    "[VERIFY] Exempt/setup task completed with no tracked changes; accepting as idempotent."
                )
                return VerificationResult(
                    commit_ok=True,
                    compile_ok=True,
                    tests_ok=True,
                    skipped_reason=(
                        "test_first_noop"
                        if all_test_first
                        else "exempt_noop"
                        if all_exempt
                        else "setup_noop"
                    ),
                )
            elif (
                not all_implementation
                and signal_files
                and completed_signals
                and not _hook_files
                and _signal_files_tracked_and_clean(signal_files)
                and not missing_claimed
            ):
                logger.info(
                    "[VERIFY] Signal files already tracked and clean from a prior attempt; "
                    "accepting without requiring a new commit."
                )
                already_satisfied_noop_files = signal_files
        if already_satisfied_noop_files:
            pass
        elif _hook_files:
            completed = [
                t for t in signal.get("tasks", []) if t.get("status") == "complete"
            ]
            completed_title = completed[0].get("title") or batch[0].get("title")
            _msg = (
                f"feat(phase-{phase_id}): {completed_title}"
                if len(completed) == 1
                else f"feat(phase-{phase_id}): implement {len(completed)} tasks"
            )
            commit_files(_hook_files, _msg)
            _fallback_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip()
        else:
            _fallback_sha = pre_sha
        if already_satisfied_noop_files:
            pass
        elif _fallback_sha != pre_sha:
            current_sha = _fallback_sha
            logger.info(
                "[VERIFY] Committed files for phase-%s via fallback: %s",
                phase_id,
                _hook_files,
            )
            if signal_files and not _signal_files_tracked_and_clean(signal_files):
                failures = [
                    {
                        **t,
                        "status": "failed",
                        "reason": "agent completed task but not all signal files were tracked and clean after fallback commit",
                    }
                    for t in batch
                ]
                return VerificationResult(failed_tasks=failures, commit_ok=False)
        else:
            reason = "agent completed task but created no commit"
            failures = [
                {
                    **t,
                    "status": "failed",
                    "reason": reason,
                }
                for t in batch
            ]
            return _harness_blocker_result(
                failed_tasks=failures,
                reason=reason,
                failure_kind="no_commit",
            )

    committed_files = _changed_files_in_commit(pre_sha, current_sha)
    if already_satisfied_noop_files:
        committed_files = already_satisfied_noop_files
    changed_files = [
        f
        for task_sig in signal.get("tasks", [])
        if task_sig.get("status") == "complete"
        for f in task_sig.get("files_changed", [])
    ]
    if not changed_files:
        changed_files = committed_files

    failed_tasks = []
    artifact_failures = _artifact_quality_failures(changed_files)
    if artifact_failures:
        return VerificationResult(
            failed_tasks=_failed_signals_for_artifacts(signal, artifact_failures),
            commit_ok=True,
            compile_ok=False,
            tests_ok=False,
        )
    test_size_failures = _test_file_size_failures(harness.config, changed_files)
    if test_size_failures:
        return VerificationResult(
            failed_tasks=_failed_signals_for_artifacts(signal, test_size_failures),
            commit_ok=True,
            compile_ok=False,
            tests_ok=False,
        )

    if all_test_first:
        return VerificationResult(
            commit_ok=True,
            compile_ok=True,
            tests_ok=True,
            skipped_reason="test_first",
            commit_sha=current_sha if pre_sha and current_sha != pre_sha else None,
            committed_files=committed_files,
        )

    for f in changed_files:
        compile_profile = _compile_profile_for_file(verification_profiles, profile, f)
        if not any(
            fnmatch.fnmatch(f, ext) for ext in compile_profile["compile_extensions"]
        ):
            continue
        if not Path(f).exists():
            continue
        if not _within_project_root(f):
            logger.warning(
                "Skipping compile check for path outside project root: %r", f
            )
            continue
        cmd = [part.replace("{file}", f) for part in compile_profile["compile_cmd"]]
        run_cmd, result = _run_command(cmd, **_verification_cmd_kwargs(harness))
        emit_event(
            "verify_command",
            kind="compile",
            call_id=call_id,
            cmd=run_cmd,
            returncode=result.returncode,
        )
        if result.returncode != 0:
            for task_sig in signal.get("tasks", []):
                if (
                    f in task_sig.get("files_changed", [])
                    and task_sig not in failed_tasks
                ):
                    failed_tasks.append(
                        {
                            **task_sig,
                            "status": "failed",
                            "reason": f"compile error in {f}: {result.stderr[:500].strip()[:200]}",
                        }
                    )

    # For test_first tasks the tests are intentionally failing — skip the run.
    # The next implementation task will make them pass.
    # Empty batch must not vacuously skip the test run.
    skipped_reason = "test_first" if all_test_first else None
    preflight_reported = False

    if not failed_tasks and not all_test_first:
        if all_exempt:
            return VerificationResult(
                failed_tasks=failed_tasks,
                commit_ok=True,
                compile_ok=True,
                tests_ok=True,
                skipped_reason="exempt_task",
                commit_sha=current_sha if pre_sha and current_sha != pre_sha else None,
                committed_files=committed_files,
            )
        if is_setup_phase:
            return VerificationResult(
                failed_tasks=failed_tasks,
                commit_ok=True,
                compile_ok=True,
                tests_ok=True,
                skipped_reason="setup_phase",
                commit_sha=current_sha if pre_sha and current_sha != pre_sha else None,
                committed_files=committed_files,
            )
        run_test_cmds: list[list[str]] = []
        stdout_tail = ""
        stderr_tail = ""
        for test_cmd in _select_test_cmds(harness, phase_id, phase_type):
            test_cmd = _prepare_verification_cmd(test_cmd)
            run_test_cmd, test_result = _run_command(
                test_cmd,
                **_verification_cmd_kwargs(harness),
            )
            run_test_cmds.append(run_test_cmd)
            emit_event(
                "verify_command",
                kind="test",
                call_id=call_id,
                cmd=run_test_cmd,
                returncode=test_result.returncode,
            )
            if test_result.returncode != 0:
                stdout_tail = test_result.stdout[-500:]
                stderr_tail = test_result.stderr[-500:]
                if _is_expected_preflight_report(
                    batch, test_result.stdout, test_result.stderr
                ):
                    logger.warning(
                        "[VERIFY] Browser preflight reported a missing external dependency."
                    )
                    preflight_reported = True
                    continue
                for task_sig in signal.get("tasks", []):
                    if task_sig.get("status") == "complete":
                        failed_tasks.append(
                            {
                                **task_sig,
                                "status": "failed",
                                "reason": f"{test_cmd[0]} failed: {test_result.stdout[-2000:].strip()[-300:]}",
                            }
                        )
                break

        _cleanup_verification_artifacts(pre_snapshot=pre_snapshot)

        if failed_tasks:
            return VerificationResult(
                failed_tasks=failed_tasks,
                commit_ok=True,
                compile_ok=True,
                tests_ok=False,
                commands=run_test_cmds,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

    if preflight_reported:
        skipped_reason = "preflight_external_dependency_reported"
    elif already_satisfied_noop_files:
        skipped_reason = "already_satisfied_noop"
    elif all_unit_test:
        skipped_reason = "unit_test_no_commit"
    return VerificationResult(
        failed_tasks=failed_tasks,
        commit_ok=True,
        compile_ok=not failed_tasks,
        tests_ok=not failed_tasks,
        skipped_reason=skipped_reason,
        commit_sha=current_sha if pre_sha and current_sha != pre_sha else None,
        committed_files=committed_files,
    )


def verify_fix(
    harness: Harness,
    state: dict,
    fixes: list,
    phase_id: int,
    pre_sha: str = "",
    pre_snapshot: set[str] | None = None,
    call_id: str | None = None,
) -> VerificationResult:
    """Run tests; update state for confirmed fixes. Returns list of still-open fix signals."""
    profile = harness.profile_for(phase_id)
    phase_type = harness.phase_type_for(phase_id)

    _sha_run = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if _sha_run.returncode != 0:
        logger.error("git rev-parse HEAD failed: %s", _sha_run.stderr[:200].strip())
        return VerificationResult(open_fixes=fixes, commit_ok=False)
    current_sha = _sha_run.stdout.strip()

    run_test_cmds: list[list[str]] = []
    stdout_tail = ""
    stderr_tail = ""
    test_passed = True
    passed_test_count = 0
    skipped_test_count = 0
    failure_artifact = None
    for test_cmd in _select_test_cmds(harness, phase_id, phase_type):
        test_cmd = _prepare_verification_cmd(test_cmd)
        run_test_cmd, test_result = _run_command(
            test_cmd,
            **_verification_cmd_kwargs(harness),
        )
        run_test_cmds.append(run_test_cmd)
        emit_event(
            "verify_command",
            kind="fix_test",
            call_id=call_id,
            cmd=run_test_cmd,
            returncode=test_result.returncode,
        )
        if test_result.returncode != 0:
            if _is_no_tests_selected(
                run_test_cmd,
                test_result.returncode,
                test_result.stdout,
                test_result.stderr,
            ):
                stdout_tail = test_result.stdout[-500:]
                stderr_tail = test_result.stderr[-500:]
                skipped_test_count += 1
                emit_event(
                    "verify_command_skipped",
                    kind="fix_test",
                    call_id=call_id,
                    cmd=run_test_cmd,
                    reason="no_tests_selected",
                )
                continue
            test_passed = False
            stdout_tail = test_result.stdout[-500:]
            stderr_tail = test_result.stderr[-500:]
            _write_fix_test_failure_log(
                run_test_cmd,
                test_result.returncode,
                test_result.stdout,
                test_result.stderr,
                phase_id=phase_id,
                fixes=fixes,
                failure_kind="test_failed",
                call_id=call_id,
            )
            failure_artifact = str(FIX_TEST_FAILURE_LOG_PATH)
            break
        passed_test_count += 1

    _cleanup_verification_artifacts(pre_snapshot=pre_snapshot)

    if test_passed and skipped_test_count and passed_test_count == 0:
        reason = "no applicable verification command: all fix test commands selected no tests"
        _write_fix_test_failure_log(
            run_test_cmds[-1] if run_test_cmds else [],
            5,
            stdout_tail,
            stderr_tail,
            phase_id=phase_id,
            fixes=fixes,
            failure_kind="no_applicable_verification",
            call_id=call_id,
        )
        return _harness_blocker_result(
            open_fixes=[{**fix, "reason": reason} for fix in fixes],
            reason=reason,
            failure_kind="no_applicable_verification",
            commands=run_test_cmds,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            failure_artifact=str(FIX_TEST_FAILURE_LOG_PATH),
        )

    if test_passed and pre_sha and current_sha == pre_sha:
        fix_signal_files = [
            f
            for fix in fixes
            if fix.get("status") == "fixed"
            for f in fix.get("files_changed", [])
        ]
        hook_files = (
            safe_changed_signal_files(
                pre_snapshot,
                fix_signal_files,
                include_preexisting_signal_files=True,
            )
            if fix_signal_files
            else []
        )
        if hook_files:
            commit_files(
                hook_files,
                f"fix(phase-{phase_id}): resolve review issues",
            )
            current_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip()

    diff_files: set[str] = set()
    if pre_sha and pre_sha != current_sha:
        diff_out = subprocess.run(
            ["git", "diff", "--name-only", f"{pre_sha}..HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        diff_files = (
            {_normalize_diff_path(f) for f in diff_out.splitlines()}
            if diff_out
            else set()
        )
    artifact_failures = _artifact_quality_failures(
        [
            f
            for fix in fixes
            if fix.get("status") == "fixed"
            for f in fix.get("files_changed", [])
        ]
    )

    open_fixes = []
    for fix in fixes:
        if fix["status"] == "fixed" and test_passed:
            if artifact_failures:
                open_fixes.append(
                    {
                        **fix,
                        "reason": "artifact quality failed: "
                        + "; ".join(artifact_failures[:3]),
                    }
                )
                continue
            if fix.get("verification_note"):
                logger.info(
                    "[VERIFY] Fix %s note: %s", fix["id"], fix["verification_note"]
                )
            if pre_sha and current_sha == pre_sha:
                reason = "claimed fixed but no commit was created"
                logger.warning(
                    "[VERIFY] Fix %s claims 'fixed' but HEAD is unchanged from %s — treating as failed.",
                    fix["id"],
                    pre_sha,
                )
                return _harness_blocker_result(
                    open_fixes=[{**fix, "reason": reason}],
                    reason=reason,
                    failure_kind="fixed_without_commit",
                    commands=run_test_cmds,
                )
            if pre_sha and pre_sha != current_sha and not diff_files:
                reason = "claimed fixed but no files changed in git"
                logger.warning(
                    "[VERIFY] Fix %s claims 'fixed' but git diff %s..HEAD is empty — treating as failed.",
                    fix["id"],
                    pre_sha,
                )
                return _harness_blocker_result(
                    open_fixes=[{**fix, "reason": reason}],
                    reason=reason,
                    failure_kind="fixed_without_diff",
                    commands=run_test_cmds,
                )
            fix_files = {
                _normalize_diff_path(f) for f in fix.get("files_changed", []) if f
            }
            if (
                pre_sha
                and pre_sha != current_sha
                and fix_files
                and not (fix_files & diff_files)
            ):
                logger.warning(
                    "[VERIFY] Fix %s claims files %r were changed but none appear in git diff %s..HEAD (actual diff: %r) — rejecting.",
                    fix["id"],
                    sorted(fix_files),
                    pre_sha,
                    sorted(diff_files),
                )
                reason = (
                    f"claimed files {sorted(fix_files)} not found in git diff "
                    f"{pre_sha}..HEAD"
                )
                return _harness_blocker_result(
                    open_fixes=[{**fix, "reason": reason}],
                    reason=reason,
                    failure_kind="fixed_files_not_in_diff",
                    commands=run_test_cmds,
                )
            update_state(
                state,
                phase_id=phase_id,
                issue_id=fix["id"],
                status="fixed",
                files_changed=fix.get("files_changed", []),
                fixed_sha=current_sha,
            )
            _remove_from_review_report(fix["id"])
        elif fix["status"] == "deferred":
            update_state(
                state, phase_id=phase_id, issue_id=fix["id"], status="deferred"
            )
        elif fix["status"] == "fixed" and not test_passed:
            open_fixes.append(
                {
                    **fix,
                    "reason": f"fix tests failed; see {FIX_TEST_FAILURE_LOG_PATH}",
                }
            )
        else:
            open_fixes.append(fix)

    return VerificationResult(
        open_fixes=open_fixes,
        tests_ok=test_passed,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        commands=run_test_cmds,
        failure_artifact=failure_artifact,
    )


def _remove_from_review_report(issue_id: str) -> None:
    if not REVIEW_REPORT_PATH.exists():
        return
    content = REVIEW_REPORT_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?:^|\n)(?:#{1,3}\s+)?"
        + re.escape(issue_id)
        + r"(?![\d.])[^\n]*(?:\n(?!#{1,3}\s+\d+\.).*)*",
        re.MULTILINE,
    )
    updated = pattern.sub("", content).strip()
    REVIEW_REPORT_PATH.write_text(updated + ("\n" if updated else ""), encoding="utf-8")
