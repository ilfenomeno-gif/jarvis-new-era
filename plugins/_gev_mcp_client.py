"""Minimal synchronous JSON-RPC client for the local GEV MCP stdio server."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable


MCP_PROTOCOL_VERSION = "2025-11-25"
_MAX_TOOL_RESULT_CHARS = 12_000


class McpClientError(RuntimeError):
    """Raised when the GEV MCP server cannot complete a protocol operation."""


class McpStdioClient:
    def __init__(
        self,
        command: list[str],
        cwd: Path,
        logger: Callable[[str], None],
        *,
        request_timeout: float = 60.0,
        popen: Callable = subprocess.Popen,
        process_started: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._logger = logger
        self._request_timeout = request_timeout
        self._popen = popen
        self._process_started = process_started
        self._process: subprocess.Popen[str] | None = None
        self._reader_threads: list[threading.Thread] = []
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, dict | None]] = {}
        self._next_id = 0
        self._failure: str | None = None
        self._tools: tuple[dict, ...] = ()

    @property
    def tools(self) -> tuple[dict, ...]:
        return self._tools

    def start(self) -> tuple[dict, ...]:
        if self._process is not None and self._process.poll() is None and self._tools:
            return self._tools
        env = os.environ.copy()
        creation_options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {}
        )
        self._process = self._popen(
            self._command,
            cwd=self._cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **creation_options,
        )
        self._failure = None
        try:
            if self._process_started is not None:
                self._process_started(self._process)
            self._reader_threads = [
                threading.Thread(
                    target=self._read_responses,
                    name="gev-mcp-stdout",
                    daemon=True,
                ),
                threading.Thread(
                    target=self._read_diagnostics,
                    name="gev-mcp-stderr",
                    daemon=True,
                ),
            ]
            for thread in self._reader_threads:
                thread.start()
            self.request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "jarvis-gev", "version": "1.0"},
                },
            )
            self.notify("notifications/initialized")
            result = self.request("tools/list", {})
            raw_tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(raw_tools, list):
                raise McpClientError("GEV MCP tools/list returned no tools array")
            self._tools = tuple(
                tool for tool in raw_tools if self._valid_tool_definition(tool)
            )
            if len(self._tools) != len(raw_tools):
                raise McpClientError("GEV MCP tools/list contains malformed entries")
            self._logger(f"GEV MCP: connesso, {len(self._tools)} tool disponibili")
            return self._tools
        except Exception:
            self.stop()
            raise

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if not isinstance(result, dict):
            raise McpClientError(f"GEV MCP tool '{name}' returned an invalid result")
        if result.get("isError"):
            content = result.get("content", [])
            details = "; ".join(
                entry.get("text", "")
                for entry in content
                if isinstance(entry, dict) and isinstance(entry.get("text"), str)
            )
            raise McpClientError(
                f"GEV MCP tool '{name}' failed: {details or 'unknown tool error'}"
            )
        return result

    def request(self, method: str, params: dict) -> dict:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpClientError(self._failure or "GEV MCP server is not running")

        with self._state_lock:
            self._next_id += 1
            request_id = self._next_id
            event = threading.Event()
            self._pending[request_id] = (event, None)
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, BrokenPipeError) as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise McpClientError(f"GEV MCP request write failed: {exc}") from exc

        if not event.wait(self._request_timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(
                f"GEV MCP request '{method}' timed out after "
                f"{self._request_timeout:.0f}s"
            )
        with self._state_lock:
            pending = self._pending.pop(request_id, None)
        response = pending[1] if pending is not None else None
        if not isinstance(response, dict):
            raise McpClientError(self._failure or f"GEV MCP '{method}' returned no response")
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                raise McpClientError(
                    f"GEV MCP '{method}' error {error.get('code')}: "
                    f"{error.get('message', 'unknown error')}"
                )
            raise McpClientError(f"GEV MCP '{method}' returned malformed error")
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpClientError(f"GEV MCP '{method}' returned an invalid result")
        return result

    def notify(self, method: str, params: dict | None = None) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpClientError(self._failure or "GEV MCP server is not running")
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        with self._write_lock:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

    def stop(self) -> None:
        process = self._process
        self._process = None
        self._tools = ()
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for thread in self._reader_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self._reader_threads = []
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for event, _ in pending:
            event.set()

    @staticmethod
    def _valid_tool_definition(tool: object) -> bool:
        return (
            isinstance(tool, dict)
            and isinstance(tool.get("name"), str)
            and isinstance(tool.get("description"), str)
            and isinstance(tool.get("inputSchema"), dict)
            and tool["inputSchema"].get("type") == "object"
        )

    def _read_responses(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._set_failure(f"GEV MCP emitted invalid JSON: {exc}")
                    continue
                request_id = response.get("id") if isinstance(response, dict) else None
                if isinstance(request_id, bool) or not isinstance(request_id, int):
                    continue
                with self._state_lock:
                    pending = self._pending.get(request_id)
                    if pending is not None:
                        self._pending[request_id] = (pending[0], response)
                        pending[0].set()
        except (OSError, ValueError) as exc:
            self._set_failure(f"GEV MCP stdout reader failed: {exc}")
        finally:
            self._set_failure("GEV MCP server closed stdout")

    def _read_diagnostics(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            for line in process.stderr:
                text = line.rstrip()
                if text:
                    self._logger(f"GEV MCP server: {text}")
        except (OSError, ValueError) as exc:
            self._logger(f"GEV MCP stderr reader failed: {exc}")

    def _set_failure(self, message: str) -> None:
        self._failure = message
        with self._state_lock:
            pending = list(self._pending.values())
        for event, _ in pending:
            event.set()


def to_gemini_schema(schema: dict) -> dict:
    """Convert the MCP JSON Schema subset used by GEV to Gemini schema keys."""
    if not isinstance(schema, dict):
        raise TypeError("MCP tool schema must be an object")
    schema_type = schema.get("type")
    type_names = {
        "object": "OBJECT",
        "array": "ARRAY",
        "string": "STRING",
        "number": "NUMBER",
        "integer": "INTEGER",
        "boolean": "BOOLEAN",
    }
    if schema_type not in type_names:
        raise ValueError(f"Unsupported MCP schema type: {schema_type!r}")

    converted = {"type": type_names[schema_type]}
    for key in ("description", "enum"):
        value = schema.get(key)
        if value is not None:
            converted[key] = value
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise TypeError("MCP object schema properties must be an object")
        converted["properties"] = {
            name: to_gemini_schema(definition)
            for name, definition in properties.items()
        }
        required = schema.get("required", [])
        if required:
            if not isinstance(required, list) or not all(
                isinstance(name, str) for name in required
            ):
                raise TypeError("MCP required fields must be a list of strings")
            converted["required"] = required
    elif schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise TypeError("MCP array schema must define items")
        converted["items"] = to_gemini_schema(items)
    return converted


def tool_result_text(name: str, result: dict) -> str:
    """Format a successful MCP result for Jarvis's text tool-response channel."""
    content = result.get("content", [])
    summary = " ".join(
        entry["text"]
        for entry in content
        if isinstance(entry, dict)
        and entry.get("type") == "text"
        and isinstance(entry.get("text"), str)
    )
    data = result.get("structuredContent")
    if data is None:
        response = summary or f"GEV tool '{name}' completed."
    else:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        response = f"{summary}\nDati: {encoded}" if summary else encoded
    if len(response) > _MAX_TOOL_RESULT_CHARS:
        response = (
            response[:_MAX_TOOL_RESULT_CHARS]
            + "\n[risposta MCP troncata per limite di lunghezza]"
        )
    return response
