import json
import logging
import os
import re
import shlex
import subprocess
import time
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import external_dependency
from calibrate import claude_session_pacing_delay, get_external_dependency_config
from events import emit_event
from git_changes import capture_status_snapshot
from state import error_phase
from subprocess_runner import RunnerTimeout, run_claude_process
from timeout_policy import compute_timeout

_JSON_SIGNAL_SUFFIX = (
    "\nYour entire response must be a single valid JSON object. "
    "No prose, no explanation, no markdown. Only JSON."
)

_INTEGRATION_GUIDE = ".claude/rules/common/integration-testing-guide.md"
_SAFE_GIT_REF_RE = re.compile(r"^(?:HEAD|[0-9a-fA-F]{7,40})$")
_RESET_RE = re.compile(
    r"resets?\s+(\d{1,2}:\d{2}\s*(?:am|pm))\s*\(([^)]+)\)",
    re.IGNORECASE,
)
_MAX_EXTERNAL_DEPENDENCY_WAIT_SECONDS = 6 * 60 * 60
_TEXT_ARTIFACT_INSTRUCTION = (
    "Write text artifacts as UTF-8 without BOM; do not create UTF-16 or NUL-byte "
    "text files."
)
_EXISTING_TRACKED_NOOP_INSTRUCTION = (
    "If the task is already satisfied by existing tracked files, do not return an "
    "empty no-op signal. Return status complete, list those existing tracked files "
    "in files_changed, and set tdd_skipped to explain that the task is already "
    "satisfied by existing tracked files."
)


class SubprocessError(Exception):
    pass


class ExternalDependencyError(SubprocessError):
    pass


class TimeoutError(SubprocessError):
    pass


def build_file_lists(profile: dict) -> tuple[list, list]:
    common = [profile["common_rules"], profile["rules_file"]]
    builder_files = (
        [profile["builder_agent"]]
        + common
        + [profile["builder_guide"], profile["builder_skill"]]
    )
    reviewer_files = (
        [profile["reviewer_agent"]]
        + common
        + [profile["reviewer_guide"], profile["reviewer_skill"]]
    )
    return builder_files, reviewer_files


def file_preamble(paths: list[str]) -> str:
    lines = ["Read these files before starting (use your Read tool, in order):"]
    lines += [f"- {p}" for p in paths]
    return "\n".join(lines)


def extract_signal(raw: str) -> dict:
    stripped = re.sub(
        r"^```json\s*|^```\s*|```$", "", raw.strip(), flags=re.MULTILINE
    ).strip()
    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    if start == -1:
        raise ValueError(f"No JSON found in agent output: {raw[:200]!r}")
    depth = 0
    for i, ch in enumerate(stripped[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start : i + 1])
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"JSON extraction failed: {e} — raw: {raw[:200]!r}"
                    ) from e
    raise ValueError(f"No complete JSON object found in agent output: {raw[:200]!r}")


def _safe_git_ref(ref: str) -> str:
    if not _SAFE_GIT_REF_RE.fullmatch(ref):
        raise ValueError(f"Unsafe git ref for review diff: {ref!r}")
    return ref


def _safe_exclude_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    if (
        not normalized
        or normalized.startswith("../")
        or "/../" in normalized
        or any(c in normalized for c in "`$;&|<>")
    ):
        raise ValueError(f"Unsafe review exclude path: {path!r}")
    return normalized


def _external_dependency_retry_delay(
    detail: str,
    *,
    now: datetime | None = None,
    max_wait_seconds: int = _MAX_EXTERNAL_DEPENDENCY_WAIT_SECONDS,
) -> float | None:
    match = _RESET_RE.search(detail or "")
    if not match:
        return None
    reset_text, tz_name = match.groups()
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return None
    current = now.astimezone(zone) if now else datetime.now(zone)
    try:
        reset_clock = datetime.strptime(
            reset_text.replace(" ", "").upper(), "%I:%M%p"
        ).time()
    except ValueError:
        return None
    reset_at = datetime.combine(current.date(), reset_clock, tzinfo=zone)
    wait_seconds = (reset_at - current).total_seconds()
    if wait_seconds <= 0:
        reset_at = reset_at + timedelta(days=1)
        wait_seconds = (reset_at - current).total_seconds()
    if wait_seconds <= 0 or wait_seconds > max_wait_seconds:
        return None
    return wait_seconds


