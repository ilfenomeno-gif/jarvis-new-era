"""Filters for third-party noise and sensitive diagnostic data."""
from __future__ import annotations

import logging
import os
import re
import sys

from core.logging_config import RedactSensitiveFilter

EXTERNAL_NAMES = ("PyQt5", "PyQt6", "Qt", "uvicorn", "asyncio", "urllib3",
                  "httpx", "sounddevice")
_SECRET = re.compile(r"(?i)(\bJARVIS_[A-Z0-9_]*_SECRET\s*=\s*)([^\s,;]+)")
_qt_handlers = {}


def is_external(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in EXTERNAL_NAMES)


def install_qt_logging() -> None:
    """Route Qt messages through logging when a Qt binding is already loaded."""
    for module_name in ("PyQt5.QtCore", "PyQt6.QtCore"):
        qt = sys.modules.get(module_name)
        if qt is None or module_name in _qt_handlers:
            continue

        def handler(message_type, context, message):
            name = getattr(message_type, "name", str(message_type))
            level = {"QtDebugMsg": logging.DEBUG, "0": logging.DEBUG,
                     "QtInfoMsg": logging.INFO, "4": logging.INFO,
                     "QtWarningMsg": logging.WARNING, "1": logging.WARNING,
                     "QtCriticalMsg": logging.ERROR, "2": logging.ERROR,
                     "QtFatalMsg": logging.CRITICAL, "3": logging.CRITICAL}.get(name, logging.WARNING)
            logging.getLogger("Qt").log(level, "%s", message)

        qt.qInstallMessageHandler(handler)
        _qt_handlers[module_name] = handler


class ExternalNoiseFilter(logging.Filter):
    def __init__(self, verbose: bool | None = None):
        super().__init__()
        self.verbose = os.environ.get("JARVIS_LOG_VERBOSE") == "1" if verbose is None else verbose

    def filter(self, record: logging.LogRecord) -> bool:
        if not is_external(record.name):
            return True
        if not self.verbose:
            return False
        if not getattr(record, "_external_prefixed", False):
            record.msg = "[EXTERNAL] " + record.getMessage()
            record.args = ()
            record._external_prefixed = True
        return True


class SensitiveDataFilter(RedactSensitiveFilter):
    @classmethod
    def _redact(cls, text: str) -> str:
        return super()._redact(_SECRET.sub(r"\1[REDACTED]", text))

    def filter(self, record: logging.LogRecord) -> bool:
        super().filter(record)
        for field in ("context", "impact", "action"):
            if hasattr(record, field):
                setattr(record, field, self._redact_value(getattr(record, field)))
        return True

    def _redact_value(self, value):
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if re.search(r"(?i)(token|password|secret|api[_-]?key|audio|pcm|image)", str(key))
                else self._redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._redact_value(item) for item in value]
        return self._redact(value) if isinstance(value, str) else value
