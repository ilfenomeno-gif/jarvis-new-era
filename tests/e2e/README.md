# Jarvis live E2E harness

This harness starts the real Jarvis desktop application, connects to its
accessible UI through pywinauto, and records process logs, app-launch audit
events, process IDs, screenshots, and a JSON report. It is intentionally not
a pytest unit-test substitute; pytest only provides scenario selection and
result reporting.

Run all scenarios from `Mark-LIV-main`:

```powershell
cd Mark-LIV-main
.venv\Scripts\python.exe tests\e2e\run_tests.py
```

Run a single live scenario:

```powershell
.venv\Scripts\python.exe -m pytest tests\e2e\run_tests.py::test_open_notepad_via_text -v -s
```

Jarvis must be configured for a working Gemini Live connection. The harness
mutes its microphone using the accessible control before any text-command
tests; launching an app includes a second explicit confirmation message.
`test_physics_drop` skips with a recorded reason if `nvidia-smi` cannot verify
that the GPU is available or if utilization/memory indicate it is busy.

Per-run logs are written to `tests/e2e/logs/`, screenshots to
`tests/e2e/screenshots/`, and a report to
`tests/e2e/report-<timestamp>.json`. Generated evidence is local and ignored by
Git. A failed scenario records the process-log tail and attempts a failure
screenshot before cleanup.

Cleanup closes only Jarvis and application PIDs that were not present in the
pre-test process snapshot. It never terminates processes by image name or
interacts with desktop controls using absolute coordinates.