def _process_output_tail(value: str) -> str:
    text = (value or "").strip()
    return text[-500:] if text else "<empty>"


def call_claude(
    prompt: str,
    model: str,
    mode: str,
    config: dict,
    tools: str = "Read,Write,Edit,Bash,Grep,Glob",
    settings_file: str | None = None,
    timeout: int | None = None,
) -> dict:
    call_id = f"{mode.lower()}-{uuid.uuid4().hex[:12]}"
    timeout = int(timeout or config["subprocess_timeout"][mode])
    cmd = [
        "claude",
        "--print",
        "--model",
        model,
        "--output-format",
        "json",
        "--allowedTools",
        tools,
    ]
    if settings_file:
        cmd += ["--settings", settings_file]
    _run_kwargs = {
        "input": prompt,
        "text": True,
        "capture_output": True,
        "timeout": timeout,
        "env": {
            **os.environ,
            "HARNESS_MODE": "1",
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": str(config.get("autocompact_pct", 80)),
        },
    }
    pacing = claude_session_pacing_delay(config)
    if pacing is not None:
        delay, reason = pacing
        emit_event(
            "session_pacing_wait_start",
            mode=mode,
            call_id=call_id,
            seconds=delay,
            reason=reason,
        )
        time.sleep(delay)
        emit_event("session_pacing_wait_end", mode=mode, call_id=call_id, reason=reason)
    waited_for_external_dependency = False
    while True:
        pre_git_snapshot = capture_status_snapshot()
        try:
            result = run_claude_process(
                cmd,
                prompt,
                mode,
                timeout,
                env=_run_kwargs["env"],
                call_id=call_id,
            )
        except RunnerTimeout:
            print(f"[WARN] {mode} timeout after {timeout}s — retrying once")
            try:
                result = run_claude_process(
                    cmd,
                    prompt,
                    mode,
                    timeout,
                    env=_run_kwargs["env"],
                    call_id=call_id,
                )
            except RunnerTimeout as e:
                emit_event(
                    "claude_subprocess_failed",
                    mode=mode,
                    call_id=call_id,
                    reason=str(e),
                )
                raise TimeoutError(
                    f"timeout after {timeout}s ({mode} mode) — "
                    "increase subprocess_timeout in harness/config.json or split the task"
                ) from e

        for line in result.stderr.splitlines():
            if "[WARN]" in line:
                print(line)

        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            if result.returncode != 0:
                stdout_tail = _process_output_tail(result.stdout)
                stderr_tail = _process_output_tail(result.stderr)
                emit_event(
                    "claude_subprocess_failed",
                    mode=mode,
                    call_id=call_id,
                    pid=result.pid,
                    returncode=result.returncode,
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    reason="nonzero exit with unparseable CLI envelope",
                )
                raise SubprocessError(
                    f"claude pid {result.pid} exited with code {result.returncode}: "
                    f"stdout_tail={stdout_tail}; stderr_tail={stderr_tail}"
                )
            raise SubprocessError(
                f"unparseable CLI envelope: {e} — stdout: {result.stdout[:300]}"
            )

        if result.returncode != 0 or envelope.get("is_error"):
            detail = (
                envelope.get("result")
                or envelope.get("error")
                or result.stderr
                or result.stdout
                or ""
            )
            status = envelope.get("api_error_status")
            prefix = (
                f"claude API error {status}"
                if status
                else f"claude exited with code {result.returncode}"
            )
            if status == 429 and not waited_for_external_dependency:
                retry_delay = _external_dependency_retry_delay(str(detail))
                if retry_delay is not None:
                    waited_for_external_dependency = True
                    context = external_dependency.start_context(
                        mode=mode,
                        root_pid=result.pid,
                        pre_git_snapshot=pre_git_snapshot,
                        retry_delay=retry_delay,
                    )
                    context = external_dependency.cleanup_before_wait(context)
                    cleanup = context.get("process_cleanup", {})
                    if context.get("cleanup_status") != "clean":
                        raise ExternalDependencyError(
                            f"{prefix}: environment cleanup before retry failed "
                            f"(tracked_dirty={context.get('tracked_dirty_files', [])}, "
                            f"quarantine_errors={context.get('quarantine_errors', [])}, "
                            f"process_error={cleanup.get('error', '')})"
                        )
                    max_wait = get_external_dependency_config(config)[
                        "max_in_process_wait_seconds"
                    ]
                    event_name = (
                        "external_dependency_wait_deferred"
                        if retry_delay > max_wait
                        else "external_dependency_wait_start"
                    )
                    emit_event(
                        event_name,
                        mode=mode,
                        call_id=call_id,
                        seconds=retry_delay,
                        max_in_process_wait_seconds=max_wait,
                        reset_at=context.get("reset_at"),
                        quarantined_files_count=len(
                            context.get("quarantined_files", [])
                        ),
                        process_cleanup_attempted=cleanup.get("attempted", False),
                        processes_terminated=len(cleanup.get("terminated_pids", [])),
                        process_cleanup_error=cleanup.get("error", ""),
                    )
                    if retry_delay > max_wait:
                        raise ExternalDependencyError(
                            f"{prefix}: retry delay {retry_delay:.0f}s exceeds "
                            f"in-process wait limit {max_wait}s; resume after "
                            f"{context.get('reset_at') or 'the reset window'}"
                        )
                    time.sleep(retry_delay)
                    preflight = external_dependency.preflight_context(
                        allow_quarantine=False
                    )
                    if not preflight.get("ok"):
                        raise ExternalDependencyError(
                            f"{prefix}: environment preflight after wait failed "
                            f"(tracked_dirty={preflight.get('tracked_dirty_files', [])}, "
                            f"untracked={preflight.get('untracked_files', [])}, "
                            f"process_error={preflight.get('process_cleanup', {}).get('error', '')})"
                        )
                    emit_event(
                        "external_dependency_wait_end", mode=mode, call_id=call_id
                    )
                    continue
            exc_type = ExternalDependencyError if status == 429 else SubprocessError
            raise exc_type(f"{prefix}: {str(detail)[:300]}")

        break

    try:
        signal = extract_signal(envelope["result"])
    except (KeyError, ValueError) as e:
        raise SubprocessError(f"could not extract signal from envelope: {e}")

    return {"signal": signal, "usage": envelope.get("usage", {}), "call_id": call_id}


