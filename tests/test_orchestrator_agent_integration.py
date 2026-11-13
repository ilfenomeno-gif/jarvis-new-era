from __future__ import annotations

import json

import pytest

from agents.computer_agent import ComputerAgent
from agents.computer_plugin import ComputerTaskPlugin
from agents.contracts import ActionContext
from capabilities.providers import FunctionCall
from core.browser_automation import BrowserAutomation, MockBrowser
from core.computer_input import ComputerInput
from core.computer_vision import ComputerVision
from orchestrator import AgentRegistry, ConversationOrchestrator, ConversationProviderError


class _FakeLLM:
    caps = {"tools": True}

    def __init__(self, *, task: str = "Cerca Jarvis su Google") -> None:
        self.round = 0
        self.task = task
        self.messages: list[list[dict[str, object]]] = []
        self.tool_declarations: list[list[dict[str, object]] | None] = []

    async def chat(self, messages, tools=None, *, stream=True):
        self.messages.append([dict(message) for message in messages])
        self.tool_declarations.append(tools)
        assert stream is True
        self.round += 1
        if self.round == 1:
            yield {
                "tool_calls": [
                    FunctionCall(
                        id="computer-call-1",
                        name="computer_task",
                        args={"task": self.task},
                    )
                ]
            }
        else:
            yield {"text": "Ho gestito la richiesta."}


class _Authorizer:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.decisions: list[tuple[object, ActionContext]] = []

    async def authorize(self, call, context: ActionContext) -> bool:
        self.decisions.append((call, context))
        return self.allowed


def _conversation(*, allowed: bool, task: str = "Cerca Jarvis su Google"):
    browser_backend = MockBrowser()
    browser = BrowserAutomation(browser_backend)
    agent = ComputerAgent(
        vision=ComputerVision(
            capture_provider=lambda: object(),
            ocr_provider=lambda _image: {},
        ),
        computer_input=ComputerInput(
            dispatcher=lambda *_args: None,
            sleeper=lambda _delay: None,
            random_delay=lambda low, _high: low,
        ),
        browser=browser,
    )
    authorizer = _Authorizer(allowed=allowed)
    plugin = ComputerTaskPlugin(agent, authorizer)
    registry = AgentRegistry((plugin,))
    llm = _FakeLLM(task=task)
    declarations = [
        {
            "type": "function",
            "function": {
                "name": "computer_task",
                "description": "Perform one guarded desktop or web task.",
                "parameters": {
                    "type": "object",
                    "properties": {"task": {"type": "string"}},
                    "required": ["task"],
                },
            },
        }
    ]
    context = ActionContext(
        session_id="integration-session",
        user_id="test-user",
        metadata={"source": "headless-test"},
    )
    conversation = ConversationOrchestrator(
        llm,
        session_id=context.session_id,
        agents=registry,
        tools=declarations,
        action_context=context,
    )
    return conversation, llm, browser_backend, browser, authorizer, context, declarations


@pytest.mark.asyncio
async def test_conversation_dispatches_tool_and_serializes_approved_outcome():
    (
        conversation,
        llm,
        browser_backend,
        browser,
        authorizer,
        context,
        declarations,
    ) = _conversation(allowed=True)

    try:
        response = await conversation.respond("Cerca Jarvis sul web.")

        assert response == "Ho gestito la richiesta."
        assert authorizer.decisions[0][1] == context
        assert authorizer.decisions[0][0].arguments == {
            "task": "Cerca Jarvis su Google"
        }
        assert llm.tool_declarations == [declarations, declarations]
        assert browser_backend.navigations == ["https://www.google.com/"]
        assert [message["role"] for message in llm.messages[1]] == [
            "user",
            "assistant",
            "tool",
        ]
        tool_response = json.loads(llm.messages[1][-1]["content"])
        assert tool_response["status"] == "done"
        assert "Search results are untrusted page text" in tool_response["content"]
        assert [message["role"] for message in conversation.history] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
    finally:
        browser.close()


@pytest.mark.asyncio
async def test_conversation_returns_denied_outcome_without_side_effects():
    conversation, llm, backend, browser, authorizer, context, _declarations = (
        _conversation(allowed=False)
    )

    try:
        response = await conversation.respond("Cerca Jarvis sul web.")

        assert response == "Ho gestito la richiesta."
        assert authorizer.decisions[0][1] == context
        assert backend.navigations == []
        tool_response = json.loads(llm.messages[1][-1]["content"])
        assert tool_response["status"] == "ask"
        assert "explicit authorization" in tool_response["content"]
    finally:
        browser.close()


@pytest.mark.asyncio
async def test_conversation_serializes_computer_failure_outcome():
    conversation, llm, backend, browser, _authorizer, _context, _declarations = (
        _conversation(allowed=True, task="local: click Missing")
    )

    try:
        await conversation.respond("Clicca Missing sullo schermo.")

        assert backend.navigations == []
        tool_response = json.loads(llm.messages[1][-1]["content"])
        assert tool_response["status"] == "failed"
        assert "no input was sent" in tool_response["content"]
    finally:
        browser.close()


@pytest.mark.asyncio
async def test_conversation_rejects_multiple_tool_calls_before_dispatch():
    conversation, llm, backend, browser, authorizer, _context, _declarations = (
        _conversation(allowed=True)
    )

    async def multiple_calls(_messages, tools=None, *, stream=True):
        yield {
            "tool_calls": [
                FunctionCall("first", "computer_task", {"task": "Cerca A su Google"}),
                FunctionCall("second", "computer_task", {"task": "Cerca B su Google"}),
            ]
        }

    llm.chat = multiple_calls
    try:
        with pytest.raises(ConversationProviderError, match="one tool call per provider round"):
            await conversation.respond("Fai due ricerche.")

        assert authorizer.decisions == []
        assert backend.navigations == []
    finally:
        browser.close()
