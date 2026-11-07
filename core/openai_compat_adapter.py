from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse


def _settings():
    from core.llm_client import get_llm_settings

    return get_llm_settings()


def _is_local(url: str) -> bool:
    return urlparse(url).hostname in {"localhost", "127.0.0.1", "::1"}


class OpenAICompatAdapter:
    name = "openai_compat"

    def requires_key(self) -> bool:
        url, _ = _settings()
        return not _is_local(url)

    @staticmethod
    def _remote_client(api_key: str):
        from openai import OpenAI

        url, _ = _settings()
        return OpenAI(api_key=api_key, base_url=url)

    def chat(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> str:
        url, configured_model = _settings()
        if not _is_local(url):
            response = self._remote_client(kw["api_key"]).chat.completions.create(
                model=model or configured_model,
                messages=messages,
                tools=kw.get("tools"),
                temperature=kw.get("temperature"),
                max_tokens=kw.get("max_output_tokens"),
                timeout=kw.get("timeout", 45),
            )
            message = response.choices[0].message
            if message.tool_calls:
                raise NotImplementedError("This facade method does not return tool calls.")
            return message.content or ""
        from core.llm_client import call_llm

        result = call_llm(
            messages,
            tools=kw.get("tools"),
            timeout=int(kw.get("timeout", 45)),
        )
        if result.get("tool_calls"):
            raise NotImplementedError("This facade method does not return tool calls.")
        return result.get("content", "")

    def stream(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> Iterator[str]:
        url, configured_model = _settings()
        if not _is_local(url):
            response = self._remote_client(kw["api_key"]).chat.completions.create(
                model=model or configured_model,
                messages=messages,
                tools=kw.get("tools"),
                temperature=kw.get("temperature"),
                max_tokens=kw.get("max_output_tokens"),
                timeout=kw.get("timeout", 45),
                stream=True,
            )
            for chunk in response:
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    raise NotImplementedError(
                        "This facade stream does not return tool calls."
                    )
                text = delta.content
                if text:
                    yield text
            return
        from core.llm_client import call_llm_stream

        for event in call_llm_stream(
            messages,
            tools=kw.get("tools"),
            timeout=int(kw.get("timeout", 45)),
        ):
            if event.get("type") == "sentence" and event.get("text"):
                yield event["text"]
            elif event.get("type") == "done" and event.get("tool_calls"):
                raise NotImplementedError(
                    "Use a tool-call capable adapter API to receive tool calls."
                )

    def json(
        self, messages: list[dict[str, Any]], schema: dict, model: str, **kw: Any
    ) -> dict:
        del messages, schema, model, kw
        raise NotImplementedError(
            "The existing OpenAI-compatible client does not enforce a JSON schema."
        )

    def vision(
        self, messages: list[dict[str, Any]], images: list[Any], model: str, **kw: Any
    ) -> str:
        del messages, images, model, kw
        raise NotImplementedError("OpenAI-compatible client does not expose vision.")

    def health(self) -> dict:
        from core.llm_client import get_llm_provider

        url, model = _settings()
        return {"provider": self.name, "ok": True, "backend": get_llm_provider(),
                "url": url, "model": model}
