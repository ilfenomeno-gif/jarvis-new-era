# PERF-POLYGLOT-000: baseline and incremental polyglot plan

**Status:** Phase 0 baseline certified; Phase 1 contract complete; Phase 2 A/B measured, native CI gate open.
**Date:** 2026-11-06
**Scope:** Windows desktop checkout, Python remains the AI/orchestration runtime.

## Executive Summary

Do not move agent orchestration, prompt routing, memory policy, or LLM decisions into another language. Measure first, then move only a demonstrated CPU-bound or isolation-sensitive leaf operation behind a versioned local IPC boundary. Every sidecar remains opt-in and callers retain a Python fallback.

The repository already has a split runtime: Gemini Live is handled in `main.py`; local Ollama streams through `core/brain_router.py`; `core/llm_client.py` is a separate `requests` client with synchronous and streaming APIs. Audio device probes and wake-word inference have background execution, plugin isolation currently uses a Python subprocess with declarative JSON on stdin/stdout, and MCP already has its own stdio/HTTP transports. The new sidecar contract is not a replacement for MCP or the plugin protocol.

## Verified Architecture and Likely Hotspots

| Area | Observed implementation | Hypothesis to measure |
|---|---|---|
| Response quality | `PromptRouter` uses keyword-selected static profiles. `CriticLoop` is a bounded generic revision helper; it is not shown as a mandatory step for every conversational turn. `ChatOrchestrator` persists content-planning conversations and uses adapters; it is not the main Gemini/Ollama chat path. | Compare Fast/Standard/Deep responses on a fixed prompt set; score correctness, relevance, tool choice, and style with a rubric before changing prompts. |
| LLM latency | Gemini Live and local Ollama are separate paths. `BrainRouter` parses Ollama streaming NDJSON, but local handling previously collected each stream into a list before dispatching final text/tools. `llm_client.py` has a separate `requests` client; its stream API yields sentence-sized chunks for TTS and is not the local `BrainRouter` path. `ws_server.py` handles Gemini full replies. | Capture live TTFT and token throughput per backend/model; compare local first-token and full-turn latency with/without warmup. |
| Audio | `main.py` uses 16 kHz input / 24 kHz output and batches output writes up to about 200 ms. The mic callback routes frames and schedules loop/UI work. Audio endpoint probing is cached and run in the background; wake-word inference runs on its own thread. STT/TTS model initialization can still be expensive. | Measure callback p95/max, input/output frame underruns, model cold-start, and end-to-end speech turn latency on the target device. |
| Computer use | OCR and input are separate Python components. Input is guarded by foreground-process checks, exact-action confirmation, and emergency stop. | Measure request-to-action and OCR time independently; evaluate C# only if UI Automation/platform calls dominate and a Windows-native implementation has parity tests. |
| Terminal/plugin safety | `TerminalAgent` parses with `shlex`, disallows shell operators, applies an allowlist, and executes with `shell=False`. Plugin sandbox is process isolation with timeout/output caps, but is explicitly not an OS security boundary. | Keep current policy as the oracle. Compare parser latency only after profiling; consider Rust/Wasmtime only if threat model and measured isolation needs justify the operational cost. |
| Network/MCP | WebSocket server binds loopback and authenticates; MCP supports stdio and streamable HTTP; n8n is outbound polling. | Measure request p50/p95, serialization cost, throughput, and failure rate under a repeatable local load before considering Rust/Go. |
| HUD/widgets/viewer | `widget_registry.py` validates payloads and throttles updates; renderer classes live in Python/Qt. HUD bridge serves loopback SSE. The 3D viewer source is already TypeScript/Three.js and includes Rapier WASM. | Measure actual Qt widget create/update time, HUD event delivery, frame time/FPS and memory at representative widget counts. JSON-only microbenchmarks do not represent render time. |
| Memory | `MemoryStore` uses SQLite/WAL. The legacy default opens a connection per operation; the opt-in pool keeps one connection per thread with NORMAL synchronous mode. Chat planning writes messages, key points, checkpoints, and events. | Validate lock contention, crash durability, and p50/p95 against a representative concurrent application workload before enabling pooling by default. |

`struttura_progetto.txt` is a generated Windows tree dump containing `.venv` and cache contents. It is not treated as an authoritative architecture map; this report and `docs/REPO_MAP.md` describe the source files inspected in the current checkout.

## Phase 0: Benchmark Contract and Baseline

### Captured environment

- Windows 11, build `10.0.26300`; Python `3.13.7`.
- CPU identifier: `Intel64 Family 6 Model 191 Stepping 2, GenuineIntel`.
- Rust compiler/Cargo are unavailable in this environment. .NET 8 runtime is installed; no .NET SDK is installed. Ruff `0.17.3` is available in `.venv`.
- The snapshot is a developer workstation measurement, not a production or GPU benchmark.

### Offline microbenchmark results

Command: `python benchmarks/bench_core.py --iterations 200`, run three times. The table reports the median of the three run-level p50/p95/max values.

| Operation | p50 (ms) | p95 (ms) | max (ms) | Notes |
|---|---:|---:|---:|---|
| ToolRouter request selection | 0.0547 | 0.0625 | 0.4713 | Four synthetic declarations; no model/network. |
| Widget registry validation | 0.0022 | 0.0029 | 0.0377 | Python schema validation only; no Qt renderer. |
| SQLite MemoryStore write + read | 8.7011 | 11.7831 | 20.7848 | Fresh key per sample; includes DB connection and durable write overhead. |
| JSON-RPC-shaped JSON encode + decode | 0.0037 | 0.0044 | 0.0245 | Serialization only; excludes sockets and native sidecars. |

