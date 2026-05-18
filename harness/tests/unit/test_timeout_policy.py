from timeout_policy import compute_timeout


def _config():
    return {
        "subprocess_timeout": {"REVIEW": 240, "EXECUTE": 300},
        "timeout_policy": {
            "EXECUTE": {"min": 300, "max": 900, "tdd_slice_bonus": 300},
            "REVIEW": {
                "min": 480,
                "max": 1200,
                "per_task": 30,
                "per_changed_file": 45,
                "per_diff_line": 0.25,
            }
        },
    }


def test_review_timeout_scales_with_changed_files():
    assert compute_timeout("REVIEW", _config(), changed_file_count=2) == 570


def test_review_timeout_scales_with_diff_lines():
    assert compute_timeout("REVIEW", _config(), diff_line_count=80) == 500


def test_review_timeout_scales_with_phase_task_count():
    assert compute_timeout("REVIEW", _config(), phase_task_count=3) == 570


def test_timeout_policy_respects_min_max():
    assert compute_timeout("REVIEW", _config(), diff_line_count=10000) == 1200


def test_execute_timeout_uses_base_timeout():
    assert compute_timeout("EXECUTE", _config(), phase_task_count=99) == 300


def test_execute_timeout_adds_tdd_slice_bonus():
    assert compute_timeout("EXECUTE", _config(), tdd_mode="tdd_slice") == 600
