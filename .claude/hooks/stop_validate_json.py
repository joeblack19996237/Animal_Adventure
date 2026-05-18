import json
import os
import re
import sys

import jsonschema

import hook_utils

# Only validate when running as a harness subprocess — skip in interactive sessions
if not os.environ.get("HARNESS_MODE"):
    sys.exit(0)

SIGNAL_SCHEMAS = {
    "TASK_BUILD": {
        "type": "object",
        "required": ["status", "mode", "phase_id", "tasks"],
        "properties": {
            "status": {"type": "string", "const": "complete"},
            "mode": {"type": "string", "const": "TASK_BUILD"},
            "phase_id": {"type": "integer"},
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "title", "task_type", "description", "tdd_mode"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "title": {"type": "string", "minLength": 1},
                        "task_type": {"type": "string"},
                        "description": {"type": "string", "minLength": 1},
                        "tdd_mode": {
                            "type": "string",
                            "enum": [
                                "test_first",
                                "implementation",
                                "tdd_slice",
                                "unit_test",
                                "exempt",
                            ],
                        },
                        "tdd_skipped": {"type": ["string", "null"]},
                        "refs": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
    "EXECUTE": {
        # No wrapper status — outcome is derived by harness from tasks[].status values.
        "type": "object",
        "required": ["mode", "phase_id", "tasks"],
        "properties": {
            "mode": {"type": "string", "const": "EXECUTE"},
            "phase_id": {"type": "integer"},
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "title", "task_type", "status", "files_changed"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "title": {"type": "string"},
                        "task_type": {"type": "string"},
                        "status": {"type": "string", "enum": ["complete", "failed"]},
                        "tdd_applied": {"type": ["boolean", "null"]},
                        "tdd_skipped": {"type": ["string", "null"]},
                        "files_changed": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                        "verification_note": {"type": "string"},
                    },
                },
            },
        },
    },
    "FIX": {
        # No wrapper status — outcome is derived by harness from fixes[].status values.
        "type": "object",
        "required": ["mode", "fixes"],
        "properties": {
            "mode": {"type": "string", "const": "FIX"},
            "fixes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "severity", "title", "status", "files_changed"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "severity": {
                            "type": "string",
                            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        },
                        "title": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["fixed", "open", "deferred"],
                        },
                        "files_changed": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                        "test_cases_covered": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "test_files_changed": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
    "EVALUATE_TESTS": {
        "type": "object",
        "required": ["mode", "phase_id", "iteration", "tests"],
        "properties": {
            "mode": {"type": "string", "const": "EVALUATE_TESTS"},
            "phase_id": {"type": "integer"},
            "iteration": {"type": "integer", "minimum": 1, "maximum": 3},
            "tests": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": [
                        "id",
                        "issue_id",
                        "status",
                        "files_changed",
                        "command",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "issue_id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "status": {"type": "string", "enum": ["authored", "open"]},
                        "files_changed": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "command": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    },
    "EVALUATE": {
        "type": "object",
        "required": ["status", "mode", "iteration", "phase_id", "verdict", "issues"],
        "properties": {
            "status": {"type": "string", "enum": ["complete"]},
            "mode": {"type": "string", "enum": ["EVALUATE"]},
            "iteration": {"type": "integer", "minimum": 1, "maximum": 3},
            "phase_id": {"type": "integer"},
            "verdict": {"type": "string", "enum": ["APPROVE", "BLOCK"]},
            "score": {
                "type": "object",
                "required": ["total", "max"],
                "properties": {
                    "total": {"type": "number"},
                    "max": {"type": "number"},
                },
            },
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "id",
                        "severity",
                        "dimension",
                        "title",
                        "description",
                        "suggestion",
                    ],
                    "properties": {
                        "id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "severity": {
                            "type": "string",
                            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        },
                        "dimension": {"type": "string"},
                        "file": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "log_info": {"type": "string"},
                        "refs": {"type": "string"},
                        "test_cases": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["id", "description", "command"],
                                "properties": {
                                    "id": {"type": "string", "minLength": 1},
                                    "type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "suggested_test_file": {"type": "string"},
                                    "command": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "pre_fix_expected": {"type": "string"},
                                    "pass_condition": {"type": "string"},
                                },
                            },
                        },
                        "non_automatable_reason": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
    "REVIEW": {
        "type": "object",
        "required": [
            "status",
            "mode",
            "phase_id",
            "verdict",
            "sha_at_review",
            "issues",
        ],
        "properties": {
            "status": {"type": "string", "const": "complete"},
            "mode": {"type": "string", "const": "REVIEW"},
            "phase_id": {"type": "integer"},
            "verdict": {"type": "string", "enum": ["APPROVE", "WARN", "BLOCK"]},
            "sha_at_review": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "severity", "dimension", "file", "title"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
                        "severity": {
                            "type": "string",
                            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        },
                        "dimension": {"type": "string"},
                        "file": {"type": "string"},
                        "title": {"type": "string"},
                    },
                },
            },
        },
    },
}

