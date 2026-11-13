"""Voice action for optional GPU and VRAM metrics."""
from actions._system_pulse_action_helpers import read_metrics


def check_gpu(parameters: dict) -> str:
    return read_metrics((
        "gpu_percent", "gpu_memory_percent", "gpu_memory_used_bytes",
        "gpu_memory_total_bytes",
    ))


TOOL = {
    "name": "check_gpu",
    "description": "Reports GPU utilization and VRAM when supported; otherwise values are null.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_gpu,
}
