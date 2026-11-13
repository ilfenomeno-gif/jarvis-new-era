from actions._clipboard_actions import list_clipboard_history

TOOL = {"name": "list_clipboard_history", "description": "Mostra soltanto i metadati della cronologia appunti.",
        "risk_class": "read", "parameters": {"type": "OBJECT", "properties": {}}, "handler": list_clipboard_history}