data = json.loads(sys.stdin.read())

# stop_hook_active=True means this is already a retry turn — exit unconditionally
# to avoid an infinite loop. extract_signal() in call_claude() handles any residue.
if data.get("stop_hook_active"):
    sys.exit(0)

text = hook_utils.read_signal_text(data)
if text is None:
    sys.exit(0)

stripped = re.sub(
    r"^```json\s*|^```\s*|```$", "", text.strip(), flags=re.MULTILINE
).strip()
try:
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Expected object", stripped, 0)
except json.JSONDecodeError as e:
    print(
        f"[SIGNAL ERROR] Your response is not valid JSON: {e}. "
        f"Respond with ONLY a valid JSON object matching the required schema. "
        f"No prose, no markdown fences. Raw output was: {text[:300]!r}"
    )
    sys.exit(1)

mode = parsed.get("mode")
schema = SIGNAL_SCHEMAS.get(mode) if isinstance(mode, str) else None
if schema is None:
    print(
        f"[SIGNAL ERROR] Missing or unknown 'mode' field: {mode!r}. "
        f"Must be one of: {list(SIGNAL_SCHEMAS)}."
    )
    sys.exit(1)

try:
    jsonschema.validate(parsed, schema)
except jsonschema.ValidationError as e:
    print(
        f"[SIGNAL ERROR] Schema validation failed at '{e.json_path}': {e.message}. "
        f"Fix your JSON and respond with ONLY the corrected signal object."
    )
    sys.exit(1)

# TDD ordering validation for TASK_BUILD (non-development phases are exempt)
if mode == "EVALUATE":
    if parsed.get("verdict") == "BLOCK":
        for issue in parsed.get("issues", []):
            severity = issue.get("severity")
            if severity not in ("CRITICAL", "HIGH"):
                continue
            test_cases = issue.get("test_cases") or []
            non_auto = issue.get("non_automatable_reason")
            if not test_cases and not non_auto:
                print(
                    "[SIGNAL ERROR] BLOCK EVALUATE issues with CRITICAL/HIGH "
                    "severity must include non-empty test_cases or a "
                    f"non_automatable_reason. Issue: {issue.get('id', '?')}"
                )
                sys.exit(1)

