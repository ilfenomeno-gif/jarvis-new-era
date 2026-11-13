"""Start OAuth for a named connector and open its provider authorization page."""

from __future__ import annotations

import webbrowser
from urllib.parse import urlsplit

from core.connectors import ConnectorError
from core.jarvis_runtime import get_runtime


def connect_service(parameters: dict, player=None) -> str:
    connector_id = str(parameters.get("connector_id", "")).strip()
    if not connector_id:
        return "Specifica il servizio da collegare, ad esempio GitHub o Spotify."

    runtime = get_runtime()
    connectors = runtime.connectors
    try:
        descriptor = connectors.get(connector_id)
    except (ConnectorError, KeyError) as exc:
        return f"Non riconosco il servizio {connector_id!r}: {exc}"

    if connectors.status(connector_id) == "connected":
        return f"{descriptor.name} è già connesso."

    begin_oauth = getattr(player, "begin_connector_oauth", None)
    if not callable(begin_oauth):
        begin_oauth = connectors.begin_oauth

    try:
        authorization_url = begin_oauth(connector_id)
        parsed_url = urlsplit(authorization_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise RuntimeError("Il provider ha restituito un URL OAuth non valido.")
        if not webbrowser.open_new_tab(authorization_url):
            raise RuntimeError("Il browser predefinito non si è aperto.")
    except Exception as exc:
        connectors.cancel_oauth(connector_id)
        raise RuntimeError(
            f"Connessione {descriptor.name} non avviata: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return (
        f"Autorizzazione {descriptor.name} avviata. Completa l'accesso nel browser; "
        "Jarvis aggiornerà lo stato della connessione al termine."
    )


TOOL = {
    "name": "connect_service",
    "description": (
        "Avvia il login OAuth e apre il browser per collegare un servizio a Jarvis. "
        "Usa questo strumento quando l'utente dice esplicitamente 'Connetti', "
        "'Collega' o 'Accedi a' seguito dal nome di un servizio come GitHub, "
        "Spotify, Google Workspace, Canva o Higgsfield. Imposta connector_id "
        "sull'identificativo esatto del servizio (per esempio 'github' o 'spotify')."
    ),
    "risk_class": "write",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "connector_id": {
                "type": "STRING",
                "description": (
                    "ID esatto del servizio: github, spotify, google-workspace, "
                    "canva, higgsfield o n8n."
                ),
            }
        },
        "required": ["connector_id"],
    },
    "handler": connect_service,
}
