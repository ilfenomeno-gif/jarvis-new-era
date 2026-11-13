import logging
import sys
from types import SimpleNamespace

from core.log_filters import ExternalNoiseFilter, SensitiveDataFilter, install_qt_logging


def record(name, message, **extra):
    item = logging.LogRecord(name, logging.WARNING, __file__, 1, message, (), None)
    item.__dict__.update(extra)
    return item


def test_external_filter():
    item = record("urllib3.connection", "noise")
    assert not ExternalNoiseFilter(False).filter(item)
    assert ExternalNoiseFilter(True).filter(item)
    assert item.getMessage() == "[EXTERNAL] noise"
    assert ExternalNoiseFilter(True).filter(item)
    assert item.getMessage() == "[EXTERNAL] noise"
    assert ExternalNoiseFilter(False).filter(record("my.urllib3", "ok"))


def test_redacts_nested_metadata_and_message():
    item = record("app", "JARVIS_FOO_SECRET=abc token=xyz",
                  context={"api_key": "hidden", "nested": ["password=hunter2"]})
    assert SensitiveDataFilter().filter(item)
    assert "abc" not in item.getMessage() and "xyz" not in item.getMessage()
    assert item.context == {"api_key": "[REDACTED]", "nested": ["password=[REDACTED]"]}


def test_qt_messages_are_routed(monkeypatch, caplog):
    from core import log_filters

    installed = []
    monkeypatch.setitem(sys.modules, "PyQt5.QtCore", SimpleNamespace(qInstallMessageHandler=installed.append))
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", SimpleNamespace(qInstallMessageHandler=installed.append))
    monkeypatch.setattr(log_filters, "_qt_handlers", {})
    install_qt_logging()
    with caplog.at_level(logging.WARNING, logger="Qt"):
        installed[0](SimpleNamespace(name="QtWarningMsg"), None, "qt warning")
    assert "qt warning" in caplog.text
