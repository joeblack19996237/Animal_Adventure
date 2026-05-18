import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_EVALUATE_ITERATIONS = 3
DEFAULT_LANGUAGE = "python"
DEFAULT_APP_TYPE = "cli"
DEFAULT_SPEC_PATH = ""
DEFAULT_EVALUATION_MIN_SCORE_PCT = 0.0
DEFAULT_CLEANUP_FIX_DEFERRED_ISSUES = True
DEFAULT_CLAUDE_SESSION_PACING = {
    "enabled": True,
    "min_seconds_between_calls": 60,
    "large_output_token_threshold": 15000,
    "large_output_cooldown_seconds": 180,
    "usage_window_seconds": 18000,
}
DEFAULT_TASK_PLANNING_LIMITS = {
    "enabled": True,
    "max_tasks_per_development_phase": 10,
    "allow_legacy_tdd_triplets": False,
}
DEFAULT_ARTIFACT_LIMITS = {
    "max_new_test_file_lines": 250,
}
DEFAULT_USAGE_GUARDRAILS = {
    "enabled": True,
    "max_single_output_tokens": 15000,
    "max_phase_claude_calls": 10,
    "max_phase_combined_tokens": 2500000,
}
DEFAULT_EXTERNAL_DEPENDENCY = {
    "max_in_process_wait_seconds": 900,
}


