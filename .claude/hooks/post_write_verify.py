import json
import sys
from pathlib import Path

data = json.loads(sys.stdin.read())
file_path = data.get("tool_input", {}).get("file_path", "")

if not Path(file_path).exists():
    print(f"[HOOK ERROR] Write succeeded but file not found on disk: {file_path!r}")
    sys.exit(2)

sys.exit(0)
