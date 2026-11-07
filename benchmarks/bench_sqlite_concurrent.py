"""Concurrent MemoryStore remember/recall benchmark for legacy and pooled modes."""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

METRICS = ("remember_ms", "recall_ms", "round_trip_ms")


def _distribution(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)

    def percentile(value: float) -> float:
        return round(ordered[max(0, math.ceil(len(ordered) * value) - 1)], 4)

    return {
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": round(ordered[-1], 4),
        "stddev_ms": round(statistics.pstdev(ordered), 4),
    }


def _measure_scenario(
    mode: str,
    thread_count: int,
    iterations_per_thread: int,
    runs: int,
    output_dir: Path,
) -> dict[str, Any]:
    from core.memory_store import MemoryStore

    os.environ["JARVIS_SQLITE_POOLED"] = "1" if mode == "pooled" else "0"
    run_samples: list[dict[int, dict[str, list[float]]]] = []
    all_samples: dict[str, list[float]] = {metric: [] for metric in METRICS}
    per_thread_samples = {
        thread_id: {metric: [] for metric in METRICS}
        for thread_id in range(thread_count)
    }

    for run_index in range(runs):
        database = output_dir / (
            f"{mode}-{thread_count}-threads-run-{run_index + 1}.sqlite3"
        )
        store = MemoryStore(database)
        barrier = threading.Barrier(thread_count)

        def worker(
            thread_id: int,
            _store: Any = store,
            _barrier: threading.Barrier = barrier,
            _run_index: int = run_index,
        ) -> tuple[int, dict[str, list[float]]]:
            measurements = {metric: [] for metric in METRICS}
            _barrier.wait(timeout=30)
            for iteration in range(iterations_per_thread):
                key = f"thread-{thread_id}:run-{_run_index}:item-{iteration}"
                expected = {
                    "thread": thread_id,
                    "run": _run_index,
                    "iteration": iteration,
                    "payload": "concurrent-memory-benchmark",
                }

                round_started = time.perf_counter_ns()
                started = time.perf_counter_ns()
                _store.remember("session", key, expected)
                measurements["remember_ms"].append(
                    (time.perf_counter_ns() - started) / 1_000_000
                )

                started = time.perf_counter_ns()
                actual = _store.recall("session", key)
                measurements["recall_ms"].append(
                    (time.perf_counter_ns() - started) / 1_000_000
                )
                measurements["round_trip_ms"].append(
                    (time.perf_counter_ns() - round_started) / 1_000_000
                )
                if actual != expected:
                    raise RuntimeError(
                        f"Memory corruption in {mode}: {key} returned {actual!r}"
                    )
            return thread_id, measurements

        try:
            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = [
                    executor.submit(worker, thread_id)
                    for thread_id in range(thread_count)
                ]
                per_run = dict(future.result() for future in futures)
            for thread_id, measurements in per_run.items():
                for metric, samples in measurements.items():
                    if len(samples) != iterations_per_thread:
                        raise RuntimeError(
                            f"Missing {metric} samples for thread {thread_id}."
                        )
                    all_samples[metric].extend(samples)
                    per_thread_samples[thread_id][metric].extend(samples)
            run_samples.append(per_run)

            expected_rows = thread_count * iterations_per_thread
            for thread_id in range(thread_count):
                for iteration in range(iterations_per_thread):
                    key = f"thread-{thread_id}:run-{run_index}:item-{iteration}"
                    expected = {
                        "thread": thread_id,
                        "run": run_index,
                        "iteration": iteration,
                        "payload": "concurrent-memory-benchmark",
                    }
                    if store.recall("session", key) != expected:
                        raise RuntimeError(f"Post-run verification failed for {key}.")
            if len(per_run) * iterations_per_thread != expected_rows:
                raise RuntimeError("Concurrent run completed with a missing worker.")
        except (sqlite3.Error, RuntimeError, TimeoutError) as exc:
            raise RuntimeError(
                f"{mode} mode failed with {thread_count} threads in run "
                f"{run_index + 1}: {exc}"
            ) from exc
        finally:
            store.close()

    run_aggregates = []
    for run_index, per_run in enumerate(run_samples):
        aggregate: dict[str, Any] = {"run": run_index + 1, "threads": {}}
        for metric in METRICS:
            aggregate[metric] = _distribution(
                [
                    sample
                    for thread_results in per_run.values()
                    for sample in thread_results[metric]
                ]
            )
        for thread_id, measurements in per_run.items():
            aggregate["threads"][str(thread_id)] = {
                metric: _distribution(samples)
                for metric, samples in measurements.items()
            }
        run_aggregates.append(aggregate)

    return {
        "mode": mode,
        "thread_count": thread_count,
        "iterations_per_thread_per_run": iterations_per_thread,
        "runs": runs,
        "aggregate": {
            metric: _distribution(samples) for metric, samples in all_samples.items()
        },
        "per_thread": {
            str(thread_id): {
                metric: _distribution(samples)
                for metric, samples in measurements.items()
            }
            for thread_id, measurements in per_thread_samples.items()
        },
        "per_run": run_aggregates,
        "verified_round_trips": thread_count * iterations_per_thread * runs,
        "data_integrity": "passed",
    }


def run_benchmark(iterations_per_thread: int = 100, runs: int = 3) -> dict[str, Any]:
    if not 1 <= iterations_per_thread <= 500:
        raise ValueError("iterations_per_thread must be between 1 and 500.")
    if not 1 <= runs <= 3:
        raise ValueError("runs must be between 1 and 3.")

    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="jarvis-sqlite-concurrent-") as directory:
        output_dir = Path(directory)
        for mode in ("legacy", "pooled"):
            results[mode] = {}
            for thread_count in (4, 8):
                results[mode][str(thread_count)] = _measure_scenario(
                    mode,
                    thread_count,
                    iterations_per_thread,
                    runs,
                    output_dir,
                )

    return {
        "schema_version": 1,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or None,
            "sqlite": sqlite3.sqlite_version,
        },
        "configuration": {
            "iterations_per_thread_per_run": iterations_per_thread,
            "runs": runs,
            "thread_counts": [4, 8],
            "measurement": "separate remember, recall, and remember+recall round-trip latency",
        },
        "results": results,
        "note": (
            "Each mode/thread-count/run uses a fresh database. Threads synchronize "
            "at a barrier; all returned and persisted values are verified."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations-per-thread", type=int, default=100)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_benchmark(args.iterations_per_thread, args.runs)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        parser.exit(2, f"Concurrent SQLite benchmark failed: {exc}\n")

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
