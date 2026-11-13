from types import SimpleNamespace

import pytest

import diagnostics
from actions import app_launcher


def test_diagnostics_accepts_created_process_despite_focus_warning(monkeypatch):
    monkeypatch.setattr(
        app_launcher, "app_launcher",
        lambda _parameters: (
            "Ho aperto Notepad, ma non sono riuscito a portarlo in primo piano. "
            "Controlla la barra delle applicazioni."
        ),
    )
    process = SimpleNamespace(
        pid=123, info={"name": "notepad.exe", "create_time": 101.0}
    )
    monkeypatch.setattr(diagnostics.time, "time", lambda: 100.0)
    monkeypatch.setattr(diagnostics.psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(diagnostics.psutil, "pid_exists", lambda pid: pid == 123)

    assert diagnostics.Diagnostics.launcher() == "Notepad avviato; PID 123 verificato."


def test_diagnostics_does_not_count_existing_process(monkeypatch):
    monkeypatch.setattr(app_launcher, "app_launcher", lambda _parameters: "Launch requested for notepad.")
    process = SimpleNamespace(
        pid=123, info={"name": "notepad.exe", "create_time": 99.0}
    )
    monkeypatch.setattr(diagnostics.time, "time", lambda: 100.0)
    monotonic_values = iter([0.0, 0.0, 6.0])
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(diagnostics.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(diagnostics.psutil, "process_iter", lambda _attrs: [process])
    with pytest.raises(diagnostics.DiagnosticFailure, match="Nessun nuovo processo"):
        diagnostics.Diagnostics.launcher()


def test_diagnostics_reports_launch_refusal(monkeypatch):
    monkeypatch.setattr(app_launcher, "app_launcher", lambda _parameters: "Refused to launch.")
    with pytest.raises(diagnostics.DiagnosticFailure, match="Refused to launch"):
        diagnostics.Diagnostics.launcher()
