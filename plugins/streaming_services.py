"""Open Netflix and Prime Video in JARVIS's integrated browser when available."""

from __future__ import annotations

from urllib.parse import urlencode

from actions.browser_control import browser_control

_SERVICES = {
    "netflix": {
        "home": "https://www.netflix.com/",
        "search": "https://www.netflix.com/search",
    },
    "prime_video": {
        "home": "https://www.primevideo.com/",
        "search": "https://www.primevideo.com/search/ref=atv_nb_sr",
    },
}

PLUGIN = {
    "name": "streaming_services",
    "description": (
        "Opens Netflix or Prime Video in JARVIS's integrated browser, with an "
        "external-browser fallback. Can open a home page or search for a title. "
        "For play, explains the Qt WebEngine DRM limitation and asks before "
        "opening the result in Chrome. It never collects passwords or buys/rents."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "service": {
                "type": "STRING",
                "description": "Streaming service to open.",
                "enum": ["netflix", "prime_video"],
            },
            "action": {
                "type": "STRING",
                "description": (
                    "open home, search for a title, or play (asks before opening "
                    "the search in Chrome because internal DRM playback is unsupported)."
                ),
                "enum": ["open", "search", "play"],
            },
            "query": {
                "type": "STRING",
                "description": "Film or series title for search/play.",
            },
            "browser": {
                "type": "STRING",
                "description": "Optional browser: chrome, edge, firefox, opera, brave, or vivaldi.",
                "enum": ["chrome", "edge", "firefox", "opera", "operagx", "brave", "vivaldi"],
            },
        },
        "required": ["service", "action"],
    },
}


def _target_url(service: str, action: str, query: str = "") -> str:
    service_key = service.strip().casefold().replace("-", "_").replace(" ", "_")
    action_key = action.strip().casefold()
    if service_key not in _SERVICES:
        raise ValueError("Service must be netflix or prime_video.")
    if action_key not in {"open", "search", "play"}:
        raise ValueError("Action must be open, search, or play.")
    if action_key == "open":
        return _SERVICES[service_key]["home"]
    if not query.strip():
        raise ValueError("A title is required for search and play.")
    params = {"q": query.strip()} if service_key == "netflix" else {
        "phrase": query.strip()
    }
    return f"{_SERVICES[service_key]['search']}?{urlencode(params)}"


def run(parameters: dict, player=None) -> str:
    service = str(parameters.get("service", ""))
    action = str(parameters.get("action", ""))
    action_key = action.casefold()
    url = _target_url(service, action, str(parameters.get("query", "")))
    browser = parameters.get("browser")
    open_in_webview = getattr(player, "open_url_in_webview", None)
    embedded = callable(open_in_webview)

    if embedded:
        try:
            open_in_webview(url)
            result = f"Opened internally in JARVIS: {url}"
        except Exception as exc:
            embedded = False
            _log(
                player,
                f"Streaming: browser interno non disponibile ({exc}); "
                "uso il browser esterno.",
            )

    if not embedded and action_key != "play":
        result = browser_control(
            parameters={
                "action": "go_to",
                "url": url,
                **({"browser": browser} if browser else {}),
            },
            player=player,
        )
        if not result.startswith("Opened"):
            return result

    if action_key != "play":
        return result

    confirm = getattr(player, "confirm_streaming_play_in_chrome", None)
    if not callable(confirm):
        _log(
            player,
            "Streaming: conferma DRM non disponibile; non avvio Chrome "
            "automaticamente.",
        )
        if embedded:
            return (
                f"{result} La riproduzione protetta (DRM) non è supportata "
                "nel pannello interno; non è stato aperto Chrome perché la "
                "conferma non è disponibile."
            )
        return (
            "Il browser interno non è disponibile e non è possibile chiedere "
            "conferma DRM; non è stato aperto alcun browser."
        )

    if not embedded:
        result = "Browser interno non disponibile; apertura esterna in attesa di conferma."

    try:
        confirmed = confirm(url)
    except Exception as exc:
        _log(player, f"Streaming: conferma per Chrome non riuscita: {exc}")
        return (
            f"{result} La riproduzione DRM non è supportata nel pannello "
            "interno; Chrome non è stato aperto perché la conferma è fallita."
        )
    if not confirmed:
        return (
            f"{result} Riproduzione protetta (DRM) non supportata nel pannello "
            "interno. Apertura esterna annullata."
        )

    chrome_result = browser_control(
        parameters={"action": "go_to", "url": url, "browser": "chrome"},
        player=player,
    )
    if not chrome_result.startswith("Opened"):
        return f"{result} Conferma ricevuta, ma Chrome non è stato aperto: {chrome_result}"
    return (
        f"{chrome_result} La riproduzione protetta (DRM) non è supportata nel "
        "pannello interno; selezioni il titolo e avvii la riproduzione in Chrome."
    )


def _log(player, message: str) -> None:
    write_log = getattr(player, "write_log", None)
    if callable(write_log):
        write_log(message)
