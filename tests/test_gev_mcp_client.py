"""Focused tests for the GEV MCP client and dynamic plugin tool routing."""

from __future__ import annotations

import json
import queue
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import plugin_loader
from core.plugin_loader import PluginRecord, PluginRegistry
from plugins._gev_mcp_client import (
    McpClientError,
    McpStdioClient,
    to_gemini_schema,
    tool_result_text,
)
from plugins import gev_plugin


_END = object()


class _QueueReader:
    def __init__(self):
        self.lines = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.lines.get(timeout=3)
        if line is _END:
            raise StopIteration
        return line

    def close(self):
        self.lines.put(_END)


class _FakeStdin:
    def __init__(self, process):
        self.process = process
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        return len(text)

    def flush(self):
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.process.respond(json.loads(line))

    def close(self):
        self.process.returncode = 0
        self.process.stdout.close()
        self.process.stderr.close()


class _FakeProcess:
    def __init__(self, tool_call_result=None):
        self.stdout = _QueueReader()
        self.stderr = _QueueReader()
        self.returncode = None
        self.tool_call_result = tool_call_result or {
            "content": [{"type": "text", "text": "Rotta calcolata"}],
            "structuredContent": {"distance_km": 80},
            "isError": False,
        }
        self.stdin = _FakeStdin(self)

    def respond(self, request):
        method = request.get("method")
        if method == "notifications/initialized":
            return
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "test-gev", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "plan_route",
                        "description": "Plan a route.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                            },
                            "required": ["from", "to"],
                        },
                    }
                ]
            }
        elif method == "tools/call":
            result = self.tool_call_result
        else:
            self.stdout.lines.put(json.dumps({
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32601, "message": "unknown method"},
            }) + "\n")
            return
        self.stdout.lines.put(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": result,
        }) + "\n")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = -9


def _client(result=None, process_started=None):
    process = _FakeProcess(result)
    client = McpStdioClient(
        ["node.exe", "stdio.js"],
        Path("."),
        lambda _message: None,
        popen=lambda *_args, **_kwargs: process,
        process_started=process_started,
    )
    return client, process


def test_gev_path_resolution_prefers_existing_checkout_with_dependencies(tmp_path):
    plugin_file = (
        tmp_path
        / "workspace"
        / "Mark-LIV-main"
        / "plugins"
        / "gev_plugin.py"
    )
    plugin_file.parent.mkdir(parents=True)
    project_checkout = (
        plugin_file.parents[1] / "gods-eye-view-main" / "_gev-clone"
    )
    workspace_checkout = (
        plugin_file.parents[2] / "gods-eye-view-main" / "_gev-clone"
    )
    project_checkout.mkdir(parents=True)
    (project_checkout / "node_modules").mkdir()
    workspace_checkout.mkdir(parents=True)

    assert gev_plugin._resolve_gev_dir(plugin_file) == project_checkout

    (project_checkout / "node_modules").rmdir()
    project_checkout.rmdir()
    assert gev_plugin._resolve_gev_dir(plugin_file) == workspace_checkout


def test_mcp_client_initializes_lists_and_calls_tool():
    client, _process = _client()
    try:
        tools = client.start()
        assert [tool["name"] for tool in tools] == ["plan_route"]
        result = client.call_tool("plan_route", {"from": "A", "to": "B"})
        assert result["structuredContent"] == {"distance_km": 80}
        assert tool_result_text("plan_route", result) == (
            'Rotta calcolata\nDati: {"distance_km":80}'
        )
    finally:
        client.stop()


def test_mcp_client_surfaces_tool_errors():
    client, _process = _client(
        {
            "content": [{"type": "text", "text": "Provider unavailable"}],
            "isError": True,
        },
    )
    try:
        client.start()
        with pytest.raises(McpClientError, match="Provider unavailable"):
            client.call_tool("plan_route", {})
    finally:
        client.stop()


