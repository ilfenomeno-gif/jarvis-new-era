"""
Expose JARVIS bundled actions as an MCP server over stdio.

Only ``read`` actions are listed unless ``--allow-write`` is given; ``destructive``
actions are never exposed. Run:  python -m core.mcp_server [--allow-write]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, IO

from core.action_loader import ActionRegistry, discover_actions

PROTOCOL_VERSION = "2025-03-26"


def to_json_schema(schema):
    """Gemini declarations use upper-case type names; MCP wants JSON Schema."""
    if isinstance(schema, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else to_json_schema(v))
                for k, v in schema.items()}
    if isinstance(schema, list):
        return [to_json_schema(v) for v in schema]
    return schema


class McpServer:
    def __init__(self, registry: ActionRegistry, allow_write: bool = False,
                 ctx: dict | None = None, name: str = "jarvis") -> None:
        self._registry = registry
        self._allow_write = allow_write
        self._ctx = ctx or {}
        self._name = name

    def _exposed(self) -> set[str]:
        allowed = {"read", "write"} if self._allow_write else {"read"}
        return {n for n in self._registry.names() if self._registry.risk_class(n) in allowed}

    def tools(self) -> list[dict]:
        exposed = self._exposed()
        return [
            {"name": d["name"], "description": d["description"],
             "inputSchema": to_json_schema(d["parameters"])}
            for d in self._registry.get_tool_declarations() if d["name"] in exposed
        ]

    def handle(self, message: dict) -> dict | None:
        method, ident = message.get("method"), message.get("id")
        if ident is None:  # notification
            return None
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                      "serverInfo": {"name": self._name, "version": "1"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tools()}
        elif method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            if name not in self._exposed():
                return {"jsonrpc": "2.0", "id": ident,
                        "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
            text = self._registry.run(name, params.get("arguments") or {}, ctx=self._ctx)
            result = {"content": [{"type": "text", "text": str(text)}], "isError": False}
        else:
            return {"jsonrpc": "2.0", "id": ident,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                reply = self.handle(json.loads(line))
            except json.JSONDecodeError:
                reply = {"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700, "message": "Parse error"}}
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()


def main(argv: list[str] | None = None, stdin: IO[str] | None = None,
         stdout: IO[str] | None = None, logger: Callable[[str], None] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS actions as an MCP server")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args(argv)
    base = Path(__file__).resolve().parents[1]
    registry = discover_actions(base / "actions",
                                logger=logger or (lambda m: print(m, file=sys.stderr)))
    McpServer(registry, allow_write=args.allow_write).serve(stdin or sys.stdin, stdout or sys.stdout)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
