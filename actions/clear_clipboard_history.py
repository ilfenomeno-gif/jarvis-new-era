from actions._clipboard_actions import clear_clipboard_history

TOOL = {"name": "clear_clipboard_history", "description": "Cancella definitivamente la cronologia degli appunti.",
        "risk_class": "destructive", "parameters": {"type": "OBJECT", "properties": {}}, "handler": clear_clipboard_history}
