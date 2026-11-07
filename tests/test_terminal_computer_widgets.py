import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from core.widgets_terminal_computer import TerminalWidget

_APP = None

def _application():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_terminal_widget_hides_controls_and_status_but_keeps_output():
    _application()
    widget = TerminalWidget({
        "payload": {
            "event": "output",
            "command": "echo hello",
            "stdout": "hello",
            "cwd": "C:\\work",
            "status": "ok",
        }
    })

    assert widget.findChildren(QPushButton) == []
    assert widget._scrollback.toPlainText() == "$ echo hello\nhello"
    assert widget._cwd.text() == "C:\\work"
    assert all(
        label.text().upper() not in {"OK", "IDLE"}
        for label in widget.findChildren(QLabel)
    )
