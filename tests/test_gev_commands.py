import pytest

from core.harness.policy import ApprovalPolicy
from core.gev_commands import EUROPEAN_COUNTRIES, classify_gev_command
from main import JarvisLive, TOOL_DECLARATIONS


def test_legacy_screen_process_is_not_declared_to_the_model():
    assert "screen_process" not in {
        declaration["name"] for declaration in TOOL_DECLARATIONS
    }


@pytest.mark.parametrize(
    "tool_name",
    ["capture_and_analyze_screen", "screen_process"],
)
def test_screen_vision_never_requires_harness_confirmation(monkeypatch, tool_name):
    class Registry:
        def has(self, name):
            return name == "capture_and_analyze_screen"

        def risk_class(self, _name):
            return "read"

        def risk_class_declared(self, _name):
            return True

    live = object.__new__(JarvisLive)
    live._action_registry = Registry()
    live._harness_runtime = type(
        "Runtime",
        (),
        {
            "approval_policy": ApprovalPolicy(
                {"default": {"read": "confirm", "write": "confirm", "destructive": "confirm"}}
            )
        },
    )()
    monkeypatch.setenv("JARVIS_HARNESS", "1")

    assert not live._action_requires_confirmation(tool_name, {})


def test_gev_commands_are_explicit_and_unambiguous():
    assert classify_gev_command("Apri God Eye View") == "open_gev"
    assert classify_gev_command("Apri God's Eye View") == "open_gev"
    assert classify_gev_command("Iris, apri GEV") == "open_gev"
    assert classify_gev_command("Apri la mappa") == "open_gev"
    assert classify_gev_command("Tour Europa") == "tour_start"
    assert classify_gev_command("tour eropa") == "tour_start"
    assert classify_gev_command("elenca tutti i paesi europei") == "list_countries"
    assert classify_gev_command("zoom avanti") == "zoom_in"
    assert classify_gev_command("riduci zoom mappa") == "zoom_out"
    assert classify_gev_command("zoom avanti su YouTube") == "chrome_zoom_in"
    assert classify_gev_command("zoom indietro su Chrome") == "chrome_zoom_out"
    assert classify_gev_command("reset zoom Chrome") == "chrome_zoom_reset"
    assert classify_gev_command("ingrandisci") == "chrome_zoom_in"
    assert classify_gev_command("zoom in") == "chrome_zoom_in"
    assert classify_gev_command("rimpicciolisci") == "chrome_zoom_out"
    assert classify_gev_command("zoom out") == "chrome_zoom_out"
    assert classify_gev_command("ripristina zoom") == "chrome_zoom_reset"
    assert classify_gev_command("amplifica la schermata") == "screen_analysis"
    assert classify_gev_command("cosa c'è sullo schermo?") == "screen_analysis"
    assert classify_gev_command("cosa vedi") == "screen_analysis"
    assert classify_gev_command("Analizza la finestra attiva") == "screen_analysis"
    assert classify_gev_command("leggi questa pagina") == "screen_analysis"
    assert classify_gev_command("usa Google Lens") == "screen_analysis"
    assert classify_gev_command("analizza questa immagine") == "screen_analysis"
    assert classify_gev_command("attiva la lente") == "screen_magnifier_on"
    assert classify_gev_command("disattiva lente") == "screen_magnifier_off"
    assert classify_gev_command("Chrome a schermo intero") == "chrome_expand"
    assert classify_gev_command("ripristina Chrome") == "chrome_restore"
    assert classify_gev_command("Mi racconti un tour d'Europa?") is None


def test_open_gev_command_shows_the_embedded_map_tab():
    sent = []
    messages = []
    live = object.__new__(JarvisLive)
    live.ui = type(
        "UI",
        (),
        {"send_to_gev": lambda _self, message: sent.append(message)},
    )()
    live._hud = type(
        "HUD",
        (),
        {"push_chat": lambda _self, role, message: messages.append((role, message))},
    )()

    assert live._handle_gev_command("Apri God's Eye View")
    assert sent == [{"action": "open_tab"}]
    assert messages == [("assistant", "Apro God's Eye View.")]


