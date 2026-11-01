"""
JARVIS plugin: agenda su Google Calendar.

Diverso da 'reminder' (promemoria singoli locali): questo plugin legge e
crea VERI eventi sul Google Calendar dell'utente, cosi restano visibili
anche fuori da JARVIS (telefono, altri dispositivi, condivisi con altri).

Setup richiesto (una tantum, fuori da JARVIS):
  1. Creare un progetto su https://console.cloud.google.com, abilitare la
     "Google Calendar API" e creare credenziali OAuth "Desktop app".
  2. Scaricare il file JSON delle credenziali e salvarlo da qualche parte
     sul disco, poi indicarne il percorso in config/api_keys.json con la
     chiave GOOGLE_CALENDAR_CREDENTIALS_PATH.
  3. Alla prima chiamata del plugin si aprirà una finestra del browser per
     autorizzare l'accesso: dopo l'autorizzazione, il token viene salvato in
     config/google_calendar_token.json e riusato automaticamente nelle
     chiamate successive (nessuna nuova autorizzazione finché e valido).

Dipendenze richieste (non ancora in requirements.txt, da installare a parte):
  pip install google-api-python-client google-auth-oauthlib
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from config import get_config

PLUGIN = {
    "name": "calendar_agenda",
    "description": (
        "Legge o crea eventi reali sul Google Calendar dell'utente. Usare "
        "action='list' con 'days_ahead' opzionale (default 1 = solo oggi) "
        "per vedere gli eventi in programma; action='create' con 'title', "
        "'start' e 'end' (date/ora ISO 8601, es. '2026-09-10T15:00:00') per "
        "creare un evento, 'description' e 'location' opzionali; "
        "action='delete' con 'event_id' (ottenuto da 'list') per eliminare "
        "un evento. NON usare 'reminder' per eventi che l'utente vuole "
        "vedere anche su telefono/altri dispositivi: usare questo plugin."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Una tra: 'list', 'create', 'delete'."},
            "days_ahead": {"type": "NUMBER", "description": "Quanti giorni in avanti considerare per action='list'. Predefinito 1 (solo oggi)."},
            "title": {"type": "STRING", "description": "Titolo dell'evento. Richiesto per action='create'."},
            "start": {"type": "STRING", "description": "Data/ora inizio ISO 8601 (es. '2026-09-10T15:00:00'). Richiesto per action='create'."},
            "end": {"type": "STRING", "description": "Data/ora fine ISO 8601. Se omessa, un'ora dopo 'start'."},
            "description": {"type": "STRING", "description": "Descrizione opzionale dell'evento."},
            "location": {"type": "STRING", "description": "Luogo opzionale dell'evento."},
            "event_id": {"type": "STRING", "description": "ID evento da eliminare. Richiesto per action='delete'."},
        },
        "required": ["action"],
    },
}

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_TOKEN_PATH = Path(__file__).resolve().parent.parent / "config" / "google_calendar_token.json"


def _get_service(cfg: dict):
    """Costruisce il client Google Calendar, gestendo login/refresh OAuth."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_path = cfg.get("GOOGLE_CALENDAR_CREDENTIALS_PATH")
    if not creds_path or not Path(creds_path).is_file():
        raise FileNotFoundError(
            "credenziali OAuth non configurate. Impostare "
            "GOOGLE_CALENDAR_CREDENTIALS_PATH in config/api_keys.json."
        )

    creds = None
    if _TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds)


def _list_events(service, days_ahead: float) -> str:
    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

    events_result = service.events().list(
        calendarId="primary", timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy="startTime", maxResults=25,
    ).execute()
    events = events_result.get("items", [])
    if not events:
        return "Non ci sono eventi in programma in questo periodo."

    lines = []
    for ev in events:
        start = ev["start"].get("dateTime", ev["start"].get("date"))
        lines.append(f"{ev.get('summary', '(senza titolo)')} — {start} [id: {ev['id']}]")
    return "Eventi in programma: " + "; ".join(lines)


def _create_event(service, params: dict) -> str:
    title = str(params.get("title", "")).strip()
    start = str(params.get("start", "")).strip()
    if not title or not start:
        raise ValueError("servono almeno 'title' e 'start' per creare un evento.")

    try:
        start_dt = datetime.fromisoformat(start)
    except ValueError:
        raise ValueError(f"formato data/ora non valido per 'start': {start!r}. Usare ISO 8601.")

    end = str(params.get("end", "")).strip()
    end_dt = datetime.fromisoformat(end) if end else start_dt + timedelta(hours=1)

    body = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    if params.get("description"):
        body["description"] = str(params["description"])
    if params.get("location"):
        body["location"] = str(params["location"])

    created = service.events().insert(calendarId="primary", body=body).execute()
    return f"Evento '{title}' creato per {start_dt.strftime('%d/%m/%Y alle %H:%M')}."


def _delete_event(service, event_id: str) -> str:
    if not event_id:
        raise ValueError("serve 'event_id' (ottenuto da action='list') per eliminare un evento.")
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return "Evento eliminato dal calendario."


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()

    try:
        try:
            cfg = get_config()
            service = _get_service(cfg)
        except ModuleNotFoundError:
            return ("Sir, mancano le dipendenze per Google Calendar. Eseguire: "
                    "pip install google-api-python-client google-auth-oauthlib")
        except FileNotFoundError as e:
            return f"Sir, {e}"

        if action == "list":
            try:
                days_ahead = float(parameters.get("days_ahead") or 1)
            except (TypeError, ValueError):
                days_ahead = 1
            result_text = _list_events(service, max(0.1, days_ahead))

        elif action == "create":
            result_text = _create_event(service, parameters)

        elif action == "delete":
            result_text = _delete_event(service, str(parameters.get("event_id", "")).strip())

        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare list, create o delete."

    except ValueError as e:
        return f"Sir, {e}"
    except Exception as e:
        return f"Sir, l'agenda Google Calendar ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
