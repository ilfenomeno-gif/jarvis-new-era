"""Headless Gemini text-chat entry point shared by UI and integrations."""

from __future__ import annotations

from dataclasses import dataclass

from google.genai import types

from core import gemini

CHAT_MODEL = "gemini-3.8-flash"


@dataclass(frozen=True)
class GeminiChatResult:
    answer: str
    thought_summaries: tuple[str, ...] = ()


def _thinking_config_is_unsupported(error: Exception) -> bool:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = str(error).casefold()
    return code in (400, "400", "INVALID_ARGUMENT") and (
        "thinking" in message or "include_thoughts" in message
    )


def _response_text(
    response,
    include_thoughts: bool,
) -> tuple[str | None, tuple[str, ...]]:
    visible_parts: list[str] = []
    thought_summaries: list[str] = []
    has_parts = False

    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            if not isinstance(text, str) or not text.strip():
                continue
            has_parts = True
            if getattr(part, "thought", False):
                if include_thoughts:
                    thought_summaries.append(text.strip())
            else:
                visible_parts.append(text.strip())

    if visible_parts:
        answer = "\n".join(visible_parts)
    elif has_parts:
        answer = None
    else:
        answer = getattr(response, "text", None)
    return answer, tuple(thought_summaries)


def ask_gemini_with_thoughts(
    prompt: str,
    history: list[dict] | None = None,
    timeout_ms: int = 30_000,
    thinking_level: str = "high",
    include_thoughts: bool = True,
) -> GeminiChatResult:
    """Return a response and any provider-supplied thought summaries."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError("Gemini prompt must be a non-empty string.")
    if type(timeout_ms) is not int or timeout_ms <= 0:
        raise RuntimeError("Gemini timeout_ms must be a positive integer.")
    if not isinstance(thinking_level, str):
        raise RuntimeError("Gemini thinking_level must be minimal, low, medium, or high.")
    try:
        level = types.ThinkingLevel(thinking_level.upper())
    except ValueError as exc:
        raise RuntimeError(
            "Gemini thinking_level must be minimal, low, medium, or high."
        ) from exc
    if type(include_thoughts) is not bool:
        raise RuntimeError("Gemini include_thoughts must be a boolean.")

    contents = (history or []) + [{"role": "user", "parts": [{"text": prompt}]}]
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level=level,
            include_thoughts=include_thoughts,
        )
    )

    try:
        client = gemini.client(timeout_ms=timeout_ms)
        try:
            response = client.models.generate_content(
                model=CHAT_MODEL,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            if not _thinking_config_is_unsupported(exc):
                raise
            response = client.models.generate_content(
                model=CHAT_MODEL,
                contents=contents,
            )
    except Exception as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    answer, thought_summaries = _response_text(response, include_thoughts)
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError(
            "Gemini returned an empty response. Check model access, "
            "API quota, or the safety feedback for this prompt."
        )
    return GeminiChatResult(answer.strip(), thought_summaries)


def ask_gemini(
    prompt: str,
    history: list[dict] | None = None,
    timeout_ms: int = 30_000,
    thinking_level: str = "high",
    include_thoughts: bool = True,
) -> str:
    """Return a Gemini response for a non-empty prompt, or raise RuntimeError."""
    return ask_gemini_with_thoughts(
        prompt,
        history=history,
        timeout_ms=timeout_ms,
        thinking_level=thinking_level,
        include_thoughts=include_thoughts,
    ).answer