Latest process snapshot: RSS `27.73 MB`; system CPU over one second `3.9%`. CPU is a noisy workstation snapshot, not an idle-JARVIS baseline. The process RSS belongs to this short benchmark, not to the full GUI application.

### Phase 1 closeout benchmark (same-harness comparison)

The older table above is a historical capture, not a comparable before/after
baseline. It used 200 iterations across three runs, validated a tiny text
widget, and encoded a small `health` request. The current harness uses at least
1,000 iterations across exactly five runs, validates a 40-row dashboard table,
and serializes a representative `tools/call` request. Percentiles use
nearest-rank per run; the table reports the median of run-level p50/p95/p99 and
standard deviations, plus the maximum seen across runs. Do not compare the
old 11.7831 ms SQLite p95 directly with the new legacy value; compare only the
legacy and pooled rows below, which were collected with the same command,
machine, and payloads.

Command for both captures:
`python benchmarks/bench_core.py --iterations 1000 --runs 5 --sqlite-mode legacy|pooled`

| Operation | Mode | p50 ms | p95 ms | p99 ms | max ms | stddev ms | p95 run-to-run stddev ms |
|---|---|---:|---:|---:|---:|---:|---:|
| ToolRouter select | Legacy | 0.0552 | 0.0689 | 0.0965 | 0.4831 | 0.0148 | 0.0075 |
| ToolRouter select | Pooled | 0.0546 | 0.0640 | 0.0996 | 0.8265 | 0.0149 | 0.0017 |
| Widget registry validation | Legacy | 0.0024 | 0.0059 | 0.0073 | 7.0413 | 0.0067 | 0.0016 |
| Widget registry validation | Pooled | 0.0023 | 0.0027 | 0.0048 | 0.1418 | 0.0017 | 0.0004 |
| SQLite write + read | Legacy | 13.0418 | 14.1656 | 15.6776 | 132.3094 | 0.6863 | 0.9719 |
| SQLite write + read | Pooled | 0.0305 | 0.0532 | 0.1237 | 7.2255 | 0.2904 | 0.0041 |
| JSON-RPC encode + decode | Legacy | 0.0584 | 0.0656 | 0.1057 | 0.9092 | 0.0153 | 0.0082 |
| JSON-RPC encode + decode | Pooled | 0.0600 | 0.0767 | 0.1141 | 0.6065 | 0.0127 | 0.0025 |

`stddev` is the median of the five per-run sample standard deviations;
`p95 run-to-run stddev` is the population standard deviation of five run-level
p95 values. A pre-change capture using this updated harness measured legacy
SQLite p50/p95/p99/max/stddev at `7.7845/9.0995/14.8353/204.9893/1.1811 ms`
(run-to-run p95 stddev `1.6666 ms`). The final flag-off repeat measured
`13.0418/14.1656/15.6776/132.3094/0.6863 ms` (run-to-run p95 stddev
`0.9719 ms`); this host variance is why the final table uses the final
flag-off/pooled captures and reports dispersion instead of claiming precision
from one run.

Against the final flag-off capture, SQLite p95 improved `99.62%` (14.1656 to
0.0532 ms) and p50 `99.77%` (13.0418 to 0.0305 ms). WAL was already enabled before this task; inspection
confirmed each operation opened a new connection and `PRAGMA synchronous`
returned `2` (`FULL`). The Phase 1 opt-in mode reused one lock-serialized
connection per `MemoryStore`, retained WAL, and set `synchronous=NORMAL`.
Phase 2 replaces this with one connection per thread while retaining the
compatibility flag. The 6.6654 ms pooled
max is a workstation outlier; the feature remains opt-in pending application
workload testing and crash-durability review.

Synthetic TTFT uses a mock six-chunk stream with a 1 ms delay per chunk. Across
five runs of 25 samples, buffered p50/p95/p99/max/stddev was
`9.4394/9.6358/9.7871/10.0852/0.1535 ms`; token-stream p50/p95/p99/max/stddev
was `1.5502/1.6175/1.6863/2.2403/0.1109 ms` (83.2% lower p95). This models
when the first visible chunk is emitted; it is not live Ollama, network, HUD
rendering, or production TTFT. The p95 run-to-run standard deviations were
`0.1156 ms` buffered and `0.0995 ms` token-stream.

The Phase 1 concurrency measurements and recommendation below refer to that
single lock-serialized connection implementation. Phase 2 retains this
historical result but measures the new thread-local implementation separately.

### Pre-task pytest baseline

The checkout was already dirty before this task (branch `refactor/src-layout`,
with tracked and untracked Phase 0 and application changes). To preserve those
changes, no stash or clean/reset was performed. The exact pre-task command was:

`$env:PYTHONPATH=(Get-Location).Path; python -m pytest -q -c pytest.ini --ignore=tests/e2e`

Result before task edits: **7 failed, 1043 passed, 16 skipped**. The seven
existing failures were:

- `tests/test_audio_output.py::test_play_audio_survives_portaudio_write_failure`
- `tests/test_deck_pipeline.py::test_presentation_request_is_routed_automatically_without_deck_command`
- `tests/test_file_processor.py::test_script_execution_requires_confirmation_before_subprocess`
- `tests/test_file_processor.py::test_host_requires_exact_script_path_confirmation`
- `tests/test_interface_studio.py::test_studio_tool_contract_and_hud_command_handlers`
- `tests/test_viewer3d.py::test_real_page_model_events_restore_viewer_and_report_load_errors`
- `tests/test_voice_config.py::test_default_voice_is_jarvis_voice_and_iris_uses_female_voice`

