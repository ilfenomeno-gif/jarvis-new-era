import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from actions.delete_note import delete_note
from actions.export_note_to_file import export_note_to_file
from actions.list_notes import list_notes as list_action
from actions.save_note import save_note
from core import notes_manager as notes
from core.action_loader import discover_actions
from core.tool_router import ToolRouter


@pytest.fixture(autouse=True)
def isolate_notes(monkeypatch, tmp_path):
    monkeypatch.setattr(notes, "NOTES_PATH", tmp_path / "config" / "notes.json")


def test_persistence_categories_search_and_delete():
    first = notes.add_note("Comprare il latte", "Spesa")
    second = notes.add_note("Compra il pane", "spesa")
    notes.add_note("Fare la relazione", "Lavoro")
    stored = json.loads(notes.NOTES_PATH.read_text(encoding="utf-8"))
    assert set(stored) == {"Spesa", "Lavoro"}
    assert stored["Spesa"] == [first, second]
    assert notes.list_notes("SPESA") == {"Spesa": [first, second]}
    assert notes.search_notes("LATTE") == {"Spesa": [first]}
    assert notes.delete_note(first["id"])
    assert not notes.delete_note(first["id"])
    assert notes.list_notes("spesa") == {"Spesa": [second]}


def test_corrupt_storage_is_not_overwritten():
    notes.NOTES_PATH.parent.mkdir(parents=True)
    notes.NOTES_PATH.write_text("{bad", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        notes.add_note("test", "Generale")
    assert notes.NOTES_PATH.read_text(encoding="utf-8") == "{bad"


def test_concurrent_writes_are_not_lost():
    threads = [threading.Thread(target=notes.add_note, args=(f"nota {i}", "Test")) for i in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(notes.list_notes("test")["Test"]) == 25


def test_actions_save_read_search_and_delete():
    assert save_note({"text": "comprare il latte"}) == "Ho preso nota, Signore: comprare il latte"
    note = notes.list_notes()["Generale"][0]
    assert note["id"] in list_action({})
    assert "comprare il latte" in list_action({"query": "LATTE"})
    assert delete_note({"note_id": note["id"]}).startswith("Serve una conferma")
    assert notes.list_notes()
    assert "cancellato" in delete_note({"note_id": note["id"], "confirmed": True})
    assert "Non ci sono" in list_action({})


def test_export_one_note_and_category_to_unique_files(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr("actions.export_note_to_file.os.path.expanduser", lambda _path: str(desktop))
    first = notes.add_note("Latte", "Spesa")
    notes.add_note("Pane", "Spesa")
    notes.add_note("Privato", "Lavoro")
    assert "Ho staccato la nota" in export_note_to_file({"note_id": first["id"]})
    files = list(desktop.glob("*.txt"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "Latte" in content and "Pane" not in content and "Privato" not in content
    assert "Desktop" in export_note_to_file({"category": "spesa"})
    files = list(desktop.glob("*.txt"))
    assert len(files) == 2
    contents = [file.read_text(encoding="utf-8") for file in files]
    assert any("Latte" in item and "Pane" in item and "Privato" not in item for item in contents)
    with pytest.raises(ValueError):
        export_note_to_file({})
    assert "Non ho trovato" in export_note_to_file({"note_id": "inesistente"})


def test_export_reports_missing_desktop(monkeypatch, tmp_path):
    note = notes.add_note("Test")
    monkeypatch.setattr("actions.export_note_to_file.os.path.expanduser", lambda _path: str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError, match="Desktop"):
        export_note_to_file({"note_id": note["id"]})


@pytest.mark.parametrize(("phrase", "expected"), [
    ("prendi appunto che devo comprare il latte", {"save_note"}),
    ("salva nota", {"save_note"}),
    ("segna che devo bere", {"save_note"}),
    ("mostrami i miei appunti", {"list_notes"}),
    ("leggi le note", {"list_notes"}),
    ("stacca l'appunto", {"export_note_to_file", "list_notes"}),
    ("esporta la nota", {"export_note_to_file", "list_notes"}),
    ("cancella la nota", {"delete_note", "list_notes"}),
])
def test_router_selects_notes_actions(phrase, expected):
    declarations = [{"name": name} for name in (
        "save_note", "list_notes", "export_note_to_file", "delete_note",
        "quick_notes", "clipboard_manager",
    )]
    actual = ToolRouter().select_for_request(phrase, declarations)
    assert {item["name"] for item in actual} == expected


def test_discovery_and_destructive_confirmation(monkeypatch):
    import main

    registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _message: None)
    assert {"save_note", "list_notes", "export_note_to_file", "delete_note"} <= registry.names()
    note = notes.add_note("Latte")
    live = object.__new__(main.JarvisLive)
    live._action_registry = registry
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "cancella la nota"
    live._asst_name = "Jarvis"
    live.ui = SimpleNamespace(set_state=lambda *_: None, write_log=lambda *_: None, muted=False)
    live.speak = lambda *_args: None
    monkeypatch.setattr(main, "require_policy_file", lambda: None)

    async def execute():
        call = SimpleNamespace(id="1", name="delete_note", args={"note_id": note["id"], "confirmed": True})
        pending = await live._execute_tool(call)
        assert pending.response["result"] == "Ask the user for explicit confirmation"
        assert notes.list_notes()
        live._last_user_text = "confermo"
        result = await live._execute_tool(call)
        assert "cancellato" in result.response["result"]

    asyncio.run(execute())
    assert not notes.list_notes()
