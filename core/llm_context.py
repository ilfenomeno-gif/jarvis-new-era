from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_context: ContextVar[dict[str, str] | None] = ContextVar(
    "jarvis_llm_context", default=None
)
_FIELDS = ("module", "tool", "agent", "session", "trace_id")


def set_context(
    module: str | None = None,
    tool: str | None = None,
    agent: str | None = None,
    session: str | None = None,
    trace_id: str | None = None,
) -> None:
    updates = {
        key: value
        for key, value in zip(_FIELDS, (module, tool, agent, session, trace_id))
        if value is not None
    }
    _context.set({**(_context.get() or {}), **updates})


def get_context() -> dict[str, str]:
    return dict(_context.get() or {})


@contextmanager
def with_context(**kw: str | None) -> Iterator[dict[str, str]]:
    unknown = set(kw) - set(_FIELDS)
    if unknown:
        raise ValueError(f"Unknown LLM context fields: {', '.join(sorted(unknown))}")
    updates = {key: value for key, value in kw.items() if value is not None}
    token: Token[dict[str, str] | None] = _context.set(
        {**(_context.get() or {}), **updates}
    )
    try:
        yield get_context()
    finally:
        _context.reset(token)
