from actions._clipboard_actions import get_last_clipboard

TOOL = {"name": "get_last_clipboard", "description": "Mostra soltanto i metadati dell'ultimo elemento negli appunti.",
        "risk_class": "read", "parameters": {"type": "OBJECT", "properties": {}}, "handler": get_last_clipboard}
