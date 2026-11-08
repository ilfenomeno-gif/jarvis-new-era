from __future__ import annotations

import math
from typing import Protocol

from google import genai
from google.genai import types

from core.api_keys import gemini_api_key

TASK_MODEL = "gemini-flash-latest"


class _AsyncModels(Protocol):
    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> object: ...


class _AsyncClient(Protocol):
    models: _AsyncModels

    async def aclose(self) -> None: ...


class _Client(Protocol):
    aio: _AsyncClient


class WorkerLLM:
    """Provide isolated, text-only Gemini requests for silent task workers."""

    def __init__(self, client: _Client | None = None, model: str = TASK_MODEL):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self.model = model.strip()
        self._owns_client = client is None
        self._client = client
        self._closed = False

    def _get_client(self) -> _Client:
        if self._closed:
            raise RuntimeError("Worker LLM client is closed")
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @staticmethod
    def _create_client() -> _Client:
        key = gemini_api_key()
        if not key:
            raise RuntimeError("Gemini API key is not configured for task workers")
        return genai.Client(api_key=key)

    async def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float = 0.4,
    ) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be non-empty text")
        if not isinstance(system_instruction, str) or not system_instruction.strip():
            raise ValueError("system_instruction must be non-empty text")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
            or not 0 <= temperature <= 2
        ):
            raise ValueError("temperature must be a finite number from 0 to 2")

        response = await self._get_client().aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=float(temperature),
            ),
        )
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Gemini returned no text for the task worker")
        return text.strip()

    async def close(self) -> None:
        """Close the async client only when this instance created it."""
        if self._owns_client and not self._closed:
            self._closed = True
            if self._client is not None:
                await self._client.aio.aclose()
