"""Swap Jarvis and the foreground window without sharing window titles."""
from actions._multi_monitor_support import call_monitor, normalize_parameters
from core.multi_monitor import swap_active_window


def run(parameters=None, **_context):
    params = normalize_parameters(parameters)
    return call_monitor(lambda _monitor, **kwargs: swap_active_window(**kwargs),
                        layout=params.get("layout", "swap"))


TOOL = {
    "name": "swap_active_window",
    "description": (
        "Scambia le posizioni della finestra Jarvis e della finestra attiva, oppure "
        "affiancale con Jarvis a sinistra o a destra, senza acquisire titoli."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "layout": {"type": "STRING", "enum": ["swap", "jarvis_left", "jarvis_right"]},
        },
    },
    "risk_class": "write",
    "handler": run,
}