The command excludes `tests/e2e`, whose conftest cannot import `tests.e2e`
because this checkout has no `tests/__init__.py`. Plain `pytest -q` also stops
before collection because the existing `pyproject.toml` has a leading UTF-8
BOM that pytest's TOML parser rejects. These environment/configuration issues
were not changed as part of this task.

### Other required live baselines (not captured yet)

Live Ollama TTFT is now measured below. No real audio loop or controlled Qt render session was used for this report. Record these before accepting performance claims in those areas:

| Metric | Measurement definition | Baseline |
|---|---|---|
| First-token latency (TTFT) | User turn accepted to first visible text/audio token; report warm/cold separately, p50/p95 over at least 30 turns per mode. | Live Ollama comparison below has 15 turns per mode; the 30-turn target remains, as do browser paint and cold-start measurements. |
| Token throughput | Output tokens divided by generation seconds, excluding user think time; report backend/model. | Not measured; provider/model unavailable. |
| Audio frame health | Callback duration p50/p95/max, queue depth, underruns/dropped frames; record input and output separately. | Not measured; requires a real audio endpoint. |
| Input-to-action | User intent accepted to first tool side effect and to verified tool result; p50/p95 by tool class. | Not measured; requires controlled desktop fixture. |
| Widget/UI | Qt widget create/update p50/p95; HUD and viewer frame-time p50/p95 and missed frames at fixed viewport/widget count. | Not measured; the offline harness does not create QApplication. |
| CPU/RAM | Jarvis process idle and scripted workload RSS/CPU; sample at 1 Hz for 5 minutes. | Not measured for the application process. |
| Errors | Tool, model, transport, and render errors divided by operation count; preserve category and backend. | Not measured end-to-end. |
| Answer quality | Fixed Italian/English prompt set, double-scored 0–2 for correctness, relevance, style/length, and tool choice; report aggregate and regressions. | Rubric proposed; no model outputs scored. |

### Repeatable harness

`benchmarks/bench_core.py` uses only existing Python modules plus optional `psutil`. It emits JSON to stdout or `--output <path>`. It requires at least 1,000 iterations and exactly five runs and emits per-run p50/p95/p99/max/stddev plus run aggregates. `--sqlite-mode legacy|pooled` selects the benchmark storage mode. Use the same host, power mode, provider/model, viewport, and payloads for comparisons. Do not commit machine-specific reports containing user paths or environment details unless explicitly reviewed.

### Empirical live TTFT and concurrent SQLite validation

These are live local measurements from 2026-11-04, not synthetic timings. No
application defaults or runtime code paths were changed for this validation.

#### Live Ollama TTFT

Run from the repository root:

```powershell
python benchmarks\bench_ttft_live.py --repeats 4 --output "$env:TEMP\jarvis-ttft-live.json"
```

Prerequisites: Ollama reachable at `JARVIS_OLLAMA_URL` (default
`http://127.0.0.1:11434`), the configured `JARVIS_OLLAMA_MODEL` installed (default
`qwen2.5:7b`), and the prompt/policy files used by JARVIS present. The script
preflights the server and model and exits nonzero without writing a report if
either is unavailable. It starts separate Python processes with
`JARVIS_STREAM_TOKEN=0` and `=1`, uses `core.brain_router.BrainRouter.stream_chat`
and the current JARVIS system prompt/local tool policy, and runs five fixed
Italian prompts (brief through multi-step) four times per mode. One warm-up
request per mode is excluded. It consumes each complete response so the
buffered measurement ends when the full event list is available; streaming
TTFT is the first non-empty application-facing content event. This does not
include browser paint, nor prior conversation history or tool declarations.
The same `/api/chat` stream request is used by `BrainRouter` for both modes;
the flag changes when the app presents the chunks, not Ollama's generation.

Captured environment: Ollama `0.40.14`; model `qwen2.5:7b`, digest
`845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`
(4,683,087,332 bytes); Windows 11 build `10.0.26300`; Intel64 Family 6 Model
191 Stepping 2; 16 logical CPUs; 31.8 GiB RAM; NVIDIA GeForce RTX 4060 with
8,188 MiB and driver `610.88`. The request uses `stream=true`, no tools, and
does not send `options`, `temperature`, or `num_predict`; the Ollama model
Modelfile returned no `PARAMETER` overrides, so server/model defaults apply.
Four repetitions of each of five prompts provide 20 samples per mode. Report
p50 as the primary signal and p95 as a comparative tail indicator. If there
are fewer than 20 samples per mode, explicitly treat p95 as noisy and p50 as
the primary signal. Per-prompt distributions have only four samples, so their
p95/p99 are noisy and effectively the observed maximum.

Across all 20 measured requests per mode. The p50 is the primary comparison;
p95 is reported as an indicative tail estimate from 20 samples:

| Mode | p50 ms | p95 ms | p99 ms | max ms | stddev ms |
|---|---:|---:|---:|---:|---:|
| Buffered (`JARVIS_STREAM_TOKEN=0`; visible after completion) | 2861.727 | 9725.197 | 9989.360 | 9989.360 | 2535.678 |
| First content event (`JARVIS_STREAM_TOKEN=1`) | 302.369 | 358.629 | 404.666 | 404.666 | 31.083 |

