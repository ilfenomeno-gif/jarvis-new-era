"""Private helpers shared by registered multi-monitor actions."""
import os

from core.multi_monitor import MultiMonitorError
from core.symbiosis_hub import get_symbiosis_hub


def call_monitor(operation, **parameters):
    try:
        hub = get_symbiosis_hub(start=False)
        if hub is None:
            if os.environ.get("JARVIS_SYMBIOSIS", "1") == "0":
                message = (
                    "Symbiosis is disabled (JARVIS_SYMBIOSIS=0); enable it to use monitor actions."
                )
            else:
                message = "The Symbiosis hub is not initialized; monitor actions require its active module."
            return {
                "ok": False,
                "error": message,
            }
        monitor = hub.get_module("monitor")
        if monitor is None:
            return {
                "ok": False,
                "error": (
                    "The monitor module is not active in Symbiosis; enable it in "
                    "JARVIS_SYMBIOSIS_MODULES."
                ),
            }
        return {"ok": True, **operation(monitor, **parameters)}
    except MultiMonitorError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "Multi-monitor operation failed."}


def snapshot(monitor):
    return monitor.snapshot()


def normalize_parameters(values):
    return values if isinstance(values, dict) else {}
