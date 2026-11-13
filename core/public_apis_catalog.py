"""Opt-in stdio integration for the public-apis-mcp catalog."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

from core.connectors import ConnectorError, ConnectorRegistry
from core.mcp_transport import stdio_invoker
from plugins._gev_mcp_client import McpStdioClient

CONNECTOR_ID = "public-apis"
READ_SCOPE = "catalog.read"
SEARCH_TOOL = "search_public_apis"
DETAILS_TOOL = "get_public_api_details"
FILTER_TOOL = "filter_apis_by_auth"
TOOL_REF_PREFIX = "public_apis"


class PublicApisCatalog:
    def __init__(
        self,
        connectors: ConnectorRegistry,
        project_dir: Path,
        logger: Callable[[str], None] | None = None,
        client_factory: Callable[..., McpStdioClient] = McpStdioClient,
    ) -> None:
        self._connectors = connectors
        self._project_dir = Path(project_dir)
        self._logger = logger or (lambda _message: None)
        self._client_factory = client_factory
        self._client: McpStdioClient | None = None
        self._lock = threading.RLock()
        self._status = "inactive"
        self._message = "Premi «Attiva Catalogo» per avviare il server MCP."
        self._activation_thread: threading.Thread | None = None
        self._stopping = False

    def view(self) -> dict[str, str]:
        with self._lock:
            return {"status": self._status, "message": self._message}

    def activate_async(self) -> dict[str, str]:
        with self._lock:
            if self._status in {"starting", "active"}:
                return {"status": self._status, "message": self._message}
            self._stopping = False
            self._status = "starting"
            self._message = "Avvio del server MCP Public APIs in corso…"
            self._activation_thread = threading.Thread(
                target=self._activate,
                name="public-apis-mcp-start",
                daemon=True,
            )
            self._activation_thread.start()
            return {"status": self._status, "message": self._message}

    def _activate(self) -> None:
        client: McpStdioClient | None = None
        try:
            if find_spec("public_apis_mcp") is None:
                raise ConnectorError(
                    "Il pacchetto public-apis-mcp non è installato nell'ambiente "
                    f"Python di Jarvis ({sys.executable}). Installa le dipendenze "
                    "del progetto e riavvia l'app."
                )
            client = self._client_factory(
                [sys.executable, "-m", "public_apis_mcp"],
                self._project_dir,
                self._logger,
                request_timeout=180.0,
            )
            with self._lock:
                self._client = client
            tools = client.start()
            with self._lock:
                if self._stopping:
                    raise ConnectorError("Catalog activation was cancelled.")
            tool_names = {tool["name"] for tool in tools}
            missing = {SEARCH_TOOL, DETAILS_TOOL} - tool_names
            if missing:
                raise ConnectorError(
                    "Il server Public APIs non espone i tool richiesti: "
                    + ", ".join(sorted(missing))
                )
            self._connectors.set_invoker(
                CONNECTOR_ID,
                stdio_invoker(client, self._connectors.get(CONNECTOR_ID).tool_map),
            )
            self._connectors.grant(CONNECTOR_ID, [READ_SCOPE])
            with self._lock:
                if self._stopping:
                    raise ConnectorError("Catalog activation was cancelled.")
                self._status = "active"
                self._message = f"Catalogo attivo: {len(tools)} tool MCP disponibili."
            self._logger("Public APIs MCP catalog activated.")
        except Exception as exc:
            if client is not None:
                client.stop()
            with self._lock:
                if self._client is client:
                    self._client = None
                if self._stopping:
                    self._status = "inactive"
                    self._message = "Attivazione del catalogo annullata."
                else:
                    self._status = "error"
                    self._message = (
                        f"Attivazione non riuscita: {type(exc).__name__}: {exc}"
                    )
            self._logger(f"Public APIs MCP activation failed ({type(exc).__name__}).")

    def watchdog_healthy(self) -> bool:
        with self._lock:
            if self._status != "active":
                return True
            client = self._client
        return client is not None and bool(getattr(client, "is_running", True))

    def recover_stopped_process(self) -> None:
        with self._lock:
            if self._status != "active":
                return
            client = self._client
            if client is None or bool(getattr(client, "is_running", True)):
                return
            self._status = "error"
            self._message = "Il server MCP si è arrestato; riavvio in corso…"
            self._client = None
        self._logger("[WATCHDOG] Riavvio del processo Public APIs MCP di Jarvis.")
        client.stop()
        self.activate_async()

    def search(self, query: str, limit: int = 10) -> str:
        query = query.strip()
        if not query:
            raise ValueError("Inserisci una parola chiave o una categoria.")
        limit = max(1, min(int(limit), 50))
        return str(
            self._connectors.call_tool(
                f"{TOOL_REF_PREFIX}.{SEARCH_TOOL}",
                {"query": query, "limit": limit},
            )
        )

    def details(self, api_id: str) -> str:
        api_id = api_id.strip()
        if not api_id:
            raise ValueError("L'identificativo API è obbligatorio.")
        return str(
            self._connectors.call_tool(
                f"{TOOL_REF_PREFIX}.{DETAILS_TOOL}",
                {"id": api_id},
            )
        )

    @staticmethod
    def _decode_result(payload: str) -> object:
        if "Dati:" in payload:
            payload = payload.rsplit("Dati:", 1)[1].strip()
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = None
            for line in reversed(payload.splitlines()):
                try:
                    decoded = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            if decoded is not None:
                if isinstance(decoded, dict) and "result" in decoded:
                    decoded = decoded["result"]
                return decoded
            start = payload.find("[")
            end = payload.rfind("]")
            if start < 0 or end < start:
                raise ConnectorError(
                    "Il server Public APIs ha restituito risultati non strutturati."
                ) from None
            try:
                decoded = json.loads(payload[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ConnectorError(
                    "Il server Public APIs ha restituito risultati JSON non validi."
                ) from exc
        if isinstance(decoded, dict) and "result" in decoded:
            decoded = decoded["result"]
        return decoded

    def filter_by_auth(
        self,
        query: str = "public APIs",
        auth: str = "none",
        limit: int = 10,
    ) -> str:
        """Filter semantic search results by auth requirements using MCP details."""
        auth_filter = auth.strip().casefold()
        if auth_filter not in {"none", "no-auth", "no_auth", "unauthenticated"}:
            raise ValueError("Il filtro supportato è 'none' per API senza autenticazione.")
        ready, reason = self._connectors.tool_ready(
            f"{TOOL_REF_PREFIX}.{FILTER_TOOL}"
        )
        if not ready:
            raise ConnectorError(reason)
        search_payload = self._decode_result(self.search(query, min(limit, 50)))
        if isinstance(search_payload, dict):
            search_items = search_payload.get("results", search_payload.get("items"))
        else:
            search_items = search_payload
        if not isinstance(search_items, list):
            raise ConnectorError("Il server Public APIs ha restituito un elenco non valido.")

        matches: list[dict] = []
        for result in search_items:
            if not isinstance(result, dict):
                continue
            api_id = result.get("id")
            if not isinstance(api_id, str) or not api_id:
                continue
            details = self._decode_result(self.details(api_id))
            if isinstance(details, list):
                details = details[0] if details else None
            if not isinstance(details, dict):
                continue
            provider_auth = details.get("auth")
            if provider_auth is None or (
                isinstance(provider_auth, str)
                and provider_auth.strip().casefold() in {"", "none", "no auth"}
            ):
                matches.append(details)
        return json.dumps(matches, ensure_ascii=False, indent=2)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            client = self._client
            self._client = None
            self._status = "inactive"
            self._message = "Catalogo disattivato."
        if client is not None:
            client.stop()
