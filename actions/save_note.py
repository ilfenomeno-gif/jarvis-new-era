"""Save a categorized note."""
from core.notes_manager import add_note


def save_note(parameters: dict | None = None) -> str:
    values = parameters or {}
    text = values.get("text", "")
    note = add_note(text, values.get("category") or "Generale")
    return f"Ho preso nota, Signore: {note['testo']}"


TOOL = {
    "name": "save_note",
    "description": "Salva un appunto dell'utente in una categoria; non usare per promemoria a orario.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING", "description": "Testo esatto dell'appunto."},
            "category": {"type": "STRING", "description": "Categoria, predefinita Generale."},
        },
        "required": ["text"],
    },
    "risk_class": "write",
    "handler": save_note,
}