def build_tasks(
    phase: dict,
    context: str,
    profile: dict,
    config: dict,
    state: dict,
    spec_context: str = "",
    completed_work_context: str = "",
) -> dict:
    builder_files, _ = build_file_lists(profile)
    if phase.get("phase_type") in ("integration", "e2e"):
        builder_files.append(_INTEGRATION_GUIDE)
    phase_text = (
        f"Phase {phase['id']}: {phase['title']}\n{phase.get('description', '')}"
    )
    if spec_context:
        phase_text += f"\n\nSpec context:\n{spec_context}"
    if context:
        phase_text += f"\n\nAdditional context:\n{context}"
    if completed_work_context:
        phase_text += (
            f"\n\nCompleted work to avoid duplicating:\n{completed_work_context}"
        )
    prompt = (
        file_preamble(builder_files) + f"\nMODE=TASK_BUILD. Phase: {phase_text}. "
        "Respond with JSON only — your entire response is the task list signal."
        + _JSON_SIGNAL_SUFFIX
    )
    result = call_claude(
        prompt,
        model=profile["build_model"],
        mode="TASK_BUILD",
        config=config,
        settings_file=profile.get("builder_settings", ".claude/settings.builder.json"),
    )
    signal = result["signal"]
    status = signal.get("status")
    # Normalise status aliases produced by correction turns.
    if status in ("ready", "task_list_created"):
        logger.warning(
            "[TASK_BUILD] Signal status %r normalised to 'complete'.", status
        )
        signal["status"] = "complete"
        status = "complete"
    tasks = signal.get("tasks")
    if status != "complete" or not isinstance(tasks, list) or not tasks:
        task_detail = "missing" if "tasks" not in signal else type(tasks).__name__
        if isinstance(tasks, list):
            task_detail = f"list[{len(tasks)}]"
        error_phase(
            state,
            phase["id"],
            f"TASK_BUILD signal invalid: status={status!r}, tasks={task_detail}",
        )
    return result


