"""Offline microbenchmarks for JARVIS hot paths; emits one JSON report."""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.schema import CURRENT_SCHEMA_VERSION  # noqa: E402


def _distribution(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)

    def percentile(value: float) -> float:
        index = max(0, math.ceil(len(ordered) * value) - 1)
        return round(ordered[index], 4)

    return {
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": round(ordered[-1], 4),
        "stddev_ms": round(statistics.pstdev(ordered), 4),
    }


def _aggregate_runs(run_stats: list[dict[str, float]]) -> dict[str, float]:
    aggregate = {
        key: round(statistics.median(item[key] for item in run_stats), 4)
        for key in ("p50_ms", "p95_ms", "p99_ms", "stddev_ms")
    }
    aggregate["max_ms"] = round(max(item["max_ms"] for item in run_stats), 4)
    aggregate["p95_between_runs_stddev_ms"] = round(
        statistics.pstdev(item["p95_ms"] for item in run_stats), 4
    )
    return aggregate


def _measure(
    operation: Callable[[], object],
    iterations: int,
    runs: int,
) -> dict[str, object]:
    measurements = []
    for _ in range(runs):
        samples_ms = []
        for _ in range(iterations):
            started = time.perf_counter_ns()
            operation()
            samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        measurements.append(_distribution(samples_ms))
    return {
        "iterations_per_run": iterations,
        "run_count": runs,
        "runs": measurements,
        "aggregate": _aggregate_runs(measurements),
    }


def _mock_tokens() -> Iterable[str]:
    for index in range(6):
        time.sleep(0.001)
        yield f"token-{index}"


def _measure_synthetic_ttft(runs: int = 5, iterations: int = 25) -> dict[str, object]:
    """Compare first visible token with buffered completion using a timed mock stream."""
    measurements: dict[str, list[dict[str, float]]] = {
        "buffered": [],
        "token_stream": [],
    }
    for _ in range(runs):
        samples = {"buffered": [], "token_stream": []}
        for _ in range(iterations):
            started = time.perf_counter_ns()
            next(_mock_tokens())
            samples["token_stream"].append(
                (time.perf_counter_ns() - started) / 1_000_000
            )

            started = time.perf_counter_ns()
            list(_mock_tokens())
            samples["buffered"].append(
                (time.perf_counter_ns() - started) / 1_000_000
            )
        for mode, values in samples.items():
            measurements[mode].append(_distribution(values))
    return {
        "mock_inter_token_delay_ms": 1,
        "tokens_per_response": 6,
        "iterations_per_run": iterations,
        "run_count": runs,
        "buffered": {
            "runs": measurements["buffered"],
            "aggregate": _aggregate_runs(measurements["buffered"]),
        },
        "token_stream": {
            "runs": measurements["token_stream"],
            "aggregate": _aggregate_runs(measurements["token_stream"]),
        },
        "note": "Synthetic mock only; not live Ollama or application TTFT.",
    }