# TDD ordering validation for TASK_BUILD (non-development phases are exempt)
if mode == "TASK_BUILD":
    phase_id = parsed.get("phase_id")
    tasks = parsed.get("tasks", [])

    phase_type = "setup" if phase_id == 1 else "development"
    try:
        _state = json.loads(open("workspace/state.json", encoding="utf-8").read())
        for _sp in _state.get("phases", []):
            if _sp.get("id") == phase_id:
                phase_type = _sp.get("phase_type", phase_type)
                break
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        pass
    allow_legacy_tdd_triplets = False
    try:
        _config = json.loads(open("harness/config.json", encoding="utf-8").read())
        allow_legacy_tdd_triplets = bool(
            _config.get("task_planning_limits", {}).get(
                "allow_legacy_tdd_triplets", False
            )
        )
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        pass

    if phase_type == "development":
        VALID_TDD_MODES = {
            "test_first",
            "implementation",
            "tdd_slice",
            "unit_test",
            "exempt",
        }
        ordering_errors: list[str] = []
        sm_state = "IDLE"  # IDLE | AFTER_TEST_FIRST | AFTER_IMPL
        last_impl_id = None

        for task in tasks:
            tdd_mode = task.get("tdd_mode")
            tid = task.get("id", "?")
            ttitle = task.get("title", "")

            if tdd_mode not in VALID_TDD_MODES:
                ordering_errors.append(
                    f"Task {tid} has invalid tdd_mode: {tdd_mode!r}. "
                    f"Use one of: {', '.join(sorted(VALID_TDD_MODES))}."
                )
                continue

            if tdd_mode == "exempt":
                if not task.get("tdd_skipped"):
                    ordering_errors.append(
                        f"Task {tid} has tdd_mode='exempt' but no tdd_skipped reason."
                    )
                continue
            if not allow_legacy_tdd_triplets:
                if tdd_mode != "tdd_slice":
                    ordering_errors.append(
                        f"Task {tid} ({ttitle!r}) uses legacy tdd_mode={tdd_mode!r}. "
                        "Use tdd_mode='tdd_slice' so tests, implementation, and "
                        "focused verification happen in one Claude task."
                    )
                continue
            if tdd_mode == "tdd_slice":
                continue

            if tdd_mode == "test_first":
                if sm_state == "AFTER_IMPL":
                    ordering_errors.append(
                        f"Task {tid} ({ttitle!r}): 'test_first' follows 'implementation' "
                        f"task {last_impl_id} with no 'unit_test' in between."
                    )
                sm_state = "AFTER_TEST_FIRST"

            elif tdd_mode == "implementation":
                if sm_state == "IDLE":
                    ordering_errors.append(
                        f"Task {tid} ({ttitle!r}): 'implementation' has no preceding 'test_first'."
                    )
                elif sm_state == "AFTER_IMPL":
                    ordering_errors.append(
                        f"Task {tid} ({ttitle!r}): 'implementation' follows task {last_impl_id} "
                        f"with no 'unit_test' in between."
                    )
                sm_state = "AFTER_IMPL"
                last_impl_id = tid

            elif tdd_mode == "unit_test":
                if sm_state != "AFTER_IMPL":
                    ordering_errors.append(
                        f"Task {tid} ({ttitle!r}): 'unit_test' has no preceding 'implementation'."
                    )
                sm_state = "IDLE"

        if sm_state == "AFTER_TEST_FIRST":
            ordering_errors.append(
                "Phase ends with a 'test_first' task but no following 'implementation' and 'unit_test'."
            )
        elif sm_state == "AFTER_IMPL":
            ordering_errors.append(
                f"Phase ends after 'implementation' task {last_impl_id} with no following 'unit_test'."
            )

        if ordering_errors:
            for err in ordering_errors:
                print(f"[SIGNAL ERROR] TDD ordering: {err}")
            sys.exit(1)

    elif phase_type == "setup":
        # Setup phases do not enforce full TDD triplet ordering. Test tasks may
        # still use normal TDD modes, while exempt tasks must explain the skip.
        print(
            "[PHASE TYPE: setup] TDD triplet not enforced — exempt setup tasks still require tdd_skipped."
        )
        VALID_TDD_MODES = {
            "test_first",
            "implementation",
            "tdd_slice",
            "unit_test",
            "exempt",
        }
        tdd_skip_errors: list[str] = []
        for task in tasks:
            tdd_mode = task.get("tdd_mode")
            if tdd_mode not in VALID_TDD_MODES:
                tdd_skip_errors.append(
                    f"Task {task.get('id', '?')} has invalid tdd_mode: {tdd_mode!r}. "
                    f"Use one of: {', '.join(sorted(VALID_TDD_MODES))}."
                )
            elif tdd_mode == "exempt" and not task.get("tdd_skipped"):
                tdd_skip_errors.append(
                    f"Task {task.get('id', '?')} ({task.get('title', '')!r}): "
                    "phase_type='setup' — exempt setup tasks still require tdd_skipped."
                )
        if tdd_skip_errors:
            for err in tdd_skip_errors:
                print(f"[SIGNAL ERROR] TDD: {err}")
            sys.exit(1)

    else:
        # integration / e2e: TDD triplet not enforced, but every task must
        # declare tdd_skipped to confirm the agent made a conscious exemption decision.
        print(
            f"[PHASE TYPE: {phase_type}] TDD triplet not enforced — all tasks must have tdd_skipped set."
        )
        tdd_skip_errors: list[str] = []
        for task in tasks:
            if not task.get("tdd_skipped"):
                tdd_skip_errors.append(
                    f"Task {task.get('id', '?')} ({task.get('title', '')!r}): "
                    f"phase_type={phase_type!r} — tdd_skipped must be set."
                )
        if tdd_skip_errors:
            for err in tdd_skip_errors:
                print(f"[SIGNAL ERROR] TDD: {err}")
            sys.exit(1)

sys.exit(0)
