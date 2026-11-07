from __future__ import annotations

import pytest

from providers.engine_pipeline import PipelineEngine


class FixedResponseLLM:
    caps = {"tools": False}

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    async def chat(self, messages, tools=None, *, stream=True):
        self.prompts.append(messages[-1]["content"])
        midpoint = max(1, len(self.response) // 2)
        yield {"text": self.response[:midpoint]}
        yield {"text": self.response[midpoint:]}


class RecordingTTS:
    caps = {}

    def __init__(self):
        self.texts: list[str] = []

    async def speak(self, text: str, voice: str = ""):
        self.texts.append(text)
        yield b"\x00\x00" * 24


@pytest.mark.parametrize(
    ("prompt", "response", "max_chars"),
    [
        ("Quanto fa 2+2?", "4.", 200),
        (
            "Spiega la fotosintesi in una frase.",
            "La fotosintesi trasforma luce, acqua e anidride carbonica in zuccheri e ossigeno.",
            400,
        ),
    ],
)
@pytest.mark.asyncio
async def test_fixed_prompt_tts_text_budget(prompt, response, max_chars):
    llm = FixedResponseLLM(response)
    tts = RecordingTTS()
    engine = PipelineEngine(llm, tts=tts, timeout=10, retries=0)
    engine._print_timing = lambda: None
    try:
        await engine.send_client_content(turns={"parts": [{"text": prompt}]})
        assert engine._gen is not None
        await engine._gen

        assert llm.prompts == [prompt]
        assert sum(len(text) for text in tts.texts) <= max_chars
        assert "".join(
            part.server_content.output_transcription.text
            for part in list(engine._queue._queue)
            if part.server_content and part.server_content.output_transcription
        ) == response
    finally:
        await engine.close()
