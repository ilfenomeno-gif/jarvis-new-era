"""
JARVIS plugin: controllo riproduzione musicale (Spotify).

Usa la Spotify Web API con un refresh token OAuth già ottenuto una tantum
dall'utente (il flusso di autorizzazione interattivo va fatto una sola volta
fuori da JARVIS, es. con uno script di setup separato o la Spotify Console:
https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens).

IMPORTANTE — credenziali NON in api_keys.json:
Le credenziali Spotify (client id/secret/refresh token) sono sensibili e non
vengono lette dal file di configurazione condiviso, per evitare che finiscano
per errore in un repository o backup. Vanno impostate come variabili
d'ambiente di sistema, una volta sola:

    Windows (PowerShell, una tantum):
        setx SPOTIFY_CLIENT_ID "il_tuo_client_id"
        setx SPOTIFY_CLIENT_SECRET "il_tuo_client_secret"
        setx SPOTIFY_REFRESH_TOKEN "il_tuo_refresh_token"

    (dopo setx serve riaprire il terminale/riavviare JARVIS perché la
    variabile sia visibile al processo)

In alternativa, se preferisci un file locale invece delle variabili di
sistema, crea config/.env (NON versionato, aggiungilo a .gitignore) con:

    SPOTIFY_CLIENT_ID=...
    SPOTIFY_CLIENT_SECRET=...
    SPOTIFY_REFRESH_TOKEN=...

e installa `python-dotenv` (pip install python-dotenv): questo modulo lo
carica automaticamente se presente, senza toccare api_keys.json.

Nota: la Spotify Web API richiede un "dispositivo attivo" (l'app Spotify
aperta da qualche parte, anche in pausa) per i comandi di playback; se non
ce n'e uno, l'API risponde 404 e il plugin lo segnala con un messaggio
comprensibile invece di un errore HTTP grezzo.
"""

from __future__ import annotations

import base64
import os
import time

# Caricamento opzionale di config/.env, se il file esiste e python-dotenv
# è installato. Se manca l'uno o l'altro il plugin funziona comunque con le
# variabili d'ambiente di sistema.
try:
    from dotenv import load_dotenv

    _env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env")
    if os.path.isfile(_env_path):
        load_dotenv(_env_path)
except ImportError:
    pass

PLUGIN = {
    "name": "spotify_music_control",
    "description": (
        "Controlla la riproduzione musicale su Spotify: play/pausa, brano "
        "successivo/precedente, volume, informazioni sul brano in "
        "riproduzione, oppure ricerca e riproduzione di un brano/artista. "
        "Usare action='play' (con 'query' opzionale per cercare un brano), "
        "'pause', 'next', 'previous', 'volume' (con 'value' 0-100), oppure "
        "'current' per sapere cosa sta suonando. Diverso da 'youtube_video': "
        "usare questo plugin solo per Spotify, non per video YouTube."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Una tra: 'play', 'pause', 'next', 'previous', 'volume', 'current'."},
            "query": {"type": "STRING", "description": "Brano o artista da cercare e riprodurre. Usato solo con action='play'."},
            "value": {"type": "NUMBER", "description": "Volume 0-100. Richiesto solo con action='volume'."},
        },
        "required": ["action"],
    },
}

_API_BASE = "https://api.spotify.com/v1"
_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Nomi delle variabili d'ambiente attese (NON chiavi in api_keys.json).
_ENV_CLIENT_ID = "SPOTIFY_CLIENT_ID"
_ENV_CLIENT_SECRET = "SPOTIFY_CLIENT_SECRET"
_ENV_REFRESH_TOKEN = "SPOTIFY_REFRESH_TOKEN"

# Cache in-process del access token: evita di richiederne uno nuovo ad ogni
# chiamata (il modulo resta caricato per tutta la sessione di JARVIS).
_token_cache = {"access_token": None, "expires_at": 0.0}


def _get_spotify_credentials() -> dict:
    """Legge le credenziali Spotify SOLO dalle variabili d'ambiente."""
    return {
        "client_id": os.environ.get(_ENV_CLIENT_ID, "").strip(),
        "client_secret": os.environ.get(_ENV_CLIENT_SECRET, "").strip(),
        "refresh_token": os.environ.get(_ENV_REFRESH_TOKEN, "").strip(),
    }


