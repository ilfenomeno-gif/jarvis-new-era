"""Opt-in JSON-RPC client for local polyglot sidecars with Python fallback."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576
DEFAULT_TIMEOUT_SECONDS = 0.5
_FEATURES = {
    "rust": ("JARVIS_POLYGLOT_RUST", "JARVIS_POLYGLOT_RUST_PORT"),
    "dotnet": ("JARVIS_POLYGLOT_DOTNET", "JARVIS_POLYGLOT_DOTNET_PORT"),
}
_BINARIES = {
    "rust": "JARVIS_POLYGLOT_RUST_BIN",
    "dotnet": "JARVIS_POLYGLOT_DOTNET_BIN",
}
_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


class SidecarError(RuntimeError):
    """The local sidecar could not complete a valid protocol exchange."""


class JsonRpcSidecar:
    """One-request-per-connection JSON-RPC client restricted to loopback."""

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.casefold() == "localhost"
        if not loopback:
            raise SidecarError("Sidecars must use a loopback address.")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise SidecarError("Sidecar port must be between 1 and 65535.")
        if not isinstance(token, str) or len(token) < 32:
            raise SidecarError("Sidecar token must contain at least 32 characters.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise SidecarError("Sidecar timeout must be a positive number.")
        self.host = host
        self.port = port
        self.token = token
        self.timeout_seconds = float(timeout_seconds)

    def _exchange(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        if not isinstance(method, str) or not method.strip():
            raise SidecarError("JSON-RPC method must be non-empty text.")
        request_id = uuid.uuid4().hex
        rpc_params = dict(params or {})
        rpc_params["contractVersion"] = PROTOCOL_VERSION
        rpc_params["token"] = self.token
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": rpc_params,
        }
        try:
            encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > MAX_MESSAGE_BYTES:
                raise SidecarError("JSON-RPC request exceeds the message limit.")
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(encoded + b"\n")
                response = self._read_response(connection)
        except SidecarError:
            raise
        except (OSError, TimeoutError) as exc:
            raise SidecarError(f"Sidecar transport failed ({type(exc).__name__}).") from None
        try:
            envelope = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SidecarError(f"Invalid JSON-RPC response ({type(exc).__name__}).") from None
        if (
            not isinstance(envelope, dict)
            or envelope.get("jsonrpc") != "2.0"
            or envelope.get("id") != request_id
        ):
            raise SidecarError("JSON-RPC response envelope or id is invalid.")
        error = envelope.get("error")
        if error is not None:
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise SidecarError(f"Sidecar returned JSON-RPC error {code}.")
        if "result" not in envelope:
            raise SidecarError("JSON-RPC response has neither result nor error.")
        return envelope["result"]

    @staticmethod
    def _read_response(connection: socket.socket) -> bytes:
        chunks = bytearray()
        while len(chunks) <= MAX_MESSAGE_BYTES:
            chunk = connection.recv(min(4096, MAX_MESSAGE_BYTES + 1 - len(chunks)))
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                chunks.extend(chunk[:newline])
                return bytes(chunks)
            chunks.extend(chunk)
        if len(chunks) > MAX_MESSAGE_BYTES:
            raise SidecarError("JSON-RPC response exceeds the message limit.")
        raise SidecarError("Sidecar closed the connection before replying.")

    def health(self) -> dict[str, Any]:
        result = self._exchange("health")
        if (
            not isinstance(result, dict)
            or result.get("contractVersion") != PROTOCOL_VERSION
            or result.get("status") != "ok"
        ):
            raise SidecarError("Sidecar health response is incompatible.")
        return result

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._exchange(method, params)


def _available_port() -> int:
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])
    except OSError as exc:
        raise SidecarError("Could not reserve a loopback port for the sidecar.") from exc


def _binary_command(feature: str, binary_path: str) -> list[str]:
    path = Path(binary_path).expanduser()
    if not path.is_file():
        raise SidecarError("Configured sidecar binary does not exist.")
    if feature == "dotnet" and path.suffix.casefold() == ".dll":
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            raise SidecarError(".NET runtime is unavailable for the configured sidecar DLL.")
        return [dotnet, str(path)]
    return [str(path)]


def _run_binary_sidecar(
    feature: str,
    method: str,
    params: Mapping[str, Any] | None,
    binary_path: str,
    token: str,
    port: int,
    timeout_seconds: float,
) -> Any:
    if not 1 <= port <= 65535:
        raise SidecarError("Sidecar port must be between 1 and 65535.")
    client = JsonRpcSidecar("127.0.0.1", port, token, timeout_seconds=timeout_seconds)
    child_environment = os.environ.copy()
    child_environment["JARVIS_POLYGLOT_TOKEN"] = token
    child_environment["JARVIS_SIDECAR_PORT"] = str(port)
    try:
        process = subprocess.Popen(
            _binary_command(feature, binary_path),
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise SidecarError(f"Could not start sidecar ({type(exc).__name__}).") from None

    deadline = time.monotonic() + timeout_seconds
    last_error: SidecarError | None = None
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SidecarError("Configured sidecar exited before responding.")
            try:
                health = client.health()
            except SidecarError as exc:
                last_error = exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                continue
            return health if method == "health" else client.call(method, params)
        raise SidecarError(
            f"Configured sidecar did not respond before timeout ({last_error})."
        )
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=max(1.0, timeout_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run_optional_sidecar(
    feature: str,
    method: str,
    params: Mapping[str, Any] | None,
    fallback: Callable[[], _T],
    *,
    environ: Mapping[str, str] | None = None,
    logger: Callable[[str], None] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any | _T:
    """Call an explicitly enabled sidecar, otherwise use the Python fallback."""
    if feature not in _FEATURES:
        raise ValueError(f"Unknown sidecar feature: {feature!r}.")
    values = os.environ if environ is None else environ
    enabled_name, port_name = _FEATURES[feature]
    if values.get(enabled_name, "0") != "1":
        return fallback()

    report = logger or _LOGGER.warning
    try:
        token = values.get("JARVIS_POLYGLOT_TOKEN", "")
        binary_path = values.get(_BINARIES[feature], "").strip()
        if binary_path:
            configured_port = values.get(port_name)
            port = int(configured_port) if configured_port else _available_port()
            return _run_binary_sidecar(
                feature,
                method,
                params,
                binary_path,
                token,
                port,
                timeout_seconds,
            )
        port = int(values.get(port_name, ""))
        client = JsonRpcSidecar(
            "127.0.0.1", port, token, timeout_seconds=timeout_seconds
        )
        client.health()
        return client.call(method, params)
    except (SidecarError, TypeError, ValueError) as exc:
        report(f"{feature} sidecar unavailable; using Python fallback ({type(exc).__name__}).")
        return fallback()
