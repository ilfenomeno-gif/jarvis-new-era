"""Headless tests for the reusable Gemini chat function."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import gemini_chat


def test_ask_gemini_returns_stripped_response_and_uses_chat_model(monkeypatch):
    generate_content = Mock(return_value=SimpleNamespace(text="  Gemini reply \n"))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    create_client = Mock(return_value=client)
    monkeypatch.setattr(gemini_chat.gemini, "client", create_client)

    result = gemini_chat.ask_gemini("  Hello Gemini  ")

    create_client.assert_called_once_with(timeout_ms=30_000)
    generate_content.assert_called_once_with(
        model=gemini_chat.CHAT_MODEL,
        contents=[
            {"role": "user", "parts": [{"text": "  Hello Gemini  "}]},
        ],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.HIGH,
                include_thoughts=True,
            )
        ),
    )
    assert result == "Gemini reply"


def test_ask_gemini_includes_conversation_history_in_payload(monkeypatch):
    history = [
        {"role": "user", "parts": [{"text": "Earlier question"}]},
        {"role": "model", "parts": [{"text": "Earlier answer"}]},
    ]
    generate_content = Mock(return_value=SimpleNamespace(text="Follow-up answer"))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    result = gemini_chat.ask_gemini(
        "Follow-up question",
        history=history,
    )

    generate_content.assert_called_once_with(
        model=gemini_chat.CHAT_MODEL,
        contents=[
            *history,
            {"role": "user", "parts": [{"text": "Follow-up question"}]},
        ],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.HIGH,
                include_thoughts=True,
            )
        ),
    )
    assert result == "Follow-up answer"


def test_ask_gemini_does_not_mutate_history(monkeypatch):
    history = [{"role": "user", "parts": [{"text": "Earlier question"}]}]
    original_history = [dict(turn) for turn in history]
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(text="Reply")))
    )
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    gemini_chat.ask_gemini("Follow-up", history=history)

    assert history == original_history


def test_ask_gemini_passes_configured_timeout(monkeypatch):
    generate_content = Mock(return_value=SimpleNamespace(text="Reply"))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    create_client = Mock(return_value=client)
    monkeypatch.setattr(gemini_chat.gemini, "client", create_client)

    assert gemini_chat.ask_gemini("Hello", timeout_ms=12_345) == "Reply"

    create_client.assert_called_once_with(timeout_ms=12_345)


def test_ask_gemini_extracts_provider_thought_summaries(monkeypatch):
    response = SimpleNamespace(
        text="Final answer",
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="Short provider summary", thought=True),
                        SimpleNamespace(text="Final answer", thought=False),
                    ]
                )
            )
        ],
    )
    generate_content = Mock(return_value=response)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    result = gemini_chat.ask_gemini_with_thoughts("Explain a concept")

    assert result.answer == "Final answer"
    assert result.thought_summaries == ("Short provider summary",)
    config = generate_content.call_args.kwargs["config"]
    assert config.thinking_config.thinking_level == types.ThinkingLevel.HIGH
    assert config.thinking_config.include_thoughts is True


def test_ask_gemini_does_not_return_thoughts_when_disabled(monkeypatch):
    response = SimpleNamespace(
        text="Final answer",
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="Provider thought", thought=True),
                        SimpleNamespace(text="Final answer", thought=False),
                    ]
                )
            )
        ],
    )
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=Mock(return_value=response))
    )
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    result = gemini_chat.ask_gemini_with_thoughts(
        "Explain a concept",
        include_thoughts=False,
    )

    assert result.answer == "Final answer"
    assert result.thought_summaries == ()


def test_ask_gemini_uses_requested_thinking_level(monkeypatch):
    generate_content = Mock(return_value=SimpleNamespace(text="Quick answer"))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    assert gemini_chat.ask_gemini(
        "Open settings",
        thinking_level="low",
        include_thoughts=False,
    ) == "Quick answer"

    config = generate_content.call_args.kwargs["config"]
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert config.thinking_config.include_thoughts is False


def test_ask_gemini_retries_without_unsupported_thinking_config(monkeypatch):
    class UnsupportedThinkingError(Exception):
        code = 400

    generate_content = Mock(
        side_effect=[
            UnsupportedThinkingError("thinking_config is not supported"),
            SimpleNamespace(text="Fallback answer"),
        ]
    )
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    assert gemini_chat.ask_gemini("Hello") == "Fallback answer"

    assert generate_content.call_count == 2
    assert "config" in generate_content.call_args_list[0].kwargs
    assert "config" not in generate_content.call_args_list[1].kwargs


def test_ask_gemini_does_not_retry_unrelated_api_errors(monkeypatch):
    class ProviderUnavailableError(Exception):
        code = 503

    generate_content = Mock(side_effect=ProviderUnavailableError("unavailable"))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    with pytest.raises(RuntimeError, match="Gemini request failed: unavailable"):
        gemini_chat.ask_gemini("Hello")

    generate_content.assert_called_once()


def test_ask_gemini_wraps_client_errors_as_runtime_error(monkeypatch):
    monkeypatch.setattr(
        gemini_chat.gemini,
        "client",
        Mock(side_effect=OSError("service unavailable")),
    )

    with pytest.raises(RuntimeError, match="Gemini request failed: service unavailable"):
        gemini_chat.ask_gemini("Hello")


def test_ask_gemini_rejects_empty_response(monkeypatch):
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(text=" ")))
    )
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))

    with pytest.raises(RuntimeError, match="Gemini returned an empty response"):
        gemini_chat.ask_gemini("Hello")


@pytest.mark.parametrize("prompt", ["", "  ", None])
def test_ask_gemini_rejects_empty_or_non_string_prompt(prompt):
    with pytest.raises(RuntimeError, match="prompt must be a non-empty string"):
        gemini_chat.ask_gemini(prompt)


@pytest.mark.parametrize("timeout_ms", [0, -1, True, 1.5])
def test_ask_gemini_rejects_invalid_timeout(timeout_ms):
    with pytest.raises(RuntimeError, match="timeout_ms must be a positive integer"):
        gemini_chat.ask_gemini("Hello", timeout_ms=timeout_ms)
