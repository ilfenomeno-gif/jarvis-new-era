from __future__ import annotations

import json
import sys
from pathlib import Path

from core.audit_log import AuditLog
from core.connectors import ConnectorRegistry
from core.public_apis_catalog import PublicApisCatalog
from core.secret_store import SecretStore

ROOT = Path(__file__).resolve().parents[1]


class _FakeBackend:
    def protect(self, data: bytes) -> bytes:
        return data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]


def _connector_registry(tmp_path: Path) -> ConnectorRegistry:
    registry = ConnectorRegistry(
        tmp_path / "connectors.json",
        SecretStore(tmp_path / "secrets.json", _FakeBackend()),
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(ROOT / "connectors" / "catalog")
    return registry


def _stdio_test_server() -> str:
    return """
import json
import sys

apis = [
    {"id": "weather-free", "name": "Weather Free", "score": 0.9, "snippet": "weather"},
    {"id": "weather-key", "name": "Weather Key", "score": 0.8, "snippet": "weather"},
]
details = {
    "weather-free": {"id": "weather-free", "api": "Weather Free", "api_link": "https://api.example/weather", "auth": None, "category": "Weather"},
    "weather-key": {"id": "weather-key", "api": "Weather Key", "api_link": "https://api.example/keyed-weather", "auth": "apiKey", "category": "Weather"},
}
tools = [
    {"name": "search_public_apis", "description": "search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "get_public_api_details", "description": "details", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}},
]

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "test", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": tools}
    elif method == "tools/call":
        name = message["params"]["name"]
        args = message["params"]["arguments"]
        value = apis if name == "search_public_apis" else details[args["id"]]
        result = {"content": [{"type": "text", "text": json.dumps(value)}], "structuredContent": {"result": value}, "isError": False}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
"""


def test_stdio_activation_search_and_auth_filter_work_end_to_end(
    tmp_path, monkeypatch
):
    import core.public_apis_catalog as module
    from plugins._gev_mcp_client import McpStdioClient

    registry = _connector_registry(tmp_path)
    monkeypatch.setattr(module, "find_spec", lambda _name: object())
    launched_commands = []

    def client_factory(command, cwd, logger, *, request_timeout):
        launched_commands.append(command)
        return McpStdioClient(
            [sys.executable, "-u", "-c", _stdio_test_server()],
            cwd,
            logger,
            request_timeout=request_timeout,
        )

    catalog = PublicApisCatalog(registry, tmp_path, client_factory=client_factory)
    assert catalog.activate_async()["status"] == "starting"
    catalog._activation_thread.join(timeout=10)

    assert catalog.view()["status"] == "active"
    assert launched_commands == [[sys.executable, "-m", "public_apis_mcp"]]
    assert registry.tool_ready("public_apis.search_public_apis") == (True, "")
    search = catalog.search("weather")
    assert "Weather Free" in search and "Weather Key" in search

    no_auth = json.loads(catalog.filter_by_auth("weather", "none", 10))
    assert [api["api"] for api in no_auth] == ["Weather Free"]

    details = catalog._decode_result(catalog.details("weather-free"))
    assert details["api_link"] == "https://api.example/weather"
    catalog.stop()
    assert catalog.view()["status"] == "inactive"


def test_activation_reports_missing_python_package_without_starting_process(
    tmp_path, monkeypatch
):
    import core.public_apis_catalog as module

    catalog = PublicApisCatalog(_connector_registry(tmp_path), tmp_path)
    monkeypatch.setattr(module, "find_spec", lambda _name: None)
    catalog.activate_async()
    catalog._activation_thread.join(timeout=2)

    status = catalog.view()
    assert status["status"] == "error"
    assert "public-apis-mcp non è installato" in status["message"]


def test_public_apis_catalog_declares_stdio_tool_mapping(tmp_path):
    registry = _connector_registry(tmp_path)
    descriptor = registry.get("public-apis")

    assert descriptor.transport == "stdio"
    assert descriptor.tool_map == {
        "public_apis.search_public_apis": "search_public_apis",
        "public_apis.get_public_api_details": "get_public_api_details",
    }
    assert "public_apis.filter_apis_by_auth" in descriptor.tool_refs


def test_actions_expose_public_apis_search_details_and_auth_filter():
    from actions.filter_apis_by_auth import TOOL as filter_tool
    from actions.get_public_api_details import TOOL as details_tool
    from actions.search_public_apis import TOOL as search_tool

    assert search_tool["name"] == "search_public_apis"
    assert details_tool["name"] == "get_public_api_details"
    assert filter_tool["name"] == "filter_apis_by_auth"


def test_public_apis_actions_forward_simulated_inputs_and_results(monkeypatch):
    from types import SimpleNamespace

    from actions import filter_apis_by_auth, get_public_api_details, search_public_apis

    calls = []

    class FakeCatalog:
        def search(self, query, limit):
            calls.append(("search", query, limit))
            return '{"results": ["weather API"]}'

        def details(self, api_id):
            calls.append(("details", api_id))
            return '{"id": "weather", "auth": null}'

        def filter_by_auth(self, query, auth, limit):
            calls.append(("filter", query, auth, limit))
            return '[{"id": "weather"}]'

    def runtime():
        return SimpleNamespace(public_apis=FakeCatalog())

    monkeypatch.setattr(search_public_apis, "get_runtime", runtime)
    monkeypatch.setattr(get_public_api_details, "get_runtime", runtime)
    monkeypatch.setattr(filter_apis_by_auth, "get_runtime", runtime)

    assert search_public_apis.TOOL["handler"]({"query": "weather", "limit": 4}) == (
        '{"results": ["weather API"]}'
    )
    assert get_public_api_details.TOOL["handler"]({"id": "weather"}) == (
        '{"id": "weather", "auth": null}'
    )
    assert filter_apis_by_auth.TOOL["handler"](
        {"query": "weather", "auth": "none", "limit": 3}
    ) == '[{"id": "weather"}]'
    assert calls == [
        ("search", "weather", 4),
        ("details", "weather"),
        ("filter", "weather", "none", 3),
    ]


def test_public_apis_voice_requests_select_read_only_tools():
    from core.action_loader import discover_actions
    from core.tool_router import ToolRouter

    registry = discover_actions(ROOT / "actions", logger=lambda _message: None)
    declarations = registry.get_tool_declarations()
    router = ToolRouter()
    expected = {
        "search_public_apis",
        "get_public_api_details",
        "filter_apis_by_auth",
    }

    for request in (
        "Cerca un'API gratuita per il meteo",
        "Trova public APIs senza autenticazione",
        "Mostrami i dettagli di questa API",
    ):
        selected = {
            declaration["name"]
            for declaration in router.select_for_request(request, declarations)
        }
        assert expected <= selected

    assert expected <= registry.names()
    assert all(registry.risk_class(name) == "read" for name in expected)
    assert all(
        declaration["description"]
        for declaration in declarations
        if declaration["name"] in expected
    )
    assert all(
        "confirmed" not in declaration["parameters"].get("properties", {})
        for declaration in declarations
        if declaration["name"] in expected
    )