def test_mcp_client_stops_if_job_assignment_fails():
    client, process = _client(
        process_started=lambda _process: (_ for _ in ()).throw(
            OSError("job assignment denied")
        ),
    )
    with pytest.raises(OSError, match="job assignment denied"):
        client.start()
    assert process.returncode == 0


def test_gemini_schema_conversion_keeps_nested_fields_and_required_keys():
    schema = to_gemini_schema({
        "type": "object",
        "properties": {
            "location": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                },
                "required": ["lat", "lon"],
            },
            "modes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["location"],
    })
    assert schema["type"] == "OBJECT"
    assert schema["required"] == ["location"]
    assert schema["properties"]["location"]["required"] == ["lat", "lon"]
    assert schema["properties"]["modes"]["items"]["type"] == "STRING"


def test_gemini_schema_conversion_rejects_unsupported_constructs():
    with pytest.raises(ValueError, match="Unsupported MCP schema type"):
        to_gemini_schema({"oneOf": [{"type": "string"}]})


def test_plugin_registry_exposes_and_routes_extra_tools(monkeypatch):
    monkeypatch.setattr(plugin_loader, "get_plugin_enabled", lambda _name: True)
    called = []
    record = PluginRecord(
        name="gev",
        description="GEV",
        run=lambda _args: "base",
        valid=True,
        extra_tool_declarations=lambda: [{
            "name": "gev_mcp_plan_route",
            "description": "Plan a route.",
            "parameters": {"type": "OBJECT", "properties": {}},
        }],
        run_extra_tool=lambda name, args, player=None: called.append(
            (name, args, player)
        ) or "route result",
    )
    registry = PluginRegistry(
        {"gev": record},
        lambda _message: None,
        reserved_tool_names={"core_tool"},
    )
    declarations = registry.get_tool_declarations()
    assert [item["name"] for item in declarations] == [
        "gev",
        "gev_mcp_plan_route",
    ]
    assert registry.has("gev_mcp_plan_route")
    assert registry.run("gev_mcp_plan_route", {"to": "Rome"}, player="ui") == (
        "route result"
    )
    assert called == [("gev_mcp_plan_route", {"to": "Rome"}, "ui")]


def test_plugin_registry_rejects_extra_tool_name_collisions(monkeypatch):
    monkeypatch.setattr(plugin_loader, "get_plugin_enabled", lambda _name: True)
    record = PluginRecord(
        name="gev",
        description="GEV",
        run=lambda _args: "base",
        valid=True,
        extra_tool_declarations=lambda: [{
            "name": "core_tool",
            "description": "collision",
            "parameters": {"type": "OBJECT", "properties": {}},
        }],
    )
    registry = PluginRegistry(
        {"gev": record},
        lambda _message: None,
        reserved_tool_names={"core_tool"},
    )
    assert [item["name"] for item in registry.get_tool_declarations()] == ["gev"]


def test_plugin_registry_honors_plugin_disabled_state_for_extra_tools(monkeypatch):
    enabled = {"gev": True}
    monkeypatch.setattr(
        plugin_loader,
        "get_plugin_enabled",
        lambda name: enabled.get(name, True),
    )
    record = PluginRecord(
        name="gev",
        description="GEV",
        run=lambda _args: "base",
        valid=True,
        extra_tool_declarations=lambda: [{
            "name": "gev_mcp_plan_route",
            "description": "Plan a route.",
            "parameters": {"type": "OBJECT", "properties": {}},
        }],
        run_extra_tool=lambda *_args, **_kwargs: "must not run",
    )
    registry = PluginRegistry({"gev": record}, lambda _message: None)
    registry.get_tool_declarations()
    enabled["gev"] = False
    assert registry.run("gev_mcp_plan_route", {}) == (
        "The 'gev' plugin is currently disabled."
    )