def load_config() -> dict:
    config = json.loads(Path("harness/config.json").read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    get_max_evaluate_iterations(config)
    get_evaluate_early_stop_on_full_score(config)
    get_default_language(config)
    get_default_app_type(config)
    get_default_spec_path(config)
    get_evaluation_min_score_pct(config)
    get_cleanup_fix_deferred_issues(config)
    get_game_quick_smoke_phase_ids(config)
    get_claude_session_pacing(config)
    get_task_planning_limits(config)
    get_artifact_limits(config)
    get_usage_guardrails(config)
    get_external_dependency_config(config)


def get_max_evaluate_iterations(config: dict) -> int:
    value = int(config.get("max_evaluate_iterations", MAX_EVALUATE_ITERATIONS))
    if value < 1 or value > MAX_EVALUATE_ITERATIONS:
        raise ValueError(
            f"max_evaluate_iterations must be between 1 and {MAX_EVALUATE_ITERATIONS}"
        )
    return value


def get_evaluate_early_stop_on_full_score(config: dict) -> bool:
    value = config.get("evaluate_early_stop_on_full_score", False)
    if not isinstance(value, bool):
        raise ValueError("evaluate_early_stop_on_full_score must be a boolean")
    return value


def get_default_language(config: dict) -> str:
    value = config.get("default_language", DEFAULT_LANGUAGE)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("default_language must be a non-empty string")
    return value


def get_default_app_type(config: dict) -> str:
    value = config.get("default_app_type", DEFAULT_APP_TYPE)
    if value not in ("cli", "web", "game"):
        raise ValueError("default_app_type must be one of: cli, web, game")
    return value


def get_default_spec_path(config: dict) -> str:
    value = config.get("default_spec_path", DEFAULT_SPEC_PATH)
    if not isinstance(value, str):
        raise ValueError("default_spec_path must be a string")
    return value


def get_evaluation_min_score_pct(config: dict) -> float:
    value = float(
        config.get("evaluation_min_score_pct", DEFAULT_EVALUATION_MIN_SCORE_PCT)
    )
    if value < 0 or value > 1:
        raise ValueError("evaluation_min_score_pct must be between 0 and 1")
    return value


def get_cleanup_fix_deferred_issues(config: dict) -> bool:
    value = config.get(
        "cleanup_fix_deferred_issues", DEFAULT_CLEANUP_FIX_DEFERRED_ISSUES
    )
    if not isinstance(value, bool):
        raise ValueError("cleanup_fix_deferred_issues must be a boolean")
    return value


def get_game_quick_smoke_phase_ids(config: dict) -> list[int]:
    value = config.get("game_quick_smoke_phase_ids", [])
    if not isinstance(value, list) or not all(
        isinstance(v, int) and v > 0 for v in value
    ):
        raise ValueError(
            "game_quick_smoke_phase_ids must be a list of positive integers"
        )
    return value


def get_claude_session_pacing(config: dict) -> dict:
    raw = config.get("claude_session_pacing", {})
    if not isinstance(raw, dict):
        raise ValueError("claude_session_pacing must be an object")
    pacing = {**DEFAULT_CLAUDE_SESSION_PACING, **raw}
    if not isinstance(pacing["enabled"], bool):
        raise ValueError("claude_session_pacing.enabled must be a boolean")
    for key in (
        "min_seconds_between_calls",
        "large_output_token_threshold",
        "large_output_cooldown_seconds",
        "usage_window_seconds",
    ):
        value = pacing[key]
        if not isinstance(value, int) or value < 0:
            raise ValueError(
                f"claude_session_pacing.{key} must be a non-negative integer"
            )
    return pacing


def get_task_planning_limits(config: dict) -> dict:
    raw = config.get("task_planning_limits", {})
    if not isinstance(raw, dict):
        raise ValueError("task_planning_limits must be an object")
    limits = {**DEFAULT_TASK_PLANNING_LIMITS, **raw}
    if not isinstance(limits["enabled"], bool):
        raise ValueError("task_planning_limits.enabled must be a boolean")
    if not isinstance(limits["allow_legacy_tdd_triplets"], bool):
        raise ValueError(
            "task_planning_limits.allow_legacy_tdd_triplets must be a boolean"
        )
    max_tasks = limits["max_tasks_per_development_phase"]
    if not isinstance(max_tasks, int) or max_tasks < 1:
        raise ValueError(
            "task_planning_limits.max_tasks_per_development_phase must be a "
            "positive integer"
        )
    return limits


def get_artifact_limits(config: dict) -> dict:
    raw = config.get("artifact_limits", {})
    if not isinstance(raw, dict):
        raise ValueError("artifact_limits must be an object")
    limits = {**DEFAULT_ARTIFACT_LIMITS, **raw}
    max_lines = limits["max_new_test_file_lines"]
    if not isinstance(max_lines, int) or max_lines < 0:
        raise ValueError(
            "artifact_limits.max_new_test_file_lines must be a non-negative integer"
        )
    return limits


def get_usage_guardrails(config: dict) -> dict:
    raw = config.get("usage_guardrails", {})
    if not isinstance(raw, dict):
        raise ValueError("usage_guardrails must be an object")
    guardrails = {**DEFAULT_USAGE_GUARDRAILS, **raw}
    if not isinstance(guardrails["enabled"], bool):
        raise ValueError("usage_guardrails.enabled must be a boolean")
    for key in (
        "max_single_output_tokens",
        "max_phase_claude_calls",
        "max_phase_combined_tokens",
    ):
        value = guardrails[key]
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"usage_guardrails.{key} must be a non-negative integer")
    return guardrails


def get_external_dependency_config(config: dict) -> dict:
    raw = config.get("external_dependency", {})
    if not isinstance(raw, dict):
        raise ValueError("external_dependency must be an object")
    settings = {**DEFAULT_EXTERNAL_DEPENDENCY, **raw}
    value = settings["max_in_process_wait_seconds"]
    if not isinstance(value, int) or value < 0:
        raise ValueError(
            "external_dependency.max_in_process_wait_seconds must be a non-negative integer"
        )
    return settings


