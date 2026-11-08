from __future__ import annotations

import logging
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.gemini_chat import GeminiChatResult
from gemini_chat_window import GeminiChatPanel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_text_input_keypress_completes_quickly_and_uses_mock_provider(
    app: QApplication,
    monkeypatch,
    caplog,
):
    provider_called = threading.Event()
    received_prompts = []

    def fake_ask(prompt, **_kwargs):
        received_prompts.append(prompt)
        provider_called.set()
        return GeminiChatResult(answer="Risposta mock", thought_summaries=())

    monkeypatch.setattr(
        "gemini_chat_window.ask_gemini_with_thoughts",
        fake_ask,
    )
    caplog.set_level(logging.INFO, logger="jarvis.ui.input")
    panel = GeminiChatPanel()
    panel.show()
    app.processEvents()
    panel._input.setFocus()

    try:
        QTest.keyClicks(panel._input, "ciao")
        started = time.perf_counter()
        QTest.keyClick(panel._input, Qt.Key.Key_Return)
        elapsed_ms = (time.perf_counter() - started) * 1000

        assert elapsed_ms < 1000
        assert provider_called.wait(1)
        assert received_prompts == ["ciao"]
        assert "INPUT_START source=gemini_chat" in caplog.text
        assert "INPUT_HANDLER_OK source=gemini_chat" in caplog.text
        assert "INPUT_HANDLER_FAIL source=gemini_chat" not in caplog.text
    finally:
        panel.close()
