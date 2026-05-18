import json
import logging


def read_signal_text(data: dict) -> str | None:
    """Extract the agent's final text content from the Stop hook stdin payload.
    Returns the raw text string, or None if no text block is found.
    Uses last_assistant_message from stdin payload directly (available in newer CLI versions).
    Falls back to reading the JSONL transcript file for older CLI versions (2.1.x)."""
    msg = data.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg

    transcript_path = data.get("transcript_path")
    if not transcript_path:
        return None
    try:
        # Claude Code transcripts are JSONL — one JSON object per line.
        # Older CLI versions (2.1.x) do not include last_assistant_message in
        # the Stop hook payload, so we parse the transcript directly.
        messages = []
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and obj.get("role"):
                        messages.append(obj)
                except json.JSONDecodeError:
                    continue
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        if not assistant_msgs:
            return None
        content = assistant_msgs[-1]["content"]
        if isinstance(content, str):
            return content
        text_blocks = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return text_blocks[-1] if text_blocks else None
    except Exception as e:
        logging.warning("Failed to read signal from transcript: %s", e)
        return None
