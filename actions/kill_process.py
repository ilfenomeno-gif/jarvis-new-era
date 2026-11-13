"""Request human-confirmed termination of a selected process."""

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def kill_process(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    reference = parameters.get("reference", "")
    if not isinstance(reference, str) or process_core._get_reference(reference) is None:
        return "A process reference from list_processes is required."
    return process_core.kill_process(reference)


TOOL = {
    "name": "kill_process",
    "description": (
        "Request termination of a process by its opaque list reference. The user's "
        "HUD confirmation is mandatory; confirmed/require_confirmation parameters "
        "cannot bypass it. Protected and stale process references are refused."
    ),
    "risk_class": "destructive",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "reference": {"type": "STRING", "description": "Reference from list_processes."},
        },
        "required": ["reference"],
    },
    "handler": kill_process,
}
