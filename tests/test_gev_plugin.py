from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins import gev_plugin


class _McpClient:
    tools = ({"name": "show_in_gods_eye_view"},)

    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {
            "structuredContent": {
                "summary": "Open Waterloo in God's Eye View",
                "data": {
                    "view": {
                        "camera": {
                            "lat": 50.6800,
                            "lon": 4.4100,
                            "altitude_m": 25000,
                        }
                    }
                },
            }
        }


class _Player:
    def __init__(self):
        self.messages = []
        self.logs = []

    def send_to_gev(self, message):
        self.messages.append(message)

    def wait_for_gev(self, timeout):
        assert timeout == 30
        return True

    def write_log(self, message):
        self.logs.append(message)


class _HttpResponse:
    def __init__(self, status=200, html="<title>God's Eye View</title>"):
        self.status = status
        self._html = html.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self._html


class _McpRuntimeClient:
    tools = ()

    def __init__(self, *_args, **_kwargs):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _SocketConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


@pytest.fixture
def isolated_gev_runtime(monkeypatch, tmp_path):
    (tmp_path / "node_modules").mkdir()
    mcp_dir = tmp_path / "server" / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "stdio.js").touch()
    (tmp_path / "node_modules" / "vite" / "bin").mkdir(parents=True)
    (tmp_path / "node_modules" / "vite" / "bin" / "vite.js").touch()

    terminated = []
    monkeypatch.setattr(gev_plugin, "GEV_DIR", tmp_path)
    monkeypatch.setattr(
        gev_plugin, "_gev_runtime", lambda: ({}, "portable-node", "npm-cli")
    )
    monkeypatch.setattr(gev_plugin, "_attach_kill_on_close_job", lambda _process: None)
    monkeypatch.setattr(gev_plugin, "_close_job_handle", lambda: None)
    monkeypatch.setattr(
        gev_plugin, "_terminate_process", lambda process: terminated.append(process)
    )
    monkeypatch.setattr(gev_plugin, "_log", lambda _message: None)
    monkeypatch.setattr(gev_plugin, "McpStdioClient", _McpRuntimeClient)
    monkeypatch.setattr(gev_plugin, "_process", None)
    monkeypatch.setattr(gev_plugin, "_started", False)
    monkeypatch.setattr(gev_plugin, "_mcp_client", None)
    monkeypatch.setattr(gev_plugin, "_mcp_start_error", None)
    with gev_plugin._output_lock:
        gev_plugin._output_lines.clear()

    yield terminated

    gev_plugin.stop()


def test_open_with_context_resolves_location_and_applies_historical_context(
    monkeypatch,
):
    client = _McpClient()
    player = _Player()
    monkeypatch.setattr(gev_plugin, "_mcp_client", client)

    result = gev_plugin.run(
        {
            "action": "open_with_context",
            "location": "Waterloo",
            "intent": "history",
            "year": 1815,
            "epoch": "1815",
            "theme": "La battaglia di Waterloo",
        },
        player=player,
    )

    assert client.calls == [
        ("show_in_gods_eye_view", {"area": {"place": "Waterloo"}})
    ]
    assert player.messages == [
        {"action": "open_tab", "params": {}},
        {
            "action": "camera_fly",
            "params": {
                "lat": 50.68,
                "lon": 4.41,
                "altitude_m": 25000,
            },
        },
        {
            "action": "historical_map",
            "params": {"command": "show", "year": 1815},
        },
        {
            "action": "annotate",
            "params": {
                "lat": 50.68,
                "lon": 4.41,
                "text": "1815 — La battaglia di Waterloo",
            },
        },
    ]
    assert result.startswith("Apro God's Eye View su Waterloo")
    assert player.logs == ["GEV: aperta su 'Waterloo' (history), anno 1815"]


def test_open_with_context_reports_missing_geocoder_result(monkeypatch):
    client = _McpClient()
    client.call_tool = lambda *_args: {"structuredContent": {"data": {}}}
    player = _Player()
    monkeypatch.setattr(gev_plugin, "_mcp_client", client)

    result = gev_plugin._run_open_with_context(
        {"location": "Atlantide", "intent": "geo"},
        player,
        lambda _message: None,
    )

    assert "non ha restituito una vista valida" in result
    assert player.messages == []


