"""Request human-confirmed restart using a process's original argument vector."""

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def restart_process(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    reference = parameters.get("reference", "")
    if not isinstance(reference, str) or process_core._get_reference(reference) is None:
        return "A process reference from list_processes is required."
    return process_core.restart_process(reference)


TOOL = {
    "name": "restart_process",
    "description": (
        "Request a HUD-confirmed restart by opaque process reference. Revalidates "
        "PID identity and executable/arguments before stopping; relaunches the same "
        "argument vector without a shell. No model parameter can bypass confirmation."
    ),
    "risk_class": "destructive",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "reference": {"type": "STRING", "description": "Reference from list_processes."},
        },
        "required": ["reference"],
    },
    "handler": restart_process,
}
