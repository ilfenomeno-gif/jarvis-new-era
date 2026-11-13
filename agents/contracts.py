"""Contracts for agents invoked by the orchestrator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from capabilities.contracts import ToolCall, ToolReply


@dataclass(frozen=True, slots=True)
class ActionContext:
    session_id: str
    user_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must not be empty.")
        if self.user_id is not None and not isinstance(self.user_id, str):
            raise TypeError("user_id must be a string or None.")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")
        if not all(isinstance(key, str) for key in self.metadata):
            raise TypeError("metadata keys must be strings.")
        object.__setattr__(self, "session_id", self.session_id.strip())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class ActionAuthorizer(Protocol):
    async def authorize(self, call: ToolCall, context: ActionContext) -> bool: ...


class AgentPlugin(Protocol):
    name: str

    async def execute(self, call: ToolCall, context: ActionContext) -> ToolReply: ...
