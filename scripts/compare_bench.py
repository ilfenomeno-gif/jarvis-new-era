#!/usr/bin/env python
"""Compare schema-v1 benchmark reports and fail on median regressions."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.schema import require_supported_schema_version  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read benchmark report {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"{path} must contain a benchmark report object.")
    try:
        require_supported_schema_version(report.get("schema_version"))
    except ValueError as exc:
        raise ValueError(f"Invalid benchmark schema in {path}: {exc}") from exc
    if not isinstance(report.get("benchmark"), dict) or not isinstance(
        report.get("metrics"), dict
    ):
        raise ValueError(f"{path} must contain benchmark and metrics objects.")
    return report


def _samples(report: dict[str, Any], name: str) -> tuple[str, list[float]]:
    metric = report["metrics"].get(name)
    if not isinstance(metric, dict):
        raise ValueError(f"Metric {name!r} is missing.")
    unit, values = metric.get("unit"), metric.get("samples")
    if not isinstance(unit, str) or not unit or not isinstance(values, list) or not values:
        raise ValueError(f"Metric {name!r} needs a unit and non-empty samples list.")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError(f"Metric {name!r} contains invalid samples.")
    return unit, [float(value) for value in values]


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    max_regression_percent: float = 10.0,
) -> dict[str, Any]:
    if max_regression_percent < 0 or not math.isfinite(max_regression_percent):
        raise ValueError("max_regression_percent must be finite and non-negative.")
    baseline_name = baseline["benchmark"].get("name")
    candidate_name = candidate["benchmark"].get("name")
    if not baseline_name or baseline_name != candidate_name:
        raise ValueError("Benchmark names must match before comparison.")
    baseline_key = baseline["benchmark"].get("comparison_key")
    candidate_key = candidate["benchmark"].get("comparison_key")
    if baseline_key != candidate_key:
        raise ValueError("Benchmark comparison keys must match.")

    common = sorted(set(baseline["metrics"]) & set(candidate["metrics"]))
    if not common:
        raise ValueError("The reports have no metric names in common.")
    if set(baseline["metrics"]) != set(candidate["metrics"]):
        raise ValueError("Benchmark reports must contain the same metric names.")
    comparisons = []
    for name in common:
        baseline_unit, baseline_values = _samples(baseline, name)
        candidate_unit, candidate_values = _samples(candidate, name)
        if baseline_unit != candidate_unit:
            raise ValueError(f"Metric {name!r} has mismatched units.")
        baseline_median = statistics.median(baseline_values)
        candidate_median = statistics.median(candidate_values)
        if baseline_median == 0:
            regression = 0.0 if candidate_median == 0 else None
            regressed = candidate_median != 0
        else:
            regression = (candidate_median / baseline_median - 1) * 100
            regressed = regression > max_regression_percent
        comparisons.append(
            {
                "metric": name,
                "unit": baseline_unit,
                "baseline_median": baseline_median,
                "candidate_median": candidate_median,
                "regression_percent": regression,
                "regressed": regressed,
            }
        )
    return {
        "benchmark": baseline_name,
        "max_regression_percent": max_regression_percent,
        "comparisons": comparisons,
        "passed": not any(item["regressed"] for item in comparisons),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--max-regression-percent",
        type=float,
        default=10.0,
        help="Fail when any common metric's median regresses by more than this percent.",
    )
    args = parser.parse_args(argv)
    try:
        result = compare_reports(
            _load(args.baseline),
            _load(args.candidate),
            max_regression_percent=args.max_regression_percent,
        )
    except ValueError as exc:
        print(f"Benchmark comparison failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
