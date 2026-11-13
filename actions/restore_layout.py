"""Restore a locally saved, privacy-preserving window layout."""
from actions._multi_monitor_support import call_monitor, normalize_parameters
from core.multi_monitor import restore_layout


def run(parameters=None, **_context):
    params = normalize_parameters(parameters)
    return call_monitor(
        lambda _monitor, **kwargs: restore_layout(**kwargs),
        layout_name=params.get("layout_name", "default"),
    )


TOOL = {
    "name": "restore_layout",
    "description": "Restore eligible window positions from a local saved layout. Window titles and process details are never returned.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "layout_name": {"type": "STRING", "description": "Saved local layout name."},
        },
    },
    "risk_class": "write",
    "handler": run,
}
