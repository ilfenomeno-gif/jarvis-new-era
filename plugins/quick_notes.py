"""
JARVIS plugin: note rapide persistenti.

Salva piccole note testuali in un file JSON locale (memory/quick_notes.json,
la stessa cartella già usata da JARVIS per la memoria persistente e già
esclusa da git tramite .gitignore). Ogni nota ha un indice, un timestamp e il
testo. Il file viene sempre riscritto in modo atomico (file temporaneo + move)
per evitare corruzioni se JARVIS viene chiuso a metà scrittura.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

PLUGIN = {
    "name": "quick_notes",
    "description": (
        "Salva, elenca o elimina piccole note testuali personali dell'utente, "
        "persistenti tra una sessione e l'altra. Usare action='add' con 'text' "
        "per salvare una nota, action='list' per leggerle tutte, "
        "action='delete' con 'index' per eliminare una nota specifica, oppure "
        "action='clear' per eliminarle tutte. NON usare per promemoria con "
        "orario (usare invece il tool 'reminder') e non usare per la memoria "
        "a lungo termine generale (usare 'save_memory')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Una tra: 'add', 'list', 'delete', 'clear'.",
            },
            "text": {
                "type": "STRING",
                "description": "Il testo della nota. Richiesto solo se action='add'.",
            },
            "index": {
                "type": "NUMBER",
                "description": "Indice numerico (1-based, come mostrato da 'list') della nota da eliminare. Richiesto solo se action='delete'.",
            },
        },
        "required": ["action"],
    },
}

_NOTES_PATH = Path(__file__).resolve().parent.parent / "memory" / "quick_notes.json"
_MAX_NOTES = 200


def _load_notes() -> list[dict]:
    if not _NOTES_PATH.exists():
        return []
    try:
        raw = json.loads(_NOTES_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_notes(notes: list[dict]) -> None:
    _NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=_NOTES_PATH.parent, prefix=".quick_notes_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _NOTES_PATH)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()

    try:
        notes = _load_notes()

        if action == "add":
            text = parameters.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return "Sir, deve specificare il testo della nota da salvare."
            if len(notes) >= _MAX_NOTES:
                return f"Sir, ha già raggiunto il limite di {_MAX_NOTES} note. Elimini qualcuna prima di aggiungerne altre."
            notes.append({"text": text.strip(), "created": datetime.now().isoformat(timespec="seconds")})
            _save_notes(notes)
            result_text = f"Nota salvata. Ha ora {len(notes)} note in totale."

        elif action == "list":
            if not notes:
                result_text = "Non ha nessuna nota salvata al momento."
            else:
                lines = [f"{i}. {n.get('text', '')}" for i, n in enumerate(notes, start=1)]
                result_text = "Le sue note sono: " + "; ".join(lines)

        elif action == "delete":
            index = parameters.get("index")
            try:
                index = int(index)
            except (TypeError, ValueError):
                return "Sir, deve specificare l'indice numerico della nota da eliminare."
            if not (1 <= index <= len(notes)):
                return f"Sir, non esiste una nota con indice {index}. Ne ha {len(notes)} in totale."
            removed = notes.pop(index - 1)
            _save_notes(notes)
            result_text = f"Nota eliminata: {removed.get('text', '')}"

        elif action == "clear":
            count = len(notes)
            _save_notes([])
            result_text = f"Eliminate tutte le {count} note." if count else "Non c'erano note da eliminare."

        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare add, list, delete o clear."

    except Exception as e:
        return f"Sir, il plugin quick_notes ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
