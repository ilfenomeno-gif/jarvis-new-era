from __future__ import annotations

from typing import Any


def messages_to_gemini(messages: list[dict[str, Any]]) -> tuple[list[dict], str]:
    contents = []
    system_parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(str(content))
            continue
        parts = content if isinstance(content, list) else [{"text": str(content)}]
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": parts,
        })
    return contents, "\n\n".join(system_parts)
