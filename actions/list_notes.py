"""List or search categorized notes."""
from core.notes_manager import list_notes as load_notes, search_notes


def list_notes(parameters: dict | None = None) -> str:
    values = parameters or {}
    category = values.get("category")
    query = values.get("query")
    if category is not None and (not isinstance(category, str) or not category.strip()):
        raise ValueError("La categoria deve essere un testo non vuoto.")
    data = search_notes(query) if query is not None else load_notes(category)
    if query is not None and category is not None:
        data = {key: notes for key, notes in data.items() if key.casefold() == category.casefold()}
    lines = [
        f"{category}: {note['testo']} (ID: {note['id']}, data: {note['data']})"
        for category, notes in data.items() for note in notes
    ]
    if not lines:
        return "Non ci sono appunti corrispondenti, Signore."
    return "I suoi appunti, Signore: " + "; ".join(lines)


TOOL = {
    "name": "list_notes",
    "description": "Elenca o cerca gli appunti categorizzati, con ID per esportazione o cancellazione.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "category": {"type": "STRING"},
            "query": {"type": "STRING", "description": "Testo da cercare nelle note."},
        },
        "required": [],
    },
    "risk_class": "read",
    "handler": list_notes,
}
