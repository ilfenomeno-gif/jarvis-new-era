"""Return a privacy-preserving summary of the already collected context."""
import time
from datetime import datetime

from core.context_awareness import current_context, format_app_name, safe_app_name
from core.personality_engine import PersonalityEngine

_CALENDAR_MAX_AGE_SECONDS = 60.0
_TONES = {
    "mattina": "energico e conciso",
    "lavoro": "formale e diretto",
    "pomeriggio": "cordiale",
    "sera": "rilassato e informale",
    "notte": "premuroso e breve",
    "relax": "amichevole e informale",
}


def check_context(parameters: dict) -> str:
    context = current_context()
    if context is None:
        return "Il monitoraggio del contesto non è disponibile o è disabilitato."
    observed_at = context.get("observed_at")
    try:
        clock = datetime.fromisoformat(observed_at).strftime("%H:%M") if observed_at else "dato non disponibile"
    except (TypeError, ValueError):
        clock = "dato non disponibile"
    category = context.get("window_category") or "dato non disponibile"
    app = safe_app_name(context)
    personality = PersonalityEngine()
    tone = (
        _TONES.get(personality.profile(context), "dato non disponibile")
        if personality.get_personality_prompt(context) else "predefinito"
    )
    calendar = context.get("calendar") or {}
    updated = context.get("calendar_updated_monotonic")
    age = time.monotonic() - updated if isinstance(updated, (int, float)) else None
    status = calendar.get("status")
    if age is None or not 0 <= age <= _CALENDAR_MAX_AGE_SECONDS:
        agenda = "dato non disponibile"
    elif status == "ongoing":
        agenda = "evento in corso"
    elif status == "upcoming" and isinstance(calendar.get("minutes"), (int, float)):
        agenda = f"evento tra {calendar['minutes']} minuti"
    elif status == "free":
        agenda = "nessun evento imminente"
    else:
        agenda = "dato non disponibile"
    application = f"Applicazione: {format_app_name(app)}. " if app else ""
    activity = f"Attività: {category}. " if not app or category != "altra applicazione" else ""
    return f"Ora: {clock}. {application}{activity}Tono: {tone}. Calendario: {agenda}."


TOOL = {
    "name": "check_context",
    "description": (
        "Legge lo snapshot in memoria solo se l'utente chiede esplicitamente "
        "il contesto o cosa sta facendo, oppure se servono informazioni sul "
        "contesto non già disponibili. Usa il nome dell'applicazione restituito "
        "anche se è sconosciuta. Non chiamare a ogni turno."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_context,
}
