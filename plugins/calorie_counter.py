"""
JARVIS plugin: conta-calorie giornaliero.

Registra pasti/alimenti con relative calorie (e macro opzionali: proteine,
carboidrati, grassi in grammi) in memory/calorie_log.json, organizzati per
data (YYYY-MM-DD). Il "reset a mezzanotte" non cancella la cronologia: il
totale giornaliero e sempre calcolato sulla data odierna, quindi appena
passa la mezzanotte il riepilogo di 'today' ricomincia naturalmente da zero
senza bisogno di un cron job o di un thread in background.
"""

from __future__ import annotations

from pathlib import Path

from plugins._plugin_utils import MEMORY_DIR, today_str, now_str, load_json, atomic_write_json

PLUGIN = {
    "name": "calorie_counter",
    "description": (
        "Registra un pasto/alimento con le sue calorie (e opzionalmente "
        "proteine/carboidrati/grassi in grammi), oppure mostra il riepilogo "
        "calorico e dei macro del giorno. Usare action='add' con 'food' e "
        "'calories' per registrare un pasto; action='summary' per il totale "
        "di oggi (o di una data specifica con 'date' in formato YYYY-MM-DD); "
        "action='list' per l'elenco dei pasti di oggi; action='delete' con "
        "'index' per eliminare un pasto; action='clear' per svuotare il "
        "giorno corrente. NON usare per informazioni nutrizionali generiche "
        "su un alimento (nessun database calorico integrato): l'utente deve "
        "fornire lui stesso il valore calorico, oppure JARVIS puo stimarlo "
        "prima di chiamare questo strumento."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Una tra: 'add', 'summary', 'list', 'delete', 'clear'."},
            "food": {"type": "STRING", "description": "Nome dell'alimento/pasto. Richiesto solo per action='add'."},
            "calories": {"type": "NUMBER", "description": "Calorie del pasto (kcal). Richiesto solo per action='add'."},
            "protein_g": {"type": "NUMBER", "description": "Proteine in grammi, opzionale."},
            "carbs_g": {"type": "NUMBER", "description": "Carboidrati in grammi, opzionale."},
            "fat_g": {"type": "NUMBER", "description": "Grassi in grammi, opzionale."},
            "index": {"type": "NUMBER", "description": "Indice (1-based, da 'list') del pasto da eliminare. Richiesto solo per action='delete'."},
            "date": {"type": "STRING", "description": "Data YYYY-MM-DD per action='summary'. Se omessa, usa oggi."},
        },
        "required": ["action"],
    },
}

_LOG_PATH = MEMORY_DIR / "calorie_log.json"
_MAX_ENTRIES_PER_DAY = 100


def _load() -> dict:
    data = load_json(_LOG_PATH, {})
    return data if isinstance(data, dict) else {}


def _num(value, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{name}' deve essere un numero, ricevuto: {value!r}")


def _totals(entries: list[dict]) -> dict:
    return {
        "calories": sum(e.get("calories", 0) or 0 for e in entries),
        "protein_g": sum(e.get("protein_g", 0) or 0 for e in entries),
        "carbs_g": sum(e.get("carbs_g", 0) or 0 for e in entries),
        "fat_g": sum(e.get("fat_g", 0) or 0 for e in entries),
    }


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()

    try:
        log = _load()
        today = today_str()

        if action == "add":
            food = str(parameters.get("food", "")).strip()
            if not food:
                return "Sir, deve specificare il nome dell'alimento o del pasto."
            try:
                calories = _num(parameters.get("calories"), "calories")
                protein_g = _num(parameters.get("protein_g"), "protein_g")
                carbs_g = _num(parameters.get("carbs_g"), "carbs_g")
                fat_g = _num(parameters.get("fat_g"), "fat_g")
            except ValueError as e:
                return f"Sir, {e}"
            if calories is None:
                return "Sir, deve specificare le calorie del pasto."

            day_entries = log.setdefault(today, [])
            if len(day_entries) >= _MAX_ENTRIES_PER_DAY:
                return f"Sir, ha già raggiunto il limite di {_MAX_ENTRIES_PER_DAY} pasti per oggi."
            day_entries.append({
                "food": food, "calories": calories,
                "protein_g": protein_g or 0, "carbs_g": carbs_g or 0, "fat_g": fat_g or 0,
                "time": now_str(),
            })
            atomic_write_json(_LOG_PATH, log)
            totals = _totals(day_entries)
            result_text = (f"Registrato: {food} ({_fmt(calories)} kcal). "
                            f"Totale di oggi: {_fmt(totals['calories'])} kcal.")

        elif action in ("summary", "list"):
            target_date = str(parameters.get("date") or today).strip()
            day_entries = log.get(target_date, [])
            label = "oggi" if target_date == today else target_date
            if not day_entries:
                result_text = f"Non ci sono pasti registrati per {label}."
            elif action == "list":
                lines = [f"{i}. {e.get('food', '?')} ({_fmt(e.get('calories', 0))} kcal)"
                         for i, e in enumerate(day_entries, start=1)]
                result_text = f"Pasti di {label}: " + "; ".join(lines)
            else:
                totals = _totals(day_entries)
                result_text = (
                    f"Riepilogo di {label}: {_fmt(totals['calories'])} kcal totali su "
                    f"{len(day_entries)} pasti. Proteine: {_fmt(totals['protein_g'])} g, "
                    f"carboidrati: {_fmt(totals['carbs_g'])} g, grassi: {_fmt(totals['fat_g'])} g."
                )

        elif action == "delete":
            index = parameters.get("index")
            try:
                index = int(index)
            except (TypeError, ValueError):
                return "Sir, deve specificare l'indice numerico del pasto da eliminare."
            day_entries = log.get(today, [])
            if not (1 <= index <= len(day_entries)):
                return f"Sir, non esiste un pasto con indice {index} per oggi. Ne ha {len(day_entries)}."
            removed = day_entries.pop(index - 1)
            log[today] = day_entries
            atomic_write_json(_LOG_PATH, log)
            result_text = f"Pasto eliminato: {removed.get('food', '?')}."

        elif action == "clear":
            count = len(log.get(today, []))
            log[today] = []
            atomic_write_json(_LOG_PATH, log)
            result_text = f"Eliminati tutti i {count} pasti di oggi." if count else "Non c'erano pasti da eliminare oggi."

        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare add, summary, list, delete o clear."

    except Exception as e:
        return f"Sir, il plugin calorie_counter ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
