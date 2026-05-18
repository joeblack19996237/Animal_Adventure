def task_build_signal(phase_id=1):
    return {
        "status": "complete",
        "mode": "TASK_BUILD",
        "phase_id": phase_id,
        "tasks": [
            {
                "id": f"{phase_id}.1",
                "title": "Mocked task",
                "task_type": "foundation",
                "description": "Create mocked app.py content for the fixture run.",
                "tdd_mode": None,
                "status": "pending",
                "files_changed": [],
            }
        ],
    }


def execute_signal(phase_id=1):
    return {
        "status": "complete",
        "mode": "EXECUTE",
        "phase_id": phase_id,
        "tasks": [
            {
                "id": f"{phase_id}.1",
                "title": "Mocked task",
                "task_type": "foundation",
                "status": "complete",
                "files_changed": ["app.py"],
            }
        ],
    }


def review_signal(phase_id=1, verdict="APPROVE"):
    issues = []
    if verdict == "BLOCK":
        issues = [
            {
                "id": f"{phase_id}.1",
                "severity": "HIGH",
                "title": "Mocked blocking issue",
                "file": "app.py",
                "status": "open",
                "attempts": 0,
                "last_error": [],
            }
        ]
    return {
        "status": "complete",
        "mode": "REVIEW",
        "phase_id": phase_id,
        "verdict": verdict,
        "sha_at_review": "mocksha",
        "issues": issues,
    }


def fix_signal(issue_id="1.1"):
    return {
        "status": "complete",
        "mode": "FIX",
        "fixes": [
            {
                "id": issue_id,
                "status": "fixed",
                "files_changed": ["app.py"],
            }
        ],
    }
