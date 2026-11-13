"""List physical monitor geometry, resolution, and effective DPI."""
from actions._multi_monitor_support import call_monitor


def run(parameters=None, **_context):
    return call_monitor(lambda monitor: {"monitors": monitor.snapshot()["monitors"]})


TOOL = {
    "name": "list_monitors",
    "description": "List display indices, physical coordinates, resolution, and DPI; no window or user data is returned.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "risk_class": "read",
    "handler": run,
}
