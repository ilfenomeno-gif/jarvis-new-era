import json
import logging
import re

from core.log_formatter import DiagnosticFormatter, JSONFormatter


def test_diagnostic_format_and_mapping():
    record = logging.LogRecord("core.network_security", logging.WARNING, __file__, 1,
                               "Failure %s", ("netsh",), None)
    record.context = {"error": "PermissionError"}
    record.impact = "offline"
    record.action = "retry"
    record.throttled_count = 3
    result = DiagnosticFormatter().format(record)
    assert re.match(r"\[\d\d:\d\d:\d\d\.\d{3}\] \[WARNING\] \[symbiosis.network\]", result)
    assert "Failure netsh (throttled: 3)" in result
    assert "├─ context:" in result and "└─ action:" in result


def test_json_metadata():
    record = logging.LogRecord("core.other", logging.ERROR, __file__, 1, "failed", (), None)
    record.component = "ai.vision"
    record.context = {"source": "camera"}
    result = json.loads(JSONFormatter("test-session").format(record))
    assert result["severity"] == "ERROR"
    assert result["component"] == "ai.vision"
    assert result["context"] == {"source": "camera"}
    assert result["session_id"] == "test-session"
    assert result["pid"] and result["thread"] and result["timestamp"]