def execute(
    tasks: list,
    phase_id: int,
    profile: dict,
    config: dict,
    failure_history: dict | None = None,
    phase_type: str = "development",
    spec_context: str = "",
) -> dict:
    builder_files, _ = build_file_lists(profile)
    if phase_type in ("integration", "e2e"):
        builder_files.append(_INTEGRATION_GUIDE)
    task = tasks[0]
    history_block = ""
    if failure_history and task["id"] in failure_history:
        all_reasons = failure_history[task["id"]]
        reasons = all_reasons[-3:]
        omitted = len(all_reasons) - len(reasons)
        offset = omitted + 1
        lines = "\n".join(f"- Attempt {offset + i}: {r}" for i, r in enumerate(reasons))
        prefix = f"({omitted} earlier attempts omitted)\n" if omitted else ""
        history_block = f"\nPrior attempts:\n{prefix}{lines}"
    task_line = f"Task {task['id']}: {task['title']}."
    if phase_type in ("integration", "e2e"):
        task_line += (
            "\nFor this integration/e2e phase, consider frontend, backend, "
            "and browser acceptance behavior together."
        )
    if task.get("description"):
        task_line += f"\n{task['description']}"
    if task.get("refs"):
        task_line += f"\nAlso read before starting: {', '.join(task['refs'])}"
    if spec_context:
        task_line += f"\n\nSpec context:\n{spec_context}"
    task_line += history_block
    prompt = (
        file_preamble(builder_files)
        + f"\nMODE=EXECUTE. Phase {phase_id}. "
        + task_line
        + " "
        + _TEXT_ARTIFACT_INSTRUCTION
        + " "
        + _EXISTING_TRACKED_NOOP_INSTRUCTION
        + f' Your JSON signal must include "phase_id": {phase_id} (integer, not null).'
        + f' Your JSON signal tasks array must contain an entry with "id": "{task["id"]}".'
        + _JSON_SIGNAL_SUFFIX
    )
    timeout = compute_timeout(
        "EXECUTE",
        config,
        phase_task_count=1,
        tdd_mode=task.get("tdd_mode"),
    )
    return call_claude(
        prompt,
        model=profile["execute_model"],
        mode="EXECUTE",
        config=config,
        settings_file=profile.get("builder_settings", ".claude/settings.builder.json"),
        timeout=timeout,
    )


