"""Measure live Ollama first-content latency through JARVIS's BrainRouter."""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROMPTS = (
    (
        "brief",
        "In una frase, spiega la differenza tra latenza e throughput in un sistema software.",
    ),
    (
        "short",
        "Riassumi in due frasi perché conviene mantenere un backup verificato prima di "
        "aggiornare un'applicazione.",
    ),
    (
        "medium",
        "Devo scegliere tra SQLite locale e un database remoto per un'app desktop usata "
        "offline. Confronta affidabilità, complessità e disponibilità dei dati, poi "
        "indica una scelta iniziale motivata in massimo quattro frasi.",
    ),
    (
        "multi_step",
        "Prepara un piano in tre passaggi per diagnosticare un'app desktop lenta: separa "
        "misura, individuazione del collo di bottiglia e verifica della correzione. Per "
        "ogni passaggio indica un dato concreto da raccogliere. Rispondi in italiano e "
        "resta sotto 120 parole.",
    ),
    (
        "long",
        "Un assistente locale deve mostrare subito una risposta mentre continua a "
        "generarla. Spiega brevemente come distinguere il tempo al primo contenuto "
        "visibile dal tempo di completamento, quali due misure registrare e quali "
        "condizioni mantenere uguali nel confronto tra streaming e buffering. Usa "
        "quattro punti elenco.",
    ),
)

LOCAL_TOOL_POLICY = (
    "LOCAL TOOL POLICY:\n"
    "For informational or conversational requests, answer directly without tools. "
    "Use only a tool provided for the current request; never call unrelated tools, "
    "create notes, or save memory unless the user explicitly asks. Never repeat a "
    "state-changing tool call. A desktop app launch requires a separate explicit user "
    "confirmation. A direct request to open a recognized app is itself explicit "
    "confirmation; indirect or ambiguous requests still require a separate confirmation. "
    "Every terminal command requires a separate explicit user confirmation before "
    "execution. Computer Use inputs still require confirmation unless the user's request "
    "already specifies both the recognized app and exact text to type. The bounded agent "
    "loop instead requires session approval bound to the exact goal and action limit; its "
    "screen images are sent to Gemini cloud."
)


def _distribution(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)

    def percentile(value: float) -> float:
        return round(ordered[max(0, math.ceil(len(ordered) * value) - 1)], 3)

    return {
        "sample_count": len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": round(ordered[-1], 3),
        "stddev_ms": round(statistics.pstdev(ordered), 3),
    }


def _p95_reliability(sample_count: int) -> str:
    if sample_count < 20:
        return "indicative only: fewer than 20 samples; p50 is the primary signal"
    return "at least 20 samples; p95 is more informative but still workload-specific"


def _request_json(url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"Ollama returned a non-object response from {url}")
    return result