def _get_access_token(creds: dict) -> str:
    import requests

    now = time.monotonic()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    basic = base64.b64encode(f"{creds['client_id']}:{creds['client_secret']}".encode()).decode()

    resp = requests.post(
        _TOKEN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": creds["refresh_token"]},
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + float(data.get("expires_in", 3600))
    return _token_cache["access_token"]


def _headers(creds: dict) -> dict:
    return {"Authorization": f"Bearer {_get_access_token(creds)}"}


def _no_active_device(resp) -> bool:
    return resp.status_code == 404


def _search_track_uri(creds: dict, query: str) -> tuple[str, str]:
    import requests

    resp = requests.get(
        f"{_API_BASE}/search", headers=_headers(creds),
        params={"q": query, "type": "track", "limit": 1}, timeout=8,
    )
    resp.raise_for_status()
    items = resp.json().get("tracks", {}).get("items", [])
    if not items:
        raise ValueError(f"nessun brano trovato per '{query}'.")
    track = items[0]
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    return track["uri"], f"{track['name']} — {artists}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()

    try:
        creds = _get_spotify_credentials()
        missing = [k for k, v in (
            ("SPOTIFY_CLIENT_ID", creds["client_id"]),
            ("SPOTIFY_CLIENT_SECRET", creds["client_secret"]),
            ("SPOTIFY_REFRESH_TOKEN", creds["refresh_token"]),
        ) if not v]
        if missing:
            return ("Sir, Spotify non e configurato. Imposti come variabili d'ambiente (non in "
                     f"api_keys.json): {', '.join(missing)}.")

        import requests

        if action == "play":
            query = str(parameters.get("query", "")).strip()
            if query:
                uri, label = _search_track_uri(creds, query)
                resp = requests.put(f"{_API_BASE}/me/player/play", headers=_headers(creds),
                                     json={"uris": [uri]}, timeout=8)
                success_text = f"Riproduzione di '{label}' avviata su Spotify."
            else:
                resp = requests.put(f"{_API_BASE}/me/player/play", headers=_headers(creds), timeout=8)
                success_text = "Riproduzione Spotify ripresa."
            if _no_active_device(resp):
                return "Sir, non trovo un dispositivo Spotify attivo. Apra l'app Spotify da qualche parte e riprovi."
            resp.raise_for_status()
            result_text = success_text

        elif action == "pause":
            resp = requests.put(f"{_API_BASE}/me/player/pause", headers=_headers(creds), timeout=8)
            if _no_active_device(resp):
                return "Sir, non trovo un dispositivo Spotify attivo."
            resp.raise_for_status()
            result_text = "Riproduzione Spotify in pausa."

        elif action == "next":
            resp = requests.post(f"{_API_BASE}/me/player/next", headers=_headers(creds), timeout=8)
            if _no_active_device(resp):
                return "Sir, non trovo un dispositivo Spotify attivo."
            resp.raise_for_status()
            result_text = "Passato al brano successivo."

        elif action == "previous":
            resp = requests.post(f"{_API_BASE}/me/player/previous", headers=_headers(creds), timeout=8)
            if _no_active_device(resp):
                return "Sir, non trovo un dispositivo Spotify attivo."
            resp.raise_for_status()
            result_text = "Tornato al brano precedente."

        elif action == "volume":
            value = parameters.get("value")
            if value is None:
                return "Sir, deve specificare il volume (0-100)."
            vol = int(max(0, min(100, float(value))))
            resp = requests.put(f"{_API_BASE}/me/player/volume", headers=_headers(creds),
                                 params={"volume_percent": vol}, timeout=8)
            if _no_active_device(resp):
                return "Sir, non trovo un dispositivo Spotify attivo."
            resp.raise_for_status()
            result_text = f"Volume Spotify impostato al {vol}%."

        elif action == "current":
            resp = requests.get(f"{_API_BASE}/me/player/currently-playing", headers=_headers(creds), timeout=8)
            if resp.status_code == 204 or _no_active_device(resp):
                return "Sir, al momento non c'e nulla in riproduzione su Spotify."
            resp.raise_for_status()
            item = resp.json().get("item") or {}
            name = item.get("name", "sconosciuto")
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            result_text = f"In riproduzione: {name} — {artists}."

        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare play, pause, next, previous, volume o current."

    except ValueError as e:
        return f"Sir, {e}"
    except Exception as e:
        return f"Sir, il controllo Spotify ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text