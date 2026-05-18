import json
import subprocess
import sys

TOOL_TIMEOUT = 10


def _run_npx(args: list[str], *, text: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["npx", "--no-install"] + args,
        capture_output=True,
        text=text,
        timeout=TOOL_TIMEOUT,
    )


def main() -> int:
    data = json.loads(sys.stdin.read())
    file_path = data.get("tool_input", {}).get("file_path", "")

    if not file_path.endswith((".ts", ".tsx")):
        return 0

    try:
        # Auto-fix formatting silently
        _run_npx(["prettier", "--write", file_path])
        # Auto-fix safe lint issues silently
        _run_npx(["eslint", "--fix", file_path])

        # Report remaining violations the agent must fix manually
        result = _run_npx(["eslint", file_path], text=True)
    except FileNotFoundError:
        print("[ESLINT] npx is not available; skipping TypeScript lint/format hook.")
        return 0
    except subprocess.TimeoutExpired:
        print(f"[ESLINT] npx timed out while processing {file_path!r}.")
        return 0

    if result.returncode != 0 and result.stdout.strip():
        print(
            f"[ESLINT] Lint violations in {file_path!r} — fix before completing the task:\n"
            f"{result.stdout.strip()}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
