"""Gmail read-only API adapter for the Google Workspace connector."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from http import HTTPStatus
from urllib.parse import quote

import requests

from core.connectors import ConnectorError

_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
_LOGGER = logging.getLogger(__name__)
_PERMISSION_ERROR = (
    "Permesso Gmail mancante. Vai su Google Cloud e abilita l'API Gmail, "
    "poi riconnetti l'account."
)


class GoogleWorkspaceApiInvoker:
    def __init__(
        self,
        token_getter: Callable[[], str | None],
        token_refresher: Callable[[], str | None],
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._token_getter = token_getter
        self._token_refresher = token_refresher
        self._http = session or requests.Session()
        self._timeout = timeout

    def _get(self, url: str, params: dict) -> dict:
        token = self._token_getter()
        if not token:
            raise ConnectorError("Google Workspace non è autenticato.")
        for attempt in range(2):
            try:
                response = self._http.get(
                    url, params=params, headers={"Authorization": "Bearer " + token},
                    timeout=self._timeout,
                )
                response.raise_for_status()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                try:
                    phrase = HTTPStatus(status).phrase
                except (TypeError, ValueError):
                    phrase = "Unknown"
                _LOGGER.error("Gmail API HTTP %s %s", status, phrase)
                if status == 401 and attempt == 0:
                    token = self._token_refresher()
                    if not token:
                        raise ConnectorError("Google Workspace: rinnovo token non disponibile.") from exc
                    continue
                if status == 403:
                    raise ConnectorError(_PERMISSION_ERROR) from exc
                raise ConnectorError(f"Gmail API: HTTP {status} {phrase}.") from exc
            except requests.RequestException as exc:
                _LOGGER.error("Gmail API richiesta fallita: %s", type(exc).__name__)
                raise ConnectorError(
                    f"Impossibile raggiungere Gmail ({type(exc).__name__})."
                ) from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise ConnectorError("Risposta JSON Gmail non valida o vuota.") from exc
            if not isinstance(data, dict):
                raise ConnectorError("Risposta JSON Gmail non valida: atteso un oggetto.")
            return data
        raise ConnectorError("Gmail API: autenticazione non riuscita.")

    def __call__(self, tool_ref: str, arguments: dict) -> str:
        if tool_ref != "gmail.search":
            raise ConnectorError(f"Tool Google Workspace non supportato: {tool_ref}.")
        query = arguments.get("query", arguments.get("q", ""))
        if not isinstance(query, str):
            raise ConnectorError("La query Gmail deve essere una stringa.")
        limit = arguments.get("max_results", arguments.get("maxResults", 10))
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ConnectorError("max_results deve essere un numero intero tra 1 e 100.")
        data = self._get(_BASE_URL, {"q": query, "maxResults": limit})
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            raise ConnectorError("Risposta Gmail non valida: elenco messaggi non valido.")
        if not messages:
            return "Nessuna email trovata."
        result = []
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not message["id"]:
                raise ConnectorError("Risposta Gmail non valida: ID messaggio mancante.")
            detail = self._get(
                f"{_BASE_URL}/{quote(message['id'], safe='')}",
                {"format": "metadata", "metadataHeaders": ["From", "Date", "Subject"]},
            )
            payload = detail.get("payload")
            headers = payload.get("headers") if isinstance(payload, dict) else None
            if not isinstance(headers, list):
                raise ConnectorError("Risposta Gmail non valida: intestazioni mancanti.")
            fields = {
                header["name"].lower(): header["value"]
                for header in headers
                if isinstance(header, dict)
                and isinstance(header.get("name"), str)
                and isinstance(header.get("value"), str)
            }
            result.append({
                "id": message["id"],
                "from": fields.get("from", ""),
                "date": fields.get("date", ""),
                "subject": fields.get("subject", ""),
                "internalDate": detail.get("internalDate", ""),
            })
        return json.dumps({"messages": result}, ensure_ascii=False)
