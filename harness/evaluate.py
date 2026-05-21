from __future__ import annotations

import logging
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import agents
from calibrate import (
    get_evaluation_min_score_pct,
    get_max_evaluate_iterations,
    log_usage,
)
from spec_context import build_evaluation_spec_context as extract_spec_sections
from state import (
    block_evaluate_external_dependency,
    error_evaluate,
    init_evaluate_state,
    save_state,
    start_evaluate_iteration,
    update_evaluate_iteration,
    update_evaluate_status,
)
from regression import collect_regression_commands
from subprocess_runner import run_command

if TYPE_CHECKING:
    from harness import Harness

logger = logging.getLogger(__name__)

EVALUATE_FIX_MD = Path("workspace/evaluate_fix.md")
RUBRIC_REPORT_MD = Path("workspace/rubric-report.md")


def run_evaluate_cycle(harness: Harness, state: dict) -> None:
    eval_phase_id = state["total_phases"] + 1
    init_evaluate_state(state, eval_phase_id)
    state["evaluate"]["app_type"] = _infer_evaluate_app_type(state)
    save_state(state)
    max_iterations = get_max_evaluate_iterations(harness.config)

    seen: set[str] = set()
    profiles: list[dict] = []
    for sp in state["phases"]:
        p = harness.profile_for(sp["id"])
        if p["name"] not in seen:
            seen.add(p["name"])
            profiles.append(p)

    spec_sections = extract_spec_sections(state["spec_file"])
    model = profiles[0]["execute_model"] if profiles else "claude-sonnet-4-6"

    iterations = state["evaluate"].get("iterations", [])
    completed_count = len(iterations)

    for iteration in range(1, max_iterations + 1):
        if iteration <= completed_count:
            saved = iterations[iteration - 1]
            if saved["verdict"] == "BLOCK" and saved["fix_sha"] is None:
                _run_evaluate_fix(harness, state, eval_phase_id, iteration, profiles)
                if saved["fix_sha"] is None:
                    return
            continue

        start_evaluate_iteration(state, iteration)
        try:
            result = agents.evaluate(model, state, iteration, spec_sections, harness.config)
        except agents.ExternalDependencyError as e:
            block_evaluate_external_dependency(state, str(e))
            return
        except agents.TimeoutError as e:
            error_evaluate(state, "timeout", str(e))
            return
        except agents.SubprocessError as e:
            error_evaluate(state, "error", str(e))
            return
        signal_iteration = result["signal"].get("iteration")
        if signal_iteration != iteration:
            report_marker = _rubric_report_contains_iteration(iteration)
            reason = (
                f"EVALUATE signal iteration={signal_iteration!r}, expected {iteration}; "
                f"rubric_report_has_iteration={report_marker}"
            )
            error_evaluate(state, "error", reason)
            return
        _normalize_evaluate_result(result, eval_phase_id, harness.config)
        _enforce_evaluation_report_gate(
            result, eval_phase_id, state["evaluate"]["app_type"], iteration
        )
        update_evaluate_iteration(state, result)
        log_usage(
            task_id=f"evaluate_{iteration}",
            phase_id=eval_phase_id,
            mode="EVALUATE",
            usage=result["usage"],
            files_changed=0,
            call_id=result.get("call_id"),
        )

        if result["signal"]["verdict"] == "BLOCK":
            _run_evaluate_fix(harness, state, eval_phase_id, iteration, profiles)
            current_iter = state["evaluate"]["iterations"][iteration - 1]
            if current_iter["fix_sha"] is None:
                return
        elif _should_early_stop(state, harness.config):
            update_evaluate_status(state, "complete")
            return

    final_verdict = state["evaluate"]["iterations"][-1]["verdict"]
    if final_verdict == "APPROVE":
        update_evaluate_status(state, "complete")
    else:
        update_evaluate_status(state, "halted")
        logger.error(
            "[HALT] Evaluate: final iteration BLOCK. Fix manually, then --resume."
        )
        sys.exit(1)