def test_vessel_is_not_advertised_as_trackable():
    assert "vessel" not in gev_plugin.PLUGIN["parameters"]["properties"][
        "target_type"
    ]["enum"]
    result = gev_plugin.run({
        "action": "track",
        "target_type": "vessel",
        "target_id": "123456789",
    })
    assert "flight o satellite" in result


def test_historical_map_action_validates_and_forwards_discrete_commands():
    sent = []

    class Player:
        def send_to_gev(self, message):
            sent.append(message)

    result = gev_plugin.run(
        {
            "action": "historical_map",
            "command": "animate",
            "start_year": 1939,
            "end_year": 1945,
            "speed": 1,
        },
        player=Player(),
    )
    assert result == "Richiesta mappa storica 'animate' inviata, signore."
    assert sent == [{
        "action": "historical_map",
        "params": {
            "command": "animate",
            "start_year": 1939,
            "end_year": 1945,
            "speed": 1,
        },
    }]


def test_historical_map_action_rejects_invalid_year_and_speed():
    class Player:
        def send_to_gev(self, _message):
            raise AssertionError("invalid commands must not be forwarded")

    assert "anno intero" in gev_plugin.run(
        {"action": "historical_map", "command": "show", "year": "1938"},
        player=Player(),
    )


def test_gev_year_schema_documents_historical_action_years():
    description = gev_plugin.PLUGIN["parameters"]["properties"]["year"]["description"]

    assert "historical_scenario" in description
    assert "historical_factions" in description
    assert "historical_events" in description


def test_camera_actions_are_advertised_in_plugin_schema():
    properties = gev_plugin.PLUGIN["parameters"]["properties"]
    assert {
        "zoom", "tilt", "rotate", "reset_camera",
    }.issubset(properties["action"]["enum"])
    assert "fly_to" not in properties["action"]["enum"]
    assert properties["level"]["enum"] == ["in", "out"]
    assert {
        "lat", "lon", "altitude_m", "heading_deg", "pitch_deg",
    }.issubset(properties)


def test_gev_tab_actions_are_advertised_and_forwarded():
    properties = gev_plugin.PLUGIN["parameters"]["properties"]
    assert {"open_tab", "hide_tab"}.issubset(properties["action"]["enum"])
    sent = []

    class Player:
        def send_to_gev(self, message):
            sent.append(message)

    assert gev_plugin.run(
        {"action": "open_tab"}, player=Player()
    ) == "Apro la scheda God's Eye View con i pannelli visibili, signore."
    assert gev_plugin.run(
        {"action": "hide_tab"}, player=Player()
    ) == "Torno alla schermata Jarvis; God's Eye View resta aperto, signore."
    assert sent == [
        {"action": "open_tab", "params": {}},
        {"action": "hide_tab", "params": {}},
    ]


def test_gev_embed_url_selects_panels_ui():
    from PyQt6.QtCore import QUrl

    from ui import _GEV_URL

    assert QUrl(_GEV_URL).query() == "ui=panels"


@pytest.mark.parametrize(
    ("parameters", "expected_response", "expected_params"),
    [
        (
            {"action": "zoom", "level": "in"},
            "Zoom avanti, signore.",
            {"level": "in"},
        ),
        (
            {"action": "zoom", "level": "out"},
            "Zoom indietro, signore.",
            {"level": "out"},
        ),
        (
            {"action": "tilt", "pitch_deg": -45},
            "Inclino la vista a -45°, signore.",
            {"pitch_deg": -45},
        ),
        (
            {"action": "rotate", "heading_deg": 180},
            "Ruoto la vista a 180°, signore.",
            {"heading_deg": 180},
        ),
        (
            {"action": "reset_camera"},
            "Torno alla vista globale, signore.",
            {},
        ),
    ],
)
def test_camera_actions_forward_to_ui_bridge(
    parameters, expected_response, expected_params
):
    sent = []
    bridge_actions = {
        "zoom": "camera_zoom",
        "tilt": "camera_tilt",
        "rotate": "camera_rotate",
        "reset_camera": "camera_reset",
    }

    class Player:
        def send_to_gev(self, message):
            sent.append(message)

    assert gev_plugin.run(parameters, player=Player()) == expected_response
    assert sent == [{
        "action": bridge_actions[parameters["action"]],
        "params": expected_params,
    }]


