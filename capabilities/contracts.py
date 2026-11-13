"""Stable, UI-independent contracts for tool calls and their outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

OutcomeStatus = Literal["done", "unverified", "failed", "ask", "started"]

_OUTCOME_STATUSES = frozenset({"done", "unverified", "failed", "ask", "started"})


def _immutable_mapping(value: Mapping[str, object], *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping.")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings.")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A provider-neutral request to execute one named tool."""

    call_id: str
    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must not be empty.")
        object.__setattr__(
            self,
            "arguments",
            _immutable_mapping(self.arguments, field_name="arguments"),
        )


@dataclass(frozen=True, slots=True)
class ToolReply:
    """A tool outcome with an explicit status and provider-neutral content."""

    call_id: str
    name: str
    status: OutcomeStatus
    content: str
    facts: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must not be empty.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must not be empty.")
        if not isinstance(self.status, str) or self.status not in _OUTCOME_STATUSES:
            raise ValueError(f"Unsupported outcome status: {self.status!r}.")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string.")
        object.__setattr__(self, "facts", _immutable_mapping(self.facts, field_name="facts"))
