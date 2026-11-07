from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

from core.harness.config import load_harness_policy
from core.harness.eval import EvalCase, EvalResult, run_eval


class RuleBasedJudge:
    """Deterministic local judge; supports only the configured rule subset."""

    def __init__(
        self,
        rules: dict[str, Any] | None = None,
        *,
        default_rule: str | None = None,
        use_configured_default: bool = True,
    ) -> None:
        if rules is None:
            config = load_harness_policy().get("eval", {}).get("judge", {})
            rules = config.get("rules", {})
            if default_rule is None and use_configured_default:
                default_rule = config.get("default_rule")
        if not isinstance(rules, dict):
            raise ValueError("eval.judge.rules must be a mapping.")
        self.rules = rules
        self.default_rule = default_rule

    def score(self, case: EvalCase, output: Any) -> dict[str, Any]:
        rule_name = case.metadata.get("rule", self.default_rule)
        if rule_name is None:
            return {
                "ok": None,
                "reason": (
                    "No LLM judge configured; case was not evaluated "
                    "(no deterministic rule configured)."
                ),
            }
        if not isinstance(rule_name, str) or rule_name not in self.rules:
            raise ValueError(f"Eval rule {rule_name!r} is not configured.")
        config = self.rules[rule_name]
        rule_type = config.get("type") if isinstance(config, dict) else config
        expected = case.expected
        try:
            ok = self._evaluate(rule_type, output, expected, case.metadata)
        except (TypeError, ValueError, re.error, json.JSONDecodeError):
            ok = False
        return {
            "ok": ok,
            "score": 1.0 if ok else 0.0,
            "reason": f"Local rule: {rule_name}.",
            "metrics": {"rule": rule_name},
        }

    @staticmethod
    def _evaluate(rule_type: Any, output: Any, expected: Any, metadata: dict[str, Any]) -> bool:
        if rule_type in ("equals", "exact"):
            return output == expected
        if rule_type in ("contains", "substring"):
            return isinstance(expected, str) and expected in str(output)
        if rule_type == "regex":
            return isinstance(expected, str) and re.search(expected, str(output)) is not None
        if rule_type == "length":
            limits = expected if isinstance(expected, dict) else metadata.get("limits", {})
            if not isinstance(limits, dict):
                return False
            length = len(output)
            minimum = limits.get("min", limits.get("min_length"))
            maximum = limits.get("max", limits.get("max_length"))
            return (
                (minimum is None or length >= minimum)
                and (maximum is None or length <= maximum)
            )
        if rule_type == "json":
            if isinstance(output, str):
                parsed = json.loads(output)
            else:
                parsed = json.loads(json.dumps(output, allow_nan=False))
            return expected is None or parsed == expected
        if rule_type == "exit_code":
            actual = output.get("exit_code") if isinstance(output, dict) else output
            return isinstance(actual, int) and not isinstance(actual, bool) and actual == (
                0 if expected is None else expected
            )
        if rule_type == "truthy":
            return bool(output) is bool(expected if expected is not None else True)
        raise ValueError(f"Unsupported local eval rule type: {rule_type!r}.")

    def __call__(self, case: EvalCase) -> EvalResult:
        output = case.output if case.output is not None else case.input
        verdict = self.score(case, output)
        return EvalResult.from_dict({"case_id": case.id, **verdict})


class LLMJudge:
    """H4 stub for provider-backed judging; never performs network calls in H3."""

    def __init__(self, llm: Any) -> None:
        if (
            os.environ.get("JARVIS_HARNESS_JUDGE_LLM") != "1"
            and os.environ.get("JARVIS_HARNESS_LLM_JUDGE") != "1"
        ):
            raise RuntimeError(
                "LLM judging requires JARVIS_HARNESS_JUDGE_LLM=1 "
                "(legacy alias: JARVIS_HARNESS_LLM_JUDGE=1)."
            )
        if llm is None or not callable(getattr(llm, "chat", None)):
            raise ValueError("LLMJudge requires an existing LLM adapter.")
        self.llm = llm

    def score(self, case: EvalCase, output: Any) -> dict[str, Any]:
        del case, output
        raise NotImplementedError("Provider-backed LLMJudge is deferred to H4.")


def run_configured_eval(
    cases: Iterable[EvalCase],
    *,
    judge_mode: str = "rule",
    llm: Any = None,
) -> list[EvalResult]:
    if judge_mode == "rule":
        configuration = load_harness_policy().get("eval", {}).get("judge", {})
        judge = RuleBasedJudge(
            configuration.get("rules", {}),
            default_rule=configuration.get("default_rule", "equals"),
        )
    elif judge_mode == "llm":
        if (
            os.environ.get("JARVIS_HARNESS_JUDGE_LLM") != "1"
            and os.environ.get("JARVIS_HARNESS_LLM_JUDGE") != "1"
        ):
            raise RuntimeError(
                "LLM judging requires JARVIS_HARNESS_JUDGE_LLM=1 "
                "(legacy alias: JARVIS_HARNESS_LLM_JUDGE=1)."
            )
        if llm is None:
            from core.llm_engine import llm as default_llm

            llm = default_llm
        judge = LLMJudge(llm)
    else:
        raise ValueError("judge_mode must be 'rule' or 'llm'.")
    return run_eval(cases, judge=judge)
