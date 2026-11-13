"""Export one note or one category to a new Desktop text file."""
import os
import uuid
from pathlib import Path

from core.notes_manager import list_notes


def export_note_to_file(parameters: dict | None = None) -> str:
    values = parameters or {}
    note_id, category = values.get("note_id"), values.get("category")
    if bool(note_id) == bool(category):
        raise ValueError("Indichi l'ID di una nota oppure una categoria, non entrambi.")
    if note_id is not None and (not isinstance(note_id, str) or not note_id.strip()):
        raise ValueError("L'ID della nota deve essere un testo non vuoto.")
    if category is not None and (not isinstance(category, str) or not category.strip()):
        raise ValueError("La categoria deve essere un testo non vuoto.")
    if note_id:
        note_id = note_id.strip()
    data = list_notes(category) if category else list_notes()
    selected = [
        (name, note)
        for name, notes in data.items()
        for note in notes
        if not note_id or note["id"] == note_id
    ]
    if not selected:
        return "Non ho trovato note da esportare, Signore."
    desktop = Path(os.path.expanduser("~/Desktop"))
    if not desktop.is_dir():
        raise FileNotFoundError(f"Cartella Desktop non disponibile: {desktop}")
    path = desktop / f"appunti-{uuid.uuid4()}.txt"
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as file:
            created = True
            for name, note in selected:
                file.write(f"Categoria: {name}\nData: {note['data']}\nID: {note['id']}\n{note['testo']}\n\n")
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise
    return f"Ho staccato la nota e l'ho salvata sul Desktop, Signore. File: {path.name}"


TOOL = {
    "name": "export_note_to_file",
    "description": "Esporta sul Desktop una nota per ID o tutte le note di una categoria. Non inventare ID o categorie: usa list_notes se necessario.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "note_id": {"type": "STRING", "description": "ID completo di una singola nota."},
            "category": {"type": "STRING", "description": "Categoria completa da esportare."},
        },
        "required": [],
    },
    "risk_class": "write",
    "handler": export_note_to_file,
}
