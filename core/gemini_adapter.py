from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from core.llm_adapter_utils import messages_to_gemini


class GeminiAdapter:
    name = "gemini"

    @staticmethod
    def _tier(model: str, kw: dict[str, Any]) -> str:
        tier = kw.get("tier")
        if tier:
            return tier
        if model in ("fast", "smart", "search"):
            return model
        return "smart" if kw.get("role") == "vision" else "fast"

    def chat(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> str:
        from core import gemini

        contents, system = messages_to_gemini(messages)
        tier = self._tier(model, kw)
        config = dict(kw.get("config") or {})
        if system and "system_instruction" not in config:
            config["system_instruction"] = system
        if kw.get("temperature") is not None:
            config.setdefault("temperature", kw["temperature"])
        if kw.get("max_output_tokens") is not None:
            config.setdefault("max_output_tokens", kw["max_output_tokens"])
        result = gemini.text(
            contents,
            tier=tier,
            config=config or None,
            timeout_ms=int(kw.get("timeout", 45) * 1000),
            key=kw.get("api_key", ""),
        )
        if not result:
            raise RuntimeError("Gemini returned no text.")
        return result

    def stream(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> Iterator[str]:
        raise NotImplementedError("Gemini one-shot ladder does not expose streaming.")

    def json(
        self, messages: list[dict[str, Any]], schema: dict, model: str, **kw: Any
    ) -> dict:
        from core import gemini

        contents, system = messages_to_gemini(messages)
        tier = self._tier(model, kw)
        config = dict(kw.get("config") or {})
        if system and "system_instruction" not in config:
            config["system_instruction"] = system
        if kw.get("temperature") is not None:
            config.setdefault("temperature", kw["temperature"])
        if kw.get("max_output_tokens") is not None:
            config.setdefault("max_output_tokens", kw["max_output_tokens"])
        config["response_mime_type"] = "application/json"
        config["response_schema"] = schema
        value = gemini.as_json(
            contents,
            tier=tier,
            config=config,
            timeout_ms=int(kw.get("timeout", 45) * 1000),
            key=kw.get("api_key", ""),
        )
        if not isinstance(value, dict):
            raise TypeError("Gemini returned no valid JSON object.")
        return value

    def vision(
        self, messages: list[dict[str, Any]], images: list[Any], model: str, **kw: Any
    ) -> str:
        from core import gemini

        contents, system = messages_to_gemini(messages)
        tier = self._tier(model, kw)
        if not contents:
            contents = [{"role": "user", "parts": []}]
        contents[-1]["parts"].extend(images)
        config = dict(kw.get("config") or {})
        if system and "system_instruction" not in config:
            config["system_instruction"] = system
        if kw.get("temperature") is not None:
            config.setdefault("temperature", kw["temperature"])
        if kw.get("max_output_tokens") is not None:
            config.setdefault("max_output_tokens", kw["max_output_tokens"])
        result = gemini.text(
            contents,
            tier=tier,
            config=config or None,
            timeout_ms=int(kw.get("timeout", 45) * 1000),
            key=kw.get("api_key", ""),
        )
        if not result:
            raise RuntimeError("Gemini returned no vision response.")
        return result

    def health(self) -> dict:
        return {"provider": self.name, "ok": True, "mode": "one-shot"}
