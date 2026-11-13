"""Tests for the embedded Gemini panel routing without network or Qt windows."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea

from core.gemini_chat import GeminiChatResult
from gemini_chat_window import GeminiChatPanel, GeminiChatWindow
from gev_chat import GevJarvisChat
from ui import JarvisUI, MainWindow


class _Stack:
    def __init__(self, current, widgets):
        self.current = current
        self.widgets = set(widgets)

    def currentWidget(self):
        return self.current

    def indexOf(self, widget):
        return 0 if widget in self.widgets else -1

    def setCurrentWidget(self, widget):
        self.current = widget


class _Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


def test_show_and_close_gemini_chat_restores_previous_page():
    hud = object()
    browser = object()
    panel = object()
    window = SimpleNamespace(
        _main_content_stack=_Stack(browser, [hud, browser, panel]),
        _gemini_chat_panel=panel,
        _gemini_chat_window=None,
        _gemini_previous_widget=None,
        _hud_cam_stack=hud,
        _log_sig=_Signal(),
    )

    MainWindow._show_gemini_chat(window)
    assert window._main_content_stack.currentWidget() is panel
    assert window._gemini_previous_widget is browser

    MainWindow._close_gemini_chat(window)
    assert window._main_content_stack.currentWidget() is browser
    assert window._gemini_previous_widget is None


def test_show_gemini_chat_uses_dialog_fallback_when_panel_missing(monkeypatch):
    class _FallbackWindow:
        def __init__(self, _parent):
            self.shown = False

        def show(self):
            self.shown = True

        def raise_(self):
            pass

        def activateWindow(self):
            pass

    monkeypatch.setattr("ui.GeminiChatWindow", _FallbackWindow)
    window = SimpleNamespace(
        _main_content_stack=_Stack(object(), []),
        _gemini_chat_panel=None,
        _gemini_chat_window=None,
        _gemini_previous_widget=None,
        _log_sig=_Signal(),
    )

    MainWindow._show_gemini_chat(window)

    assert window._gemini_chat_window.shown
    assert any("finestra separata" in item for item in window._log_sig.messages)


def test_gev_chat_toggle_resizes_map_and_focuses_input():
    class _Panel:
        def __init__(self):
            self.visible = False
            self.focused = False
            self._input = SimpleNamespace(setFocus=lambda: setattr(self, "focused", True))

        def setVisible(self, visible):
            self.visible = visible

    class _Splitter:
        def __init__(self):
            self.sizes = []

        def width(self):
            return 900

        def setSizes(self, sizes):
            self.sizes = sizes

    class _Toggle:
        def setChecked(self, _checked):
            pass

    panel = _Panel()
    splitter = _Splitter()
    window = SimpleNamespace(_gev_jarvis_chat=panel)

    MainWindow._set_gev_chat_visible(window, True, splitter, _Toggle())
    assert panel.visible and panel.focused
    assert splitter.sizes == [600, 300]

    MainWindow._set_gev_chat_visible(window, False, splitter, _Toggle())
    assert not panel.visible
    assert splitter.sizes == [900, 0]


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_chat_panel_sends_and_displays_mocked_gemini_reply(monkeypatch, app):
    requests = []

    def fake_ask_gemini(
        prompt,
        history=None,
        timeout_ms=30_000,
        thinking_level="high",
        include_thoughts=True,
        on_chunk=None,
    ):
        if on_chunk is not None:
            on_chunk("Risposta di test")
        requests.append(
            {
                "prompt": prompt,
                "history": list(history or []),
                "timeout_ms": timeout_ms,
                "thinking_level": thinking_level,
                "include_thoughts": include_thoughts,
            }
        )
        return GeminiChatResult(
            answer="Risposta di test",
            thought_summaries=("Sintesi di test",),
        )

    monkeypatch.setattr(
        "gemini_chat_window.ask_gemini_with_thoughts",
        fake_ask_gemini,
    )
    panel = GeminiChatPanel()
    panel._history.extend(
        [
            {"role": "user", "parts": [{"text": "Domanda precedente"}]},
            {"role": "model", "parts": [{"text": "Risposta precedente"}]},
        ]
    )
    panel._input.setText("Ciao Gemini")
    panel._send()

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and panel._send_button.isEnabled() is False:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert requests
    assert requests[0] == {
        "prompt": "Ciao Gemini",
        "history": [
            {"role": "user", "parts": [{"text": "Domanda precedente"}]},
            {"role": "model", "parts": [{"text": "Risposta precedente"}]},
        ],
        "timeout_ms": 60_000,
        "thinking_level": "low",
        "include_thoughts": True,
    }
    assert panel._transcript.toPlainText().strip().endswith(
        "Risposta di test"
    )
    assert "You:" not in panel._transcript.toPlainText()
    assert "Gemini:" not in panel._transcript.toPlainText()
    assert not panel._thoughts_button.isHidden()
    assert panel._thoughts_button.text() == "THOUGHT SUMMARY (1)"
    assert panel._thoughts_view.isHidden()
    panel._thoughts_button.click()
    assert not panel._thoughts_view.isHidden()
    assert panel._thoughts_view.toPlainText() == "Sintesi di test"
    panel.close()


def test_gemini_chat_renders_streamed_markdown_without_changing_previous_turns(app):
    panel = GeminiChatPanel()
    panel._transcript.setPlainText("Messaggio precedente")
    cursor = panel._transcript.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertBlock()
    panel._response_start = type(cursor)(cursor)
    panel._response_start.setKeepPositionOnInsert(True)
    panel._transcript.setTextCursor(cursor)
    panel._responses.put(("chunk", "domanda", "**Tit", ()))
    panel._responses.put(("chunk", "domanda", "olo**\n\n* primo", ()))
    panel._responses.put(("chunk", "domanda", "\n* secondo", ()))
    panel._responses.put(("ok", "domanda", "**Titolo**\n\n* primo\n* secondo", ()))
    panel._poll_responses()
    html = panel._transcript.toHtml()
    text = panel._transcript.toPlainText()
    assert "font-weight:700" in html
    assert html.count("<li") == 2
    assert text.count("Messaggio precedente") == 1
    assert text.count("Titolo") == 1
    assert "primo" in text and "secondo" in text
    panel.close()


def test_gemini_chat_renders_unstreamed_markdown_as_text_not_html(app):
    panel = GeminiChatPanel()
    panel._responses.put(("ok", "domanda", "**Risposta**\n\n- prima\n- <script>seconda</script>", ()))
    panel._poll_responses()
    html = panel._transcript.toHtml()
    assert html.count("<li") == 2
    assert "<script>" not in html
    assert "seconda" in panel._transcript.toPlainText()
    panel.close()


def test_standalone_fallback_wraps_the_reusable_panel(app):
    window = GeminiChatWindow()
    assert isinstance(window.panel, GeminiChatPanel)
    window.close()


def test_gev_jarvis_chat_submits_commands_and_displays_chat_events(app):
    chat = GevJarvisChat()
    commands = []
    chat.commandSubmitted.connect(commands.append)

    assert "#00060a" in chat.styleSheet()
    assert "#010d14" in chat.styleSheet()
    chat._input.setText("Vai a Roma")
    chat._send()
    chat.add_message("assistant", "Chrome sta mostrando Roma")
    chat.add_message("system", "JARVIS non è ancora connesso.")

    assert commands == ["Vai a Roma"]
    assert chat.findChild(QLabel).text() == "JARVIS · GOD'S EYE VIEW"
    assert "Chrome sta mostrando Roma" in chat._transcript.toPlainText()
    assert "SISTEMA: JARVIS non è ancora connesso." in chat._transcript.toPlainText()
    chat.close()


def test_memory_rows_use_dark_background_and_escape_stored_html(monkeypatch, app):
    from ui import MemoryOverlay

    monkeypatch.setattr(
        "memory.memory_manager.all_entries_for_ui",
        lambda: [{
            "key": "profile_<admin>",
            "value": "<script>ignored()</script>",
            "category": "profile",
            "updated": "today",
        }],
    )
    overlay = MemoryOverlay()

    scroll = overlay.findChild(QScrollArea)
    assert scroll is not None
    assert "#010d14" in scroll.styleSheet()
    labels = scroll.findChildren(QLabel)
    assert any("&lt;script&gt;" in label.text() for label in labels)
    overlay.close()


def test_streaming_confirmation_signal_runs_prompt_on_ui_thread(app):
    prompt_threads = []
    results = []

    class _Window(QObject):
        confirm_signal = pyqtSignal(str, object)

        def __init__(self):
            super().__init__()
            self.confirm_signal.connect(self._confirm)

        def _ask_open_streaming_in_chrome(self, _url):
            prompt_threads.append(QApplication.instance().thread())
            return True

        def _confirm(self, url, response):
            MainWindow._confirm_streaming_play_on_ui_thread(self, url, response)

    window = _Window()
    facade = SimpleNamespace(
        _win=window,
        write_log=lambda message: None,
    )
    window._streaming_play_confirm_sig = window.confirm_signal

    worker = threading.Thread(
        target=lambda: results.append(
            JarvisUI.confirm_streaming_play_in_chrome(
                facade, "https://www.netflix.com/search?q=test", timeout=2
            )
        )
    )
    worker.start()
    deadline = time.monotonic() + 2
    while worker.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    worker.join(timeout=0.1)
    app.processEvents()

    assert not worker.is_alive()
    assert results == [True]
    assert prompt_threads == [app.thread()]


@pytest.mark.parametrize(("choice", "expected"), [("accept", True), ("cancel", False)])
def test_streaming_confirmation_dialog_has_explicit_choices(
    monkeypatch, choice, expected
):
    dialogs = []

    class _ButtonRole:
        AcceptRole = 1
        RejectRole = 2

    class _Dialog:
        ButtonRole = _ButtonRole

        def __init__(self, _parent):
            self.buttons = []
            self.selected = None
            dialogs.append(self)

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setInformativeText(self, text):
            self.informative_text = text

        def addButton(self, label, _role):
            button = SimpleNamespace(label=label)
            self.buttons.append(button)
            if (choice == "accept" and label == "Apri in Chrome") or (
                choice == "cancel" and label == "Annulla"
            ):
                self.selected = button
            return button

        def setDefaultButton(self, button):
            self.default_button = button

        def setEscapeButton(self, button):
            self.escape_button = button

        def exec(self):
            pass

        def clickedButton(self):
            return self.selected

    monkeypatch.setattr("ui.QMessageBox", _Dialog)

    result = MainWindow._ask_open_streaming_in_chrome(SimpleNamespace(), "url")

    dialog = dialogs[0]
    assert result is expected
    assert [button.label for button in dialog.buttons] == [
        "Apri in Chrome",
        "Annulla",
    ]
    assert dialog.default_button.label == "Annulla"
    assert dialog.escape_button.label == "Annulla"
    assert "DRM" in dialog.text
