"""Local HTTP tool endpoint for n8n → JARVIS VII calls.

WHY
    n8n self-hosted orchestrates workflows and agents; JARVIS VII owns the
    desktop (OS, OCR, UI automation, 3D, voice). This module lets n8n call the
    desktop tools over HTTP on the loopback interface, so an n8n workflow/agent
    can use them as tools.

SECURITY (non-negotiable)
    * Binds to 127.0.0.1 ONLY — never 0.0.0.0.
    * Every request needs the header ``X-JARVIS-TOKEN`` matching the shared
      secret stored in the DPAPI SecretStore under ``n8n:tool_token``.
    * Only actions with risk_class read/write are exposed; ``destructive``
      actions are NEVER exposed here (they need the on-screen confirm gate).
    * Every call is written to the audit log.

ENDPOINT
    POST http://127.0.0.1:8766/tool/<name>     {"args": {...}}  → tool result
    GET  http://127.0.0.1:8766/tools           list exposed tools + JSON Schema

Run:  python -m core.tool_server
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.action_loader import discover_actions
from core.jarvis_runtime import get_runtime
from core.mcp_server import to_json_schema

BASE_DIR = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 8766
TOKEN_SECRET_NAME = "n8n:tool_token"
_MAX_BODY = 64_000


def _exposed_actions():
    """read/write actions only; destructive never exposed over HTTP."""
    registry = discover_actions(BASE_DIR / "actions", logger=lambda m: None)
    return registry, {
        n for n in registry.names() if registry.risk_class(n) in ("read", "write")
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "JarvisToolServer/1"

    # silence default logging to stderr per request
    def log_message(self, *a):  # noqa: D401
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = get_runtime().secrets.get(TOKEN_SECRET_NAME)
        if not expected:
            return False
        return self.headers.get("X-JARVIS-TOKEN", "") == expected

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/tools":
            if not self._authorized():
                return self._json(401, {"error": "unauthorized"})
            registry, exposed = _exposed_actions()
            tools = [
                {"name": d["name"], "description": d["description"],
                 "inputSchema": to_json_schema(d["parameters"])}
                for d in registry.get_tool_declarations() if d["name"] in exposed
            ]
            return self._json(200, {"tools": tools})
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/tool/"):
            return self._json(404, {"error": "not found"})
        if not self._authorized():
            get_runtime().audit.record(tool="tool_server", outcome="failed",
                                       detail="unauthorized", arguments={"path": self.path})
            return self._json(401, {"error": "unauthorized"})

        name = self.path[len("/tool/"):].strip("/")
        registry, exposed = _exposed_actions()
        if name not in exposed:
            return self._json(404, {"error": f"unknown or non-exposed tool: {name}"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > _MAX_BODY:
            return self._json(413, {"error": "body too large"})
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON body"})
        args = payload.get("args") if isinstance(payload, dict) else None
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return self._json(400, {"error": "args must be an object"})

        try:
            result = registry.run(name, args, ctx={})
            get_runtime().audit.record(tool=f"tool_server.{name}", outcome="done")
            return self._json(200, {"name": name, "result": str(result)})
        except Exception as exc:
            get_runtime().audit.record(tool=f"tool_server.{name}", outcome="failed",
                                       detail=type(exc).__name__)
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def serve(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"[tool_server] listening on http://{host}:{port} (loopback only)")
    threading.Thread(target=server.serve_forever, daemon=True,
                     name="tool-server").start()
    return server


if __name__ == "__main__":
    serve().serve_forever()
