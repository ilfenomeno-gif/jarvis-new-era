import json
from datetime import UTC, datetime

import pytest

from core import log_diagnostic
from core.tool_router import ToolRouter


def test_report_includes_errors_and_summaries(tmp_path, monkeypatch):
    now = datetime.now(UTC).isoformat()
    entries = [
        {"timestamp": now, "component": "ai.vision", "severity": "ERROR"},
        {"timestamp": now, "component": "system.throttler", "severity": "NOTICE",
         "message": "Ripetuto 12 volte in 1.0 min: WARNING|context.window: fallita", "throttled_count": 12},
    ]
    (tmp_path / "jarvis.session.jsonl").write_text(
        "\n".join(map(json.dumps, entries)), encoding="utf-8"
    )
    monkeypatch.setattr(log_diagnostic, "module_status",
                        lambda: {"available": True, "active": ["pulse"], "total": 2})
    monkeypatch.setattr(log_diagnostic, "hardware_status",
                        lambda: {"cpu": 12, "ram": 45, "disk": 60})
    report = log_diagnostic.LogDiagnostic(tmp_path).generate_report()
    assert "ai.vision: 1" in report and "context.window: fallita: 12" in report
    assert "1/2" in report and "CPU 12%" in report
    with pytest.raises(ValueError):
        log_diagnostic.LogDiagnostic(tmp_path).generate_report(0)


@pytest.mark.parametrize("phrase", [
    "Jarvis, dammi il report del sistema", "Jarvis, che errori ci sono?",
    "Jarvis, fai un check-up",
])
def test_voice_router(phrase):
    selected = ToolRouter().select_for_request(phrase, [{"name": "diagnostic_report"}])
    assert [item["name"] for item in selected] == ["diagnostic_report"]


def test_action_saves_report(tmp_path, monkeypatch):
    from actions import log_diagnostic as action

    monkeypatch.setattr(action, "LOG_DIR", tmp_path)
    monkeypatch.setattr(action, "LogDiagnostic", lambda: type(
        "Diagnostic", (), {"generate_report": lambda self, period: f"report {period}"}
    )())
    result = action.diagnostic_report({"period_minutes": 10})
    files = list(tmp_path.glob("diagnostic_report_*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "report 10"
    assert "report 10" in result
