import json
import sys

data = json.loads(sys.stdin.read())
tool_input = data.get("tool_input", {})
file_path = tool_input.get("file_path", "")
new_string = tool_input.get("new_string", "")

# Python files are handled by post_py_lint_format.py — ruff may reformat
# the content, making an exact new_string match a false positive.
if file_path.endswith(".py"):
    sys.exit(0)

try:
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
except OSError:
    print(f"[HOOK WARN] Could not read file after Edit: {file_path!r}")
    sys.exit(0)

if new_string and new_string not in content:
    print(
        f"[HOOK WARN] Edit applied but new_string not found in {file_path!r}. "
        "The edit may not have taken effect — re-read the file and retry the edit."
    )

sys.exit(0)
