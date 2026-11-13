"""Headless conversation with streaming LLM responses and guarded tool dispatch."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from uuid import uuid4

from agents.contracts import ActionContext
from capabilities.contracts import ToolCall
from capabilities.providers import LLM, FunctionCall
from kernel.events import Event, EventBus
from orchestrator.plugins import AgentRegistry

ConversationMessage = dict[str, object]


class ConversationProviderError(RuntimeError):
    """Raised when a provider returns an invalid or empty text response."""


class ToolCallsRequirePolicyError(RuntimeError):
    """Raised when a provider requests tools before an action policy is wired."""


class ToolCallLimitError(RuntimeError):
    """Raised when a provider exceeds the configured tool-call round limit."""


class ConversationOrchestrator:
    """Owns one in-memory conversation and serializes turns through an LLM."""

    def __init__(
        self,
        llm: LLM,
        *,
        session_id: str | None = None,
        system_instruction: str = "",
        events: EventBus | None = None,
        agents: AgentRegistry | None = None,
        tools: Sequence[dict[str, object]] | None = None,
        action_context: ActionContext | None = None,
        max_tool_rounds: int = 3,
    ) -> None:
        if not callable(getattr(llm, "chat", None)):
            raise TypeError("llm must implement the provider chat contract.")
        if not isinstance(system_instruction, str):
            raise TypeError("system_instruction must be a string.")
        if session_id is not None and (
            not isinstance(session_id, str) or not session_id.strip()
        ):
            raise ValueError("session_id must not be empty.")
        if agents is not None and not isinstance(agents, AgentRegistry):
            raise TypeError("agents must be an AgentRegistry or None.")
        if tools is not None and (
            not isinstance(tools, Sequence)
            or isinstance(tools, (str, bytes))
            or any(not isinstance(tool, dict) for tool in tools)
        ):
            raise TypeError("tools must be a sequence of tool declaration mappings.")
        if (
            isinstance(max_tool_rounds, bool)
            or not isinstance(max_tool_rounds, int)
            or max_tool_rounds < 0
        ):
            raise ValueError("max_tool_rounds must be a non-negative integer.")
        self.session_id = session_id.strip() if session_id is not None else uuid4().hex
        self._llm = llm
        self._events = events
        self._agents = agents
        self._tools = [dict(tool) for tool in tools] if tools is not None else None
        if action_context is not None and (
            not isinstance(action_context, ActionContext)
            or action_context.session_id != self.session_id
        ):
            raise ValueError("action_context must belong to this conversation session.")
        self._action_context = action_context or ActionContext(
            session_id=self.session_id
        )
        self._max_tool_rounds = max_tool_rounds
        self._messages: list[ConversationMessage] = []
        if system_instruction.strip():
            self._messages.append(
                {"role": "system", "content": system_instruction.strip()}
            )
        self._turn_lock = asyncio.Lock()

    @property
    def history(self) -> tuple[ConversationMessage, ...]:
        """Return a detached snapshot; callers cannot mutate internal history."""
        return tuple(dict(message) for message in self._messages)

    async def respond(self, user_text: str) -> str:
        """Return one complete assistant response and commit the successful turn."""
        if not isinstance(user_text, str):
            raise TypeError("user_text must be a string.")
        text = user_text.strip()
        if not text:
            raise ValueError("user_text must not be empty.")

        async with self._turn_lock:
            pending: list[ConversationMessage] = [
                *self._messages,
                {"role": "user", "content": text},
            ]
            if self._events is not None:
                await self._events.publish(
                    Event(
                        "conversation.user_message",
                        {"session_id": self.session_id, "text": text},
                        correlation_id=self.session_id,
                    )
                )

            tool_rounds = 0
            while True:
                chunks: list[str] = []
                calls: list[FunctionCall] = []
                async for event in self._llm.chat(
                    [dict(message) for message in pending],
                    tools=[dict(tool) for tool in self._tools]
                    if self._tools is not None
                    else None,
                    stream=True,
                ):
                    if not isinstance(event, dict):
                        raise ConversationProviderError(
                            "The LLM provider emitted a non-mapping event."
                        )
                    if event.get("type") == "tool_call" and not event.get("tool_calls"):
                        raise ConversationProviderError(
                            "The LLM provider emitted an unsupported tool-call event."
                        )
                    raw_calls = event.get("tool_calls")
                    if raw_calls is not None:
                        if not isinstance(raw_calls, (list, tuple)) or any(
                            not isinstance(call, FunctionCall) for call in raw_calls
                        ):
                            raise ConversationProviderError(
                                "The LLM provider emitted invalid tool calls."
                            )
                        calls.extend(raw_calls)
                    chunk = event.get("text")
                    if chunk is None:
                        continue
                    if not isinstance(chunk, str):
                        raise ConversationProviderError(
                            "The LLM provider emitted a non-text response chunk."
                        )
                    chunks.append(chunk)

                if not calls:
                    response = "".join(chunks).strip()
                    if not response:
                        raise ConversationProviderError(
                            "The LLM provider completed without a text response."
                        )
                    pending.append({"role": "assistant", "content": response})
                    self._messages = pending
                    break

                if self._agents is None:
                    raise ToolCallsRequirePolicyError(
                        "Tool calls are disabled until an authorized agent registry is connected."
                    )
                if tool_rounds >= self._max_tool_rounds:
                    raise ToolCallLimitError(
                        "The provider exceeded the configured tool-call round limit."
                    )
                if len(calls) != 1:
                    raise ConversationProviderError(
                        "This orchestrator supports one tool call per provider round."
                    )
                provider_call = calls[0]
                if not provider_call.id or not provider_call.name:
                    raise ConversationProviderError(
                        "The provider emitted a tool call without an ID or name."
                    )
                tool_rounds += 1
                pending.append(
                    {
                        "role": "assistant",
                        "content": "".join(chunks).strip() or None,
                        "tool_calls": [
                            {
                                "id": provider_call.id,
                                "type": "function",
                                "function": {
                                    "name": provider_call.name,
                                    "arguments": json.dumps(
                                        provider_call.args,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ),
                                },
                            }
                        ],
                    }
                )
                try:
                    call = ToolCall(
                        call_id=provider_call.id,
                        name=provider_call.name,
                        arguments=provider_call.args,
                    )
                except (TypeError, ValueError) as exc:
                    raise ConversationProviderError(
                        "The provider emitted invalid tool-call arguments."
                    ) from exc
                reply = await self._agents.dispatch(call, self._action_context)
                pending.append(
                    {
                        "role": "tool",
                        "tool_call_id": reply.call_id,
                        "name": reply.name,
                        "content": json.dumps(
                            {
                                "status": reply.status,
                                "content": reply.content,
                                "facts": dict(reply.facts),
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                )
                self._messages = list(pending)

            if self._events is not None:
                await self._events.publish(
                    Event(
                        "conversation.assistant_message",
                        {"session_id": self.session_id, "text": response},
                        correlation_id=self.session_id,
                    )
                )
            return response
