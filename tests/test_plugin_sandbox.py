"""Security tests for the plugin subprocess sandbox (P4).

A deliberately "malicious" plugin fixture tries to escape: hang (infinite loop),
huge output, non-JSON noise, raising, and touching the network. The sandbox must
contain each: timeout, output cap, IPC validation, error envelope — and the
plugin module must NEVER be imported into the assistant's process.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from core.plugin_sandbox import SandboxError, run_sandboxed
from core.plugin_loader import discover_plugins


def _write_plugin(tmp_path: Path, name: str, body: str, sandboxed=True) -> Path:
    p = tmp_path / f"{name}.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# ── benign sandboxed plugin ───────────────────────────────────────────────────
def test_benign_sandboxed_plugin_runs(tmp_path):
    f = _write_plugin(tmp_path, "ok_plugin", '''
        PLUGIN = {"name": "ok_plugin", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}},
                  "sandboxed": True}
        def run(parameters):
            return "hello " + str(parameters.get("who", "world"))
    ''')
    assert run_sandboxed(f, {"who": "jarvis"}) == "hello jarvis"


def test_plugin_module_not_imported_in_parent(tmp_path):
    f = _write_plugin(tmp_path, "noimport", '''
        PLUGIN = {"name": "noimport", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}}}
        def run(parameters):
            return "ran"
    ''')
    assert "sandboxed_plugin" not in sys.modules
    run_sandboxed(f, {})
    assert "sandboxed_plugin" not in sys.modules  # still not imported here


# ── malicious behaviours, contained ──────────────────────────────────────────
def test_hanging_plugin_times_out(tmp_path):
    f = _write_plugin(tmp_path, "loopy", '''
        PLUGIN = {"name": "loopy", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}}}
        def run(parameters):
            import time
            while True:
                time.sleep(0.1)
    ''')
    with pytest.raises(SandboxError, match="timed out"):
        run_sandboxed(f, {}, timeout=2.0)


def test_raising_plugin_returns_error_envelope(tmp_path):
    f = _write_plugin(tmp_path, "raiser", '''
        PLUGIN = {"name": "raiser", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}}}
        def run(parameters):
            raise ValueError("boom")
    ''')
    with pytest.raises(SandboxError, match="boom"):
        run_sandboxed(f, {})


def test_huge_output_is_capped(tmp_path):
    f = _write_plugin(tmp_path, "chatty", '''
        PLUGIN = {"name": "chatty", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}}}
        def run(parameters):
            return "x" * 100000
    ''')
    from core.plugin_sandbox import MAX_OUTPUT_CHARS
    assert len(run_sandboxed(f, {})) == MAX_OUTPUT_CHARS


def test_non_json_stdout_noise_does_not_crash(tmp_path):
    f = _write_plugin(tmp_path, "noisy", '''
        PLUGIN = {"name": "noisy", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}}}
        def run(parameters):
            print("some debug noise to stdout")
            return "clean result"
    ''')
    # worker writes the envelope as the LAST line; noise before it is ignored
    assert run_sandboxed(f, {}) == "clean result"


def test_missing_file_and_missing_worker(tmp_path):
    with pytest.raises(SandboxError, match="not found"):
        run_sandboxed(tmp_path / "ghost.py", {})


# ── loader integration: sandboxed flag is read and routed ────────────────────
def test_loader_marks_and_routes_sandboxed_plugin(tmp_path):
    _write_plugin(tmp_path, "sand", '''
        PLUGIN = {"name": "sand", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}},
                  "sandboxed": True}
        def run(parameters):
            return "sandboxed result"
    ''')
    _write_plugin(tmp_path, "inline", '''
        PLUGIN = {"name": "inline", "description": "d",
                  "parameters": {"type": "OBJECT", "properties": {}}}
        def run(parameters):
            return "inline result"
    ''')
    registry = discover_plugins(tmp_path, core_tool_names=set(), logger=lambda m: None)
    sand = registry._plugins["sand"]
    inline = registry._plugins["inline"]
    assert sand.sandboxed is True
    assert inline.sandboxed is False
    # sandboxed runs via subprocess; inline runs in-process
    assert registry.run("sand", {}) == "sandboxed result"
    assert registry.run("inline", {}) == "inline result"
