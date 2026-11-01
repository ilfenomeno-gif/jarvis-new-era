import json

import pytest

from core.brain_router import (
    BrainRouter,
    DEFAULT_OLLAMA_MODEL,
    ollama_tool_declarations,
    resolve_ollama_model,
)


def test_switch_local_and_gemini():
    router = BrainRouter(backend="gemini")
    assert router.switch("local") == "Brain switched to local"
    assert router.backend == "local"
    assert router.switch("gemini") == "Brain switched to gemini"
    with pytest.raises(ValueError):
        router.switch("openai")


def test_default_ollama_model_is_valid(monkeypatch):
    monkeypatch.delenv("JARVIS_OLLAMA_MODEL", raising=False)
    assert resolve_ollama_model() == DEFAULT_OLLAMA_MODEL

    monkeypatch.setenv("JARVIS_OLLAMA_MODEL", "mistral:latest")
    assert resolve_ollama_model() == "mistral:latest"


def test_ollama_tool_declarations_use_lowercase_json_schema_types():
    tools = ollama_tool_declarations([{
        "name": "open_app",
        "description": "Open an app",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING"},
                "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["app_name"],
        },
    }])

    assert tools == [{
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open an app",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["app_name"],
            },
        },
    }]


def test_stream_ollama_yields_content_and_done(monkeypatch):
    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({"message": {"content": "Ciao"}, "done": False})
            yield json.dumps({"message": {"content": " mondo"}, "done": True})

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: FakeStream())

    router = BrainRouter(backend="local")
    events = list(router.stream_chat([{"role": "user", "content": "test"}]))

    assert events[0] == {"type": "content", "text": "Ciao"}
    assert events[1] == {"type": "content", "text": " mondo"}
    assert events[-1] == {"type": "done", "full_text": "Ciao mondo"}


def test_stream_ollama_yields_tool_calls(monkeypatch):
    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {
                    "tool_calls": [{
                        "id": "call-1",
                        "function": {
                            "name": "open_app",
                            "arguments": {"app_name": "Notepad"},
                        }
                    }]
                },
                "done": True,
            })

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: FakeStream())
    router = BrainRouter(backend="local")
    events = list(router.stream_chat([{"role": "user", "content": "test"}], tools=[{"name": "open_app"}]))

    assert events[0] == {
        "type": "tool_call",
        "id": "call-1",
        "name": "open_app",
        "args": {"app_name": "Notepad"},
    }
    assert events[1] == {"type": "done", "full_text": ""}
