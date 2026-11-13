"""Small Spotify Web API adapter exposed through the connector registry."""

from __future__ import annotations

from collections.abc import Callable

import requests


class SpotifyApiInvoker:
    def __init__(
        self,
        token_getter: Callable[[], str | None],
        *,
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._token_getter = token_getter
        self._http = session or requests.Session()
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        token = self._token_getter()
        if not token:
            raise RuntimeError("Spotify non è autenticato.")
        return {"Authorization": f"Bearer {token}"}

    def __call__(self, tool_ref: str, arguments: dict) -> str:
        if tool_ref == "spotify.currently_playing":
            response = self._http.get(
                "https://api.spotify.com/v1/me/player/currently-playing",
                headers=self._headers(),
                timeout=self._timeout,
            )
            if response.status_code == 204:
                return "Nessun brano è attualmente in riproduzione."
            response.raise_for_status()
            return response.text or "Nessun brano è attualmente in riproduzione."

        if tool_ref == "spotify.play":
            uri = str(arguments.get("uri", "")).strip()
            query = str(arguments.get("query", "")).strip()
            if not uri and query:
                response = self._http.get(
                    "https://api.spotify.com/v1/search",
                    headers=self._headers(),
                    params={"q": query, "type": "track", "limit": 1},
                    timeout=self._timeout,
                )
                response.raise_for_status()
                tracks = response.json().get("tracks", {}).get("items", [])
                if not tracks:
                    raise ValueError(f"Nessun brano trovato per: {query}")
                uri = str(tracks[0].get("uri", ""))
            if not uri.startswith("spotify:track:"):
                raise ValueError("Specificare un URI Spotify valido o il titolo del brano.")
            response = self._http.put(
                "https://api.spotify.com/v1/me/player/play",
                headers=self._headers(),
                json={"uris": [uri]},
                timeout=self._timeout,
            )
            if response.status_code == 404:
                raise RuntimeError(
                    "Nessun dispositivo Spotify attivo; aprire prima l'app Spotify."
                )
            response.raise_for_status()
            return "Riproduzione Spotify avviata."

        raise ValueError(f"Tool Spotify non supportato: {tool_ref}")
