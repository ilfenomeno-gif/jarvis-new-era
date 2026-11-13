from __future__ import annotations

import pytest

from capabilities.contracts import ToolCall, ToolReply
from capabilities.providers import LLM, STT, TTS, Engine
from kernel.config import RuntimeConfig
from kernel.events import Event, EventBus, EventBusClosedError, EventDispatchError
from kernel.lifecycle import Kernel, KernelState, LifecycleError
from providers.base import LLM as LegacyLLM
from providers.base import STT as LegacySTT
from providers.base import TTS as LegacyTTS
from providers.base import Engine as LegacyEngine


def test_provider_protocols_keep_legacy_identity():
    assert Engine is LegacyEngine
    assert LLM is LegacyLLM
    assert STT is LegacySTT
    assert TTS is LegacyTTS


def test_tool_contracts_validate_and_freeze_mappings():
    arguments = {"query": "weather"}
    call = ToolCall(call_id="call-1", name="search", arguments=arguments)
    arguments["query"] = "changed"

    assert call.arguments["query"] == "weather"
    with pytest.raises(TypeError):
        call.arguments["query"] = "mutated"

    reply = ToolReply(
        call_id="call-1",
        name="search",
        status="unverified",
        content="The request was sent but not confirmed.",
        facts={"verified": False},
    )
    assert reply.status == "unverified"
    with pytest.raises(ValueError, match="Unsupported outcome"):
        ToolReply(call_id="call-1", name="search", status="success", content="ok")


def test_runtime_config_reads_only_validated_public_settings():
    config = RuntimeConfig.from_legacy_mapping(
        {
            "assistant_name": " JARVIS ",
            "user_name": "Ada",
            "gemini_api_key": "must-not-be-copied",
            "providers": {"mode": " PIPELINE ", "creds": {"llm": {"api_key": "secret"}}},
        }
    )

    assert config.provider_mode == "pipeline"
    assert config.assistant_name == "JARVIS"
    assert config.user_name == "Ada"
    assert not hasattr(config, "gemini_api_key")
    assert not hasattr(config, "providers")
    with pytest.raises(ValueError, match="Unsupported provider mode"):
        RuntimeConfig.from_legacy_mapping({"providers": {"mode": "unknown"}})


@pytest.mark.asyncio
async def test_event_bus_delivers_in_subscription_order_and_unsubscribes():
    bus = EventBus()
    received: list[str] = []

    async def first(event: Event) -> None:
        received.append(f"first:{event.payload['text']}")

    async def second(event: Event) -> None:
        received.append(f"second:{event.payload['text']}")

    subscription = bus.subscribe("chat.message", first)
    bus.subscribe("chat.message", second)
    await bus.publish(Event("chat.message", {"text": "hello"}))
    assert bus.unsubscribe(subscription)
    assert not bus.unsubscribe(subscription)
    await bus.publish(Event("chat.message", {"text": "again"}))

    assert received == ["first:hello", "second:hello", "second:again"]


@pytest.mark.asyncio
async def test_event_bus_accepts_async_callable_objects():
    bus = EventBus()
    received: list[str] = []
    bus.subscribe("event", _AsyncHandler(received))

    await bus.publish(Event("event"))

    assert received == ["called"]


@pytest.mark.asyncio
async def test_event_bus_surfaces_handler_errors_after_notifying_other_handlers():
    bus = EventBus()
    received: list[str] = []

    async def fail(_event: Event) -> None:
        raise ValueError("subscriber failed")

    async def continue_delivery(_event: Event) -> None:
        received.append("called")

    bus.subscribe("event", fail)
    bus.subscribe("event", continue_delivery)

    with pytest.raises(EventDispatchError) as caught:
        await bus.publish(Event("event"))

    assert received == ["called"]
    assert caught.value.event_name == "event"
    assert isinstance(caught.value.errors[0], ValueError)


@pytest.mark.asyncio
async def test_event_bus_close_is_idempotent_and_rejects_new_work():
    bus = EventBus()
    bus.close()
    bus.close()

    with pytest.raises(EventBusClosedError):
        bus.subscribe("event", _noop_handler)
    with pytest.raises(EventBusClosedError):
        await bus.publish(Event("event"))


async def _noop_handler(_event: Event) -> None:
    return None


@pytest.mark.asyncio
async def test_kernel_starts_in_order_and_closes_in_reverse_order():
    calls: list[str] = []
    kernel = Kernel((_Component("one", calls), _Component("two", calls)))

    await kernel.start()
    assert kernel.state is KernelState.RUNNING
    await kernel.close()
    await kernel.close()

    assert kernel.state is KernelState.CLOSED
    assert calls == ["start:one", "start:two", "close:two", "close:one"]
    with pytest.raises(LifecycleError):
        await kernel.start()


@pytest.mark.asyncio
async def test_kernel_rolls_back_started_components_after_start_failure():
    calls: list[str] = []
    kernel = Kernel(
        (
            _Component("one", calls),
            _Component("two", calls, fail_start=True),
            _Component("three", calls),
        )
    )

    with pytest.raises(RuntimeError, match="start:two failed"):
        await kernel.start()

    assert kernel.state is KernelState.FAILED
    assert calls == ["start:one", "start:two", "close:two", "close:one"]
    await kernel.close()
    assert kernel.state is KernelState.CLOSED


@pytest.mark.asyncio
async def test_kernel_shutdown_closes_remaining_components_and_reports_failures():
    calls: list[str] = []
    kernel = Kernel(
        (
            _Component("one", calls, fail_close=True),
            _Component("two", calls),
        )
    )
    await kernel.start()

    with pytest.raises(ExceptionGroup) as caught:
        await kernel.close()

    assert kernel.state is KernelState.CLOSED
    assert calls == ["start:one", "start:two", "close:two", "close:one"]
    assert isinstance(caught.value.exceptions[0], RuntimeError)


class _AsyncHandler:
    def __init__(self, received: list[str]):
        self.received = received

    async def __call__(self, _event: Event) -> None:
        self.received.append("called")


class _Component:
    def __init__(
        self,
        name: str,
        calls: list[str],
        *,
        fail_start: bool = False,
        fail_close: bool = False,
    ):
        self.name = name
        self.calls = calls
        self.fail_start = fail_start
        self.fail_close = fail_close

    async def start(self) -> None:
        self.calls.append(f"start:{self.name}")
        if self.fail_start:
            raise RuntimeError(f"start:{self.name} failed")

    async def close(self) -> None:
        self.calls.append(f"close:{self.name}")
        if self.fail_close:
            raise RuntimeError(f"close:{self.name} failed")
