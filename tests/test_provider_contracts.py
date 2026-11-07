from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from providers.base import FunctionCall
from providers.engine_pipeline import PipelineEngine
from providers.llm_openai import _ToolCallBuffer
from providers.retry import retry_call, retry_stream, validate_retries, validate_timeout


class MockSTT:
    caps = {}

    def __init__(self):
        self.calls = 0
        self.received = None

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000, language: str = "") -> str:
        self.calls += 1
        self.received = (pcm, sample_rate, language)
        if self.calls == 1:
            raise httpx.ConnectError("temporary STT outage")
        return "open the browser"


class MockLLM:
    caps = {"tools": True, "tool_format": "openai"}

    def __init__(self):
        self.calls = 0
        self.messages = []
        self.tools = None

    async def chat(self, messages, tools=None, *, stream=True):
        self.calls += 1
        self.messages = messages
        self.tools = tools
        if self.calls == 1:
            raise httpx.ConnectError("temporary LLM outage")
        yield {"text": "Mock response."}


class MockTTS:
    caps = {}

    def __init__(self):
        self.calls = 0
        self.text = ""

    async def speak(self, text: str, voice: str = ""):
        self.calls += 1
        self.text = text
        if self.calls == 1:
            raise httpx.ConnectError("temporary TTS outage")
        yield b"\x00\x00" * 24


class MockLiveConfig:
    system_instruction = "You are a contract-test assistant."
    tools = [{
        "function_declarations": [{
            "name": "open_app",
            "description": "Open a named app.",
            "parameters": {
                "type": "OBJECT",
                "properties": {"app_name": {"type": "STRING"}},
                "required": ["app_name"],
            },
        }],
    }]


def _tracer():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("jarvis.provider.contracts"), exporter, provider


def test_provider_declarations_satisfy_discovery_contract():
    from providers import registry
    from providers.base import caps_of, validate

    declarations = registry.discover()
    assert {item["kind"] for item in declarations} >= {"engine", "llm", "stt", "tts"}
    for declaration in declarations:
        assert validate(declaration) == ""
        assert callable(declaration["factory"])
        assert caps_of(declaration)["tool_format"] in (
            None, "gemini", "openai", "anthropic", "prompt",
        )


def test_mock_provider_matrix_retries_and_emits_contract_spans():
    stt, llm, tts = MockSTT(), MockLLM(), MockTTS()
    tracer, exporter, provider = _tracer()

    async def run_turn():
        engine = PipelineEngine(
            llm,
            stt,
            tts,
            config=MockLiveConfig(),
            tracer=tracer,
            timeout=1,
            retries=1,
        )
        pcm = b"\x00\x00" * 4096
        await engine.send_realtime_input(audio=SimpleNamespace(data=pcm))
        transcript = await engine.flush_microphone()
        await asyncio.wait_for(engine._gen, timeout=1)
        messages = []
        while not engine._queue.empty():
            messages.append(engine._queue.get_nowait())
        await engine.close()
        return transcript, messages

    try:
        transcript, messages = asyncio.run(run_turn())
        assert transcript == "open the browser"
        assert stt.calls == llm.calls == tts.calls == 2
        assert stt.received == (b"\x00\x00" * 4096, 16000, "")
        assert llm.messages[-1] == {"role": "user", "content": transcript}
        assert llm.tools[0]["function"]["name"] == "open_app"
        assert llm.tools[0]["function"]["parameters"]["properties"]["app_name"]["type"] == "string"
        assert tts.text == "Mock response."
        assert any(
            message.server_content
            and message.server_content.input_transcription
            and message.server_content.input_transcription.text == transcript
            for message in messages
        )
        assert any(
            message.server_content
            and message.server_content.output_transcription
            and message.server_content.output_transcription.text == "Mock response."
            for message in messages
        )
        assert any(message.data == b"\x00\x00" * 24 for message in messages)
        assert any(
            message.server_content and message.server_content.turn_complete
            for message in messages
        )
        spans = exporter.get_finished_spans()
        names = {span.name for span in spans}
        assert {"voice.turn", "voice.stt", "voice.llm", "voice.tts"} <= names
        turn = next(span for span in spans if span.name == "voice.turn")
        for stage in ("voice.llm", "voice.tts"):
            span = next(span for span in spans if span.name == stage)
            assert span.parent.span_id == turn.context.span_id
    finally:
        provider.shutdown()


