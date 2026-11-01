from core import task_runner


def task_runner_confirm(parameters: dict, **_ignored) -> str:
    runner = task_runner.get_runner()
    return runner.confirm() if runner else "The TaskRunner is not available yet."


TOOL = {
    "name": "task_runner_confirm",
    "description": (
        "Resumes a TaskRunner task paused on a write/destructive step. Call it only after the user "
        "explicitly said yes; otherwise call task_runner_cancel."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    "handler": task_runner_confirm,
}
