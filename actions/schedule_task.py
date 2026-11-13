"""Schedule safe spoken reminders, weather reports, and briefings."""
from __future__ import annotations

from core.scheduler import get_scheduler


def schedule_task(parameters: dict | None = None, **_context) -> str:
    values = parameters or {}
    task = get_scheduler().add(
        values.get("kind", "reminder"), values.get("message", ""),
        values.get("schedule", "once"), delay_minutes=values.get("delay_minutes"),
        hour=values.get("hour"), minute=values.get("minute", 0), at=values.get("at"),
    )
    return f"Task pianificato per {task['next_run']} (ID {task['id']}). Jarvis deve essere in esecuzione."


TOOL = {
    "name": "schedule_task",
    "description": (
        "Pianifica un promemoria vocale, il meteo o un briefing. Usa delay_minutes "
        "per 'tra 10 minuti', daily con hour e minute per ogni mattina, interval "
        "con delay_minutes per intervalli, o at in ISO 8601 per una data precisa. "
        "Non pianifica comandi di sistema arbitrari."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "kind": {"type": "STRING", "enum": ["reminder", "weather", "briefing"]},
            "message": {"type": "STRING", "description": "Testo del promemoria o città per il meteo."},
            "schedule": {"type": "STRING", "enum": ["once", "daily", "interval"]},
            "delay_minutes": {"type": "INTEGER"},
            "hour": {"type": "INTEGER"},
            "minute": {"type": "INTEGER"},
            "at": {"type": "STRING", "description": "Data e ora ISO 8601."},
        },
        "required": ["kind", "schedule"],
    },
    "risk_class": "write",
    "handler": schedule_task,
}
