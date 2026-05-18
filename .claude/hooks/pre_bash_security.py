import json
import re
import sys

BLOCKED_PATTERNS = [
    (
        r"\brm\s+-(?=[^\s]*r)(?=[^\s]*f)[^\s]+(?:\s+--no-preserve-root)?\s+/(?:\s|$)",
        "rm -rf / is destructive",
    ),
    (
        r"\brm\s+-(?=[^\s]*r)(?=[^\s]*f)[^\s]+(?:\s+--no-preserve-root)?\s+/\*",
        "rm -rf /* is destructive",
    ),
    (
        r"\brm\s+-(?=[^\s]*r)(?=[^\s]*f)[^\s]+(?:\s+--no-preserve-root)?\s+/[^\s]+",
        "rm -rf absolute path is destructive",
    ),
    (
        r"\brm\s+-(?=[^\s]*r)(?=[^\s]*f)[^\s]+\s+[A-Za-z]:[\\/]",
        "rm -rf Windows absolute path is destructive",
    ),
    (r"\brm\s+-(?=[^\s]*r)(?=[^\s]*f)[^\s]+\s+\*", "rm -rf * is destructive"),
    (
        r"\bRemove-Item\b(?=[^\r\n]*\s-(?:Recurse|r)\b)(?=[^\r\n]*\s-(?:Force|f)\b)[^\r\n]*(?:[A-Za-z]:[\\/]|\\\\)",
        "Remove-Item recursive force on absolute path is destructive",
    ),
    (
        r"\b(?:rmdir|rd)\b(?=[^\r\n]*/s\b)(?=[^\r\n]*/q\b)[^\r\n]*\s+(?:[A-Za-z]:[\\/]|\\\\)",
        "rmdir /s /q absolute path is destructive",
    ),
    (
        r"\bdel\b(?=[^\r\n]*/s\b)(?=[^\r\n]*/q\b)[^\r\n]*\s+(?:[A-Za-z]:[\\/]|\\\\)",
        "del /s /q absolute path is destructive",
    ),
    (r"\bDROP\s+TABLE\b", "DROP TABLE is destructive"),
    (r"\bDROP\s+DATABASE\b", "DROP DATABASE is destructive"),
    (r"curl\s+.*\|\s*bash", "curl | bash is a remote code execution risk"),
    (r"wget\s+.*\|\s*sh", "wget | sh is a remote code execution risk"),
    (
        r"git\s+push\s+--force\s+.*\b(main|master)\b",
        "force push to main/master is blocked",
    ),
    (r"python\s+-c\s+['\"]", "python -c with inline code is a prompt injection vector"),
    (r"IGNORE\s+PREVIOUS\s+INSTRUCTIONS", "prompt injection detected"),
]


def main() -> int:
    data = json.loads(sys.stdin.read())
    command = data.get("tool_input", {}).get("command", "")

    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            print(f"[SECURITY BLOCK] Command blocked: {reason}. Command: {command!r}")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
