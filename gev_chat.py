"""JARVIS command chat for the God’s Eye View workspace."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QTextCursor, QTextDocument, QTextDocumentFragment
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class GevJarvisChat(QWidget):
    """Command chat connected to JARVIS and the visible GEV workspace."""

    commandSubmitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QWidget { background: #00060a; color: #b8f7ff; }"
            "QTextEdit, QLineEdit {"
            " background: #010d14; color: #d8f8ff;"
            " border: 1px solid #0d3347; padding: 7px;"
            "}"
            "QPushButton {"
            " background: #010f18; color: #00d4ff;"
            " border: 1px solid #0d3347; padding: 6px 12px;"
            "}"
            "QPushButton:hover { border-color: #00d4ff; }"
        )
        self._stream_cursor = None
        self._stream_text = ""
        self._last_streamed_response = ""

        layout = QVBoxLayout(self)
        title = QLabel("JARVIS · GOD'S EYE VIEW")
        title.setStyleSheet("color: #00d4ff; font-weight: bold;")
        layout.addWidget(title)
        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setPlaceholderText(
            "Scrivi a JARVIS per controllare God’s Eye View."
        )
        layout.addWidget(self._transcript, stretch=1)

        controls = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Comando per JARVIS…")
        self._input.returnPressed.connect(self._send)
        controls.addWidget(self._input, stretch=1)
        self._send_button = QPushButton("INVIA")
        self._send_button.clicked.connect(self._send)
        controls.addWidget(self._send_button)
        layout.addLayout(controls)

    def _send(self) -> None:
        command = self._input.text().strip()
        if command:
            self._input.clear()
            self.commandSubmitted.emit(command)

    def add_message(self, role: str, text: str) -> None:
        if role == "stream":
            phase, _, chunk = text.partition("\n")
            if phase == "start":
                self._append_message("JARVIS", "")
                self._stream_text = ""
                self._stream_cursor = self._transcript.textCursor()
                self._stream_cursor.movePosition(
                    self._stream_cursor.MoveOperation.End
                )
                self._stream_cursor.setKeepPositionOnInsert(True)
            elif phase == "append" and self._stream_cursor is not None:
                self._stream_text += chunk
                cursor = self._transcript.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.setPosition(self._stream_cursor.position(), QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                cursor.insertFragment(QTextDocumentFragment.fromMarkdown(
                    self._stream_text,
                    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
                    | QTextDocument.MarkdownFeature.MarkdownNoHTML,
                ))
                self._transcript.setTextCursor(cursor)
            elif phase == "end":
                self._last_streamed_response = self._stream_text.strip()
                self._stream_cursor = None
            return
        if text.strip():
            if role == "assistant" and text.strip() == self._last_streamed_response:
                self._last_streamed_response = ""
                return
            speaker = {
                "assistant": "JARVIS",
                "system": "SISTEMA",
            }.get(role, "TU")
            self._append_message(speaker, text.strip())

    def _append_message(self, speaker: str, text: str) -> None:
        cursor = self._transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._transcript.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(f"{speaker}: ")
        if text:
            cursor.insertFragment(QTextDocumentFragment.fromMarkdown(
                text,
                QTextDocument.MarkdownFeature.MarkdownDialectGitHub
                | QTextDocument.MarkdownFeature.MarkdownNoHTML,
            ))
        self._transcript.setTextCursor(cursor)
        self._transcript.ensureCursorVisible()
