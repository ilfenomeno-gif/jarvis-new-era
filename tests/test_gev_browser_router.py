from threading import Event, Lock
from types import SimpleNamespace

from core.gev_browser_router import classify_browser_command


def test_geographic_navigation_is_not_a_browser_command():
    command = classify_browser_command("Vai a Roma")

    assert command is None


def test_search_command_opens_google_results():
    command = classify_browser_command("Cerca meteo a Milano")

    assert command is not None
    assert command.action == "search"
    assert command.url.endswith("q=meteo+a+Milano")


def test_video_command_is_distinct_from_gemini_chat():
    command = classify_browser_command("Metti il video Daft Punk")

    assert command is not None
    assert command.action == "play_video"
    assert command.query == "Daft Punk"
    assert command.url.startswith("https://www.youtube.com/results?search_query=")


def test_explicit_supported_sites_can_be_opened():
    command = classify_browser_command("Apri YouTube")

    assert command is not None
    assert command.url == "https://www.youtube.com"


def test_conversational_text_is_not_mistaken_for_browser_command():
    assert classify_browser_command("Mi racconti la storia di Roma?") is None
    assert classify_browser_command("vai a") is None
    assert classify_browser_command("apri sito-esempio.invalid") is None


def test_history_request_does_not_open_or_route_to_gev(monkeypatch):
    import asyncio
    import main

    gev_calls = []
    live = main.JarvisLive.__new__(main.JarvisLive)
    live._loop = SimpleNamespace(is_running=lambda: True)
    live.ui = SimpleNamespace(write_log=lambda _message: None)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live._plugin_registry = SimpleNamespace(
        run=lambda *args, **kwargs: gev_calls.append((args, kwargs))
    )
    monkeypatch.setattr(
        main.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, _loop: asyncio.run(coroutine),
    )

    assert live._schedule_geo_route("Raccontami la storia di Roma") is False
    assert gev_calls == []


def test_jarvis_routes_direct_navigation_to_gev_not_chrome(monkeypatch):
    import asyncio

    from main import JarvisLive

    completed = Event()
    gev_calls = []
    chat_messages = []
    ui = SimpleNamespace(
        send_to_gev=lambda message: gev_calls.append(message),
        wait_for_gev=lambda _timeout: True,
        write_log=lambda message: gev_calls.append(message),
    )

    def push_chat(role, text):
        chat_messages.append((role, text))
        if role == "assistant":
            completed.set()

    live = object.__new__(JarvisLive)
    live.ui = ui
    live._asst_name = "JARVIS"
    live.session = None
    live._loop = SimpleNamespace(is_running=lambda: True)
    live._hud = SimpleNamespace(push_chat=push_chat)
    live._try_handle_fables_text = lambda _text: False
    live._try_handle_copilot_handoff = lambda _text: False
    live._plugin_registry = SimpleNamespace(
        run=lambda name, parameters, **kwargs: (
            gev_calls.append((name, parameters, kwargs))
            or "Mappa GEV centrata su Roma"
        )
    )
    live._browser_automation = SimpleNamespace(
        start=lambda: (_ for _ in ()).throw(
            AssertionError("A geographic command must not launch Chrome")
        )
    )

    def schedule(coroutine, _loop):
        from threading import Thread

        def run():
            try:
                asyncio.run(coroutine)
            finally:
                completed.set()

        Thread(target=run, daemon=True).start()
        return None

    monkeypatch.setattr("main.asyncio.run_coroutine_threadsafe", schedule)
    monkeypatch.setattr(
        "main.asyncio.get_running_loop",
        lambda: (_ for _ in ()).throw(RuntimeError("no running loop")),
    )

    live._on_text_command("Vai a Roma")
    assert completed.wait(1)

    gev_dispatch = next(call for call in gev_calls if isinstance(call, tuple))
    assert gev_dispatch[0] == "gev"
    assert gev_dispatch[1]["action"] == "open_with_context"
    assert gev_dispatch[1]["location"] == "Roma"
    assert gev_dispatch[2]["player"] is ui
    assert chat_messages[0] == ("user", "Vai a Roma")
    assert ("assistant", "Mappa GEV centrata su Roma") in chat_messages
    assert "GEV: Mappa GEV centrata su Roma" in gev_calls


