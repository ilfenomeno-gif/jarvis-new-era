"""BrainRouter abstraction for the Jarvis LLM backend.

Supports the current Gemini Live path and a local Ollama backend that is used
for textual chat routing without duplicating the live API implementation.
"""
from __future__ import annotations

import json
import os
from typing import Any, Generator

import httpx

OLLAMA_URL = os.environ.get("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"


def resolve_ollama_model() -> str:
    return os.environ.get("JARVIS_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def ollama_tool_declarations(
    declarations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def normalize_schema(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    child.lower()
                    if key == "type" and isinstance(child, str)
                    else normalize_schema(child)
                )
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [normalize_schema(item) for item in value]
        return value

    return [
        {
            "type": "function",
            "function": {
                "name": declaration["name"],
                "description": declaration.get("description", ""),
                "parameters": normalize_schema(declaration.get("parameters", {})),
            },
        }
        for declaration in declarations
    ]


class BrainRouter:
    """Concrete backend switch for the conversational brain."""

    def __init__(self, backend: str | None = None):
        self.backend = backend or os.environ.get("JARVIS_BRAIN", "gemini")

    def switch(self, backend: str) -> str:
        if backend not in ("gemini", "local"):
            raise ValueError(f"Unknown brain backend: {backend}")
        self.backend = backend
        return f"Brain switched to {backend}"

    def model_name(self) -> str:
        return resolve_ollama_model()

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Yield conversation events from the active backend.

        The Gemini path remains handled in main.py; local mode uses Ollama's HTTP
        chat API and emits lightweight events for UI layering.
        """
        if self.backend == "local":
            yield from self._stream_ollama(messages, tools)
            return
        raise NotImplementedError(
            "Gemini path is handled by the existing Live API in main.py. Do not duplicate."
        )

    def _stream_ollama(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        payload: dict[str, Any] = {
            "model": resolve_ollama_model(),
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        with httpx.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=300.0,
        ) as response:
            response.raise_for_status()
            full_text = ""
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                content = msg.get("content", "")
                if content:
                    full_text += content
                    yield {"type": "content", "text": content}
                for tool_call in msg.get("tool_calls", []) or []:
                    fn = tool_call.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    yield {
                        "type": "tool_call",
                        "id": tool_call.get("id"),
                        "name": fn.get("name"),
                        "args": args,
                    }
                if chunk.get("done"):
                    yield {"type": "done", "full_text": full_text}
                    return


def get_router() -> BrainRouter:
    return BrainRouter()
