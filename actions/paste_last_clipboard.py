from actions._clipboard_actions import paste_last_clipboard

TOOL = {"name": "paste_last_clipboard", "description": "Ripristina e incolla l'ultimo elemento degli appunti nella finestra attiva.",
        "risk_class": "write", "parameters": {"type": "OBJECT", "properties": {}}, "handler": paste_last_clipboard}