The primary p50 signal improved from 2.862 s buffered to 0.302 s at the first
content event. The indicative p95 was 9.725 s buffered and 0.359 s streaming.
Per-prompt distributions (four samples each; consequently p95 and p99 are noisy
and effectively the sample maximum) were:

| Mode | Prompt | p50 ms | p95 ms | p99 ms | max ms | stddev ms |
|---|---|---:|---:|---:|---:|---:|
| Buffered | brief | 1198.957 | 2241.826 | 2241.826 | 2241.826 | 434.837 |
| Buffered | short | 2333.785 | 3086.230 | 3086.230 | 3086.230 | 396.079 |
| Buffered | medium | 2757.900 | 3497.350 | 3497.350 | 3497.350 | 554.663 |
| Buffered | multi-step | 3103.185 | 4086.704 | 4086.704 | 4086.704 | 470.214 |
| Buffered | long | 8103.813 | 9989.360 | 9989.360 | 9989.360 | 2026.297 |
| First content event | brief | 305.613 | 340.303 | 340.303 | 340.303 | 16.134 |
| First content event | short | 293.829 | 353.182 | 353.182 | 353.182 | 25.059 |
| First content event | medium | 289.141 | 358.629 | 358.629 | 358.629 | 30.766 |
| First content event | multi-step | 294.180 | 404.666 | 404.666 | 404.666 | 48.069 |
| First content event | long | 328.528 | 347.464 | 347.464 | 347.464 | 10.020 |

This confirms a real steady-state improvement at the BrainRouter-to-caller
boundary for this model and workload. It is not a browser-render measurement;
per-prompt p95/p99 remain noisy because they have four observations. Repeat on
the target machine and with real HUD clients before treating the measurements
as a production SLA.

#### Concurrent SQLite remember/recall

Run from the repository root:

```powershell
python benchmarks\bench_sqlite_concurrent.py --iterations-per-thread 100 --runs 3 --output "$env:TEMP\jarvis-sqlite-concurrent.json"
```

The harness permits at most 500 iterations per thread and three runs, comparing
`JARVIS_SQLITE_POOLED=0` and `=1` at 4 and 8 barrier-synchronized threads. Each
thread performs 100 remember/recall round trips per run; three fresh-database
runs are used for each mode/thread count. It reports
p50/p95/p99/max/stddev separately for remember, recall, and round-trip, both
aggregated and per thread, and verifies all written values after each run.
This capture verified 1,200 round trips at 4 threads and 2,400 at 8 threads
per mode, with no exceptions or data mismatches.

Aggregate remember+recall round-trip latency:

| Threads | Mode | p50 ms | p95 ms | p99 ms | max ms | stddev ms | Per-thread p95 range ms |
|---:|---|---:|---:|---:|---:|---:|---:|
| 4 | Legacy | 19.7571 | 69.7759 | 157.9285 | 1102.0479 | 49.1062 | 61.0393–78.7680 |
| 4 | Pooled | 0.2654 | 0.4258 | 0.9619 | 2.6212 | 0.1634 | 0.3944–0.4415 |
| 8 | Legacy | 13.3501 | 80.5535 | 652.5009 | 2762.8295 | 162.5806 | 60.9628–133.5104 |
| 8 | Pooled | 0.5428 | 1.0099 | 2.8205 | 11.1785 | 0.9109 | 0.8675–1.1114 |

An exploratory legacy run at 200 iterations per thread stopped with
`sqlite3.OperationalError: database is locked` during `remember`; it produced
no accepted timing report and is not included in the table. The repeatable
100-iteration runs completed cleanly. This higher-load lock failure is retained
as a finding, not hidden by retries or percentile adjustments. Pooling's
shared-connection lock serializes operations, but in the measured workload its
p95 remained below legacy at both concurrency levels. The high legacy maxima
and the one failed exploratory run warrant a longer soak before changing
defaults.

#### Raccomandazione default

- **`JARVIS_SQLITE_POOLED`: promote with caveat, but leave the code default off
  for now.** The three-run concurrent p95 is substantially lower in pooled mode
  at 4 and 8 threads and all accepted round trips passed integrity checks.
  Keep the flag opt-in until at least 14 days of application-workload
  observation show no corruption, unrecoverable lock errors, or shutdown/
  restart issues; explicitly review the durability trade-off from
  `synchronous=NORMAL` before changing the default.
- **`JARVIS_STREAM_TOKEN`: promote with caveat, but leave the code default off
  for now.** The primary live TTFT p50 improved from 2.862 s buffered to
  0.302 s at the first content event; the 20-sample p95s were 9.725 s and
  0.359 s respectively, and should be treated as indicative. Observe at least
  7 days with the real HUD client and representative conversation lengths;
  verify event ordering, completion/error cleanup, and perceived rendering
  before changing the default. The present measurement excludes browser paint.

Neither recommendation changes a feature-flag default in this task.

## Phase 1: Versioned Sidecar Contract

### Contract v1

