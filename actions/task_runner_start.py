import json

from core import task_runner

NOT_READY = "The TaskRunner is not available yet."


def task_runner_start(parameters: dict, **_ignored) -> str:
    runner = task_runner.get_runner()
    if runner is None:
        return NOT_READY
    params = parameters or {}
    steps = params.get("steps")
    if isinstance(steps, str) and steps.strip():
        try:
            steps = json.loads(steps)
        except ValueError:
            return "Invalid plan: steps is not valid JSON."
    return runner.start(str(params.get("objective") or "").strip(), steps or None)


TOOL = {
    "name": "task_runner_start",
    "description": (
        "Plans and runs a multi-step request on its own, e.g. 'disassemble the PC and explain the CPU' "
        "(load_model, explode_model, highlight_part) or 'search a Ferrari, make it 3D, show it realistic'. "
        "For one explicit action, such as creating one requested 3D model, call that action directly instead; "
        "it is tracked as a single task without a second confirmation. Multi-step plans pause write steps "
        "for confirmation. "
        "Read-only steps (viewer_3d: highlight, rotate, explode) run back to back without asking. "
        "A write/destructive step (search_3d_model, generate_3d_model) pauses: ask the user, then call "
        "task_runner_confirm. Pass 'steps' to choose the tools yourself, otherwise known objectives are planned "
        "automatically. While it runs, keep talking about the parts being highlighted."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "objective": {"type": "STRING", "description": "The user's request in one sentence."},
            "steps": {
                "type": "STRING",
                "description": ("Optional plan as a JSON array of {\"tool\": name, \"args\": {...}, "
                                "\"fallback\": {tool, args}} objects, run in order. 'fallback' runs if the step fails."),
            },
        },
        "required": ["objective"],
    },
    "handler": task_runner_start,
}
