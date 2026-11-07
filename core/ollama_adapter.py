from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class OllamaAdapter:
    name = "ollama"

    @staticmethod
    def _router():
        from core.brain_router import BrainRouter

        return BrainRouter(backend="local")

    def chat(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> str:
        del model
        full_text = ""
        for event in self._router().stream_chat(messages, kw.get("tools")):
            if event.get("type") == "content":
                full_text += event.get("text", "")
            elif event.get("type") == "tool_call":
                raise NotImplementedError(
                    "Use BrainRouter stream events to receive Ollama tool calls."
                )
            elif event.get("type") == "done":
                return event.get("full_text", full_text)
        return full_text

    def stream(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> Iterator[str]:
        for event in self.stream_events(messages, model, **kw):
            if event.get("type") == "content" and event.get("text"):
                yield event["text"]
            elif event.get("type") == "tool_call":
                raise NotImplementedError(
                    "Use stream_events() to receive Ollama tool calls."
                )

    def stream_events(
        self, messages: list[dict[str, Any]], model: str, **kw: Any
    ) -> Iterator[dict[str, Any]]:
        del model
        yield from self._router().stream_chat(messages, kw.get("tools"))

    def json(
        self, messages: list[dict[str, Any]], schema: dict, model: str, **kw: Any
    ) -> dict:
        del messages, schema, model, kw
        raise NotImplementedError(
            "The existing BrainRouter API does not enforce a JSON schema."
        )

    def vision(
        self, messages: list[dict[str, Any]], images: list[Any], model: str, **kw: Any
    ) -> str:
        del messages, images, model, kw
        raise NotImplementedError("Ollama BrainRouter adapter does not expose vision.")

    def health(self) -> dict:
        return {"provider": self.name, "ok": True, "mode": "local"}
