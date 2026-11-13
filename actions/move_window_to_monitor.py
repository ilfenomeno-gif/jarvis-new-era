"""Move one uniquely titled, eligible window to a display."""
from actions._multi_monitor_support import call_monitor, normalize_parameters
from core.multi_monitor import move_window_to_monitor


def run(parameters=None, **_context):
    params = normalize_parameters(parameters)
    return call_monitor(
        lambda _monitor, **kwargs: move_window_to_monitor(**kwargs),
        window_title=params.get("window_title"),
        monitor_index=params.get("monitor_index"),
    )


TOOL = {
    "name": "move_window_to_monitor",
    "description": "Move the unique window matching the supplied title to a display. The title is used only for selection and is never returned.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "window_title": {"type": "STRING", "description": "Exact visible window title to select; never returned in results."},
            "monitor_index": {"type": "INTEGER", "description": "Zero-based physical display index."},
        },
        "required": ["window_title", "monitor_index"],
    },
    "risk_class": "write",
    "handler": run,
}