def review_phase(
    phase_id: int,
    base_sha: str,
    spec_paths: list,
    profile: dict,
    config: dict,
    phase_task_count: int = 0,
    spec_context: str = "",
) -> dict:
    _, reviewer_files = build_file_lists(profile)
    spec_list = ", ".join(spec_paths)
    exclude_paths = profile.get("review_exclude_paths", [])
    safe_base_sha = _safe_git_ref(base_sha)
    if exclude_paths:
        safe_excludes = [_safe_exclude_path(p) for p in exclude_paths]
        diff_args = ["git", "diff", f"{safe_base_sha}..HEAD", "--", "."] + [
            f":(exclude){p}" for p in safe_excludes
        ]
    else:
        diff_args = ["git", "diff", f"{safe_base_sha}..HEAD"]
    diff_cmd = " ".join(shlex.quote(arg) for arg in diff_args)
    changed_file_count, diff_line_count = _diff_stats(diff_args)
    timeout = compute_timeout(
        "REVIEW",
        config,
        phase_task_count=phase_task_count,
        changed_file_count=changed_file_count,
        diff_line_count=diff_line_count,
    )
    emit_event(
        "timeout_policy",
        mode="REVIEW",
        timeout=timeout,
        phase_task_count=phase_task_count,
        changed_file_count=changed_file_count,
        diff_line_count=diff_line_count,
    )
    prompt = (
        file_preamble(reviewer_files)
        + f"\nMODE=REVIEW. Phase {phase_id}. Spec files: {spec_list}. "
        + (f"Spec context:\n{spec_context}\n" if spec_context else "")
        + f"Base SHA for diff: {safe_base_sha}. "
        f"Run `{diff_cmd}` to scope your review. "
        "Also run `git status --short` and check phase-relevant untracked files. "
        "Write findings to workspace/review_report.md. Respond with JSON only."
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt,
        model=profile["execute_model"],
        mode="REVIEW",
        config=config,
        settings_file=profile.get(
            "reviewer_settings", ".claude/settings.reviewer.json"
        ),
        timeout=timeout,
    )


def review_fix(
    phase_id: int,
    issue_ids: list[str],
    base_sha: str,
    head_sha: str,
    spec_paths: list,
    profile: dict,
    config: dict,
    spec_context: str = "",
) -> dict:
    _, reviewer_files = build_file_lists(profile)
    safe_base_sha = _safe_git_ref(base_sha)
    safe_head_sha = _safe_git_ref(head_sha)
    ids = ", ".join(issue_ids)
    spec_list = ", ".join(spec_paths)
    exclude_paths = profile.get("review_exclude_paths", [])
    if exclude_paths:
        safe_excludes = [_safe_exclude_path(p) for p in exclude_paths]
        diff_args = [
            "git",
            "diff",
            f"{safe_base_sha}..{safe_head_sha}",
            "--",
            ".",
        ] + [f":(exclude){p}" for p in safe_excludes]
    else:
        diff_args = ["git", "diff", f"{safe_base_sha}..{safe_head_sha}"]
    diff_cmd = " ".join(shlex.quote(arg) for arg in diff_args)
    prompt = (
        file_preamble(reviewer_files)
        + f"\nMODE=REVIEW. Targeted fix re-review for Phase {phase_id}. "
        f"Issue IDs: {ids}. Spec files: {spec_list}. "
        + (f"Spec context:\n{spec_context}\n" if spec_context else "")
        + f"Run `{diff_cmd}` and confirm the listed CRITICAL/HIGH issues are fixed. "
        "Also run `git status --short` and check fix-relevant untracked files. "
        "Write findings to workspace/review_report.md only if still blocking. Respond with JSON only."
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt,
        model=profile["execute_model"],
        mode="REVIEW",
        config=config,
        settings_file=profile.get(
            "reviewer_settings", ".claude/settings.reviewer.json"
        ),
    )


def _diff_stats(diff_args: list[str]) -> tuple[int, int]:
    name_args = ["git", "diff", "--name-only"] + diff_args[2:]
    diff_stat_args = ["git", "diff", "--numstat"] + diff_args[2:]
    names_out = _check_output_no_run(name_args)
    stats_out = _check_output_no_run(diff_stat_args)
    changed_file_count = len(names_out.splitlines())
    diff_line_count = 0
    for line in stats_out.splitlines():
        parts = line.split("\t")
        for part in parts[:2]:
            if part.isdigit():
                diff_line_count += int(part)
    return changed_file_count, diff_line_count


