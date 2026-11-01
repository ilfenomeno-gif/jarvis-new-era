from core import task_runner


def task_runner_status(parameters: dict, **_ignored) -> str:
    runner = task_runner.get_runner()
    return runner.status_text() if runner else "The TaskRunner is not available yet."


TOOL = {
    "name": "task_runner_status",
    "description": "Shows the active TaskRunner task: each step with its state and result, and whether it waits for the user's OK.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    "handler": task_runner_status,
}
