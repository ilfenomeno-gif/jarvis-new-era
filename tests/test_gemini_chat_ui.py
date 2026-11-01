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

from PyQt6.QtWidgets import QApplication

from core.gemini_chat import GeminiChatResult
from gemini_chat_window import GeminiChatPanel, GeminiChatWindow
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
    ):
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
        "Gemini: Risposta di test"
    )
    assert not panel._thoughts_button.isHidden()
    assert panel._thoughts_button.text() == "THOUGHT SUMMARY (1)"
    assert panel._thoughts_view.isHidden()
    panel._thoughts_button.click()
    assert not panel._thoughts_view.isHidden()
    assert panel._thoughts_view.toPlainText() == "Sintesi di test"
    panel.close()


def test_standalone_fallback_wraps_the_reusable_panel(app):
    window = GeminiChatWindow()
    assert isinstance(window.panel, GeminiChatPanel)
    window.close()


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
