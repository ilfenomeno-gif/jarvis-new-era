"""Compose a single spoken briefing from weather, headlines and scheduled tasks."""
from __future__ import annotations

from datetime import datetime

from core.scheduler import get_scheduler


def local_weather(city: str = "") -> str:
    from actions.web_search import _ddg_search, _run_bounded
    from memory.memory_manager import load_memory

    memory = load_memory()
    city_entry = memory.get("identity", {}).get("city", {})
    city = str(city or (city_entry.get("value", "") if isinstance(city_entry, dict) else "")).strip()
    if city:
        weather = _run_bounded(lambda: _ddg_search(f"meteo oggi {city}", max_results=3),
                               timeout=5.0, label="meteo")
        snippet = next((str(item.get("snippet", "")).strip() for item in weather or [] if item.get("snippet")), "")
        return f"Per il meteo a {city}: {snippet}" if snippet else f"Il meteo per {city} non è disponibile."
    return "Non conosco la tua città, quindi non posso fornire il meteo locale."


def morning_briefing(parameters: dict | None = None, **_context) -> str:
    from actions.web_search import _ddg_news, _run_bounded

    values = parameters or {}
    sections = ["Buongiorno, Signore.", local_weather(values.get("city", ""))]
    news = _run_bounded(lambda: _ddg_news("tecnologia ultime notizie", max_results=3),
                        timeout=5.0, label="notizie") or []
    headlines = [str(item.get("title", "")).strip() for item in news if item.get("title")][:3]
    sections.append("Le ultime notizie tecnologiche: " + "; ".join(headlines) + "." if headlines else "Le notizie tecnologiche non sono disponibili.")
    today = datetime.now().astimezone().date()
    tasks = [
        task for task in get_scheduler().list_tasks()
        if datetime.fromisoformat(task["next_run"]).astimezone().date() == today
    ]
    if tasks:
        details = [
            f"{datetime.fromisoformat(task['next_run']).astimezone():%H:%M}: "
            f"{task['message'] or task['kind']}" for task in tasks
        ]
        sections.append("I task pianificati per oggi sono: " + "; ".join(details) + ".")
    else:
        sections.append("Non ci sono task Jarvis pianificati per oggi.")
    sections.append("Il calendario esterno non è incluso in questo briefing.")
    return " ".join(sections)


TOOL = {
    "name": "morning_briefing",
    "description": "Prepara un unico briefing vocale con meteo locale, tre notizie tecnologiche e task Jarvis di oggi.",
    "parameters": {"type": "OBJECT", "properties": {"city": {"type": "STRING"}}, "required": []},
    "risk_class": "read",
    "handler": morning_briefing,
}