- Transport: one JSON-RPC 2.0 request and response per TCP connection, newline-delimited UTF-8 JSON.
- Network exposure: bind and connect only to `127.0.0.1`; non-loopback hosts are rejected by the Python client.
- Authentication: `JARVIS_POLYGLOT_TOKEN`, at least 32 characters, sent in `params.token`; never log it or request payloads.
- Versioning: each request includes `params.contractVersion: 1`; health response includes `result.contractVersion: 1`.
- Required method: `health`, returning `{contractVersion: 1, status: "ok", implementation, capabilities: ["health"]}`.
- Errors: JSON-RPC standard codes `-32700` parse, `-32600` invalid request, `-32601` unknown method, plus `-32001` unauthorized and `-32002` incompatible contract.
- Limits: 1 MiB per line, 0.5 s default client connect/read timeout (caller-overridable), one request per connection. Future method schemas must add input/output size bounds and cancellation semantics before implementation.
- Logging: diagnostics go to stderr; stdout is not used as a control channel for these TCP sidecars. No secrets or prompts are logged.
- Capability negotiation: consumers must inspect `capabilities`; unknown capabilities/methods fail closed and use Python fallback.

Python entry point: `core.sidecar_runtime.JsonRpcSidecar`. `run_optional_sidecar()` recognizes only the `rust` and `dotnet` feature names. Flags are disabled unless set exactly to `1`:

- `JARVIS_POLYGLOT_RUST=1` and `JARVIS_POLYGLOT_RUST_PORT` (default server port 18761).
- `JARVIS_POLYGLOT_DOTNET=1` and `JARVIS_POLYGLOT_DOTNET_PORT` (default server port 18762).
- `JARVIS_POLYGLOT_TOKEN` is required whenever either flag is enabled.
- Each server reads `JARVIS_SIDECAR_PORT` (default set by language: Rust 18761, .NET 18762) and the shared token.

Both native skeletons currently implement health only; unsupported operations return JSON-RPC `-32601`, and the Python adapter falls back. These processes do not start automatically and do not change JARVIS behavior while flags are off. Do not enable a flag until the matching sidecar is built, launched with a fresh local token, and tested against the same contract version.

### Phase 1 application feature flags and streaming path

- `JARVIS_MEMORY_POOL=0` (default): preserve per-operation connections. Set to
  `1` to enable a thread-local Python SQLite connection pool with
  `journal_mode=WAL` and `synchronous=NORMAL`; call `MemoryStore.close()` during
  explicit teardown. `JARVIS_SQLITE_POOLED` remains a compatibility alias when
  `JARVIS_MEMORY_POOL` is unset. Set the selected flag back to `0` to roll back.
- `JARVIS_STREAM_TOKEN=0` (default): preserve buffered local chat behavior. Set
  to `1` to publish Ollama `BrainRouter` content chunks as additive
  `chat_stream` (`start`/`append`/`end`) events over the existing HUD SSE
  channel. Set back to `0` to roll back.
- `core/chat_orchestrator.py` persists planner conversations; it is not the
  Ollama chat path. `core/llm_client.py` has its own streaming generator but is
  not used by the local `BrainRouter` route. `core/ws_server.py` handles Gemini
  full replies, not the local Ollama route. The runtime change therefore uses
  the actual `main.py` → `core/brain_router.py` → HUD SSE path and does not
  change the WebSocket, MCP, or JSON-RPC contracts.

The `.github/workflows/build-sidecars.yml` workflow installs stable Rust and
the .NET 8 SDK and compiles both health-only skeletons. In Phase 2 it was
updated to run the binary-required pytest smoke tests after `cargo build
--release` and `dotnet build -c Release`. The local host has neither
Cargo/Rust nor a .NET SDK, so those native builds cannot be verified here.
Phase 1 implementation is complete, but its acceptance gate remains **open
until the workflow completes successfully in CI**.

## Phase 2: Native build, smoke, and SQLite A/B gates

Date: 2026-11-06. No JARVIS tool operation was migrated to either sidecar.

### Gate 1 — Native CI build

- The existing `build-sidecars.yml` was extended rather than duplicated. It
  installs stable Rust and the .NET 8 SDK, runs `cargo build --release` in
  `sidecars/rust/`, runs `dotnet build -c Release` in `sidecars/dotnet/`, then
  runs the binary-required smoke tests.
- **Status: open / blocked for local verification.** `cargo` and `rustc` are
  absent; `dotnet` reports that no SDK is installed. No native build output is
  claimed. The configured GitHub repository currently exposes zero Actions
  workflows and zero workflow runs; commit/push this workflow to a branch and
  wait for a successful run before marking the gate green.
- No compiler errors were observable locally, so neither `main.rs` nor
  `Program.cs` was changed speculatively.

### Gate 2 — Real-binary health smoke and fallback

- `JARVIS_POLYGLOT_RUST_BIN` and `JARVIS_POLYGLOT_DOTNET_BIN` now optionally
  identify a binary or .NET DLL for `run_optional_sidecar()`. With a binary
  configured, the runtime chooses a loopback port, starts the process, checks
  versioned `health`, performs the requested method, then terminates and waits
  for the process. Without a binary path, the prior externally launched
  sidecar/mock-or-Python-fallback behavior is unchanged.
- Tests marked `requires_sidecar_binary` run both native targets and include
  the direct `sidecars.smoke` process-cleanup check. They skip with explicit
  build/runtime prerequisites when a binary or .NET 8 runtime is missing.
  Separate tests verify that a child that exits early or never replies falls
  back to Python.
- **Status: yellow / native half open.** Focused tests report 14 passed and
  2 native-binary tests skipped locally: Rust binary absent (Rust stable and
  `cargo build --release` required); .NET binary absent (.NET 8 SDK and
  `dotnet build -c Release` required). The Python mock tests are not evidence
  of native compilation. CI must run the marked tests against both build
  outputs.