def _run_evaluate_fix(
    harness: Harness,
    state: dict,
    eval_phase_id: int,
    iteration: int,
    profiles: list[dict],
) -> None:
    _write_evaluate_fix_md(state, iteration)
    target_iter = state["evaluate"]["iterations"][iteration - 1]
    missing_contract = _issues_missing_test_contract(target_iter)
    if missing_contract:
        target_iter["last_fix_error"] = (
            "blocking evaluate issues missing test_cases: "
            + ", ".join(missing_contract)
        )
        update_evaluate_status(state, "halted")
        logger.error("[EVALUATE] %s", target_iter["last_fix_error"])
        sys.exit(1)

    if _requires_test_authoring(target_iter) and target_iter.get("test_status") != "red_verified":
        update_evaluate_status(state, "test_authoring")
        try:
            test_result = agents.author_evaluate_tests(
                str(EVALUATE_FIX_MD),
                profiles,
                harness.config,
                iteration,
                eval_phase_id,
                spec_context=extract_spec_sections(state["spec_file"]),
            )
        except agents.ExternalDependencyError as e:
            block_evaluate_external_dependency(state, str(e))
            return
        except agents.TimeoutError as e:
            error_evaluate(state, "timeout", str(e))
            return
        except agents.SubprocessError as e:
            error_evaluate(state, "error", str(e))
            return

        authored_tests = test_result["signal"].get("tests", [])
        target_iter["authored_tests"] = authored_tests
        log_usage(
            task_id=f"evaluate_{iteration}_tests",
            phase_id=eval_phase_id,
            mode="EVALUATE_TESTS",
            usage=test_result["usage"],
            files_changed=sum(
                len(t.get("files_changed", []))
                for t in authored_tests
                if t.get("status") == "authored"
            ),
            call_id=test_result.get("call_id"),
        )
        if not any(t.get("status") == "authored" for t in authored_tests):
            target_iter["test_attempts"] = target_iter.get("test_attempts", 0) + 1
            target_iter["last_test_error"] = "test authoring reported no authored tests"
            save_state(state)
            return

        update_evaluate_status(state, "red_verifying")
        red_evidence = _run_targeted_test_commands(
            _targeted_test_commands(target_iter, authored_tests)
        )
        target_iter["red_verification"] = red_evidence
        if not _all_commands_failed(red_evidence):
            target_iter["test_attempts"] = target_iter.get("test_attempts", 0) + 1
            target_iter["last_test_error"] = (
                "targeted evaluation tests did not fail before the fix"
            )
            save_state(state)
            return
        target_iter["test_status"] = "red_verified"
        target_iter["test_sha"] = _git_head()
        save_state(state)

    pre_sha = _git_head()
    update_evaluate_status(state, "fixing")
    try:
        fix_result = agents.fix_evaluate_issues(
            str(EVALUATE_FIX_MD),
            profiles,
            harness.config,
            spec_context=extract_spec_sections(state["spec_file"]),
            red_evidence=target_iter.get("red_verification"),
        )
    except agents.ExternalDependencyError as e:
        block_evaluate_external_dependency(state, str(e))
        return
    except agents.TimeoutError as e:
        error_evaluate(state, "timeout", str(e))
        return
    except agents.SubprocessError as e:
        error_evaluate(state, "error", str(e))
        return
    fixes = fix_result["signal"].get("fixes", [])
    log_usage(
        task_id=f"evaluate_{iteration}_fix",
        phase_id=eval_phase_id,
        mode="FIX",
        usage=fix_result["usage"],
        files_changed=sum(
            len(f.get("files_changed", []))
            for f in fixes
            if f.get("status") == "fixed"
        ),
        call_id=fix_result.get("call_id"),
    )
    if not any(f.get("status") == "fixed" for f in fixes):
        logger.warning(
            "[EVALUATE FIX] Fix agent returned no 'fixed' statuses in iteration %d — skipping verify_evaluate_fix.",
            iteration,
        )
        target_iter = state["evaluate"]["iterations"][iteration - 1]
        target_iter["fix_attempts"] = target_iter.get("fix_attempts", 0) + 1
        target_iter["last_fix_error"] = "fix agent reported no fixed issues"
        save_state(state)
        return

    if _requires_test_authoring(target_iter):
        update_evaluate_status(state, "targeted_verifying")
        green_evidence = _run_targeted_test_commands(_targeted_test_commands(target_iter))
        target_iter["green_verification"] = green_evidence
        if not _all_commands_passed(green_evidence):
            target_iter["fix_attempts"] = target_iter.get("fix_attempts", 0) + 1
            target_iter["last_fix_error"] = (
                "targeted evaluation tests failed after fix"
            )
            save_state(state)
            return

    verify_evaluate_fix(harness, state, eval_phase_id, iteration, pre_sha)