def test_open_with_context_rejects_invalid_year_before_mcp_call(monkeypatch):
    client = _McpClient()
    monkeypatch.setattr(gev_plugin, "_mcp_client", client)

    result = gev_plugin._run_open_with_context(
        {
            "location": "Waterloo",
            "intent": "history",
            "year": True,
        },
        _Player(),
        lambda _message: None,
    )

    assert "anno intero valido" in result
    assert client.calls == []


def test_gev_checkout_is_deterministic_from_plugin_location():
    assert gev_plugin.GEV_DIR == (
        Path(gev_plugin.__file__).resolve().parents[1]
        / "gods-eye-view-main"
        / "_gev-clone"
    )


def test_dependency_install_uses_tracked_lockfile_and_npm_ci(tmp_path, monkeypatch):
    (tmp_path / "package-lock.json").touch()
    monkeypatch.setattr(gev_plugin, "GEV_DIR", tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gev_plugin.subprocess, "run", fake_run)

    gev_plugin._install_gev_dependencies({"PATH": "test"}, "portable-node", "npm-cli")

    assert len(calls) == 1
    command, options = calls[0]
    assert command == ["portable-node", "npm-cli", "ci"]
    assert options["cwd"] == tmp_path
    assert options["env"] == {"PATH": "test"}
    assert options["timeout"] == gev_plugin.INSTALL_TIMEOUT_SEC


def test_dependency_install_fails_clearly_without_lockfile(tmp_path, monkeypatch):
    monkeypatch.setattr(gev_plugin, "GEV_DIR", tmp_path)
    monkeypatch.setattr(
        gev_plugin.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not install without a lockfile"),
    )

    with pytest.raises(FileNotFoundError, match="package-lock.json non trovato"):
        gev_plugin._install_gev_dependencies({}, "portable-node", "npm-cli")


def test_start_runtime_reuses_healthy_existing_server_without_owning_it(
    isolated_gev_runtime, monkeypatch
):
    terminated = isolated_gev_runtime
    monkeypatch.setattr(
        gev_plugin.socket, "create_connection", lambda *_args, **_kwargs: _SocketConnection()
    )
    monkeypatch.setattr(
        gev_plugin, "urlopen", lambda *_args, **_kwargs: _HttpResponse()
    )
    monkeypatch.setattr(
        gev_plugin.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("must not start a second Vite server"),
    )
    monkeypatch.setattr(
        gev_plugin.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("dependencies are already present"),
    )

    gev_plugin._start_runtime()
    client = gev_plugin._mcp_client

    assert gev_plugin._started is True
    assert gev_plugin._process is None
    assert client is not None and client.started
    gev_plugin.stop()
    assert client.stopped
    assert terminated == []


def test_start_runtime_rejects_occupied_port_when_health_check_is_not_gev(
    isolated_gev_runtime, monkeypatch
):
    terminated = isolated_gev_runtime
    monkeypatch.setattr(
        gev_plugin.socket, "create_connection", lambda *_args, **_kwargs: _SocketConnection()
    )
    monkeypatch.setattr(
        gev_plugin,
        "urlopen",
        lambda *_args, **_kwargs: _HttpResponse(html="<title>Other Service</title>"),
    )
    monkeypatch.setattr(
        gev_plugin,
        "_gev_runtime",
        lambda: pytest.fail("must reject the occupied non-GEV service first"),
    )
    monkeypatch.setattr(
        gev_plugin.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("must not start over another service"),
    )

    with pytest.raises(RuntimeError, match="non.*GEV|health check"):
        gev_plugin._start_runtime()

    assert gev_plugin._process is None
    assert gev_plugin._started is False
    assert terminated == []


def test_start_runtime_reports_exit_code_and_vite_output(
    isolated_gev_runtime, monkeypatch
):
    terminated = isolated_gev_runtime
    monkeypatch.setattr(
        gev_plugin.socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("connection refused")),
    )
    monkeypatch.setattr(
        gev_plugin.subprocess,
        "Popen",
        lambda *_args, **_kwargs: type(
            "ExitedProcess",
            (),
            {
                "returncode": 1,
                "stdout": io.StringIO(
                    "Error when starting dev server:\nPort 4173 is already in use\n"
                ),
                "poll": lambda self: 1,
            },
        )(),
    )

    with pytest.raises(RuntimeError) as exc_info:
        gev_plugin._start_runtime()

    message = str(exc_info.value)
    assert "exit code 1" in message
    assert "stdout/stderr:" in message
    assert "Error when starting dev server" in message
    assert "Port 4173 is already in use" in message
    assert len(terminated) == 1
    assert gev_plugin._process is None
