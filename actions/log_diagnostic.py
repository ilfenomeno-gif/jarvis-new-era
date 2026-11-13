"""On-demand local diagnostic report."""
from datetime import datetime

from core.log_diagnostic import LogDiagnostic
from core.log_reporter import LOG_DIR


def diagnostic_report(parameters: dict) -> str:
    report = LogDiagnostic().generate_report(parameters.get("period_minutes", 15))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"diagnostic_report_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    path.write_text(report, encoding="utf-8")
    return f"{report}\nSalvato in: {path}"


TOOL = {
    "name": "diagnostic_report",
    "description": "Genera il report diagnostico locale per richieste su errori o check-up del sistema.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {
        "period_minutes": {"type": "INTEGER", "description": "Periodo in minuti, default 15."},
    }},
    "handler": diagnostic_report,
}