@pytest.mark.parametrize(
    ("parameters", "request_type", "response_type", "result", "expected"),
    [
        (
            {"action": "historical_scenario", "name": "ww2", "year": 1941},
            "gev:historical-scenario",
            "gev:historical-scenario-applied",
            {"year": 1941, "map": {"year": 1938}},
            "snapshot 1938",
        ),
        (
            {"action": "historical_factions", "scenario": "ww2", "year": 1943},
            "gev:historical-factions",
            "gev:historical-factions-applied",
            {"selectedFactionYear": 1943},
            "applicate per 1943",
        ),
        (
            {"action": "historical_events", "scenario": "ww2", "year": 1944},
            "gev:historical-events",
            "gev:historical-events-applied",
            {"count": 2},
            "caricati: 2",
        ),
        (
            {"action": "historical_years"},
            "gev:historical-years",
            "gev:historical-years-applied",
            [-123000, 1938, 1945],
            "-123000, 1938, 1945",
        ),
    ],
)
def test_historical_extended_actions_round_trip_through_embedded_bridge(
    parameters, request_type, response_type, result, expected
):
    class Player:
        callback = None

        def on_gev_message(self, callback):
            self.callback = callback

        def send_to_gev(self, message):
            request = message["params"]
            assert message["action"] == "historical_map"
            assert request["command"] == "stop"
            assert request["command"] in {"show", "animate", "stop", "clear"}
            assert request["type"] == request_type
            self.callback({
                "type": response_type,
                "id": request["id"],
                "ok": True,
                "result": result,
            })

    response = gev_plugin.run(parameters, player=Player())
    assert expected in response


def test_historical_extended_action_propagates_geV_errors():
    class Player:
        def on_gev_message(self, callback):
            self.callback = callback

        def send_to_gev(self, message):
            request = message["params"]
            assert request["command"] == "stop"
            assert request["command"] in {"show", "animate", "stop", "clear"}
            assert request["type"] == "gev:historical-scenario"
            self.callback({
                "type": "gev:historical-scenario-applied",
                "id": request["id"],
                "ok": False,
                "error": "Unknown historical scenario",
            })

    response = gev_plugin.run(
        {"action": "historical_scenario", "name": "missing"},
        player=Player(),
    )
    assert "Unknown historical scenario" in response


def test_historical_extended_action_reports_missing_bridge_response(monkeypatch):
    monkeypatch.setattr(gev_plugin, "_HISTORICAL_RESPONSE_TIMEOUT_SEC", 0.001)

    class Player:
        def on_gev_message(self, _callback):
            pass

        def send_to_gev(self, _message):
            pass

    response = gev_plugin.run(
        {"action": "historical_years"},
        player=Player(),
    )
    assert "timeout" in response


def test_historical_extended_actions_validate_arguments_before_sending():
    class Player:
        def send_to_gev(self, _message):
            raise AssertionError("invalid command must not be sent")

    assert "nome" in gev_plugin.run(
        {"action": "historical_scenario"}, player=Player()
    )
    assert "anno intero" in gev_plugin.run(
        {
            "action": "historical_factions",
            "scenario": "ww2",
            "year": True,
        },
        player=Player(),
    )
    assert "velocità" in gev_plugin.run(
        {
            "action": "historical_map",
            "command": "animate",
            "start_year": 1938,
            "end_year": 1945,
            "speed": 0.1,
        },
        player=Player(),
    )
    assert "anno intero" in gev_plugin.run(
        {
            "action": "historical_map",
            "command": "show",
            "year": 10**1000,
        },
        player=Player(),
    )