def test_explicit_browser_search_opens_default_chrome_without_live_session(
    monkeypatch,
):
    import main

    from main import JarvisLive

    completed = Event()
    browser_calls = []
    chat_messages = []
    ui = SimpleNamespace(
        write_log=lambda _message: None,
    )

    def push_chat(role, text):
        chat_messages.append((role, text))
        if role == "assistant":
            completed.set()

    live = object.__new__(JarvisLive)
    live.ui = ui
    live._asst_name = "JARVIS"
    live.session = None
    live._loop = None
    live._hud = SimpleNamespace(push_chat=push_chat)
    live._try_handle_fables_text = lambda _text: False
    live._try_handle_copilot_handoff = lambda _text: False
    monkeypatch.setattr(
        main,
        "open_chrome_url",
        lambda url: browser_calls.append(("open", url)),
    )

    live._on_text_command("Cerca meteo a Milano")

    assert completed.wait(1)
    assert browser_calls[0][0] == "open"
    assert "google.com/search" in browser_calls[0][1]
    assert chat_messages[-1][0] == "assistant"


def test_jarvis_reports_unavailable_live_connection_in_gev_chat():
    from main import JarvisLive

    chat_messages = []
    log_messages = []
    live = object.__new__(JarvisLive)
    live.ui = SimpleNamespace(write_log=log_messages.append)
    live._hud = SimpleNamespace(
        push_chat=lambda role, text: chat_messages.append((role, text))
    )
    live._loop = None
    live._try_handle_fables_text = lambda _text: False
    live._try_handle_copilot_handoff = lambda _text: False

    live._on_text_command("Ciao Jarvis")

    assert chat_messages == [
        ("user", "Ciao Jarvis"),
        (
            "system",
            "JARVIS non è connesso: attendi che la connessione sia pronta "
            "e riprova.",
        ),
    ]
    assert "non è connesso" in log_messages[-1]


def test_jarvis_lists_new_gev_commands():
    from main import JarvisLive

    messages = []
    live = object.__new__(JarvisLive)
    live._hud = SimpleNamespace(
        push_chat=lambda role, text: messages.append((role, text))
    )

    assert live._handle_gev_command("comandi GEV") is True
    assert "tour Europa" in messages[0][1]
    assert "zoom avanti" in messages[0][1]
    assert "Chrome a schermo intero" in messages[0][1]


def test_jarvis_europe_tour_visits_every_country_without_geocoding():
    from core.gev_commands import EUROPEAN_COUNTRIES
    from main import JarvisLive

    class NotCancelled:
        def is_set(self):
            return False

        def wait(self, _seconds):
            return False

    sent = []
    statuses = []
    live = object.__new__(JarvisLive)
    live._gev_tour_cancel = NotCancelled()
    live._gev_tour_lock = Lock()
    live._gev_tour_active = True
    live.ui = SimpleNamespace(
        send_to_gev=sent.append,
        wait_for_gev=lambda _timeout: True,
        write_log=lambda _message: None,
    )
    live._hud = SimpleNamespace(
        push_chat=lambda role, text: statuses.append((role, text))
    )

    live._run_gev_country_tour()

    assert sent[0] == {"action": "open_tab"}
    assert len(sent) == len(EUROPEAN_COUNTRIES) + 1
    assert [message["params"]["lat"] for message in sent[1:]] == [
        lat for _country, lat, _lon in EUROPEAN_COUNTRIES
    ]
    assert len([message for role, message in statuses if role == "system"]) == 50
    assert statuses[-1] == ("assistant", "Tour europeo completato.")
    assert live._gev_tour_active is False


def test_jarvis_gev_zoom_opens_map_then_sends_zoom():
    from main import JarvisLive

    sent = []
    live = object.__new__(JarvisLive)
    live.ui = SimpleNamespace(
        send_to_gev=sent.append,
        wait_for_gev=lambda _timeout: True,
    )

    live._run_gev_zoom("in")

    assert sent == [
        {"action": "open_tab"},
        {"action": "camera_zoom", "params": {"level": "in"}},
    ]
