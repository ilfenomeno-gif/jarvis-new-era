"""A separate, text-only Gemini chat window for the JARVIS desktop UI."""

from __future__ import annotations

import queue
import threading

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.gemini_chat import ask_gemini_with_thoughts
from core.prompt_router import PromptRouter


class GeminiChatPanel(QWidget):
    closeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QWidget { background: #00060a; color: #8ffcff; }"
            "QPlainTextEdit, QLineEdit {"
            " background: #010d14; color: #d8f8ff;"
            " border: 1px solid #0d3347; padding: 7px;"
            "}"
            "QPushButton {"
            " background: #010f18; color: #00d4ff;"
            " border: 1px solid #0d3347; padding: 6px 12px;"
            "}"
            "QPushButton:hover { border-color: #00d4ff; }"
        )
        self._history: list[dict] = []
        self._responses: queue.Queue[tuple[str, str, str, tuple[str, ...]]] = queue.Queue()
        self._prompt_router = PromptRouter()

        layout = QVBoxLayout(self)
        self._transcript = QPlainTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setPlaceholderText(
            "Gemini text chat. Your conversation stays in this window."
        )
        layout.addWidget(self._transcript, stretch=1)

        self._thoughts_button = QPushButton("THOUGHT SUMMARY")
        self._thoughts_button.setCheckable(True)
        self._thoughts_button.setChecked(False)
        self._thoughts_button.setVisible(False)
        self._thoughts_button.toggled.connect(self._thoughts_view_visibility)
        layout.addWidget(self._thoughts_button)
        self._thoughts_view = QPlainTextEdit()
        self._thoughts_view.setReadOnly(True)
        self._thoughts_view.setMaximumHeight(140)
        self._thoughts_view.setPlaceholderText(
            "Provider-supplied thought summaries appear here."
        )
        self._thoughts_view.setVisible(False)
        layout.addWidget(self._thoughts_view)

        self._status = QLabel("Ready")
        layout.addWidget(self._status)

        controls = QHBoxLayout()
        self._close_button = QPushButton("BACK TO JARVIS")
        self._close_button.clicked.connect(self.closeRequested.emit)
        controls.addWidget(self._close_button)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Write a message…")
        self._input.returnPressed.connect(self._send)
        controls.addWidget(self._input, stretch=1)
        self._send_button = QPushButton("SEND")
        self._send_button.clicked.connect(self._send)
        controls.addWidget(self._send_button)
        layout.addLayout(controls)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_responses)
        self._poll_timer.start(100)

    def _send(self) -> None:
        prompt = self._input.text().strip()
        if not prompt or not self._send_button.isEnabled():
            return

        self._input.clear()
        self._transcript.appendPlainText(f"You: {prompt}")
        self._thoughts_button.setChecked(False)
        self._thoughts_button.setVisible(False)
        self._thoughts_view.clear()
        self._thoughts_view.setVisible(False)
        self._send_button.setEnabled(False)
        self._input.setEnabled(False)
        self._status.setText("Gemini is responding…")

        def request() -> None:
            try:
                result = ask_gemini_with_thoughts(
                    prompt,
                    history=self._history,
                    timeout_ms=60_000,
                    thinking_level=self._prompt_router.thinking_level_for(prompt),
                    include_thoughts=True,
                )
                self._responses.put(
                    ("ok", prompt, result.answer, result.thought_summaries)
                )
            except Exception as exc:
                self._responses.put(
                    ("error", prompt, f"{type(exc).__name__}: {exc}", ())
                )

        try:
            threading.Thread(
                target=request,
                daemon=True,
                name="jarvis-gemini-chat",
            ).start()
        except RuntimeError as exc:
            self._send_button.setEnabled(True)
            self._input.setEnabled(True)
            self._status.setText(f"Could not start Gemini request: {exc}")

    def _poll_responses(self) -> None:
        try:
            status, prompt, result, thoughts = self._responses.get_nowait()
        except queue.Empty:
            return

        self._send_button.setEnabled(True)
        self._input.setEnabled(True)
        self._input.setFocus()
        if status == "ok":
            self._transcript.appendPlainText(f"Gemini: {result}\n")
            if thoughts:
                self._thoughts_button.setText(
                    f"THOUGHT SUMMARY ({len(thoughts)})"
                )
                self._thoughts_button.setVisible(True)
                self._thoughts_view.setPlainText("\n\n".join(thoughts))
            self._history.extend(
                [
                    {"role": "user", "parts": [{"text": prompt}]},
                    {"role": "model", "parts": [{"text": result}]},
                ]
            )
            self._status.setText("Ready")
        else:
            self._transcript.appendPlainText(f"Gemini error: {result}\n")
            self._status.setText("Request failed; the conversation can continue.")

    def _thoughts_view_visibility(self, visible: bool) -> None:
        self._thoughts_view.setVisible(visible)


class GeminiChatWindow(QDialog):
    """Standalone fallback that presents the same reusable chat panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gemini Chat — JARVIS")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        self.panel = GeminiChatPanel(self)
        self.panel.closeRequested.connect(self.close)
        layout.addWidget(self.panel)
