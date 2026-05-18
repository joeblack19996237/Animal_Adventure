from __future__ import annotations


def compute_timeout(
    mode: str,
    config: dict,
    *,
    phase_task_count: int = 0,
    changed_file_count: int = 0,
    diff_line_count: int = 0,
    tdd_mode: str | None = None,
) -> int:
    base = int(config.get("subprocess_timeout", {}).get(mode, 300))
    policy = config.get("timeout_policy", {})
    mode_policy = policy.get(mode, {})

    timeout = base
    if mode == "REVIEW":
        timeout = max(timeout, int(mode_policy.get("min", base)))
        timeout += int(mode_policy.get("per_task", 0)) * max(phase_task_count, 0)
        timeout += int(mode_policy.get("per_changed_file", 0)) * max(
            changed_file_count, 0
        )
        per_diff_line = float(mode_policy.get("per_diff_line", 0))
        timeout += int(per_diff_line * max(diff_line_count, 0))
    elif mode == "EXECUTE" and tdd_mode == "tdd_slice":
        timeout += int(mode_policy.get("tdd_slice_bonus", 0))

    minimum = int(mode_policy.get("min", timeout))
    maximum = int(mode_policy.get("max", timeout))
    return max(minimum, min(int(timeout), maximum))