### Gate 3 — SQLite A/B measurement and decision

The offline harness runs 200 iterations in each of three measured runs and
reports the median run-level p50/p95 plus the maximum across runs. Commands,
from the project root:

```powershell
python benchmarks\bench_core.py --iterations 200 --sqlite-mode legacy
python benchmarks\bench_core.py --iterations 200 --sqlite-mode pooled
```

`pooled` selects the `JARVIS_MEMORY_POOL=1` thread-local implementation; the
legacy row selects `JARVIS_MEMORY_POOL=0`. Both use the same operation: a
fresh-key `MemoryStore.remember()` followed by `recall()`. Results below are
local offline microbenchmarks, not application-live measurements:

| Scenario | Median p50 (ms) | Median p95 (ms) | Max across 3 runs (ms) | Runs × iterations |
|---|---:|---:|---:|---:|
| A — legacy connection per operation | 13.9253 | 16.0004 | 79.2554 | 3 × 200 |
| B — thread-local Python pool | 0.0327 | 0.0639 | 9.7349 | 3 × 200 |
| C — native SQLite sidecar | Not measured | Not measured | Not measured | Not run |

Decision threshold applied: **B p95 < 3 ms means no SQLite sidecar**. B
measured `0.0639 ms` p95, so the decision is **NO-GO for a SQLite sidecar**;
the measured connection setup overhead is removable in Python. Scenario C was
not run because no native binaries were available and both sidecars remain
health-only, with no SQLite operation to benchmark. The largest B sample was
`9.7349 ms`, a tail outlier retained in the report; the pool stays opt-in
pending representative concurrency and durability observation.

### H3 scope and residual risks

This phase does not change Harness H3 (`docs/impl/HARNESS-H3.md`). Its
documented follow-up work is tracked as H4: keyed journal
authenticity/migration, operation-specific effect classification, granular
redaction/expiry, and configurable judge schemas. For PERF-POLYGLOT, remaining
risks are unverified native builds/smoke, `synchronous=NORMAL` durability,
per-thread connection growth and SQLite write contention, and the fact that
offline percentiles do not represent a live JARVIS workload.

#### QtWebEngine viewer3D test investigation

Verdict: **environment-specific QtWebEngine/GPU failure in suite context; no
Phase 2 regression found.** The exact viewer test passed three consecutive
isolated runs (9.10 s, 9.23 s, 10.64 s), and passed in 10.29 s with only the
Phase 2 task files stashed. The test code and its strict assertions were not
changed. This stash comparison shows the Phase 2 files do not determine the
failure.

The original full suite and the filtered suite showed Chromium GPU
context-loss diagnostics around the PBR assertion. With `QT_OPENGL=software`
and `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, the isolated test failed at
the rendering assertion and QtWebEngine reported `Failed to create GLES3
context` and `Failed to create shared context for virtualization`. This
environment does not provide a working software-render path for the test.

A subsequent full-suite rerun terminated with Windows access violation
`-1073741819` inside the different viewer3D case
`test_real_page_pc_cad_explodes` (`tests/test_viewer3d.py:821`), while
constructing `JarvisUI`; it produced no pytest summary/counts. The filtered
rerun completed with **1 failed, 1122 passed, 7 skipped, 7 deselected**, 49
warnings in 147.09 s, with the original realistic-PBR assertion as its only
failure. The varying isolated/full-suite outcomes are consistent with
QtWebEngine GPU/resource instability and shared UI state on this machine,
not a deterministic product assertion regression.

No `requires_gpu` marker was added: the exact test passes when isolated on
this host, and marking it skipped would conceal valid GPU-capable runs. Do
not weaken its PBR assertions. Treat it as environment-specific and
**not verifiable in CI without a supported GPU/WebEngine runner**; rerun there
if a GPU-enabled CI target is available.

Captured failure excerpt (last 30+ lines from the isolated software-rendering
run; full output saved locally as
`%TEMP%\perf-polyglot-viewer3d-software-gpu.txt`):

```text
        from PyQt6.QtWidgets import QApplication
        import ui as ui_module

        MODELS_DIR.mkdir(exist_ok=True)
        gen = MODELS_DIR / "image-ferrari-abc123.glb"
        gen.write_bytes(trimesh.creation.box().export(file_type="glb"))
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            jarvis = ui_module.JarvisUI("")
            win = jarvis._win
            viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/pc.glb"}, player=jarvis)
            state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
            assert state["model"]["status"] == "ready", state["model"]
            viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
            viewer_3d.viewer_3d({"mode": "highlight_part", "part": "cpu"}, player=jarvis)
            state = _poll_state(app, win, lambda s: s["model"]["explode"] == 1 and s["model"]["glowing"] > 0)
            assert state["model"]["glowing"] > 0 and state["model"]["highlight"] == "cpu", state["model"]

            viewer_3d.viewer_3d({"mode": "set_material_style", "style": "realistic"}, player=jarvis)
            state = _poll_state(app, win, lambda s: s["model"]["style"] == "realistic" and s["look"]["shadows"])
            look = state["look"]
>           assert look["shadows"] and look["shadowFloor"] and look["shadowCasters"] >= 9, look
E           AssertionError: {'environment': False, 'envLoaded': False, 'envError': '', 'shadows': False, ...}
E           assert (False)

