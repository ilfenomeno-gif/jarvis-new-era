"""Model-facing clipboard operations return metadata, never clipboard contents."""
from core.symbiosis_hub import get_symbiosis_hub


def _clipboard():
    hub = get_symbiosis_hub(start=False)
    if hub is None or hub.clipboard is None:
        raise RuntimeError("Monitoraggio clipboard non disponibile.")
    return hub.clipboard


def get_last_clipboard(parameters):
    values = _clipboard().metadata(1)
    return str(values[0]) if values else "Cronologia clipboard vuota."


def list_clipboard_history(parameters):
    return str(_clipboard().metadata(10))


def search_clipboard(parameters):
    query = parameters.get("query", "")
    items = _clipboard().search(query)
    return str([{"type": item["type"], "length": len(item["content"]),
                 "timestamp": item["timestamp"]} for item in items])


def paste_last_clipboard(parameters):
    _clipboard().restore(0)
    import pyautogui
    pyautogui.hotkey("ctrl", "v")
    return "Ultimo elemento ripristinato e comando Incolla inviato alla finestra attiva."


def clear_clipboard_history(parameters):
    _clipboard().clear()
    return "Cronologia clipboard cancellata."
