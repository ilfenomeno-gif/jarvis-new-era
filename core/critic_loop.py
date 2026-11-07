"""Bounded, auditable revision loop used by the intellectual core."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")
C = TypeVar("C")


@dataclass(frozen=True)
class RevisionRecord:
    cycle: int
    from_version: int
    critique: Any
    to_version: int


class CriticLoop(Generic[T, C]):
    """Runs a fixed number of critique/revision cycles and records each edge."""

    def __init__(self, cycles: int = 2):
        if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
            raise ValueError("CriticLoop requires at least one revision cycle.")
        self.cycles = cycles

    def run(
        self,
        draft: T,
        critique: C,
        *,
        critique_fn: Callable[[T], C],
        revise_fn: Callable[[T, C, int], T],
    ) -> tuple[T, tuple[RevisionRecord, ...]]:
        records: list[RevisionRecord] = []
        current_draft = draft
        current_critique = critique
        for cycle in range(1, self.cycles + 1):
            from_version = getattr(current_draft, "version", None)
            if not isinstance(from_version, int):
                raise TypeError("Revision drafts must expose an integer version.")
            next_draft = revise_fn(current_draft, current_critique, cycle)
            to_version = getattr(next_draft, "version", None)
            if to_version != from_version + 1:
                raise ValueError("Each revision cycle must advance the draft by one version.")
            records.append(
                RevisionRecord(
                    cycle=cycle,
                    from_version=from_version,
                    critique=current_critique,
                    to_version=to_version,
                )
            )
            current_draft = next_draft
            if cycle < self.cycles:
                current_critique = critique_fn(current_draft)
        return current_draft, tuple(records)