tests\test_viewer3d.py:505: AssertionError
---------------------------- Captured stderr call -----------------------------
[25760:9252:1106/221229.711:ERROR:../../../qtwebengine/src/3rdparty/chromium/gpu/ipc/service/gpu_channel_manager.cc:920] Failed to create GLES3 context, fallback to GLES2.
[25760:9252:1106/221229.711:ERROR:../../../qtwebengine/src/3rdparty/chromium/gpu/ipc/service/gpu_channel_manager.cc:931] ContextResult::kFatalFailure: Failed to create shared context for virtualization.
[25760:9252:1106/221230.452:ERROR:../../../qtwebengine/src/3rdparty/chromium/gpu/ipc/service/gpu_channel_manager.cc:920] Failed to create GLES3 context, fallback to GLES2.
[25760:9252:1106/221230.452:ERROR:../../../qtwebengine/src/3rdparty/chromium/gpu/ipc/service/gpu_channel_manager.cc:931] ContextResult::kFatalFailure: Failed to create shared context for virtualization.
[25760:9252:1106/221230.452:ERROR:../../../qtwebengine/src/3rdparty/chromium/gpu/ipc/service/gpu_channel_manager.cc:920] Failed to create GLES3 context, fallback to GLES2.
[25760:9252:1106/221230.452:ERROR:../../../qtwebengine/src/3rdparty/chromium/gpu/ipc/service/gpu_channel_manager.cc:931] ContextResult::kFatalFailure: Failed to create shared context for virtualization.
=========================== short test summary info ===========================
FAILED tests/test_viewer3d.py::test_real_page_realistic_pbr_teaching_and_generated_label
============================= 1 failed in 48.36s =============================
```

### Phase 3 TODO

Keep all sidecars health-only and defaults off. First collect representative
audio callback/underrun, UI Automation, and application-memory profiles; only
then select a leaf operation for a sidecar if it clears the documented 20%
p95 improvement or isolation/availability criterion. Before enabling memory
pooling by default, run a concurrent workload and durability/restart soak.
Close Gate 1 with a successful CI link/log and Gate 2 with both native smoke
tests green.

### Rollback

Set both polyglot flags to `0` or unset them; all callers immediately take their Python fallback. Stop the optional sidecar processes. No runtime database, prompt, or existing UI state is migrated. The Python protocol adapter can be removed independently of the unreferenced native skeletons. Future hot-module migrations must keep the original Python path behind the same flag for at least one release.

## Incremental Roadmap

| Phase | Scope and candidate files | Exit gate | Effort estimate |
|---|---|---|---:|
| 0. Measure | `benchmarks/bench_core.py`, this report, `docs/REPO_MAP.md` | 1,000+ iterations × five runs; live metrics explicitly identified. | Complete |
| 1. Contract/skeleton | `core/sidecar_runtime.py`, `sidecars/rust/`, `sidecars/dotnet/`, `sidecars/smoke.py`, workflow and runtime flags | Unit tests/fallbacks pass; native health workflow green. CI result pending. | Implementation complete; CI gate pending |
| 2. Native and memory gates | Extend sidecar CI/smoke, measure legacy vs thread-local SQLite, make a measured go/no-go decision. | Both native build/smoke jobs green; A/B uses at least three runs; sidecar only if B ≥ 3 ms p95 and C < B/2. | Complete except native CI |
| 3. Hot modules | First profile audio; separately evaluate C# UI Automation, Rust guard/sandbox only if justified. | At least 20% p95 improvement or a documented isolation/availability gain, parity tests, privacy review, and rollback flag. Do not choose Go for a measured non-bottleneck. | 1–3 weeks per selected module |
| 4. HUD/widgets | Evolve `core/widget_registry.py`, renderers, `ui.py`, `core/jarvis_hud.html`, `assets/viewer3d/src/`; TypeScript incrementally. | Versioned widget schema, permission/layout/render contracts, invalid-widget fallback test, Qt fallback preserved, frame-time baseline improved or neutral. | 2–4 weeks |
| 5. Response quality | Add policy/style modules near `core/prompt_router.py`, `core/guardrails.py`, `core/critic_loop.py`; fixed evaluation set. | No raw chain-of-thought; quality rubric non-regression and measured latency per Fast/Standard/Deep policy. | 1–2 weeks |
| 6. Optimization | Profile-gated changes near `core/brain_router.py`, `core/llm_client.py`, memory, WebSocket streaming. | Per-change before/after p50/p95, bounded cache/timeout, and provider fallback tests. | 1–2 weeks |

Effort assumes one engineer and a working target model/device. It excludes procurement, model downloads, SDK/toolchain setup, and end-user acceptance testing. Phases 3–6 are proposals, not part of this implementation.

## Test and Benchmark Plan

1. Unit tests for strict loopback-only addressing, contract version, token rejection, JSON-RPC IDs/errors, message limit, timeout, feature-off no-connect, feature-on result, and failure-to-Python fallback.
2. Native CI smoke: build both skeletons, launch them with an ephemeral loopback token/port, and validate JSON-RPC v1 health. Add wrong-token/version and unknown-method smoke cases before any native operation is introduced.
3. Run focused Python tests and the full pytest suite; run Ruff on changed Python modules. Preserve and report baseline failures; do not treat skipped live/hardware tests as passed measurements. Phase 1 excluded `tests/test_ui_panels.py` due a reported Windows Qt access violation; Phase 2's exact full and filtered test outcomes are recorded at the end of this report.
4. For Phase 2 SQLite A/B, use at least three runs per mode and apply the decision thresholds above. For other comparisons, preserve the five-run reports where recorded. Add live model/audio/UI measurements only with fixed fixtures and environment metadata.
5. For response policies, use a small fixed prompt corpus and rubric; reject any rollout that exposes hidden reasoning or regresses correctness/tool selection.
6. For HUD changes, compare before/after screenshots and frame timing at the same viewport and fixed widget count; invalid widget payloads must not disrupt unrelated widgets.

## Phase 1 Branch Proposal and PR Draft (historical)

**Branch:** `feat/perf-polyglot-phase-1-close` (created from the existing dirty checkout; no commit or push made).

**Draft PR title:** `Close Phase 1 performance gate with SQLite and Ollama streaming`

**Summary:** Certifies five-run benchmark output and pre-task test failures; adds opt-in SQLite connection reuse and Ollama chunk updates over HUD SSE; adds native Rust/.NET build and JSON-RPC health smoke CI. All feature flags default off; JSON-RPC v1, MCP, and `ui.py` remain unchanged.

**Tests:** Pre-task baseline 7 failed / 1043 passed / 16 skipped. Focused changed-path tests: 73 passed. Final broad run excluding the crashing Qt panel module: the same 7 failures, 1035 passed, 15 skipped. Full runs abort in native Qt; the panel test and the local-stream-to-panel sequence pass when isolated. Final five-run SQLite p95: 14.1656 ms flag-off / 0.0532 ms pooled. Synthetic mock TTFT p95: 9.6358 ms buffered / 1.6175 ms token stream. Rust/.NET builds are not run locally; CI result is pending. Ruff passes on new/isolated files; the pre-existing runtime-file lint findings remain in `main.py`/`core/hud_bridge.py` and one existing test (`B023`).

**Risks:** SQLite pooling uses one serialized connection and `synchronous=NORMAL` weakens durability versus `FULL`; remain opt-in pending crash-durability review. Token TTFT is synthetic, and actual Ollama/HUD frame latency is unmeasured. Native CI has not yet run. The working tree includes unrelated pre-existing uncommitted changes, so it must be reviewed/isolated before opening a PR.

**Next step:** Run the new workflow and resolve its build/smoke issues, rerun pytest with the same documented baseline command, then review and commit only the task-scoped changes before opening the draft PR.

## Phase 2 validation results

Commands were run from the project root using the checkout's `.venv`:

| Command | Result |
|---|---|
| `python -m pytest -q` (Phase 2 original run) | **1 failed, 1122 passed, 7 skipped, 7 xfailed**, 49 warnings, 136.55 s. Failure: `tests/test_viewer3d.py::test_real_page_realistic_pbr_teaching_and_generated_label`; stderr showed Chromium GPU context-loss errors. |
| `python -m pytest -q` (investigation rerun) | Process exited `-1073741819` (Windows access violation) inside `test_real_page_pc_cad_explodes` at `tests/test_viewer3d.py:821`; no pytest counts. |
| `python -m pytest -q -m "not pre_existing"` | **1 failed, 1122 passed, 7 skipped, 7 deselected**, 49 warnings, 147.09 s. The realistic-PBR viewer assertion failed with GPU context-loss logs. |
| Isolated target test, default environment (3 runs) | Each run passed: **1 passed** in 9.10 s, 9.23 s, and 10.64 s. |
| Isolated target test, Phase 2 files temporarily stashed | **1 passed** in 10.29 s; stash immediately popped successfully. No Phase 2 regression observed. |
| Isolated target test, `QT_OPENGL=software QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` | **1 failed** in 48.36 s; QtWebEngine could not create GLES3/shared contexts, so the rendering assertions could not be satisfied. |
| `python -m pytest -q -rs tests/test_sidecar_runtime.py tests/test_sidecar_smoke.py tests/test_memory_store_pool.py` | **14 passed, 2 skipped**. Native skips identify missing Rust binary/toolchain and missing .NET build output/SDK. |
| `python benchmarks/bench_core.py --iterations 200 --sqlite-mode legacy` | Three runs; SQLite p50/p95/max (ms): `13.9253/15.6405/17.7702`, `14.8392/17.3185/79.2554`, `13.4727/16.0004/18.0584`; median p50 `13.9253`, median p95 `16.0004`, maximum `79.2554`. |
| `python benchmarks/bench_core.py --iterations 200 --sqlite-mode pooled` | Three runs; SQLite p50/p95/max (ms): `0.0327/0.0618/0.2311`, `0.0365/0.0789/0.1231`, `0.0319/0.0639/9.7349`; median p50 `0.0327`, median p95 `0.0639`, maximum `9.7349`. |
| `ruff check` on the six changed Python source/test files | Passed. |
| `python -m py_compile` on changed Python source/test files | Passed. |
| `git diff --check` | No whitespace errors in changed tracked files; untracked task files were separately checked with `git diff --no-index --check`. |
| `tomllib` check of `pyproject.toml` | Parsed successfully; UTF-8 BOM absent. |

The full and filtered test-suite failures are outside the sidecar/memory changes
and reproduce on both runs of the filtered suite; do not mark either command
green. Gate 1 remains **open** until the workflow runs on a branch with CI
enabled. Gate 2 remains **yellow/open for native binaries** despite passing
Python fallback and harness tests. Gate 3 is **green for A/B decision**:
thread-local Python pooling is far below the 3 ms p95 threshold, so SQLite
sidecar is **NO-GO**.
