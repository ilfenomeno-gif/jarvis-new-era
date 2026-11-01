"""Small, optional visual effects for the JARVIS Qt interface."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QLinearGradient
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget


def start_pulsing_glow(
    label: QLabel, color: str, reduced_motion: bool = False
) -> QPropertyAnimation | None:
    if reduced_motion:
        return None

    effect = QGraphicsDropShadowEffect(label)
    effect.setColor(QColor(color))
    effect.setOffset(0, 0)
    effect.setBlurRadius(6)
    label.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"blurRadius", label)
    animation.setDuration(2400)
    animation.setStartValue(6.0)
    animation.setKeyValueAt(0.5, 18.0)
    animation.setEndValue(6.0)
    animation.setLoopCount(-1)
    animation.start()
    return animation


class ScanlineOverlay(QWidget):
    def __init__(
        self,
        parent: QWidget,
        color: str,
        reduced_motion: bool = False,
        interval_ms: int = 50,
    ):
        super().__init__(parent)
        self._color = QColor(color)
        self._offset = 0.0
        self._reduced_motion = reduced_motion
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._advance)
        if not reduced_motion:
            self._timer.start()
            self.show()
            self.raise_()
        else:
            self.hide()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(watched, event)

    def _advance(self) -> None:
        height = max(1, self.height())
        self._offset = (self._offset + 3.0) % (height + 24.0)
        self.update()

    def paintEvent(self, _event) -> None:
        if self._reduced_motion:
            return
        painter = QPainter(self)
        if not painter.isActive():
            return
        gradient = QLinearGradient(0, 0, self.width(), 0)
        color = QColor(self._color)
        color.setAlpha(28)
        gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 0))
        gradient.setColorAt(0.5, color)
        gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))

        band_height = 18.0
        y = self._offset - band_height
        path = QPainterPath()
        path.moveTo(0, y + band_height)
        path.lineTo(self.width(), y)
        path.lineTo(self.width(), y + band_height)
        path.lineTo(0, y + band_height * 2)
        path.closeSubpath()
        painter.fillPath(path, gradient)

    def stop(self) -> None:
        self._timer.stop()
