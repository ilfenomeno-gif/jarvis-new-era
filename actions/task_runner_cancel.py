from core import task_runner


def task_runner_cancel(parameters: dict, **_ignored) -> str:
    runner = task_runner.get_runner()
    return runner.cancel() if runner else "The TaskRunner is not available yet."


TOOL = {
    "name": "task_runner_cancel",
    "description": "Stops the active TaskRunner task; steps not yet run are skipped. Use when the user says stop or declines a paused step.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    "handler": task_runner_cancel,
}