def _ollama_metadata() -> dict[str, Any]:
    base_url = os.environ.get("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("JARVIS_OLLAMA_MODEL", "qwen2.5:7b")
    try:
        version = _request_json(f"{base_url}/api/version")
        tags = _request_json(f"{base_url}/api/tags")
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(
            f"Ollama is unavailable at {base_url}; start Ollama and retry. Details: {exc}"
        ) from exc

    models = tags.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Ollama /api/tags response does not contain a models list.")
    model_info = next(
        (
            item
            for item in models
            if isinstance(item, dict)
            and item.get("name") in {model, model.split(":")[0]}
        ),
        None,
    )
    if model_info is None:
        available = ", ".join(
            item.get("name", "?") for item in models if isinstance(item, dict)
        )
        raise RuntimeError(
            f"Configured Ollama model '{model}' is not installed. Available models: "
            f"{available or 'none'}"
        )

    model_details: dict[str, Any] | None = None
    try:
        details = _request_json(f"{base_url}/api/show", payload={"model": model})
        model_details = details.get("details")
        modelfile = details.get("modelfile", "")
        parameter_overrides = [
            line.strip()
            for line in modelfile.splitlines()
            if line.strip().upper().startswith("PARAMETER ")
        ] if isinstance(modelfile, str) else []
        model_parameters = {
            "parameter_overrides": parameter_overrides,
            "note": (
                "No PARAMETER overrides were returned by /api/show; Ollama runtime "
                "defaults apply."
                if not parameter_overrides
                else "Overrides are extracted from the model's Ollama Modelfile."
            ),
        }
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        model_parameters = {"status": "unavailable", "reason": str(exc)}

    gpu = "unavailable: nvidia-smi not found"
    executable = shutil.which("nvidia-smi")
    if executable:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        gpu = result.stdout.strip() if result.returncode == 0 else (
            f"unavailable: {result.stderr.strip() or 'nvidia-smi failed'}"
        )

    ram_gb: float | None = None
    try:
        import psutil

        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass

    return {
        "ollama_url": base_url,
        "ollama_version": version.get("version", "not returned"),
        "model": model,
        "model_digest": model_info.get("digest"),
        "model_size_bytes": model_info.get("size"),
        "model_details": model_details,
        "model_parameters": model_parameters,
        "generation_parameters": {
            "stream": True,
            "tools": None,
            "options": None,
            "temperature": "not specified; Ollama/model default",
            "num_predict": "not specified; Ollama/model default",
            "note": (
                "BrainRouter sends no per-request options; Ollama and model defaults "
                "apply."
            ),
        },
        "hardware": {
            "platform": platform.platform(),
            "cpu": platform.processor() or platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "ram_gb": ram_gb,
            "gpu": gpu,
        },
    }


def _system_message() -> str:
    prompt_path = ROOT / "core" / "prompt.txt"
    policy_path = ROOT / "regole e vincoli" / "regole e vincoli.md"
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
        policy = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Cannot load the same local prompt inputs used by JARVIS: {exc}") from exc
    return f"{prompt}\n\nSECURITY POLICY (MANDATORY):\n{policy}\n\n{LOCAL_TOOL_POLICY}"


def _warmup(router: Any, system_message: str) -> None:
    events = list(
        router.stream_chat(
            [
                {"role": "system", "content": system_message},
                {"role": "user", "content": "Rispondi con una sola parola: pronto."},
            ]
        )
    )
    if not any(event.get("type") == "done" for event in events):
        raise RuntimeError("Ollama warm-up ended without a completion event.")


def _measure_mode(mode: str, repeats: int) -> dict[str, Any]:
    os.environ["JARVIS_STREAM_TOKEN"] = "1" if mode == "stream" else "0"
    from core.brain_router import BrainRouter, resolve_ollama_model

    router = BrainRouter(backend="local")
    system_message = _system_message()
    _warmup(router, system_message)
    prompt_results: dict[str, Any] = {}
    all_samples: list[float] = []

    for prompt_id, prompt in PROMPTS:
        samples: list[float] = []
        for repetition in range(repeats):
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ]
            started = time.perf_counter_ns()
            first_content_ns: int | None = None
            completed = False
            for event in router.stream_chat(messages):
                now = time.perf_counter_ns()
                if (
                    first_content_ns is None
                    and event.get("type") == "content"
                    and event.get("text")
                ):
                    first_content_ns = now
                if event.get("type") == "done":
                    completed = True
            if not completed:
                raise RuntimeError(f"Ollama did not complete prompt '{prompt_id}'.")
            if first_content_ns is None:
                raise RuntimeError(f"Ollama returned no visible content for '{prompt_id}'.")

            visible_ns = (
                first_content_ns if mode == "stream" else time.perf_counter_ns()
            )
            samples.append((visible_ns - started) / 1_000_000)
            print(
                f"{mode}: prompt={prompt_id} repetition={repetition + 1}/{repeats} "
                f"ttft_ms={samples[-1]:.3f}",
                file=sys.stderr,
                flush=True,
            )
        prompt_results[prompt_id] = {
            "prompt_characters": len(prompt),
            "samples_ms": samples,
            "distribution": _distribution(samples),
            "p95_reliability": _p95_reliability(len(samples)),
        }
        all_samples.extend(samples)

    return {
        "mode": mode,
        "stream_flag": os.environ["JARVIS_STREAM_TOKEN"],
        "model": resolve_ollama_model(),
        "warmup_requests_excluded": 1,
        "prompts": prompt_results,
        "all_prompt_samples": _distribution(all_samples),
        "p95_reliability": _p95_reliability(len(all_samples)),
        "measurement_boundary": (
            "Stream mode: first non-empty BrainRouter content event. Buffered mode: "
            "the time when the full BrainRouter event iterator has completed. Both "
            "consume the complete response; HUD/browser paint is not measured."
        ),
    }


def _worker_main(mode: str, repeats: int) -> int:
    report = _measure_mode(mode, repeats)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--_worker-mode", choices=("buffered", "stream"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("--repeats must be at least 3.")
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive.")
    if args._worker_mode:
        flag_mode = "stream" if os.environ.get("JARVIS_STREAM_TOKEN") == "1" else "buffered"
        if flag_mode != args._worker_mode:
            parser.error("Worker mode must match JARVIS_STREAM_TOKEN.")
        return _worker_main(flag_mode, args.repeats)

    try:
        metadata = _ollama_metadata()
        modes: dict[str, Any] = {}
        for mode in ("buffered", "stream"):
            environment = os.environ.copy()
            environment["JARVIS_STREAM_TOKEN"] = "0" if mode == "buffered" else "1"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--repeats",
                str(args.repeats),
                "--timeout-seconds",
                str(args.timeout_seconds),
                "--_worker-mode",
                mode,
            ]
            result = subprocess.run(
                command,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                timeout=args.timeout_seconds,
            )
            if result.returncode:
                detail = result.stdout.strip()
                raise RuntimeError(
                    f"{mode} benchmark process exited with status {result.returncode}"
                    + (f": {detail}" if detail else ".")
                )
            try:
                modes[mode] = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{mode} benchmark process returned invalid output: {exc}"
                ) from exc
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        print(f"Live TTFT benchmark not completed: {exc}", file=sys.stderr)
        return 2

    report = {
        "schema_version": 1,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmark": {
            "path": "core.brain_router.BrainRouter.stream_chat",
            "prompt_count": len(PROMPTS),
            "repetitions_per_prompt_per_mode": args.repeats,
            "warmup_per_mode": 1,
            "run_processes": "separate subprocess for each stream flag value",
        },
        "ollama": metadata,
        "modes": modes,
        "limitations": [
            "This is live local Ollama output, not a mock.",
            "The measured visibility boundary is the application-facing content event, not browser paint.",
            "Each prompt starts a fresh conversation with the current JARVIS system prompt.",
            "No tool declarations or prior chat history are included.",
            "Warm-up is excluded; results describe steady-state rather than cold model load.",
            "Per-prompt p95 and p99 use only the configured repeat count; interpret as noisy when fewer than 20 samples.",
        ],
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
