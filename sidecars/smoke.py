"""Launch one native sidecar and verify its JSON-RPC v1 health response."""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path

from core.sidecar_runtime import JsonRpcSidecar, SidecarError

ROOT = Path(__file__).resolve().parents[1]


def _available_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def smoke(command: list[str], implementation: str, timeout: float = 15.0) -> None:
    if not command:
        raise ValueError("A sidecar command is required after --.")
    token = secrets.token_hex(32)
    port = _available_port()
    environment = os.environ.copy()
    environment["JARVIS_POLYGLOT_TOKEN"] = token
    environment["JARVIS_SIDECAR_PORT"] = str(port)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    client = JsonRpcSidecar("127.0.0.1", port, token, timeout_seconds=1.0)
    deadline = time.monotonic() + timeout
    last_error: SidecarError | None = None
    try:
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                details = process.stderr.read() if process.stderr is not None else ""
                raise RuntimeError(
                    f"{implementation} sidecar exited with {exit_code}: {details.strip()}"
                )
            try:
                result = client.health()
                if result.get("implementation") != implementation:
                    raise RuntimeError(
                        f"Expected {implementation} health response, got {result!r}"
                    )
                print(
                    f"{implementation} JSON-RPC v1 health OK "
                    f"(status={result['status']})"
                )
                return
            except SidecarError as exc:
                last_error = exc
                time.sleep(0.1)
        raise TimeoutError(
            f"{implementation} sidecar health timed out: {last_error}"
        )
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            process.stderr.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", choices=("rust", "dotnet"), required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    smoke(command, args.implementation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
