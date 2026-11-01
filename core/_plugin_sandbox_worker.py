"""Subprocess worker for the plugin sandbox. Not imported by the assistant.

Reads one JSON request from stdin, imports the plugin file BY PATH in THIS
throwaway process, calls run(parameters), and writes one JSON envelope to
stdout. Any exception becomes {"ok": false, "error": ...}. The parent never
imports the plugin — that is the isolation.
"""
from __future__ import annotations

import importlib.util
import json
import sys


def _load(path: str):
    spec = importlib.util.spec_from_file_location("sandboxed_plugin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load plugin module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
        module = _load(request["plugin_file"])
        run = getattr(module, "run", None)
        if not callable(run):
            raise RuntimeError("plugin has no callable run()")
        result = run(request.get("parameters") or {})
        envelope = {"ok": True, "result": result if isinstance(result, str) else str(result)}
    except Exception as exc:  # noqa: BLE001 — the envelope is the error channel
        envelope = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
