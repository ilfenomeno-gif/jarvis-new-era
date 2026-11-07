from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


class Judge(Protocol):
    def score(self, case: EvalCase, output: Any) -> dict[str, Any]: ...


@dataclass
class EvalCase:
    id: str
    input: Any
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    output: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        return cls(
            id=str(data["id"]),
            input=data.get("input"),
            expected=data.get("expected"),
            metadata=dict(data.get("metadata") or {}),
            output=data.get("output"),
        )


@dataclass
class EvalResult:
    case_id: str
    ok: bool | None
    score: float | None = None
    reason: str = ""
    trace_id: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalResult:
        return cls(
            case_id=str(data["case_id"]),
            ok=data.get("ok"),
            score=data.get("score"),
            reason=str(data.get("reason", "")),
            trace_id=str(data.get("trace_id", "")),
            metrics=dict(data.get("metrics") or {}),
        )


def run_eval(
    cases: Iterable[EvalCase],
    judge: Judge | Callable[[EvalCase], EvalResult | dict[str, Any] | bool] | None = None,
) -> list[EvalResult]:
    if judge is None:
        from core.harness.judge import RuleBasedJudge

        judge = RuleBasedJudge(use_configured_default=False)
    results = []
    for case in cases:
        if callable(getattr(judge, "score", None)):
            output = case.output if case.output is not None else case.input
            verdict = judge.score(case, output)
        elif callable(judge):
            verdict = judge(case)
        else:
            raise TypeError("judge must implement score(case, output) or be callable.")
        if isinstance(verdict, EvalResult):
            results.append(verdict)
        elif isinstance(verdict, bool):
            results.append(EvalResult(case_id=case.id, ok=verdict))
        elif isinstance(verdict, dict):
            results.append(EvalResult.from_dict({"case_id": case.id, **verdict}))
        else:
            raise TypeError("judge must return EvalResult, dict, or bool.")
    return results
