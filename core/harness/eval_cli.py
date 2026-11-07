from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from core.harness.config import load_harness_policy
from core.harness.eval import EvalCase
from core.harness.judge import run_configured_eval


def _load_cases(path: Path) -> list[EvalCase]:
    try:
        with path.open(encoding="utf-8") as suite_file:
            data: Any = yaml.safe_load(suite_file)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load eval suite {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("Eval suite must be a mapping with a cases list.")
    return [EvalCase.from_dict(item) for item in data["cases"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Jarvis Harness evaluation suite.")
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--judge", choices=("rule", "llm"))
    args = parser.parse_args(argv)
    configuration = load_harness_policy()
    eval_configuration = configuration.get("eval", {})
    judge_configuration = eval_configuration.get("judge", {})
    if isinstance(judge_configuration, dict):
        configured_judge_mode = judge_configuration.get("mode", "rule")
    else:
        configured_judge_mode = judge_configuration or "rule"
    suite_path = args.suite or Path(eval_configuration.get(
        "suite", "tests/eval/harness_suite.yaml"
    ))
    judge_mode = args.judge or configured_judge_mode
    results = run_configured_eval(_load_cases(suite_path), judge_mode=judge_mode)
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))
    return 0 if all(result.ok is True for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
