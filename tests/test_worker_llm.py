from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.worker_llm import WorkerLLM


class _FakeModels:
    def __init__(self, response_text: str | None = "  generated answer  "):
        self.response_text = response_text
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.response_text)


class _FakeAsyncClient:
    def __init__(self, models: _FakeModels):
        self.models = models
        self.closed = False

    async def aclose(self):
        self.closed = True


class _FakeClient:
    def __init__(self, models: _FakeModels):
        self.aio = _FakeAsyncClient(models)


@pytest.mark.asyncio
async def test_generate_text_uses_isolated_system_instruction():
    models = _FakeModels()
    llm = WorkerLLM(client=_FakeClient(models), model="test-model")

    result = await llm.generate_text(
        "Write a short poem",
        system_instruction="You are a silent writer.",
        temperature=0.7,
    )

    assert result == "generated answer"
    call = models.calls[0]
    assert call["model"] == "test-model"
    assert call["contents"] == "Write a short poem"
    assert call["config"].system_instruction == "You are a silent writer."
    assert call["config"].temperature == 0.7


@pytest.mark.asyncio
async def test_generate_text_rejects_empty_response():
    llm = WorkerLLM(client=_FakeClient(_FakeModels(response_text="  ")))

    with pytest.raises(RuntimeError, match="returned no text"):
        await llm.generate_text("Task", system_instruction="Worker role")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "instruction", "temperature"),
    [
        (" ", "Worker role", 0.4),
        ("Task", " ", 0.4),
        ("Task", "Worker role", float("nan")),
        ("Task", "Worker role", True),
    ],
)
async def test_generate_text_validates_inputs(prompt, instruction, temperature):
    llm = WorkerLLM(client=_FakeClient(_FakeModels()))

    with pytest.raises(ValueError):
        await llm.generate_text(
            prompt,
            system_instruction=instruction,
            temperature=temperature,
        )


@pytest.mark.asyncio
async def test_close_only_closes_owned_client(monkeypatch):
    from core import worker_llm

    models = _FakeModels()
    owned_client = _FakeClient(models)
    monkeypatch.setattr(worker_llm, "gemini_api_key", lambda: "test-key")
    monkeypatch.setattr(worker_llm.genai, "Client", lambda api_key: owned_client)

    owned = WorkerLLM()
    await owned.generate_text("Task", system_instruction="Worker role")
    injected_client = _FakeClient(models)
    injected = WorkerLLM(client=injected_client)
    await owned.close()
    await injected.close()

    assert owned_client.aio.closed
    assert not injected_client.aio.closed


@pytest.mark.asyncio
async def test_missing_api_key_fails_only_when_generation_is_requested(monkeypatch):
    from core import worker_llm

    monkeypatch.setattr(worker_llm, "gemini_api_key", lambda: "")
    llm = WorkerLLM()

    with pytest.raises(RuntimeError, match="API key is not configured"):
        await llm.generate_text("Task", system_instruction="Worker role")
