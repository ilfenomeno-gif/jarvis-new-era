"""Generate a diagnostic report from locally retained log records."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from core.log_reporter import LOG_DIR, hardware_status, module_status, recent_records
from core.log_throttler import LogThrottler


class LogDiagnostic:
    def __init__(self, log_dir: Path = LOG_DIR):
        self.log_dir = log_dir

    def generate_report(self, period_minutes: int = 15) -> str:
        if isinstance(period_minutes, bool) or not isinstance(period_minutes, int) or period_minutes <= 0:
            raise ValueError("period_minutes deve essere un intero positivo")
        records = recent_records(period_minutes, self.log_dir)
        errors = Counter(item.get("component", "unknown") for item in records
                         if item.get("severity") in {"ERROR", "CRITICAL"})
        repeated = Counter()
        for item in records:
            if item.get("component") == "system.throttler" and item.get("throttled_count"):
                message = item.get("message", "")
                key = message.split(": ", 1)[-1]
                if key.startswith("WARNING|") or key.startswith("WARN|"):
                    repeated[key.split("|", 1)[1]] += item["throttled_count"]
        for key, count in LogThrottler().counts().items():
            if key.startswith("WARNING|") or key.startswith("WARN|"):
                repeated[key.split("|", 1)[1]] += count
        modules, hardware = module_status(), hardware_status()
        lines = [f"📊 REPORT DIAGNOSTICO — ultimi {period_minutes} minuti",
                 "────────────────────────────────────────",
                 f"🔴 ERRORI ({sum(errors.values())}):"]
        lines.extend(f"   {key}: {count}" for key, count in errors.most_common())
        if not errors:
            lines.append("   (nessuno)")
        lines.append(f"🟡 WARNING RICORRENTI ({len(repeated)}):")
        lines.extend(f"   {key}: {count} occorrenze soppresse" for key, count in repeated.most_common())
        if not repeated:
            lines.append("   (nessuno)")
        if modules["available"]:
            lines.append(f"🟢 MODULI ATTIVI ({len(modules['active'])}/{modules['total']}):")
            lines.append("   " + (", ".join("symbiosis." + name for name in modules["active"]) or "(nessuno)"))
        else:
            lines.append("🟢 MODULI ATTIVI: stato non disponibile")
        lines.append(f"💻 HARDWARE: CPU {hardware['cpu']}% | RAM {hardware['ram']}% | Disk {hardware['disk']}%")
        lines.append("────────────────────────────────────────")
        if any("PermissionError" in key and "network" in key for key in repeated):
            lines.append("Azione suggerita: verificare i permessi di rete; valutare l'esecuzione come amministratore.")
        else:
            lines.append("Azione suggerita: verificare i dettagli degli errori prima di intervenire.")
        return "\n".join(lines)
