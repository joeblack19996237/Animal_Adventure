import json
import os
import re
import subprocess
import sys
from pathlib import Path

import hook_utils


# Only commit when running as a harness subprocess — skip in interactive sessions.
# No stop_hook_active guard needed: this hook always exits 0 so it cannot loop.
# On a correction turn (stop_hook_active=True), the corrected signal should be committed.
if not os.environ.get("HARNESS_MODE"):
    sys.exit(0)

data = json.loads(sys.stdin.read())

text = hook_utils.read_signal_text(data)
if text is None:
    sys.exit(0)

stripped = re.sub(
    r"^```json\s*|^```\s*|```$", "", text.strip(), flags=re.MULTILINE
).strip()

try:
    signal = json.loads(stripped)
except json.JSONDecodeError:
    sys.exit(0)  # stop_validate_json.py handles invalid JSON — don't duplicate

mode = signal.get("mode", "")

if mode in ("TASK_BUILD", "REVIEW"):
    sys.exit(0)  # no code changes to commit for these modes

if mode == "EXECUTE":
    completed = [t for t in signal.get("tasks", []) if t.get("status") == "complete"]
    files = [f for task in completed for f in task.get("files_changed", [])]
    if len(completed) == 1:
        msg = f"feat(phase-{signal.get('phase_id', '?')}): {completed[0]['title']}"
    else:
        msg = f"feat(phase-{signal.get('phase_id', '?')}): implement {len(completed)} tasks"
elif mode == "EVALUATE_TESTS":
    authored = [t for t in signal.get("tests", []) if t.get("status") == "authored"]
    files = [f for test in authored for f in test.get("files_changed", [])]
    msg = f"test(evaluate-{signal.get('iteration', '?')}): cover evaluation issues"
elif mode == "FIX":
    files = [
        f
        for fix in signal.get("fixes", [])
        if fix.get("status") == "fixed"
        for f in fix.get("files_changed", [])
    ]
    fixes = signal.get("fixes", [])
    phase_id = fixes[0]["id"].split(".")[0] if fixes else "?"
    msg = f"fix(phase-{phase_id}): fix CRITICAL/HIGH issues"
else:
    sys.exit(0)

if not files:
    sys.exit(0)

_UNSAFE_PATH = re.compile(r"[*?:\[\]\\]")

root = Path(".").resolve()


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name.lower()
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or name.startswith("test_")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
    )

status_r = subprocess.run(
    ["git", "status", "--porcelain", "-z"],
    capture_output=True,
    text=True,
)
changed_in_git: set[str] = set()
for _entry in status_r.stdout.split("\0"):
    _entry = _entry.strip()
    if len(_entry) > 3:
        changed_in_git.add(_entry[3:])

safe_files = []
for f in files:
    if not f or f in (".", "..") or _UNSAFE_PATH.search(f):
        print(f"[SECURITY] Rejected unsafe pathspec: {f!r}", file=sys.stderr)
        continue
    if mode == "EVALUATE_TESTS" and not _is_test_path(f):
        print(f"[SECURITY] Rejected non-test file for EVALUATE_TESTS: {f!r}", file=sys.stderr)
        continue
    try:
        resolved = (root / f).resolve()
        if not resolved.is_relative_to(root):
            print(
                f"[SECURITY] Blocked path outside project root: {f!r}", file=sys.stderr
            )
            continue
        if resolved.is_dir():
            print(f"[SECURITY] Rejected directory path: {f!r}", file=sys.stderr)
            continue
    except Exception:
        print(f"[SECURITY] Blocked invalid path: {f!r}", file=sys.stderr)
        continue
    if f not in changed_in_git:
        print(f"[SECURITY] Skipped path absent from git status: {f!r}", file=sys.stderr)
        continue
    safe_files.append(f)

if not safe_files:
    sys.exit(0)

add_result = subprocess.run(
    ["git", "add", "--"] + safe_files, capture_output=True, text=True
)
if add_result.returncode != 0:
    print(f"[WARN] git add failed: {add_result.stderr}", file=sys.stderr)
    sys.exit(0)

msg = msg.strip().replace("\r", "").replace("\n", " ")
result = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
if result.returncode != 0 and "nothing to commit" not in result.stdout:
    print(f"[WARN] git commit failed: {result.stderr}", file=sys.stderr)

sys.exit(0)
