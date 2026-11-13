import json

import pytest

from core.clipboard_intelligence import ClipboardIntelligence, classify


def test_capture_search_restore_and_metadata(tmp_path):
    writes = []
    path = tmp_path / "history.json"
    history = ClipboardIntelligence(path=path, writer=writes.append)
    history.capture("https://example.com/private")
    history.capture("def f(): pass")
    assert history.search("example")[0]["type"] == "url"
    assert history.get_last()["type"] == "code"
    history.restore(1)
    assert writes == ["https://example.com/private"]
    assert "private" not in json.dumps(history.metadata())
    assert ClipboardIntelligence(path=path).get_last()["type"] == "code"
    history.clear()
    assert history.get_history() == []
    with pytest.raises(ValueError):
        history.restore(0)


@pytest.mark.parametrize(("value", "expected"), [
    ('{"a": 1}', "json"), ("x@example.com", "email"), (r"C:\a.txt", "path"),
    ("https://example.com", "url"), ("something", "text"),
])
def test_categories(value, expected):
    assert classify(value) == expected


def test_limits_thread_and_rejects_sensitive_data(tmp_path):
    history = ClipboardIntelligence(path=tmp_path / "history.json", reader=lambda: "")
    history.capture("a" * 11000)
    assert len(history.get_last()["content"].encode()) <= 10240
    history.start()
    assert history._thread.daemon
    history.stop()
    assert not history._thread.is_alive()


def test_model_actions_do_not_expose_clipboard_content(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    import actions._clipboard_actions as actions

    history = ClipboardIntelligence(path=tmp_path / "history.json", writer=lambda _: None)
    history.capture("https://example.com/secret-location")
    monkeypatch.setattr(actions, "get_symbiosis_hub", lambda **_: SimpleNamespace(clipboard=history))
    for result in (actions.get_last_clipboard({}), actions.list_clipboard_history({}),
                   actions.search_clipboard({"query": "secret-location"})):
        assert "secret-location" not in result
        assert "url" in result
    hotkeys = []
    monkeypatch.setitem(sys.modules, "pyautogui", SimpleNamespace(hotkey=lambda *args: hotkeys.append(args)))
    assert "Incolla" in actions.paste_last_clipboard({})
    assert hotkeys == [("ctrl", "v")]


def test_invalid_history_and_input(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        ClipboardIntelligence(path=path)
    path.write_text("[]", encoding="utf-8")
    history = ClipboardIntelligence(path=path, writer=lambda _: None)
    assert history.capture("") is False
    with pytest.raises(ValueError):
        history.get_history(-1)
    with pytest.raises(ValueError):
        history.search("")
    with pytest.raises(ValueError):
        history.restore(True)
    with pytest.raises(ValueError):
        ClipboardIntelligence(path=path, interval=0)


def test_duplicate_and_sensitive_detection(monkeypatch, tmp_path):
    import core.clipboard_intelligence as clipboard
    history = ClipboardIntelligence(path=tmp_path / "history.json")
    assert history.capture("hello")
    assert not history.capture("hello")
    monkeypatch.setattr(clipboard, "redact_sensitive", lambda value: "[redacted]" if value == "secret" else value)
    assert not history.capture("secret")
    assert [item["content"] for item in history.get_history()] == ["hello"]


def test_save_failure_preserves_existing_history(monkeypatch, tmp_path):
    history = ClipboardIntelligence(path=tmp_path / "history.json")
    history.capture("first")
    monkeypatch.setattr(history, "_save", lambda: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        history.capture("second")
    assert history.get_last()["content"] == "first"
    with pytest.raises(OSError):
        history.clear()
    assert history.get_last()["content"] == "first"


def test_sequence_monitor_reads_only_after_change(tmp_path):
    import threading
    reads = []
    seen = threading.Event()
    def reader():
        reads.append(True)
        seen.set()
        return "copied"
    history = ClipboardIntelligence(path=tmp_path / "history.json", reader=reader,
                                    sequence_reader=lambda: 1, interval=0.01)
    history.start()
    assert seen.wait(1)
    assert history._stop.wait(0.05) is False
    history.stop()
    assert len(reads) == 1
