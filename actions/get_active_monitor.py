"""Return geometry for the display containing the foreground window."""
from actions._multi_monitor_support import call_monitor


def run(parameters=None, **_context):
    return call_monitor(lambda monitor: {
        "active_monitor": monitor.snapshot()["active_monitor"],
    })


TOOL = {
    "name": "get_active_monitor",
    "description": "Get active display geometry, resolution, and DPI. Never returns window titles or process details.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "risk_class": "read",
    "handler": run,
}