def _infer_evaluate_app_type(state: dict) -> str:
    app_type = state.get("app_type", "cli")
    if app_type != "cli":
        return app_type
    if any((phase.get("language") or "").lower() == "typescript" for phase in state.get("phases", [])):
        return "web"
    if Path("client/index.html").exists():
        return "web"
    if Path("index.html").exists() or Path("src/main.ts").exists():
        return "web"
    package_json = Path("package.json")
    if package_json.exists() and "vite" in package_json.read_text(encoding="utf-8").lower():
        return "web"
    return "cli"


def _rubric_report_contains_iteration(iteration: int) -> bool:
    if not RUBRIC_REPORT_MD.exists():
        return False
    marker = f"Rubric Report — Iteration {iteration}"
    return marker in RUBRIC_REPORT_MD.read_text(encoding="utf-8")


def _should_early_stop(state: dict, config: dict) -> bool:
    if not config.get("evaluate_early_stop_on_full_score", False):
        return False
    iterations = state.get("evaluate", {}).get("iterations", [])
    if len(iterations) < 2:
        return False
    for iteration in iterations[-2:]:
        if iteration.get("verdict") != "APPROVE":
            return False
        score = iteration.get("score")
        if not isinstance(score, dict) or score.get("total") != score.get("max"):
            return False
        if not _score_meets_threshold(score, config):
            return False
    return True


def _normalize_evaluate_result(result: dict, eval_phase_id: int, config: dict) -> None:
    signal = result["signal"]
    if signal.get("verdict") != "APPROVE":
        return
    score = signal.get("score")
    if not isinstance(score, dict) or _score_meets_threshold(score, config):
        return
    signal["verdict"] = "BLOCK"
    issues = signal.setdefault("issues", [])
    if issues:
        return
    total = score.get("total")
    max_score = score.get("max")
    threshold = get_evaluation_min_score_pct(config)
    issues.append(
        {
            "id": f"{eval_phase_id}.1",
            "severity": "HIGH",
            "dimension": "Quality",
            "file": "N/A",
            "title": "Evaluation score below threshold",
            "description": (
                f"Evaluation returned APPROVE with score {total}/{max_score}, "
                f"below threshold {threshold:.0%}."
            ),
            "suggestion": "Address rubric deductions until the score meets the configured threshold.",
            "log_info": "",
            "refs": "workspace/rubric-report.md",
            "test_cases": [],
            "non_automatable_reason": (
                "Synthetic score-threshold issue; use rubric deductions in "
                "workspace/rubric-report.md to derive concrete fixes."
            ),
        }
    )


