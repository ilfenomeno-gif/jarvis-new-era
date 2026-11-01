"""Open the local code-server instance in JARVIS's integrated browser."""

from __future__ import annotations

from actions.browser_control import browser_control


_CODE_SERVER_URL = "http://127.0.0.1:8080"

PLUGIN = {
    "name": "vscode_web",
    "description": (
        "Open the locally installed code-server editor in JARVIS's integrated "
        "browser. Use for requests such as 'open VS Code in the browser'. "
        "JARVIS does not install or start code-server."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Open the locally running code-server instance.",
                "enum": ["open"],
            },
        },
        "required": ["action"],
    },
}


def _log_fallback(player, reason: str) -> None:
    write_log = getattr(player, "write_log", None)
    if callable(write_log):
        try:
            write_log(
                "VS Code web: browser interno non disponibile "
                f"({reason}); uso il browser esterno."
            )
        except Exception:
            pass


def run(parameters: dict, player=None) -> str:
    action = str(parameters.get("action", "")).strip().casefold()
    if action != "open":
        return "Azione non valida per vscode_web. Usare action='open'."

    open_in_webview = getattr(player, "open_url_in_webview", None)
    if callable(open_in_webview):
        try:
            open_in_webview(_CODE_SERVER_URL)
            return f"code-server aperto nel browser interno di JARVIS: {_CODE_SERVER_URL}"
        except Exception as exc:
            _log_fallback(player, str(exc))
    else:
        _log_fallback(player, "metodo open_url_in_webview non disponibile")

    try:
        result = browser_control(
            parameters={"action": "go_to", "url": _CODE_SERVER_URL},
            player=player,
        )
    except Exception as exc:
        return f"Impossibile aprire code-server nel browser: {exc}"
    return str(result)


TOOL = {**PLUGIN, "handler": run}
