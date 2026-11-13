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


def setup_logging(level: str | None = None, verbose: bool = False) -> int:
    """Select the diagnostic configuration or the unmodified legacy setup."""
    if os.environ.get("JARVIS_LOG_LEGACY") == "1" or os.environ.get("JARVIS_LOG_DIAGNOSTIC", "1") != "1":
        return configure_logging(level)
    configured = (level or os.environ.get("JARVIS_LOG_LEVEL", "INFO")).upper()
    resolved = logging.getLevelName(configured)
    if not isinstance(resolved, int):
        raise ValueError(f"Invalid log level: {configured!r}")
    setup_diagnostic_logging(verbose=verbose, level=resolved)
    return resolved


class _ThrottleFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from core.log_throttler import LogThrottler

        if record.name == "system.throttler" or record.levelno < 25:
            return True
        if not hasattr(record, "_jarvis_allowed"):
            context = getattr(record, "context", None)
            detail = ""
            if isinstance(context, dict):
                detail = " ".join(str(context[name]) for name in ("error", "source") if name in context)
            key = f"{record.levelname}|{getattr(record, 'component', record.name)}: {record.getMessage()}"
            if detail:
                key += f" ({detail})"
            record._jarvis_allowed = LogThrottler().should_log(key, record.levelname)
        return record._jarvis_allowed


class _ExternalOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from core.log_filters import is_external

        return is_external(record.name)


def setup_diagnostic_logging(verbose: bool = False, *, level: int = logging.INFO) -> None:
    from logging.handlers import RotatingFileHandler
    from pathlib import Path
    import sys

    from core.log_filters import ExternalNoiseFilter, SensitiveDataFilter
    from core.log_formatter import DiagnosticFormatter, JSONFormatter, NOTICE

    verbose = verbose or os.environ.get("JARVIS_LOG_VERBOSE") == "1"
    logs = Path(__file__).resolve().parent.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_jarvis_diagnostic", False):
            root.removeHandler(handler)
            handler.close()

    console = logging.StreamHandler(sys.stderr)
    app = RotatingFileHandler(logs / "jarvis.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    diagnostics = logging.FileHandler(logs / "jarvis.diagnostics.log", encoding="utf-8")
    jsonl = RotatingFileHandler(logs / "jarvis.session.jsonl", maxBytes=50 * 1024 * 1024, backupCount=3, encoding="utf-8")
    external = RotatingFileHandler(logs / "jarvis.external.log", maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
    for handler, threshold, formatter in (
        (console, logging.INFO if verbose else NOTICE, DiagnosticFormatter()),
        (app, logging.INFO, DiagnosticFormatter()),
        (diagnostics, logging.ERROR, DiagnosticFormatter()),
        (jsonl, logging.INFO, JSONFormatter()),
    ):
        handler.setLevel(threshold)
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        handler.addFilter(ExternalNoiseFilter(verbose))
        handler.addFilter(_ThrottleFilter())
        handler._jarvis_diagnostic = True
        root.addHandler(handler)
    external.setLevel(logging.INFO)
    external.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    external.addFilter(SensitiveDataFilter())
    external.addFilter(_ExternalOnlyFilter())
    external._jarvis_diagnostic = True
    root.addHandler(external)
    root.setLevel(level)
    _install_on_configured_handlers()
