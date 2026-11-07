from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.sidecar_runtime import run_optional_sidecar
from sidecars.smoke import smoke

ROOT = Path(__file__).resolve().parents[1]
SIDECARS = {
    "rust": (
        "JARVIS_POLYGLOT_RUST",
        "JARVIS_POLYGLOT_RUST_BIN",
        ROOT / "sidecars" / "rust" / "target" / "release" / "jarvis-sidecar-rust",
    ),
    "dotnet": (
        "JARVIS_POLYGLOT_DOTNET",
        "JARVIS_POLYGLOT_DOTNET_BIN",
        ROOT / "sidecars" / "dotnet" / "bin" / "Release" / "net8.0" / "Jarvis.Sidecar",
    ),
}


def test_smoke_runner_launches_process_and_checks_versioned_health():
    server_script = """
import json
import os
import socketserver

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        request = json.loads(self.rfile.readline())
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "contractVersion": 1,
                "status": "ok",
                "implementation": "rust",
            },
        }
        self.wfile.write(json.dumps(response).encode() + b"\\n")

server = socketserver.TCPServer(
    ("127.0.0.1", int(os.environ["JARVIS_SIDECAR_PORT"])),
    Handler,
)
server.serve_forever()
"""

    smoke([sys.executable, "-c", server_script], "rust", timeout=5.0)


def _find_binary(implementation: str) -> Path:
    _, binary_env, default_binary = SIDECARS[implementation]
    configured = os.environ.get(binary_env)
    if configured:
        binary = Path(configured).expanduser()
        if binary.is_file():
            return binary
        pytest.skip(f"{binary_env} points to a missing binary: {binary}")

    candidates = (
        default_binary,
        default_binary.with_suffix(".exe"),
        default_binary.with_suffix(".dll"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if implementation == "rust":
        pytest.skip(
            "Rust sidecar binary is missing; install Rust stable and run "
            "`cargo build --release` in sidecars/rust."
        )
    pytest.skip(
        ".NET sidecar binary is missing; install the .NET 8 SDK and run "
        "`dotnet build -c Release` in sidecars/dotnet."
    )


@pytest.mark.requires_sidecar_binary
@pytest.mark.parametrize("implementation", ("rust", "dotnet"))
def test_native_sidecar_binary_and_runtime_env(implementation):
    feature_env, binary_env, _ = SIDECARS[implementation]
    binary = _find_binary(implementation)
    dotnet = shutil.which("dotnet")
    if implementation == "dotnet":
        if dotnet is None:
            pytest.skip(".NET runtime/host is unavailable for the sidecar binary.")
        runtimes = subprocess.run(
            [dotnet, "--list-runtimes"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        if runtimes.returncode != 0 or "Microsoft.NETCore.App 8." not in runtimes.stdout:
            pytest.skip(".NET 8 runtime is unavailable for the sidecar binary.")

    token = secrets.token_hex(32)
    result = run_optional_sidecar(
        implementation,
        "health",
        None,
        lambda: pytest.fail("A configured native sidecar must not use the fallback."),
        environ={
            feature_env: "1",
            binary_env: str(binary),
            "JARVIS_POLYGLOT_TOKEN": token,
        },
        timeout_seconds=5,
    )
    assert result["contractVersion"] == 1
    assert result["status"] == "ok"
    assert result["implementation"] == implementation

    command = [str(binary)]
    if binary.suffix.casefold() == ".dll":
        if dotnet is None:
            pytest.skip(".NET host is unavailable for the sidecar DLL.")
        command = [dotnet, str(binary)]
    smoke(command, implementation)
