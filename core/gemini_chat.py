"""Headless Gemini text-chat entry point shared by UI and integrations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google.genai import types

from core import gemini
from core.chat_formatting import MARKDOWN_LIST_INSTRUCTION


@dataclass(frozen=True)
class GeminiChatResult:
    answer: str
    thought_summaries: tuple[str, ...] = ()


def _thinking_config_is_unsupported(error: Exception) -> bool:
    current: BaseException | None = error
    while current is not None:
        code = getattr(current, "code", None) or getattr(current, "status_code", None)
        message = str(current).casefold()
        unsupported = "thinking" in message or "include_thoughts" in message
        if unsupported and (
            code in (400, "400", "INVALID_ARGUMENT")
            or "400" in message
        ):
            return True
        current = current.__cause__
    return False


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


def _conversation_prompt(prompt: str, history: list[dict] | None) -> str:
    turns = []
    for turn in history or []:
        role = turn.get("role")
        speaker = "User" if role == "user" else "Gemini"
        parts = turn.get("parts", [])
        text = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        )
        if text:
            turns.append(f"{speaker}: {text}")
    if not turns:
        return prompt
    return (
        "Conversation so far:\n"
        + "\n".join(turns)
        + f"\n\nCurrent message from user:\n{prompt}"
    )


def ask_gemini_with_thoughts(
    prompt: str,
    history: list[dict] | None = None,
    timeout_ms: int = 30_000,
    thinking_level: str = "high",
    include_thoughts: bool = True,
    on_chunk: Callable[[str], None] | None = None,
    system_instruction: str | None = None,
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
    if system_instruction is not None and (
        not isinstance(system_instruction, str) or not system_instruction.strip()
    ):
        raise RuntimeError("Gemini system_instruction must be a non-empty string.")

    contents = _conversation_prompt(prompt, history)
    config = types.GenerateContentConfig(
        system_instruction=(system_instruction or (
            "You are JARVIS, the user's helpful AI assistant. Respond naturally "
            "to the current message, use the conversation history when relevant, "
            "and answer in the user's language. Do not claim that you are not "
            "JARVIS or that you are only a data-processing function. Be concise "
            "unless the user asks for detail."
        )) + "\n\n" + MARKDOWN_LIST_INSTRUCTION,
        thinking_config=types.ThinkingConfig(
            thinking_level=level,
            include_thoughts=include_thoughts,
        )
    )

    streamed_chunks: list[str] = []

    def generate(config_to_use):
        if on_chunk is None:
            kwargs = {
                "tier": gemini.CHAT,
                "timeout_ms": timeout_ms,
                "raise_on_failure": True,
            }
            if config_to_use is not None:
                kwargs["config"] = config_to_use
            return gemini.call(contents, **kwargs)
        kwargs = {"tier": gemini.CHAT, "timeout_ms": timeout_ms}
        if config_to_use is not None:
            kwargs["config"] = config_to_use
        for chunk in gemini.stream(contents, **kwargs):
            text = getattr(chunk, "text", None)
            if isinstance(text, str) and text:
                streamed_chunks.append(text)
                on_chunk(text)
        return None

    try:
        response = generate(config)
    except Exception as exc:
        if streamed_chunks:
            raise RuntimeError(
                f"Gemini streaming failed after partial output: {exc}"
            ) from exc
        if _thinking_config_is_unsupported(exc):
            try:
                response = generate(types.GenerateContentConfig(
                    system_instruction=config.system_instruction,
                ))
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Gemini request failed: {fallback_exc}"
                ) from fallback_exc
        else:
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    if on_chunk is not None:
        answer = "".join(streamed_chunks)
        thought_summaries = ()
    else:
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
    system_instruction: str | None = None,
) -> str:
    """Return a Gemini response for a non-empty prompt, or raise RuntimeError."""
    return ask_gemini_with_thoughts(
        prompt,
        history=history,
        timeout_ms=timeout_ms,
        thinking_level=thinking_level,
        include_thoughts=include_thoughts,
        system_instruction=system_instruction,
    ).answer
