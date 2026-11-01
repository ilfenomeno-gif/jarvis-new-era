"""
MCP transports that plug into ``ConnectorRegistry.set_invoker``.

* ``stdio_invoker`` reuses an already-started ``McpStdioClient``.
* ``HttpMcpInvoker`` speaks streamable-HTTP JSON-RPC (initialize, tools/call).

Connector tool refs are namespaced (``gmail.search``); the remote server sees
the bare name unless a ``tool_map`` says otherwise.
"""
from __future__ import annotations

import ipaddress
import json
from typing import Callable
from urllib.parse import urlparse

import requests

PROTOCOL_VERSION = "2025-03-26"


class McpTransportError(RuntimeError):
    pass


def _check_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    loopback = host == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise McpTransportError("MCP endpoints must use https (http only on loopback).")


def _bare(tool_ref: str, tool_map: dict[str, str] | None) -> str:
    if tool_map and tool_ref in tool_map:
        return tool_map[tool_ref]
    return tool_ref.split(".", 1)[-1]


def result_text(result: dict) -> str:
    parts = [e.get("text", "") for e in result.get("content", [])
             if isinstance(e, dict) and e.get("type") == "text"]
    if result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(p for p in parts if p) or "Done."
    if result.get("isError"):
        raise McpTransportError(text)
    return text


def stdio_invoker(client, tool_map: dict[str, str] | None = None) -> Callable[[str, dict], str]:
    def invoke(tool_ref: str, arguments: dict) -> str:
        return result_text(client.call_tool(_bare(tool_ref, tool_map), arguments))
    return invoke


class HttpMcpInvoker:
    def __init__(self, endpoint: str, token_getter: Callable[[], str | None],
                 tool_map: dict[str, str] | None = None, timeout: float = 30.0,
                 session: requests.Session | None = None) -> None:
        _check_endpoint(endpoint)
        self._endpoint = endpoint
        self._token_getter = token_getter
        self._tool_map = tool_map
        self._timeout = timeout
        self._http = session or requests.Session()
        self._session_id: str | None = None
        self._next_id = 0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        token = self._token_getter()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _decode(response: requests.Response) -> dict:
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise McpTransportError("Empty event stream from MCP server.")
        return response.json()

    def _post(self, payload: dict, expect_reply: bool = True) -> dict:
        response = self._http.post(self._endpoint, json=payload, headers=self._headers(),
                                   timeout=self._timeout)
        if response.status_code == 401:
            raise McpTransportError("MCP server rejected the credentials (401).")
        response.raise_for_status()
        self._session_id = response.headers.get("Mcp-Session-Id", self._session_id)
        return self._decode(response) if expect_reply else {}

    def _rpc(self, method: str, params: dict) -> dict:
        self._next_id += 1
        reply = self._post({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        if "error" in reply:
            raise McpTransportError(str(reply["error"].get("message", reply["error"])))
        return reply.get("result", {})

    def _ensure_session(self) -> None:
        if self._session_id is not None:
            return
        self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                 "clientInfo": {"name": "jarvis", "version": "1"}})
        self._session_id = self._session_id or ""
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

    def __call__(self, tool_ref: str, arguments: dict) -> str:
        self._ensure_session()
        return result_text(self._rpc("tools/call", {"name": _bare(tool_ref, self._tool_map),
                                                    "arguments": arguments}))