def _enforce_evaluation_report_gate(
    result: dict, eval_phase_id: int, app_type: str, iteration: int
) -> None:
    signal = result["signal"]
    if app_type != "game" or signal.get("verdict") != "APPROVE":
        return

    report = _extract_rubric_section(iteration)
    lower_report = report.lower()
    problems: list[str] = []

    required_sections = [
        "Spec Acceptance Checklist",
        "Command Evidence",
        "Code Quality Audit",
    ]
    for section in required_sections:
        if not _report_has_section(report, section):
            problems.append(f"missing `{section}` section")

    if "webkit-ipad" not in lower_report:
        problems.append("missing explicit `webkit-ipad` evidence")
    if re.search(r"\bnot[\s_-]?tested\b", lower_report):
        problems.append("contains core requirements marked `not_tested`")
    if any("webkit-ipad" in line and "skipped" in line for line in lower_report.splitlines()):
        problems.append("counts skipped `webkit-ipad` evidence as acceptable")

    if not problems:
        return

    signal["verdict"] = "BLOCK"
    signal.setdefault("issues", []).append(
        {
            "id": f"{eval_phase_id}.report-gate",
            "severity": "HIGH",
            "dimension": "Quality",
            "file": "workspace/rubric-report.md",
            "title": "Evaluation report missing required game acceptance evidence",
            "description": (
                "Game evaluation returned APPROVE, but the rubric report is missing "
                "required evidence: "
                + "; ".join(problems)
                + "."
            ),
            "suggestion": (
                "Rerun evaluation with a rubric report that includes Spec Acceptance "
                "Checklist, Command Evidence, Code Quality Audit, and explicit "
                "passing webkit-ipad touch/reconnect evidence."
            ),
            "log_info": "",
            "refs": "workspace/rubric-report.md",
            "test_cases": [],
            "non_automatable_reason": (
                "This is an evaluator evidence failure; it must be fixed by rerunning "
                "or correcting the evaluation report, not by changing product code."
            ),
        }
    )


def _report_has_section(report: str, title: str) -> bool:
    return bool(
        re.search(rf"^##+\s+{re.escape(title)}\b", report, flags=re.IGNORECASE | re.MULTILINE)
    )


def _score_meets_threshold(score: dict, config: dict) -> bool:
    total = score.get("total")
    max_score = score.get("max")
    if not isinstance(total, (int, float)) or not isinstance(max_score, (int, float)):
        return True
    if max_score <= 0:
        return True
    return (total / max_score) >= get_evaluation_min_score_pct(config)


def _issues_missing_test_contract(iteration_entry: dict) -> list[str]:
    missing = []
    for issue in iteration_entry.get("issues", []):
        if issue.get("severity") not in ("CRITICAL", "HIGH"):
            continue
        if issue.get("test_cases") or issue.get("non_automatable_reason"):
            continue
        missing.append(issue.get("id", "?"))
    return missing


def _requires_test_authoring(iteration_entry: dict) -> bool:
    return any(issue.get("test_cases") for issue in iteration_entry.get("issues", []))


def _format_test_cases(issue: dict) -> str:
    test_cases = issue.get("test_cases") or []
    if test_cases:
        return json.dumps(test_cases, indent=2)
    reason = issue.get("non_automatable_reason")
    if reason:
        return f"Non-automatable: {reason}"
    return "[]"


def _write_evaluate_fix_md(state: dict, iteration: int) -> None:
    rubric_section = _extract_rubric_section(iteration)
    issues = state["evaluate"]["iterations"][iteration - 1]["issues"]
    issue_lines = []
    for iss in issues:
        issue_lines.append(
            f"## {iss['id']} [{iss['severity']}] {iss['title']}\n"
            f"- File: {iss.get('file', 'N/A')}\n"
            f"- Dimension: {iss.get('dimension', 'N/A')}\n"
            f"- Description: {iss.get('description', '')}\n"
            f"- Suggestion: {iss.get('suggestion', '')}\n"
            f"- Log info: {iss.get('log_info', '')}\n"
            f"- Refs: {iss.get('refs', '')}\n"
            f"- Test cases: {_format_test_cases(iss)}\n"
        )
    content = (
        rubric_section + "\n\n---\n\n## Issues to Fix\n\n" + "\n".join(issue_lines)
    )
    EVALUATE_FIX_MD.write_text(content, encoding="utf-8")