def _append_jsonl(path: str, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_usage_jsonl() -> list:
    path = Path("workspace/usage.jsonl")
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def usage_token_totals(entry: dict) -> dict:
    actual = int(entry.get("actual_input_tokens", 0)) + int(
        entry.get("actual_output_tokens", 0)
    )
    cache = int(entry.get("cache_read_tokens", 0)) + int(
        entry.get("cache_write_tokens", 0)
    )
    return {
        "actual_tokens": actual,
        "cache_tokens": cache,
        "combined_tokens": actual + cache,
    }


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def recent_usage_entries(
    window_seconds: int = 18000, now: datetime | None = None
) -> list:
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(seconds=window_seconds)
    entries = []
    for entry in read_usage_jsonl():
        ts = _parse_ts(entry.get("ts", ""))
        if ts and ts >= cutoff:
            entries.append(entry)
    return entries


def recent_usage_summary(
    window_seconds: int = 18000, now: datetime | None = None, top_n: int = 5
) -> dict:
    entries = recent_usage_entries(window_seconds, now)
    by_mode: dict[str, dict] = {}
    totals = {"actual_tokens": 0, "cache_tokens": 0, "combined_tokens": 0}
    for entry in entries:
        entry_totals = usage_token_totals(entry)
        mode = entry.get("mode", "UNKNOWN")
        mode_totals = by_mode.setdefault(
            mode,
            {
                "calls": 0,
                "actual_tokens": 0,
                "cache_tokens": 0,
                "combined_tokens": 0,
            },
        )
        mode_totals["calls"] += 1
        for key in totals:
            totals[key] += entry_totals[key]
            mode_totals[key] += entry_totals[key]
    top_recent_calls = []
    for entry in entries[-top_n:]:
        entry_totals = usage_token_totals(entry)
        top_recent_calls.append(
            {
                "ts": entry.get("ts"),
                "phase_id": entry.get("phase_id"),
                "task_id": entry.get("task_id"),
                "mode": entry.get("mode"),
                "actual_tokens": entry_totals["actual_tokens"],
                "cache_tokens": entry_totals["cache_tokens"],
                "combined_tokens": entry_totals["combined_tokens"],
            }
        )
    return {
        "window_seconds": window_seconds,
        "calls": len(entries),
        **totals,
        "by_mode": by_mode,
        "top_recent_calls": top_recent_calls,
    }


def latest_usage_entry() -> dict | None:
    entries = read_usage_jsonl()
    return entries[-1] if entries else None


def phase_usage_summary(phase_id: int) -> dict:
    entries = [e for e in read_usage_jsonl() if e.get("phase_id") == phase_id]
    totals = {"actual_tokens": 0, "cache_tokens": 0, "combined_tokens": 0}
    for entry in entries:
        entry_totals = usage_token_totals(entry)
        for key in totals:
            totals[key] += entry_totals[key]
    return {"phase_id": phase_id, "calls": len(entries), **totals}


def claude_session_pacing_delay(
    config: dict, now: datetime | None = None
) -> tuple[float, str] | None:
    pacing = get_claude_session_pacing(config)
    if not pacing["enabled"]:
        return None
    latest = latest_usage_entry()
    if not latest:
        return None
    current = now or datetime.now(timezone.utc)
    ts = _parse_ts(latest.get("ts", ""))
    if not ts:
        return None
    elapsed = max(0.0, (current - ts).total_seconds())
    min_delay = max(0.0, float(pacing["min_seconds_between_calls"]) - elapsed)
    large_delay = 0.0
    if (
        int(latest.get("actual_output_tokens", 0))
        >= pacing["large_output_token_threshold"]
    ):
        large_delay = max(
            0.0, float(pacing["large_output_cooldown_seconds"]) - elapsed
        )
    delay = max(min_delay, large_delay)
    if delay <= 0:
        return None
    reason = (
        "large_output_cooldown"
        if large_delay >= min_delay and large_delay > 0
        else "min_interval"
    )
    return delay, reason


def log_usage(
    task_id: str,
    phase_id: int,
    mode: str,
    usage: dict,
    files_changed: int,
    task_type: str = "default",
    call_id: str | None = None,
) -> None:
    usage_missing = "input_tokens" not in usage or "output_tokens" not in usage
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase_id": phase_id,
        "task_id": task_id,
        "mode": mode,
        "task_type": task_type,
        "files_changed": files_changed,
        "call_id": call_id,
        "actual_input_tokens": usage.get("input_tokens", 0),
        "actual_output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
    }
    if usage_missing:
        entry["usage_missing"] = True
    _append_jsonl("workspace/usage.jsonl", entry)
