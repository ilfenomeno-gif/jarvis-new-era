"""Stop queued Computer Use work and terminate a currently running terminal action."""

from core.actions_bridge import stop as stop_bridge


def run(parameters=None, **_context):
    from actions.terminal_exec import kill_active
    from core.computer_action_support import audit, emit
    from core.computer_use import trigger_emergency_stop

    stop_bridge()
    trigger_emergency_stop()
    terminal_killed = kill_active()
    emit("stopped", status="stopped", terminal_killed=terminal_killed)
    audit("computer_stop", "completed", f"terminal_killed={terminal_killed}")
    return {
        "ok": True,
        "status": "stopped",
        "terminal_killed": terminal_killed,
        "computer_use_requires_restart": True,
    }


TOOL = {
    "name": "computer_stop",
    "description": "Activate the Computer Use emergency stop without confirmation.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "risk_class": "destructive",
    "handler": run,
}
