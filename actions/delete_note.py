"""Delete a single confirmed note."""
from core.notes_manager import delete_note as remove_note


def delete_note(parameters: dict | None = None) -> str:
    values = parameters or {}
    if values.get("confirmed") is not True:
        return "Serve una conferma esplicita per cancellare la nota."
    if not remove_note(values.get("note_id", "")):
        return "Non ho trovato una nota con questo ID, Signore."
    return "Ho cancellato la nota, Signore."


TOOL = {
    "name": "delete_note",
    "description": "Cancella una sola nota per ID dopo conferma esplicita. Se l'ID non è noto, usa list_notes.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"note_id": {"type": "STRING", "description": "ID completo della nota da eliminare."}},
        "required": ["note_id"],
    },
    "risk_class": "destructive",
    "handler": delete_note,
}
