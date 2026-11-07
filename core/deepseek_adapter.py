from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class DeepSeekAdapter:
    name = "deepseek"

    @staticmethod
    def _client(api_key: str):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("DeepSeek adapter requires the existing openai package.") from exc
        return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    def chat(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> str:
        if kw.get("tools"):
            raise NotImplementedError("This facade method does not return tool calls.")
        response = self._client(kw["api_key"]).chat.completions.create(
            model=model,
            messages=messages,
            temperature=kw.get("temperature", 0.7),
            max_tokens=kw.get("max_output_tokens"),
            timeout=kw.get("timeout", 45),
        )
        return response.choices[0].message.content or ""

    def stream(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> Iterator[str]:
        if kw.get("tools"):
            raise NotImplementedError("This facade stream returns text only.")
        response = self._client(kw["api_key"]).chat.completions.create(
            model=model,
            messages=messages,
            temperature=kw.get("temperature", 0.7),
            max_tokens=kw.get("max_output_tokens"),
            timeout=kw.get("timeout", 45),
            stream=True,
        )
        for chunk in response:
            text = chunk.choices[0].delta.content
            if text:
                yield text

    def json(
        self, messages: list[dict[str, Any]], schema: dict, model: str, **kw: Any
    ) -> dict:
        del messages, schema, model, kw
        raise NotImplementedError("DeepSeek adapter does not enforce JSON schemas.")

    def vision(
        self, messages: list[dict[str, Any]], images: list[Any], model: str, **kw: Any
    ) -> str:
        del messages, images, model, kw
        raise NotImplementedError("DeepSeek text adapter does not expose vision.")

    def health(self) -> dict:
        return {"provider": self.name, "ok": True}