def _check_output_no_run(cmd: list[str]) -> str:
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        out, _ = proc.communicate(timeout=10)
        return out if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def evaluate(
    model: str,
    state: dict,
    iteration: int,
    spec_sections: str,
    config: dict,
) -> dict:
    app_type = state.get("evaluate", {}).get("app_type") or state.get("app_type", "cli")
    eval_phase_id = state.get("evaluate", {}).get(
        "phase_id", state.get("total_phases", 0) + 1
    )
    prompt = (
        "Read .claude/agents/evaluator.md before starting.\n"
        f"MODE=EVALUATE. Iteration {iteration}/3. Phase ID: {eval_phase_id}. App type: {app_type}.\n"
        f"Minimum score threshold: {config.get('evaluation_min_score_pct', 0):.0%}.\n"
        f"Spec sections:\n{spec_sections}\n"
        "State file: workspace/state.json\n"
        "Screenshots directory: workspace/screenshots/\n"
        "For game evaluation, rubric-report.md must include Spec Acceptance Checklist, "
        "Command Evidence, Code Quality Audit, and explicit webkit-ipad evidence; "
        "skipped WebKit-iPad checks do not count as verified.\n"
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt,
        model=model,
        mode="EVALUATE",
        config=config,
        tools="Read,Write,Bash,Grep,Glob",
        settings_file=".claude/settings.evaluator.json",
    )


def author_evaluate_tests(
    source_file: str,
    profiles: list[dict],
    config: dict,
    iteration: int,
    eval_phase_id: int,
    spec_context: str = "",
) -> dict:
    seen: set[str] = set()
    all_builder_files: list[str] = []
    for profile in profiles:
        builder_files, _ = build_file_lists(profile)
        for f in builder_files:
            if f not in seen:
                seen.add(f)
                all_builder_files.append(f)

    test_cmds: list[list[str]] = []
    seen_cmds: set[tuple] = set()
    for profile in profiles:
        cmd = tuple(profile.get("test_cmd", ["pytest"]))
        if cmd not in seen_cmds:
            seen_cmds.add(cmd)
            test_cmds.append(list(cmd))
    test_run_instruction = " and then ".join(f"`{' '.join(cmd)}`" for cmd in test_cmds)
    model = profiles[0]["execute_model"]
    prompt = (
        file_preamble(all_builder_files)
        + f"\nMODE=EVALUATE_TESTS. Phase ID: {eval_phase_id}. Iteration: {iteration}. "
        + f"Read all evaluation issues and test_cases from {source_file}. "
        + "Write only tests that reproduce those issues; do not modify application, source, config, docs, or harness files. "
        + "The authored tests should fail against the current code before the fix. "
        + (f"Spec context:\n{spec_context}\n" if spec_context else "")
        + f"Run focused targeted test commands for authored tests when possible; full regression is run by the harness later. Baseline commands are {test_run_instruction}. "
        + _TEXT_ARTIFACT_INSTRUCTION
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt,
        model=model,
        mode="EVALUATE_TESTS",
        config=config,
        settings_file=profiles[0].get(
            "builder_settings", ".claude/settings.builder.json"
        ),
    )


def fix_evaluate_issues(
    source_file: str,
    profiles: list[dict],
    config: dict,
    failure_history: dict | None = None,
    spec_context: str = "",
    red_evidence: dict | None = None,
) -> dict:
    seen: set[str] = set()
    all_builder_files: list[str] = []
    for profile in profiles:
        builder_files, _ = build_file_lists(profile)
        for f in builder_files:
            if f not in seen:
                seen.add(f)
                all_builder_files.append(f)

    test_cmds: list[list[str]] = []
    seen_cmds: set[tuple] = set()
    for profile in profiles:
        cmd = tuple(profile.get("test_cmd", ["pytest"]))
        if cmd not in seen_cmds:
            seen_cmds.add(cmd)
            test_cmds.append(list(cmd))

    test_run_instruction = " and then ".join(f"`{' '.join(cmd)}`" for cmd in test_cmds)
    model = profiles[0]["execute_model"]
    evidence_block = ""
    if red_evidence:
        evidence_block = (
            "\nTargeted test red-verification evidence from the harness:\n"
            + json.dumps(red_evidence, indent=2)
            + "\n"
        )

    prompt = (
        file_preamble(all_builder_files)
        + f"\nMODE=FIX. Read all open issues from {source_file}. Fix each in severity order. "
        + "For evaluation fixes, preserve every test authored for these issues; do not delete, skip, xfail, weaken assertions, or change expected behavior to make tests pass. "
        + evidence_block
        + (f"Spec context:\n{spec_context}\n" if spec_context else "")
        + f"Run the targeted tests first, then run {test_run_instruction} after all fixes. The harness will also run full regression before the next evaluation."
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt,
        model=model,
        mode="FIX",
        config=config,
        settings_file=".claude/settings.builder.json",
    )