def run_benchmarks(
    iterations: int = 1000,
    runs: int = 3,
    *,
    sqlite_pooled: bool | None = None,
) -> dict:
    from core.memory_store import MemoryStore
    from core.tool_router import ToolRouter
    from core.widget_registry import registry as widget_registry

    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 200 <= iterations <= 100_000:
        raise ValueError("iterations must be between 200 and 100000")
    if isinstance(runs, bool) or not isinstance(runs, int) or not 3 <= runs <= 5:
        raise ValueError("runs must be between 3 and 5 for comparable reports")

    if sqlite_pooled is not None:
        pool_flag = "1" if sqlite_pooled else "0"
        os.environ["JARVIS_MEMORY_POOL"] = pool_flag
        os.environ["JARVIS_SQLITE_POOLED"] = pool_flag
    pool_enabled = (
        os.environ.get("JARVIS_MEMORY_POOL", os.environ.get("JARVIS_SQLITE_POOLED", "0"))
        == "1"
    )
    sqlite_mode = "pooled" if pool_enabled else "legacy"

    router = ToolRouter()
    declarations = [
        {
            "name": name,
            "description": "benchmark tool",
            "parameters": {"type": "OBJECT", "properties": {}},
        }
        for name in ("browser_automation", "web_search", "terminal_run", "chatbot_plan")
    ]

    def routing() -> object:
        return router.select_for_request("cerca una pagina web", declarations)

    widget_counter = 0
    table_rows = [
        {
            "timestamp": f"2026-11-04T21:{index % 60:02d}:00Z",
            "source": f"sensor-{index % 8}",
            "status": "online" if index % 7 else "degraded",
            "value": round(index * 0.137, 3),
            "details": "Representative dashboard row with stable validation fields.",
        }
        for index in range(40)
    ]

    def validate_widget() -> None:
        nonlocal widget_counter
        widget_counter += 1
        error = widget_registry.validate(
            {
                "id": f"perf-{widget_counter}-{uuid.uuid4().hex}",
                "type": "table",
                "payload": {
                    "headers": ["timestamp", "source", "status", "value", "details"],
                    "rows": table_rows,
                },
            }
        )
        if error is not None:
            raise RuntimeError(error)

    rpc_payload = {
        "jsonrpc": "2.0",
        "id": "dashboard-widget-update-000001",
        "method": "tools/call",
        "params": {
            "name": "widget_update",
            "arguments": {
                "id": "system-health",
                "type": "table",
                "payload": {
                    "headers": ["timestamp", "source", "status", "value", "details"],
                    "rows": table_rows,
                },
                "metadata": {
                    "contractVersion": 1,
                    "origin": "dashboard",
                    "session": "benchmark-session-0001",
                },
            },
        },
    }

    def serialize_rpc() -> None:
        encoded = json.dumps(rpc_payload, separators=(",", ":"))
        json.loads(encoded)

    with tempfile.TemporaryDirectory(prefix="jarvis-perf-") as temporary:
        memory = MemoryStore(Path(temporary) / "memory.sqlite3")
        memory_counter = 0

        def memory_roundtrip() -> None:
            nonlocal memory_counter
            memory_counter += 1
            key = f"bench-{memory_counter}"
            memory.remember("session", key, {"value": "baseline"})
            if memory.recall("session", key) != {"value": "baseline"}:
                raise RuntimeError("memory round-trip returned a different value")

        try:
            results = {
                "tool_router_select": _measure(routing, iterations, runs),
                "widget_registry_validate": _measure(validate_widget, iterations, runs),
                "memory_sqlite_roundtrip": _measure(memory_roundtrip, iterations, runs),
                "json_rpc_encode_decode": _measure(serialize_rpc, iterations, runs),
            }
        finally:
            close = getattr(memory, "close", None)
            if close is not None:
                close()
            del memory_roundtrip
            gc.collect()

    resources = None
    try:
        import psutil

        process = psutil.Process()
        resources = {
            "process_rss_mb": round(process.memory_info().rss / (1024 * 1024), 2),
            "system_cpu_percent_1s": psutil.cpu_percent(interval=1.0),
        }
    except ImportError:
        pass

    return {
        "schema_version": 2,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmark_config": {
            "iterations_per_run": iterations,
            "runs": runs,
            "sqlite_mode": sqlite_mode,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or None,
        },
        "microbenchmarks": results,
        "synthetic_ttft": _measure_synthetic_ttft(),
        "resource_snapshot": resources,
        "notes": [
            "The harness requires 200-100000 iterations and 3-5 runs; use three runs for Phase 2 comparisons.",
            "Per-run distributions include p50/p95/p99/max and population stddev.",
            "Aggregate percentiles are medians across runs; max is the maximum across runs.",
            "Microbenchmarks exclude live model/network, real audio hardware, and Qt rendering.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--sqlite-mode", choices=("legacy", "pooled"), default="legacy")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    details = run_benchmarks(
        args.iterations,
        args.runs,
        sqlite_pooled=args.sqlite_mode == "pooled",
    )
    metrics = {}
    for name, result in details["microbenchmarks"].items():
        samples = [run["p50_ms"] for run in result["runs"]]
        metrics[name] = {
            "unit": "ms",
            "samples": samples,
            "median": statistics.median(samples),
        }
    for mode in ("buffered", "token_stream"):
        samples = [
            run["p50_ms"]
            for run in details["synthetic_ttft"][mode]["runs"]
        ]
        metrics[f"synthetic_ttft.{mode}"] = {
            "unit": "ms",
            "samples": samples,
            "median": statistics.median(samples),
        }

    stable_report = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "created_at_utc": details["created_at_utc"],
        "benchmark": {
            "name": "jarvis.core",
            "kind": "offline",
            "unit": "ms",
            "comparison_key": (
                f"sqlite={args.sqlite_mode};iterations={args.iterations}"
            ),
            "parameters": {
                "iterations": args.iterations,
                "runs": args.runs,
                "sqlite_mode": args.sqlite_mode,
            },
            "environment": details["environment"],
        },
        "metrics": metrics,
        "details": details,
    }
    report = json.dumps(stable_report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
