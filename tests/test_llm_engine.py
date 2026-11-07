from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from core import llm_budget, llm_events
from core.gemini_adapter import GeminiAdapter
from core.llm_context import with_context
from core.llm_engine import (
    LLMAuthError,
    LLMBudgetExceeded,
    LLMEngine,
    get_llm,
)


class FakeAdapter:
    def __init__(self, answer: str = "ok"):
        self.answer = answer
        self.models = []

    def chat(self, messages, model, **kwargs):
        self.models.append(model)
        return self.answer

    def stream(self, messages, model, **kwargs):
        self.models.append(model)
        return iter(["one", " two"])

    def health(self):
        return {"ok": True}


def _engine(adapter=None, **role_policy):
    adapter = adapter or FakeAdapter()
    role_policy = role_policy or {"planner": {"provider": "fake", "model": "planner-v1"}}
    policy = {
        "providers": {"fake": {}},
        "roles": role_policy,
        "defaults": {"timeout_seconds": 1, "retries": 0},
        "budget": {"max_tokens_session": 0, "max_cost_day": 0, "warn_ratio": 0.8},
    }
    return LLMEngine(policy, {"fake": adapter}), adapter


def test_get_llm_singleton_thread_safe():
    with ThreadPoolExecutor(max_workers=10) as pool:
        engines = list(pool.map(lambda _: get_llm(), range(10)))
    assert all(engine is engines[0] for engine in engines)


def test_chat_uses_policy_role():
    engine, adapter = _engine()
    assert engine.chat([{"role": "user", "content": "hello"}], role="planner") == "ok"
    assert adapter.models == ["planner-v1"]


def test_gemini_adapter_uses_existing_fast_ladder(monkeypatch):
    observed = {}

    def fake_text(contents, **kwargs):
        observed.update(kwargs)
        return "hello"

    monkeypatch.setattr("core.gemini.text", fake_text)
    result = GeminiAdapter().chat(
        [{"role": "user", "content": "hello"}],
        "gemini-2.5-flash",
        tier="fast",
        role="planner",
        api_key="test-key",
    )
    assert result == "hello"
    assert observed["tier"] == "fast"
    assert observed["key"] == "test-key"


def test_budget_exceeded_blocks_second_call():
    engine, adapter = _engine()
    session = "budget-test-session"
    llm_budget.set_limits(max_tokens_session=1)
    try:
        with with_context(session=session):
            engine.chat([{"role": "user", "content": "hello"}], role="planner")
            with pytest.raises(LLMBudgetExceeded):
                engine.chat([{"role": "user", "content": "again"}], role="planner")
        assert adapter.models == ["planner-v1"]
    finally:
        llm_budget.set_limits()


def test_missing_key_fails_closed(monkeypatch):
    engine, adapter = _engine(
        FakeAdapter(),
        chat={"provider": "gemini", "model": "gemini-test"},
    )
    monkeypatch.setattr("core.llm_engine._resolve_key", lambda *_: "")
    with pytest.raises(LLMAuthError):
        engine.chat([{"role": "user", "content": "private prompt"}], role="chat")
    assert adapter.models == []


def test_events_emitted_without_prompt_or_response():
    engine, _ = _engine(FakeAdapter("private response"))
    requests = []
    responses = []
    llm_events.drain_buffer(lambda *_: None)
    on_request = requests.append
    on_response = responses.append
    llm_events.subscribe("llm.request", on_request)
    llm_events.subscribe("llm.response", on_response)
    try:
        engine.chat(
            [{"role": "user", "content": "private prompt"}],
            role="planner",
        )
    finally:
        llm_events.unsubscribe("llm.request", on_request)
        llm_events.unsubscribe("llm.response", on_response)
    assert requests[0]["trace_id"]
    assert requests[0]["model"] == "planner-v1"
    assert "private prompt" not in repr(requests + responses)
    assert "private response" not in repr(requests + responses)


def test_stream_passthrough_and_events():
    engine, _ = _engine()
    starts = []
    chunks = []
    ends = []
    llm_events.drain_buffer(lambda *_: None)
    on_start = starts.append
    on_chunk = chunks.append
    on_end = ends.append
    llm_events.subscribe("llm.stream_start", on_start)
    llm_events.subscribe("llm.stream_chunk", on_chunk)
    llm_events.subscribe("llm.stream_end", on_end)
    try:
        assert list(engine.stream(
            [{"role": "user", "content": "hello"}],
            role="planner",
        )) == ["one", " two"]
    finally:
        llm_events.unsubscribe("llm.stream_start", on_start)
        llm_events.unsubscribe("llm.stream_chunk", on_chunk)
        llm_events.unsubscribe("llm.stream_end", on_end)
    assert starts and len(chunks) == 2 and ends
    assert all("text" not in event for event in starts + chunks + ends)


def test_embed_not_implemented():
    engine, _ = _engine(
        embed={"provider": "none", "model": "none"}
    )
    with pytest.raises(NotImplementedError, match="TODO ADAPTER-EMBED"):
        engine.embed(["sample"])


def test_context_propagated():
    engine, _ = _engine()
    captured = []
    callback = captured.append
    llm_events.drain_buffer(lambda *_: None)
    llm_events.subscribe("llm.request", callback)
    try:
        with with_context(agent="coder"):
            engine.chat([{"role": "user", "content": "hello"}], role="planner")
    finally:
        llm_events.unsubscribe("llm.request", callback)
    assert captured[0]["agent"] == "coder"
