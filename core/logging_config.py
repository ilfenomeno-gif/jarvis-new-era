"""Environment-driven logging configuration for the desktop runtime."""
from __future__ import annotations

import logging
import os
import re
import traceback

_REDACTED = "[REDACTED]"
_HEADER_VALUE = re.compile(
    r"(?i)(\b(?:authorization|x-api-key|api-key|bearer|cookie|set-cookie)\b\s*[:=]\s*)"
    r"[^,\r\n;}]+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_SENSITIVE_VALUE = re.compile(
    r"""(?i)(["']?(?:audio|pcm|image|token|api[_-]?key|password|secret)["']?\s*[:=]\s*)"""
    r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^,\r\n}\]]+)"""
)
_LONG_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{201,}(?![A-Za-z0-9+/=_-])")
_SENSITIVE_FIELD_NAMES = {"audio", "pcm", "image", "token", "apikey", "password", "secret"}


class RedactSensitiveFilter(logging.Filter):
    """Redact credentials and encoded payloads before a handler emits a record."""

    @staticmethod
    def _redact(text: str) -> str:
        text = _HEADER_VALUE.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
        text = _BEARER_TOKEN.sub(lambda match: f"{match.group().split()[0]} {_REDACTED}", text)
        text = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
        return _LONG_BASE64.sub(_REDACTED, text)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{''.join(traceback.format_exception(*record.exc_info))}"
            record.exc_info = None
            record.exc_text = None
        record.msg = self._redact(message)
        record.args = ()
        if isinstance(record.stack_info, str):
            record.stack_info = self._redact(record.stack_info)

        for field, value in tuple(record.__dict__.items()):
            if field in {"msg", "args", "exc_info", "exc_text", "stack_info"}:
                continue
            normalized_field = field.lower().replace("_", "").replace("-", "")
            if normalized_field in _SENSITIVE_FIELD_NAMES:
                record.__dict__[field] = _REDACTED
            elif isinstance(value, str):
                record.__dict__[field] = self._redact(value)
        return True


def install_redaction_filter(handler: logging.Handler) -> None:
    if not any(isinstance(item, RedactSensitiveFilter) for item in handler.filters):
        handler.addFilter(RedactSensitiveFilter())


def _install_on_configured_handlers() -> None:
    loggers = [logging.getLogger()]
    loggers.extend(
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in loggers:
        for handler in logger.handlers:
            install_redaction_filter(handler)


def configure_logging(level: str | None = None) -> int:
    configured = (level or os.environ.get("JARVIS_LOG_LEVEL", "INFO")).upper()
    resolved = logging.getLevelName(configured)
    if not isinstance(resolved, int):
        raise ValueError(f"Invalid JARVIS_LOG_LEVEL: {configured!r}")

    logging.basicConfig(
        level=resolved,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s "
        "%(threadName)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger().setLevel(resolved)
    _install_on_configured_handlers()
    return resolved
