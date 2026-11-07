"""Remove legacy output overlays and connect terminal bridge handlers."""

from __future__ import annotations

from core import actions_bridge
from core.widget_registry import registry
from core.widgets_terminal_computer import register_widget_types

_installed_ui = None


def install(ui) -> None:
    remove_widget = getattr(ui, "remove_widget", None)
    if callable(remove_widget):
        remove_widget("terminal")
        remove_widget("computer_use")
    global _installed_ui
    if _installed_ui is ui:
        return
    register_widget_types(registry)

    def clear_terminal():
        actions_bridge.push_event("terminal", {"event": "clear"})

    def kill_terminal():
        from actions.terminal_exec import kill_active

        killed = kill_active()
        actions_bridge.push_event(
            "terminal",
            {
                "event": "output" if killed else "ok",
                "stderr": "" if killed else "No active terminal command.",
                "status": "ok",
            },
        )

    def open_terminal_cwd():
        from actions.terminal_open_ext import run

        return run({"cwd": actions_bridge.get_terminal_cwd()})

    actions_bridge.register_handler("terminal", "clear", clear_terminal)
    actions_bridge.register_handler("terminal", "kill", kill_terminal)
    actions_bridge.register_handler("terminal", "open_cwd", open_terminal_cwd)
    _installed_ui = ui