def _extract_rubric_section(iteration: int) -> str:
    if not RUBRIC_REPORT_MD.exists():
        return ""
    content = RUBRIC_REPORT_MD.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^# Rubric Report — Iteration {iteration}\b.*$", re.MULTILINE
    )
    m = pattern.search(content)
    if not m:
        return ""
    start = m.start()
    next_h1 = re.search(r"^# ", content[start + 1 :], re.MULTILINE)
    end = start + 1 + next_h1.start() if next_h1 else len(content)
    return content[start:end].strip()


def _git_head() -> str:
    run = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else ""


def _targeted_test_commands(
    iteration_entry: dict, authored_tests: list[dict] | None = None
) -> list[list[str]]:
    commands: list[list[str]] = []
    for test in authored_tests or iteration_entry.get("authored_tests", []):
        if test.get("status") != "authored":
            continue
        command = test.get("command")
        if _valid_command(command):
            commands.append(list(command))
    for issue in iteration_entry.get("issues", []):
        for test_case in issue.get("test_cases") or []:
            command = test_case.get("command")
            if _valid_command(command):
                commands.append(list(command))
    return _dedupe_commands(commands)


def _valid_command(command: object) -> bool:
    return isinstance(command, list) and bool(command) and all(
        isinstance(part, str) and part for part in command
    )


def _dedupe_commands(commands: list[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[list[str]] = []
    for command in commands:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


def _run_targeted_test_commands(commands: list[list[str]]) -> dict:
    results = []
    for command in commands:
        run_cmd, result = run_command(command, capture_output=True, text=True)
        results.append(
            {
                "cmd": run_cmd,
                "returncode": result.returncode,
                "stdout_tail": str(result.stdout or "")[-500:],
                "stderr_tail": str(result.stderr or "")[-500:],
            }
        )
    return {"commands": results}


def _all_commands_failed(evidence: dict) -> bool:
    commands = evidence.get("commands", [])
    return bool(commands) and all(c.get("returncode") != 0 for c in commands)


def _all_commands_passed(evidence: dict) -> bool:
    commands = evidence.get("commands", [])
    return bool(commands) and all(c.get("returncode") == 0 for c in commands)


def _collect_regression_commands(harness: Harness, state: dict) -> list[list[str]]:
    return collect_regression_commands(harness, state)


def verify_evaluate_fix(
    harness: Harness, state: dict, eval_phase_id: int, iteration: int, pre_sha: str
) -> bool:
    update_evaluate_status(state, "regression_verifying")
    target_iter = state["evaluate"]["iterations"][iteration - 1]
    regression_evidence = _run_targeted_test_commands(
        _collect_regression_commands(harness, state)
    )
    target_iter["full_regression"] = regression_evidence
    if not _all_commands_passed(regression_evidence):
        logger.warning("[EVALUATE FIX] Full regression failed after fix")
        target_iter["fix_attempts"] = target_iter.get("fix_attempts", 0) + 1
        target_iter["last_fix_error"] = "full regression failed after evaluate fix"
        save_state(state)
        return False

    sha_run = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if sha_run.returncode != 0:
        logger.warning(
            "[EVALUATE FIX] Could not read HEAD after fix: %s",
            sha_run.stderr[-500:].strip(),
        )
        return False
    current_sha = sha_run.stdout.strip()
    if pre_sha and current_sha == pre_sha:
        logger.warning(
            "[EVALUATE FIX] HEAD SHA unchanged after fix (%r == pre_sha) — no commit made; skipping fix_sha update.",
            current_sha,
        )
        return False
    target_iter["fix_sha"] = current_sha
    for issue in target_iter.get("issues", []):
        if issue.get("severity") in ("CRITICAL", "HIGH"):
            issue["status"] = "fixed"
            issue["fixed_sha"] = current_sha
    save_state(state)
    EVALUATE_FIX_MD.write_text("", encoding="utf-8")
    return True
