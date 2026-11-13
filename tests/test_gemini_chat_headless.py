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


def test_ask_gemini_returns_stripped_response_and_uses_chat_fallback(monkeypatch):
    call = Mock(return_value=SimpleNamespace(text="  Gemini reply \n"))
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    result = gemini_chat.ask_gemini("  Hello Gemini  ")

    call.assert_called_once()
    assert call.call_args.args[0] == "  Hello Gemini  "
    assert call.call_args.kwargs["tier"] == gemini_chat.gemini.CHAT
    assert call.call_args.kwargs["timeout_ms"] == 30_000
    assert call.call_args.kwargs["raise_on_failure"] is True
    config = call.call_args.kwargs["config"]
    assert "You are JARVIS" in config.system_instruction
    assert config.thinking_config.thinking_level == types.ThinkingLevel.HIGH
    assert config.thinking_config.include_thoughts is True
    assert result == "Gemini reply"


def test_ask_gemini_includes_conversation_history_in_payload(monkeypatch):
    history = [
        {"role": "user", "parts": [{"text": "Earlier question"}]},
        {"role": "model", "parts": [{"text": "Earlier answer"}]},
    ]
    call = Mock(return_value=SimpleNamespace(text="Follow-up answer"))
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    result = gemini_chat.ask_gemini(
        "Follow-up question",
        history=history,
    )

    assert call.call_args.args[0] == (
        "Conversation so far:\n"
        "User: Earlier question\n"
        "Gemini: Earlier answer\n\n"
        "Current message from user:\n"
        "Follow-up question"
    )
    assert call.call_args.kwargs["tier"] == gemini_chat.gemini.CHAT
    assert result == "Follow-up answer"


def test_ask_gemini_does_not_mutate_history(monkeypatch):
    history = [{"role": "user", "parts": [{"text": "Earlier question"}]}]
    original_history = [dict(turn) for turn in history]
    monkeypatch.setattr(
        gemini_chat.gemini,
        "call",
        Mock(return_value=SimpleNamespace(text="Reply")),
    )

    gemini_chat.ask_gemini("Follow-up", history=history)

    assert history == original_history


def test_ask_gemini_uses_context_specific_system_instruction(monkeypatch):
    call = Mock(return_value=SimpleNamespace(text="Map answer"))
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    gemini_chat.ask_gemini(
        "Where is Rome?",
        system_instruction="You are the independent GEV map assistant.",
    )

    instruction = call.call_args.kwargs["config"].system_instruction
    assert instruction.startswith("You are the independent GEV map assistant.")
    assert "- Elemento 1\n- Elemento 2" in instruction


def test_streaming_chat_delivers_text_as_chunks_without_live_rung(monkeypatch):
    observed = []
    monkeypatch.setattr(
        gemini_chat.gemini,
        "stream",
        lambda *_args, **_kwargs: iter([
            SimpleNamespace(text="Prima "),
            SimpleNamespace(text="frase."),
        ]),
    )

    result = gemini_chat.ask_gemini_with_thoughts(
        "Ciao",
        on_chunk=observed.append,
    )

    assert observed == ["Prima ", "frase."]
    assert result.answer == "Prima frase."
    assert result.thought_summaries == ()


def test_stream_falls_back_only_before_first_chunk(monkeypatch):
    from core import gemini

    monkeypatch.setattr(gemini, "_LADDERS", {gemini.CHAT: (gemini.LIVE, "first", "second")})
    monkeypatch.setattr(gemini, "_cooling", lambda _model: False)
    calls = []

    class Models:
        def generate_content_stream(self, *, model, **_kwargs):
            calls.append(model)
            if model == "first":
                raise RuntimeError("model unavailable")
            return iter([SimpleNamespace(text="answer")])

    monkeypatch.setattr(
        gemini,
        "client",
        lambda **_kwargs: SimpleNamespace(models=Models()),
    )

    chunks = list(gemini.stream("prompt", key="test-key"))

    assert calls == ["first", "second"]
    assert [chunk.text for chunk in chunks] == ["answer"]


def test_stream_does_not_retry_after_partial_output(monkeypatch):
    from core import gemini

    monkeypatch.setattr(gemini, "_LADDERS", {gemini.CHAT: (gemini.LIVE, "first", "second")})
    monkeypatch.setattr(gemini, "_cooling", lambda _model: False)
    calls = []

    def broken_stream():
        yield SimpleNamespace(text="partial")
        raise RuntimeError("connection lost")

    class Models:
        def generate_content_stream(self, *, model, **_kwargs):
            calls.append(model)
            return broken_stream()

    monkeypatch.setattr(
        gemini,
        "client",
        lambda **_kwargs: SimpleNamespace(models=Models()),
    )

    with pytest.raises(RuntimeError, match="after partial output"):
        list(gemini.stream("prompt", key="test-key"))

    assert calls == ["first"]


