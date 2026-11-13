"""Arrange eligible windows using a grid, cascade, or left-right layout."""
from actions._multi_monitor_support import call_monitor, normalize_parameters
from core.multi_monitor import arrange_windows


def run(parameters=None, **_context):
    params = normalize_parameters(parameters)
    return call_monitor(
        lambda _monitor, **kwargs: arrange_windows(**kwargs),
        layout=params.get("layout"),
        monitor_index=params.get("monitor_index"),
    )


TOOL = {
    "name": "arrange_windows",
    "description": "Arrange eligible windows on one display as grid, cascade, or left-right. Window titles and process details are never returned.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "layout": {"type": "STRING", "enum": ["grid", "cascade", "left-right"]},
            "monitor_index": {"type": "INTEGER", "description": "Optional zero-based physical display index; defaults to active display."},
        },
        "required": ["layout"],
    },
    "risk_class": "write",
    "handler": run,
}
