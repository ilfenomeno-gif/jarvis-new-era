from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _live():
    from main import JarvisLive

    live = JarvisLive.__new__(JarvisLive)
    live.ui = SimpleNamespace(write_log=lambda _message: None)
    return live


def test_engine_mode_defaults_to_gemini_when_config_lookup_fails(monkeypatch):
    from memory import config_manager

    def fail_lookup():
        raise OSError("settings unavailable")

    monkeypatch.setattr(config_manager, "get_provider_mode", fail_lookup)

    assert _live()._engine_mode() == "gemini"


def test_engine_mode_uses_validated_provider_mode(monkeypatch):
    from memory import config_manager

    monkeypatch.setattr(config_manager, "get_provider_mode", lambda: "pipeline")

    assert _live()._engine_mode() == "pipeline"


def test_resolve_engine_caps_builds_pipeline_capabilities_before_config(
    monkeypatch,
):
    from memory import config_manager
    from providers import registry

    saved_vision: list[tuple[str, bool]] = []
    provider = SimpleNamespace(
        caps={"tools": True, "vision": True, "tool_format": "openai"},
        ensure_vision_known=lambda save: save(
            {"vision": "1", "vision_model": "mock-model"}
        )
        or True,
    )
    monkeypatch.setattr(config_manager, "get_provider_mode", lambda: "pipeline")
    monkeypatch.setattr(
        config_manager,
        "get_pipeline",
        lambda: {"llm": "mock-llm", "stt": "mock-stt", "tts": "mock-tts"},
    )
    monkeypatch.setattr(
        config_manager,
        "get_provider_config",
        lambda provider_id: {"model": provider_id},
    )
    monkeypatch.setattr(
        config_manager,
        "save_provider_config",
        lambda provider_id, values: saved_vision.append(
            (provider_id, values["vision"] == "1")
        ),
    )
    monkeypatch.setattr(registry, "missing_fields", lambda _id, _config: [])
    monkeypatch.setattr(registry, "build", lambda _id, _config: provider)
    live = _live()
    logs: list[str] = []
    live.ui.write_log = logs.append

    caps = live._resolve_engine_caps()

    assert caps == {"tools": True, "vision": True, "tool_format": "openai", "audio_out": True}
    assert saved_vision == [("mock-llm", True)]
    assert logs == ["SYS: mock-llm can see images."]


def test_resolve_engine_caps_falls_back_to_live_when_pipeline_is_invalid(
    monkeypatch,
):
    from memory import config_manager
    from providers import registry

    monkeypatch.setattr(config_manager, "get_provider_mode", lambda: "pipeline")
    monkeypatch.setattr(config_manager, "get_pipeline", lambda: {"llm": ""})
    monkeypatch.setattr(registry, "missing_fields", lambda *_args: [])
    live = _live()
    logs: list[str] = []
    live.ui.write_log = logs.append

    assert live._resolve_engine_caps() is None
    assert len(logs) == 1
    assert "using Gemini Live" in logs[0]


def test_gemini_session_opens_and_closes_with_selected_api_version(monkeypatch):
    import main

    lifecycle: list[object] = []

    class FakeLiveSession:
        async def __aenter__(self):
            lifecycle.append("entered")
            return self

        async def __aexit__(self, _type, _value, _traceback):
            lifecycle.append("closed")

    class FakeLive:
        def connect(self, *, model, config):
            lifecycle.append(("connect", model, config))
            return FakeLiveSession()

    clients: list[dict[str, object]] = []

    def make_client(**kwargs):
        clients.append(kwargs)
        return SimpleNamespace(
            aio=SimpleNamespace(live=FakeLive())
        )

    monkeypatch.setattr(main.genai, "Client", make_client)
    monkeypatch.setattr(main, "_get_api_key", lambda: "test-key")
    live = _live()
    live._engine_caps = None
    live._enhanced_live = True
    config = object()

    async def run():
        async with live._open_session("fake-live-model", config) as session:
            assert session is not None
            assert lifecycle == [
                ("connect", "fake-live-model", config),
                "entered",
            ]
        assert lifecycle == [
            ("connect", "fake-live-model", config),
            "entered",
            "closed",
        ]

    asyncio.run(run())

    assert clients == [
        {"api_key": "test-key", "http_options": {"api_version": "v1alpha"}}
    ]