def test_local_session_warms_providers_before_accepting_a_turn(monkeypatch):
    from main import JarvisLive
    from memory import config_manager
    from providers import registry

    warmed = []
    monkeypatch.setattr(config_manager, "get_pipeline", lambda: {
        "llm": "mock-llm",
        "stt": "mock-stt",
        "tts": "mock-tts",
    })
    monkeypatch.setattr(config_manager, "get_provider_config", lambda _pid: {})
    monkeypatch.setattr(registry, "build", lambda _pid, _config: MockLLM())

    async def record_warmup(engine):
        warmed.append(engine)

    monkeypatch.setattr(PipelineEngine, "warmup", record_warmup)
    live = JarvisLive.__new__(JarvisLive)
    live._engine_caps = {}
    live._ptt_enabled = False
    live.ui = SimpleNamespace(write_log=lambda _message: None)

    async def run():
        async with live._open_session("unused", None) as engine:
            assert warmed == [engine]
            assert live._engine is engine
        assert live._engine is None

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["stt", "llm", "tts"])
def test_provider_contract_enforces_timeout_and_cancellation(stage):
    async def slow_call():
        await asyncio.sleep(10)
        return "too late"

    async def slow_stream():
        await asyncio.sleep(10)
        yield "too late"

    async def exercise():
        if stage == "stt":
            await retry_call(slow_call, retries=0, timeout=0.01)
            return
        async for _ in retry_stream(slow_stream, retries=0, timeout=0.01):
            pass

    with pytest.raises(TimeoutError):
        asyncio.run(exercise())


def test_stream_retry_stops_after_first_visible_chunk():
    attempts = 0

    async def partial_then_fail():
        nonlocal attempts
        attempts += 1
        yield {"text": "Already spoken."}
        raise httpx.ReadError("stream disconnected")

    async def consume():
        return [event async for event in retry_stream(partial_then_fail, retries=2)]

    with pytest.raises(httpx.ReadError):
        asyncio.run(consume())
    assert attempts == 1


def test_invalid_tool_json_is_recovered_or_safely_empty():
    buffer = _ToolCallBuffer()
    buffer.feed([{
        "index": 0,
        "id": "call_valid",
        "function": {
            "name": "open_app",
            "arguments": 'prefix {"app_name":"browser"} suffix',
        },
    }])
    buffer.feed([{
        "index": 1,
        "id": "call_invalid",
        "function": {"name": "open_app", "arguments": '{"app_name":'},
    }])

    calls = buffer.drain()
    assert [(call.id, call.args) for call in calls] == [
        ("call_valid", {"app_name": "browser"}),
        ("call_invalid", {}),
    ]


@pytest.mark.parametrize("value", [-1, 4, True, "1.5", "bad"])
def test_provider_retry_configuration_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_retries(value)


@pytest.mark.parametrize("value", [0, -1, float("inf"), True, "bad"])
def test_provider_timeout_configuration_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_timeout(value)


def test_voice_tool_calls_have_named_error_spans(monkeypatch):
    from opentelemetry import trace

    import main

    tracer, exporter, provider = _tracer()
    monkeypatch.setattr(trace, "get_tracer", lambda _name: tracer)

    class Runner:
        async def _execute_tool(self, _call):
            raise RuntimeError("tool failed")

    try:
        with pytest.raises(RuntimeError, match="tool failed"):
            asyncio.run(
                main.JarvisLive._execute_voice_tool(
                    Runner(), FunctionCall(name="open_app", args={})
                )
            )
        span = next(span for span in exporter.get_finished_spans() if span.name == "voice.tool")
        assert span.attributes["tool.name"] == "open_app"
        assert span.status.status_code.name == "ERROR"
    finally:
        provider.shutdown()
