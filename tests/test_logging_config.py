import json
import logging

from core import logging_config
from core.log_filters import SensitiveDataFilter


def test_diagnostic_handlers_and_routing(monkeypatch, tmp_path):
    monkeypatch.setattr(logging_config, "__file__", str(tmp_path / "core" / "logging_config.py"))
    root = logging.getLogger()
    previous_level = root.level
    try:
        logging_config.setup_diagnostic_logging()
        handlers = [h for h in root.handlers if getattr(h, "_jarvis_diagnostic", False)]
        assert len(handlers) == 5
        assert all(any(isinstance(f, SensitiveDataFilter) for f in h.filters) for h in handlers)
        logging.getLogger("core.example").error("password=secret")
        logging.getLogger("uvicorn.error").error("external noise")
        for handler in handlers:
            handler.flush()
        logs = tmp_path / "logs"
        app = (logs / "jarvis.log").read_text(encoding="utf-8")
        assert "secret" not in app and "[REDACTED]" in app
        assert "external noise" not in app
        assert "external noise" in (logs / "jarvis.external.log").read_text(encoding="utf-8")
        assert "REDACTED" in (logs / "jarvis.diagnostics.log").read_text(encoding="utf-8")
        assert json.loads((logs / "jarvis.session.jsonl").read_text(encoding="utf-8"))["severity"] == "ERROR"
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_jarvis_diagnostic", False):
                root.removeHandler(handler)
                handler.close()
        root.setLevel(previous_level)


def test_legacy_flag(monkeypatch):
    monkeypatch.setenv("JARVIS_LOG_LEGACY", "1")
    calls = []
    monkeypatch.setattr(logging_config, "configure_logging", lambda level: calls.append(level) or 20)
    assert logging_config.setup_logging("WARNING") == 20
    assert calls == ["WARNING"]
    assert logging_config.setup_logging() == 20
    assert calls == ["WARNING", None]


def test_suppression_shared_across_handlers_and_summary(monkeypatch, tmp_path):
    from core.log_throttler import LogThrottler

    monkeypatch.setattr(logging_config, "__file__", str(tmp_path / "core" / "logging_config.py"))
    root = logging.getLogger()
    previous_level = root.level
    try:
        logging_config.setup_diagnostic_logging()
        logger = logging.getLogger("test.throttle")
        for _ in range(11):
            logger.warning("repeat unique warning", extra={"component": "context.window"})
        summary = LogThrottler().flush_summary()
        assert summary["WARNING|context.window: repeat unique warning"] == 10
        for handler in root.handlers:
            handler.flush()
        items = [json.loads(line) for line in (tmp_path / "logs" / "jarvis.session.jsonl").read_text(encoding="utf-8").splitlines()]
        assert sum(item["component"] == "context.window" for item in items) == 1
        assert any(item.get("throttled_count") == 10 for item in items)
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_jarvis_diagnostic", False):
                root.removeHandler(handler)
                handler.close()
        root.setLevel(previous_level)