def test_pipeline_session_composes_slots_warms_and_closes(monkeypatch):
    from memory import config_manager
    from providers import engine_pipeline, registry

    llm = SimpleNamespace(caps={"tools": True})
    stt = object()
    tts = object()
    providers = {"llm-id": llm, "stt-id": stt, "tts-id": tts}
    built: list[tuple[str, dict]] = []
    instances: list[object] = []

    monkeypatch.setattr(
        config_manager,
        "get_provider_mode",
        lambda: "pipeline",
    )
    monkeypatch.setattr(
        config_manager,
        "get_pipeline",
        lambda: {"llm": "llm-id", "stt": "stt-id", "tts": "tts-id"},
    )
    monkeypatch.setattr(
        config_manager,
        "get_provider_config",
        lambda provider_id: {"configured": provider_id},
    )
    monkeypatch.setattr(registry, "missing_fields", lambda _id, _config: [])

    def build(provider_id, config):
        built.append((provider_id, config))
        return providers[provider_id]

    monkeypatch.setattr(registry, "build", build)

    class FakePipelineEngine:
        def __init__(self, actual_llm, actual_stt, actual_tts, *, config, log):
            self.parts = (actual_llm, actual_stt, actual_tts)
            self.config = config
            self.log = log
            self.auto_turn = None
            self.closed = False
            self.warmed = False
            instances.append(self)

        async def warmup(self):
            self.warmed = True

        async def close(self):
            self.closed = True

    monkeypatch.setattr(engine_pipeline, "PipelineEngine", FakePipelineEngine)
    live = _live()
    live._ptt_enabled = True
    config = object()
    live._engine_caps = live._resolve_engine_caps()
    assert live._engine_caps == {"tools": True, "audio_out": True}

    async def run():
        async with live._open_session("unused", config) as engine:
            assert engine.parts == (llm, stt, tts)
            assert engine.config is config
            assert engine.log == live.ui.write_log
            assert engine.warmed
            assert engine.auto_turn is False
            assert live._engine is engine
        assert live._engine is None
        assert engine.closed

    asyncio.run(run())

    assert len(instances) == 1
    assert [provider_id for provider_id, _ in built] == [
        "llm-id",
        "llm-id",
        "stt-id",
        "tts-id",
    ]
    assert all(config["configured"] == provider_id for provider_id, config in built)
    assert "log" not in built[0][1]
    assert all(config["log"] == live.ui.write_log for _, config in built[1:])


def test_pipeline_session_closes_engine_when_session_body_raises(monkeypatch):
    from memory import config_manager
    from providers import engine_pipeline, registry

    monkeypatch.setattr(config_manager, "get_pipeline", lambda: {})
    monkeypatch.setattr(config_manager, "get_provider_config", lambda _id: {})
    monkeypatch.setattr(registry, "build", lambda *_args: None)
    instances = []

    class FakePipelineEngine:
        def __init__(self, *_args, **_kwargs):
            self.closed = False
            self.auto_turn = None
            instances.append(self)

        async def warmup(self):
            return None

        async def close(self):
            self.closed = True

    monkeypatch.setattr(engine_pipeline, "PipelineEngine", FakePipelineEngine)
    live = _live()
    live._engine_caps = {}
    live._ptt_enabled = False

    async def run():
        with pytest.raises(RuntimeError, match="characterization"):
            async with live._open_session("unused", None):
                raise RuntimeError("characterization")
        assert live._engine is None

    asyncio.run(run())

    assert len(instances) == 1
    assert instances[0].closed
