"""Persistent categorized notes stored in a local JSON file."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import TypedDict

NOTES_PATH = Path(__file__).resolve().parents[1] / "config" / "notes.json"
_lock = threading.RLock()


class Note(TypedDict):
    id: str
    testo: str
    data: str


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} non può essere vuoto.")
    return value.strip()


def _load() -> dict[str, list[Note]]:
    try:
        raw = NOTES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Il file delle note deve contenere un oggetto per categoria.")
    ids: set[str] = set()
    for category, notes in data.items():
        if not isinstance(category, str) or not category.strip() or not isinstance(notes, list):
            raise ValueError("Categoria o elenco di note non valido.")
        for note in notes:
            if not isinstance(note, dict) or any(
                not isinstance(note.get(key), str) or not note[key].strip()
                for key in ("id", "testo", "data")
            ):
                raise ValueError("Nota non valida nel file delle note.")
            if note["id"] in ids:
                raise ValueError("ID duplicato nel file delle note.")
            ids.add(note["id"])
    return data


def _save(data: dict[str, list[Note]]) -> None:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".notes-", suffix=".tmp", dir=NOTES_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(filename, NOTES_PATH)
    finally:
        Path(filename).unlink(missing_ok=True)


def add_note(text: str, category: str = "Generale") -> Note:
    text = _text(text, "Il testo")
    category = _text(category, "La categoria")
    note: Note = {
        "id": str(uuid.uuid4()),
        "testo": text,
        "data": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with _lock:
        data = _load()
        category = next((name for name in data if name.casefold() == category.casefold()), category)
        data.setdefault(category, []).append(note)
        _save(data)
    return dict(note)


def list_notes(category: str | None = None) -> dict[str, list[Note]]:
    if category is not None:
        category = _text(category, "La categoria")
    with _lock:
        data = _load()
        return {
            key: [dict(note) for note in notes]
            for key, notes in data.items()
            if category is None or key.casefold() == category.casefold()
        }


def delete_note(note_id: str) -> bool:
    note_id = _text(note_id, "L'ID della nota")
    with _lock:
        data = _load()
        for category, notes in data.items():
            for index, note in enumerate(notes):
                if note["id"] == note_id:
                    del notes[index]
                    if not notes:
                        del data[category]
                    _save(data)
                    return True
    return False


def search_notes(query: str) -> dict[str, list[Note]]:
    query = _text(query, "La ricerca").casefold()
    return {
        category: matches
        for category, notes in list_notes().items()
        if (matches := [note for note in notes if query in note["testo"].casefold()])
    }
