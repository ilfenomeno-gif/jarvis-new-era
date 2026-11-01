"""Opt-in subprocess sandbox for plugins.

WHY
    Today every plugin runs in-process with full trust (importlib): a plugin can
    import anything, open the network, read any file the user can read. That is
    the documented current state. This module adds an OPTIONAL hard boundary: a
    plugin that declares ``PLUGIN["sandboxed"] = True`` has its ``run()`` executed
    in a separate Python subprocess that speaks a small declarative JSON IPC over
    stdin/stdout.

WHAT THE SANDBOX DOES AND DOES NOT DO
    It ISOLATES: the plugin's run() executes in another process, so a crash or a
    hang does not take down the assistant, and the work happens off the Qt/async
    threads. It enforces a TIMEOUT and an OUTPUT CAP.

    It is NOT a security boundary against a determined malicious plugin on its
    own: the subprocess still runs as the user. The defence-in-depth value is
    that the ONLY channel back is the declared JSON result — the parent never
    imports the plugin module, so plugin code never executes in the assistant's
    process. Combined with the OS (a low-rights helper, job objects, firewall
    rules) it becomes a real boundary; that OS integration is platform-specific
    and marked DA VERIFICARE.

IPC CONTRACT (declarative, one request / one response per line, JSON)
    parent → child:   {"parameters": {...}, "player_available": false}
    child → parent:   {"ok": true,  "result": "spoken text"}
                   or {"ok": false, "error": "message"}

    The child imports the plugin file by path and calls its run(parameters).
    `player`/`session_memory` are NOT passed across the process boundary (they
    are live Qt objects); a sandboxed plugin must work from `parameters` alone.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

DEFAULT_TIMEOUT_SEC = 30.0
MAX_OUTPUT_CHARS = 4000
_MAX_LINE_BYTES = 1_000_000

_WORKER = Path(__file__).with_name("_plugin_sandbox_worker.py")


class SandboxError(RuntimeError):
    pass


def run_sandboxed(plugin_file: str | Path, parameters: dict,
                  *, timeout: float = DEFAULT_TIMEOUT_SEC,
                  python: str | None = None) -> str:
    """Run a plugin's run(parameters) in a subprocess; return its spoken result.

    Raises SandboxError on timeout, bad IPC, or a non-"ok" envelope. Never
    imports the plugin in this process.
    """
    plugin_file = Path(plugin_file)
    if not plugin_file.is_file():
        raise SandboxError(f"plugin file not found: {plugin_file}")
    if not _WORKER.is_file():
        raise SandboxError(f"sandbox worker missing: {_WORKER}")

    request = json.dumps({
        "plugin_file": str(plugin_file),
        "parameters": parameters or {},
        "player_available": False,
    })

    proc = subprocess.Popen(
        [python or sys.executable, str(_WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out, err = proc.communicate(input=request, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise SandboxError(f"plugin timed out after {timeout:.0f}s")

    line = ""
    for candidate in out.splitlines():
        if candidate.strip():
            line = candidate   # keep the LAST non-empty line: the JSON envelope
    if not line:
        raise SandboxError(
            f"no IPC response (exit {proc.returncode}): {err.strip()[:200]}")
    if len(line.encode("utf-8", "replace")) > _MAX_LINE_BYTES:
        raise SandboxError("IPC response too large")

    try:
        envelope = json.loads(line)
    except json.JSONDecodeError:
        raise SandboxError("malformed IPC response")
    if not isinstance(envelope, dict):
        raise SandboxError("IPC response is not an object")

    if not envelope.get("ok"):
        raise SandboxError(str(envelope.get("error") or "unknown sandbox error"))

    result = envelope.get("result")
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return text[:MAX_OUTPUT_CHARS]
