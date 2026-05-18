import json
import subprocess
import sys


def main() -> int:
    data = json.loads(sys.stdin.read())
    file_path = data.get("tool_input", {}).get("file_path", "")

    if not file_path.endswith(".py"):
        return 0

    # Auto-fix formatting and safe lint issues silently
    try:
        subprocess.run(["ruff", "format", file_path], capture_output=True, timeout=30)
        subprocess.run(
            ["ruff", "check", "--fix", file_path], capture_output=True, timeout=30
        )

        # Report any remaining violations the agent must fix manually
        result = subprocess.run(
            ["ruff", "check", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("[RUFF] ruff is not installed; skipping Python lint/format hook.")
        return 0
    except subprocess.TimeoutExpired:
        print(f"[RUFF] ruff timed out while processing {file_path!r}.")
        return 0

    if result.returncode != 0 and result.stdout.strip():
        print(
            f"[RUFF] Lint violations in {file_path!r} — fix before completing the task:\n"
            f"{result.stdout.strip()}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
