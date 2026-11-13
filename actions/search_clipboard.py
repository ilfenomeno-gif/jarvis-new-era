from actions._clipboard_actions import search_clipboard

TOOL = {"name": "search_clipboard", "description": "Cerca negli appunti localmente e restituisce solo metadati.",
        "risk_class": "read", "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}}, "required": ["query"]}, "handler": search_clipboard}