@pytest.mark.parametrize(
    "phrase",
    [
        "Cosa c'è sullo schermo?",
        "Usa Google Lens",
        "Analizza questa immagine",
        "Cosa vedi",
    ],
)
def test_screen_analysis_voice_command_runs_action_and_speaks(monkeypatch, phrase):
    import main

    calls = []
    messages = []
    spoken = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    class Registry:
        def run(self, name, parameters, ctx):
            calls.append((name, parameters, ctx))
            return "Sul display è visibile una pagina di notizie."

    live = object.__new__(JarvisLive)
    live._action_registry = Registry()
    live._asst_name = "Iris"
    live.ui = type(
        "UI",
        (),
        {"write_log": lambda _self, message: messages.append(("log", message))},
    )()
    live._hud = type(
        "HUD",
        (),
        {"push_chat": lambda _self, role, message: messages.append((role, message))},
    )()
    live._set_task_idle = lambda _idle: None
    live.speak = spoken.append
    live.session = object()
    live._loop = object()
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    assert live._handle_gev_command(phrase)
    assert len(calls) == 1
    assert calls[0][0:2] == ("capture_and_analyze_screen", {"question": phrase})
    assert callable(calls[0][2]["player"].write_log)
    assert ("assistant", "Sul display è visibile una pagina di notizie.") in messages
    assert len(spoken) == 1
    assert spoken[0].endswith("Sul display è visibile una pagina di notizie.")
    assert "non aggiungere" in spoken[0].lower()


def test_active_window_voice_command_selects_active_capture(monkeypatch):
    import main

    calls = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    live = object.__new__(JarvisLive)
    live._action_registry = type(
        "Registry", (), {
            "run": lambda _self, name, parameters, ctx: (
                calls.append((name, parameters)) or "Vedo il browser."
            )
        }
    )()
    live._asst_name = "Jarvis"
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda _idle: None
    live.session = None
    live._loop = None
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    assert live._handle_gev_command("Analizza la finestra attiva")
    assert calls == [("capture_and_analyze_screen", {
        "question": "Analizza la finestra attiva", "capture_mode": "active_window",
    })]


def test_text_command_runs_screen_analysis_without_confirmation(monkeypatch):
    import main

    calls = []
    messages = []
    spoken = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    class Registry:
        def run(self, name, parameters, ctx):
            calls.append(name)
            return "Vedo una finestra del browser."

    live = object.__new__(JarvisLive)
    live._action_registry = Registry()
    live._asst_name = "Iris"
    live.ui = type(
        "UI",
        (),
        {
            "write_log": lambda _self, message: messages.append(("log", message)),
        },
    )()
    live._hud = type(
        "HUD",
        (),
        {
            "push_chat": lambda _self, role, message: messages.append((role, message)),
        },
    )()
    live._set_task_idle = lambda _idle: None
    live._try_handle_fables_text = lambda _text: False
    live._try_handle_copilot_handoff = lambda _text: False
    live.speak = spoken.append
    live.session = object()
    live._loop = object()
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    live._process_text_command("Cosa vedi")

    assert calls == ["capture_and_analyze_screen"]
    assert len(spoken) == 1 and spoken[0].endswith("Vedo una finestra del browser.")
    assert all("conferma" not in message.lower() for _role, message in messages)


def test_screen_analysis_failure_always_releases_idle_state(monkeypatch):
    import main

    idle_states = []
    messages = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    class Registry:
        def run(self, _name, _parameters, ctx):
            assert callable(ctx["player"].write_log)
            raise RuntimeError("errore di test")

    live = object.__new__(JarvisLive)
    live._action_registry = Registry()
    live._asst_name = "Iris"
    live.ui = type(
        "UI",
        (),
        {"write_log": lambda _self, message: messages.append(("log", message))},
    )()
    live._hud = type(
        "HUD",
        (),
        {"push_chat": lambda _self, role, message: messages.append((role, message))},
    )()
    live._set_task_idle = idle_states.append
    live.session = None
    live._loop = None
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    assert live._handle_gev_command("Cosa vedi")
    assert idle_states == [False, True]
    assert any("errore di test" in message for _role, message in messages)


def test_screen_analysis_speaks_slow_server_message(monkeypatch):
    import main
    from actions.capture_and_analyze_screen import VISION_SLOW_MESSAGE

    spoken = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    class Registry:
        def run(self, _name, _parameters, ctx):
            return f"Tool 'capture_and_analyze_screen' failed: {VISION_SLOW_MESSAGE}"

    live = object.__new__(JarvisLive)
    live._action_registry = Registry()
    live._asst_name = "Iris"
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda _idle: None
    live.session = object()
    live._loop = object()
    live.speak = spoken.append
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    assert live._handle_gev_command("Cosa vedi")
    assert len(spoken) == 1 and spoken[0].endswith(VISION_SLOW_MESSAGE)


def test_country_tour_has_unique_valid_stops():
    names = [name for name, _lat, _lon in EUROPEAN_COUNTRIES]

    assert len(names) == 50
    assert len(set(names)) == len(names)
    assert all(-90 <= lat <= 90 and -180 <= lon <= 180 for _, lat, lon in EUROPEAN_COUNTRIES)