def fix_issues(
    source_file: str,
    profile: dict,
    config: dict,
    failure_history: dict | None = None,
    phase_type: str = "development",
    spec_context: str = "",
    timeout: int | None = None,
) -> dict:
    builder_files, _ = build_file_lists(profile)
    history_block = ""
    if failure_history:
        lines = []
        for issue_id, all_reasons in failure_history.items():
            recent = all_reasons[-3:]
            omitted = len(all_reasons) - len(recent)
            offset = omitted + 1
            for i, r in enumerate(recent):
                lines.append(f"- Issue {issue_id} attempt {offset + i}: {r}")
            if omitted:
                lines.insert(
                    len(lines) - len(recent), f"  ({omitted} earlier attempts omitted)"
                )
        history_block = "\nPrior failed attempts:\n" + "\n".join(lines)

    if source_file.endswith(".jsonl"):
        read_instruction = (
            f"Read all open issues from {source_file} "
            "(newline-delimited JSON, one issue per line). "
            "Fix each MEDIUM issue first, then LOW, in file order."
        )
    else:
        read_instruction = (
            f"Read all open issues from {source_file}. Fix each in severity order."
        )

    if phase_type in ("integration", "e2e"):
        test_cmd = profile.get(
            "integration_test_cmd", profile.get("test_cmd", ["pytest"])
        )
    else:
        test_cmd = profile.get("test_cmd", ["pytest"])

    prompt = (
        file_preamble(builder_files)
        + f"\nMODE=FIX. {read_instruction}{history_block} "
        + (f"Spec context:\n{spec_context}\n" if spec_context else "")
        + _TEXT_ARTIFACT_INSTRUCTION
        + " If an issue has Dimension: Regression or source=regression, treat it as a HIGH severity phase advancement blocker. Do not delete, skip, or weaken regression tests to make the command pass; fix the product behavior or legitimate test integration problem."
        + " If the regression evidence clearly points to harness/environment infrastructure (for example .tmp, .pytest_cache, workspace/verification-tmp, pytest collection PermissionError, missing command, or timeout cleanup failure), do not modify product code; report the issue as open with a concise harness infra blocker reason."
        + " For e2e regression failures with browser-project-specific failures (e.g. [webkit-ipad] only),"
        " run `npx playwright test --project=webkit-ipad --reporter=list` first to get per-assertion"
        " failure details before diagnosing — this is 4x faster than the full suite and shows exact"
        " TimeoutError lines and assertion mismatches. Fix test timing constants (waitForTimeout,"
        " toBeVisible timeout, CLOSE_AFTER_TURN_IN_MS) in the failing spec files, then verify with"
        " `npx playwright test --project=webkit-ipad` before running the full suite."
        + f" Run `{' '.join(test_cmd)}` after all fixes. Respond with JSON only."
        + _JSON_SIGNAL_SUFFIX
    )
    return call_claude(
        prompt,
        model=profile["execute_model"],
        mode="FIX",
        config=config,
        settings_file=profile.get("builder_settings", ".claude/settings.builder.json"),
        timeout=timeout,
    )
