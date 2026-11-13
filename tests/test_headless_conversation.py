from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from capabilities.providers import FunctionCall
from kernel.events import Event, EventBus
from orchestrator import (
    ConversationOrchestrator,
    ConversationProviderError,
    ToolCallsRequirePolicyError,
)


class _FakeLLM:
    caps = {"tools": False}

    def __init__(self, scripts: list[list[dict[str, object]]]):
        self.scripts = list(scripts)
        self.messages: list[list[dict[str, str]]] = []
        self.options: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, *, stream=True):
        self.messages.append([dict(message) for message in messages])
        self.options.append({"tools": tools, "stream": stream})
        script = self.scripts.pop(0)
        for event in script:
            await asyncio.sleep(0)
            yield event


@pytest.mark.asyncio
async def test_conversation_streams_text_and_preserves_multi_turn_context():
    llm = _FakeLLM(
        [
            [{"text": "Ciao "}, {"text": "Ada."}],
            [{"text": "Ti ho chiamata Ada."}],
        ]
    )
    conversation = ConversationOrchestrator(
        llm,
        session_id="test-session",
        system_instruction="You are JARVIS.",
    )

    first = await conversation.respond("  Ciao, chiamami Ada.  ")
    second = await conversation.respond("Come mi hai appena chiamata?")

    assert first == "Ciao Ada."
    assert second == "Ti ho chiamata Ada."
    assert llm.options == [
        {"tools": None, "stream": True},
        {"tools": None, "stream": True},
    ]
    assert [message["role"] for message in llm.messages[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert llm.messages[1][-2]["content"] == "Ciao Ada."
    assert [message["role"] for message in conversation.history] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_failed_provider_turn_does_not_commit_partial_history():
    class FailingLLM:
        caps = {"tools": False}

        async def chat(self, _messages, tools=None, *, stream=True):
            del tools, stream
            yield {"text": "partial"}
            raise ConnectionError("provider unavailable")

    conversation = ConversationOrchestrator(FailingLLM())

    with pytest.raises(ConnectionError, match="provider unavailable"):
        await conversation.respond("Will this be retained?")

    assert conversation.history == ()


@pytest.mark.asyncio
async def test_tool_call_is_rejected_without_dispatch_or_history_commit():
    llm = _FakeLLM(
        [[{"tool_calls": [FunctionCall("call-1", "delete_file", {})]}]]
    )
    conversation = ConversationOrchestrator(llm)

    with pytest.raises(ToolCallsRequirePolicyError, match="agent registry"):
        await conversation.respond("Do something.")

    assert conversation.history == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        [],
        [{"text": ""}],
        [{"text": 42}],
        ["not-an-event"],
    ],
)
async def test_invalid_or_empty_provider_responses_fail_explicitly(script):
    conversation = ConversationOrchestrator(_FakeLLM([script]))

    with pytest.raises(ConversationProviderError):
        await conversation.respond("Answer me.")

    assert conversation.history == ()


@pytest.mark.asyncio
async def test_conversation_publishes_user_and_assistant_events():
    bus = EventBus()
    observed: list[Event] = []

    async def observe(event: Event) -> None:
        observed.append(event)

    bus.subscribe("conversation.user_message", observe)
    bus.subscribe("conversation.assistant_message", observe)
    conversation = ConversationOrchestrator(
        _FakeLLM([[{"text": "Ready."}]]),
        session_id="session-1",
        events=bus,
    )

    assert await conversation.respond("Start.")
    assert [event.name for event in observed] == [
        "conversation.user_message",
        "conversation.assistant_message",
    ]
    assert [event.payload["text"] for event in observed] == ["Start.", "Ready."]
    assert all(event.correlation_id == "session-1" for event in observed)


@pytest.mark.asyncio
async def test_concurrent_turns_are_serialized_with_consistent_context():
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class BlockingLLM:
        caps = {"tools": False}

        def __init__(self):
            self.messages = []

        async def chat(self, messages, tools=None, *, stream=True):
            self.messages.append([dict(message) for message in messages])
            if len(self.messages) == 1:
                first_started.set()
                await release_first.wait()
                yield {"text": "First."}
            else:
                yield {"text": "Second."}

    llm = BlockingLLM()
    conversation = ConversationOrchestrator(llm)
    first_turn = asyncio.create_task(conversation.respond("One"))
    await first_started.wait()
    second_turn = asyncio.create_task(conversation.respond("Two"))
    await asyncio.sleep(0)
    assert len(llm.messages) == 1

    release_first.set()
    assert await asyncio.gather(first_turn, second_turn) == ["First.", "Second."]
    assert [message["role"] for message in llm.messages[1]] == [
        "user",
        "assistant",
        "user",
    ]


def test_orchestrator_imports_without_desktop_or_cloud_sdk_modules():
    root = Path(__file__).resolve().parents[1]
    script = (
        "import sys; import orchestrator; "
        "assert not any(name.startswith('PyQt6') for name in sys.modules); "
        "assert 'google.genai' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
