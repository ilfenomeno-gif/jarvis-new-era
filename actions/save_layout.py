"""Save a local, privacy-preserving window layout."""
from actions._multi_monitor_support import call_monitor, normalize_parameters
from core.multi_monitor import save_layout


def run(parameters=None, **_context):
    params = normalize_parameters(parameters)
    return call_monitor(
        lambda _monitor, **kwargs: save_layout(**kwargs),
        layout_name=params.get("layout_name", "default"),
    )


TOOL = {
    "name": "save_layout",
    "description": "Save eligible window positions locally under a name. Window titles are stored only as one-way hashes and never returned.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "layout_name": {"type": "STRING", "description": "Local layout name; it is not included in the result."},
        },
    },
    "risk_class": "write",
    "handler": run,
}
