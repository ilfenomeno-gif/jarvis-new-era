from types import SimpleNamespace

import pytest

from benchmarks.bench_ttft_live import TTFT_METRIC_SEMANTICS
from providers import engine_pipeline
from providers.engine_pipeline import PipelineEngine


def test_ttft_metric_semantics_distinguish_first_content_from_completion():
    assert "first non-empty content event" in TTFT_METRIC_SEMANTICS["stream.*"]
    buffered_semantics = TTFT_METRIC_SEMANTICS["buffered.*"]
    assert "full response" in buffered_semantics
    assert "not time to first token" in buffered_semantics


def _spoken_text(message) -> str | None:
    content = message.server_content
    if content is None or content.output_transcription is None:
        return None
    return content.output_transcription.text


@pytest.mark.asyncio
async def test_first_sentence_is_emitted_before_stream_completion(
    fake_clock, fake_streaming_provider, monkeypatch
):
    monkeypatch.setattr(
        engine_pipeline,
        "time",
        SimpleNamespace(monotonic=fake_clock),
    )
    engine = PipelineEngine(
        fake_streaming_provider,
        timeout=10,
        retries=0,
    )
    engine._print_timing = lambda: None
    emission_times = []
    emit = engine._emit

    async def record_emission(message):
        if _spoken_text(message) is not None:
            emission_times.append(fake_clock())
        await emit(message)

    engine._emit = record_emission

    try:
        await engine.send_client_content(
            turns={"parts": [{"text": "Rispondi con due frasi."}]}
        )
        first_generation = engine._gen
        assert first_generation is not None
        await fake_streaming_provider.started.wait()

        message = await engine._queue.get()
        assert _spoken_text(message) == "Prima frase."
        assert not fake_streaming_provider.completed.is_set()

        fake_streaming_provider.release_tail.set()
        await first_generation
        assert engine._timing["llm_first"] == pytest.approx(0.125)
        assert emission_times[0] == pytest.approx(0.25)
        remaining = []
        while not engine._queue.empty():
            remaining.append(engine._queue.get_nowait())
        assert any(
            (text := _spoken_text(item)) is not None
            and text.startswith("Seconda frase.")
            for item in remaining
        )
    finally:
        fake_streaming_provider.release_tail.set()
        await engine.close()


@pytest.mark.asyncio
async def test_two_rapid_submissions_are_serialized_without_dropping_input(
    fake_streaming_provider,
):
    engine = PipelineEngine(fake_streaming_provider, timeout=10, retries=0)
    engine._print_timing = lambda: None
    try:
        await engine.send_client_content(
            turns={"parts": [{"text": "Primo messaggio"}]}
        )
        first_generation = engine._gen
        assert first_generation is not None
        await fake_streaming_provider.started.wait()

        await engine.send_client_content(
            turns={"parts": [{"text": "Secondo messaggio"}]}
        )
        fake_streaming_provider.release_tail.set()
        await first_generation

        second_generation = engine._gen
        assert second_generation is not None
        await second_generation

        assert fake_streaming_provider.calls == 2
        assert fake_streaming_provider.max_active_calls == 1
        assert [item["content"] for item in fake_streaming_provider.messages[0]
                if item["role"] == "user"] == ["Primo messaggio"]
        assert [item["content"] for item in fake_streaming_provider.messages[1]
                if item["role"] == "user"] == [
                    "Primo messaggio",
                    "Secondo messaggio",
                ]
    finally:
        fake_streaming_provider.release_tail.set()
        await engine.close()