def test_ask_gemini_passes_configured_timeout(monkeypatch):
    call = Mock(return_value=SimpleNamespace(text="Reply"))
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    assert gemini_chat.ask_gemini("Hello", timeout_ms=12_345) == "Reply"

    assert call.call_args.kwargs["timeout_ms"] == 12_345


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
    call = Mock(return_value=response)
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    result = gemini_chat.ask_gemini_with_thoughts("Explain a concept")

    assert result.answer == "Final answer"
    assert result.thought_summaries == ("Short provider summary",)
    config = call.call_args.kwargs["config"]
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
    monkeypatch.setattr(
        gemini_chat.gemini,
        "call",
        Mock(return_value=response),
    )

    result = gemini_chat.ask_gemini_with_thoughts(
        "Explain a concept",
        include_thoughts=False,
    )

    assert result.answer == "Final answer"
    assert result.thought_summaries == ()


def test_ask_gemini_uses_requested_thinking_level(monkeypatch):
    call = Mock(return_value=SimpleNamespace(text="Quick answer"))
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    assert gemini_chat.ask_gemini(
        "Open settings",
        thinking_level="low",
        include_thoughts=False,
    ) == "Quick answer"

    config = call.call_args.kwargs["config"]
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert config.thinking_config.include_thoughts is False


def test_ask_gemini_retries_without_unsupported_thinking_config(monkeypatch):
    call = Mock(
        side_effect=[
            RuntimeError("gemini-3.8-flash: 400 thinking_config is not supported"),
            SimpleNamespace(text="Fallback answer"),
        ]
    )
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    assert gemini_chat.ask_gemini("Hello") == "Fallback answer"

    assert call.call_count == 2
    assert "config" in call.call_args_list[0].kwargs
    fallback_config = call.call_args_list[1].kwargs["config"]
    assert fallback_config.thinking_config is None
    assert "- Elemento 1\n- Elemento 2" in fallback_config.system_instruction


def test_ask_gemini_does_not_retry_unrelated_api_errors(monkeypatch):
    call = Mock(side_effect=RuntimeError("models unavailable"))
    monkeypatch.setattr(gemini_chat.gemini, "call", call)

    with pytest.raises(RuntimeError, match="Gemini request failed: models unavailable"):
        gemini_chat.ask_gemini("Hello")

    call.assert_called_once()


def test_ask_gemini_wraps_client_errors_as_runtime_error(monkeypatch):
    monkeypatch.setattr(
        gemini_chat.gemini,
        "call",
        Mock(side_effect=OSError("service unavailable")),
    )

    with pytest.raises(RuntimeError, match="Gemini request failed: service unavailable"):
        gemini_chat.ask_gemini("Hello")


def test_ask_gemini_rejects_empty_response(monkeypatch):
    monkeypatch.setattr(
        gemini_chat.gemini,
        "call",
        Mock(return_value=SimpleNamespace(text=" ")),
    )

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


def test_chat_fallback_tries_alternative_models_after_provider_errors(monkeypatch):
    models = Mock(
        side_effect=[
            RuntimeError("503 unavailable"),
            SimpleNamespace(text="Fallback answer"),
        ]
    )
    client = SimpleNamespace(models=SimpleNamespace(generate_content=models))
    monkeypatch.setattr(gemini_chat.gemini, "api_key", lambda: "test-key")
    live_call = Mock(side_effect=RuntimeError("Live unavailable"))
    monkeypatch.setattr(gemini_chat.gemini, "_live_call", live_call)
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))
    monkeypatch.setattr(gemini_chat.gemini, "_cooling", lambda _model: False)
    monkeypatch.setattr(gemini_chat.gemini, "_cool", lambda _model: None)

    response = gemini_chat.gemini.call(
        "Hello",
        tier=gemini_chat.gemini.CHAT,
        raise_on_failure=True,
    )

    assert response.text == "Fallback answer"
    assert [
        item.kwargs["model"] for item in models.call_args_list
    ] == ["gemini-3.8-flash", "gemini-3.7-flash"]
    assert live_call.call_args.kwargs["conversational"] is True


def test_chat_fallback_surfaces_all_provider_failures(monkeypatch):
    models = Mock(side_effect=RuntimeError("503 unavailable"))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=models))
    monkeypatch.setattr(gemini_chat.gemini, "api_key", lambda: "test-key")
    monkeypatch.setattr(gemini_chat.gemini, "_live_call", Mock(
        side_effect=RuntimeError("Live unavailable")
    ))
    monkeypatch.setattr(gemini_chat.gemini, "client", Mock(return_value=client))
    monkeypatch.setattr(gemini_chat.gemini, "_cooling", lambda _model: False)
    monkeypatch.setattr(gemini_chat.gemini, "_cool", lambda _model: None)

    with pytest.raises(RuntimeError, match="All Gemini fallback models failed"):
        gemini_chat.gemini.call(
            "Hello",
            tier=gemini_chat.gemini.CHAT,
            raise_on_failure=True,
        )

    assert models.call_count == 4
