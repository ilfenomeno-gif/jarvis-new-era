import pytest

from benchmarks.schema import SUPPORTED_SCHEMA_VERSIONS
from scripts.compare_bench import compare_reports


def _report(samples):
    return {
        "schema_version": max(SUPPORTED_SCHEMA_VERSIONS),
        "benchmark": {"name": "jarvis.core"},
        "metrics": {"turn.first_token": {"unit": "ms", "samples": samples}},
    }


def test_benchmark_comparison_accepts_regression_within_threshold():
    result = compare_reports(
        _report([100, 105, 110]),
        _report([105, 110, 115]),
        max_regression_percent=10,
    )
    assert result["passed"]
    assert result["comparisons"][0]["regressed"] is False


def test_benchmark_comparison_fails_regression_over_threshold():
    result = compare_reports(
        _report([100, 100, 100]),
        _report([112, 120, 115]),
        max_regression_percent=10,
    )
    assert not result["passed"]
    assert result["comparisons"][0]["regressed"] is True


def test_benchmark_comparison_rejects_different_metric_sets():
    candidate = _report([100, 100, 100])
    candidate["metrics"]["removed.metric"] = {
        "unit": "ms",
        "samples": [1],
    }

    with pytest.raises(ValueError, match="same metric names"):
        compare_reports(_report([100, 100, 100]), candidate)


def test_benchmark_comparison_accepts_optional_metric_semantics():
    legacy = _report([100, 100, 100])
    annotated = _report([100, 100, 100])
    annotated["metric_semantics"] = {"turn.*": "time to first content"}

    result = compare_reports(legacy, annotated)

    assert result["passed"]


@pytest.mark.parametrize(
    "version",
    [0, 2, True, "1"],
)
def test_benchmark_schema_rejects_unsupported_versions(version):
    from benchmarks.schema import require_supported_schema_version

    with pytest.raises(ValueError, match="schema version|schema versions"):
        require_supported_schema_version(version)
