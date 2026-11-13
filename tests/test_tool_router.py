import ast
import asyncio
import json
from pathlib import Path

import pytest

from core.tool_router import ALWAYS, BASE, ToolRouter, connector_connection_id

ROOT = Path(__file__).resolve().parent.parent


def decl(name: str, size: int = 200) -> dict:
    return {"name": name, "description": "x" * size, "parameters": {"type": "OBJECT", "properties": {}}}


def names(selected) -> set[str]:
    return {d["name"] for d in selected}


SAMPLE = [decl(n) for n in (
    sorted(ALWAYS | BASE)
    + ["generate_3d_model", "viewer_3d", "weather_report", "reminder", "flight_finder", "file_controller",
       "gev", "gev_mcp_get_earthquakes", "gev_mcp_aircraft_in_area", "spotify_music_control", "brand_new_tool"]
)]


def test_vague_request_gets_always_and_base_only():
    out = names(ToolRouter().select("dimmi qualcosa di utile", SAMPLE))
    assert out >= ALWAYS | BASE
    assert "weather_report" not in out and "gev_mcp_get_earthquakes" not in out and "generate_3d_model" not in out


def test_app_launcher_is_available_for_application_requests():
    declarations = SAMPLE + [decl("app_launcher")]

    assert "app_launcher" in names(
        ToolRouter().select("apri il Blocco Note", declarations)
    )


def test_terminal_run_is_selected_only_for_explicit_terminal_requests():
    declarations = [decl("terminal_run"), decl("agent_loop"), decl("quick_notes")]
    router = ToolRouter()

    assert names(
        router.select_for_request("Esegui il comando echo hello", declarations)
    ) == {"terminal_run"}
    assert names(router.select("Esegui il comando echo hello", declarations)) >= {
        "terminal_run"
    }
    assert "agent_loop" not in names(
        router.select_for_request("Esegui il comando echo hello", declarations)
    )
    assert router.select_for_request("Dimmi una curiosità", declarations) == []


def test_computer_use_tools_are_selected_for_perception_and_input_requests():
    declarations = [
        decl("computer_perception"),
        decl("computer_read_screen"),
        decl("computer_input"),
    ]
    router = ToolRouter()

    assert {
        "computer_perception",
        "computer_read_screen",
    } <= names(
        router.select_for_request("Leggi il testo sullo schermo con OCR", declarations)
    )
    assert names(
        router.select_for_request("Clicca sul pulsante in Notepad", declarations)
    ) == {"computer_input"}
    assert router.select_for_request("Dimmi una curiosità", declarations) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Cosa c'è sullo schermo?",
        "Usa Google Lens",
        "Analizza questa immagine",
        "Cosa vedi",
        "Amplifica la schermata",
        "Leggi questa pagina",
    ],
)
def test_screen_analysis_requests_force_gemini_vision_tool(phrase):
    declarations = [
        decl("capture_and_analyze_screen"),
        decl("screen_process"),
        decl("accessibility_read_screen"),
        decl("computer_read_screen"),
        decl("web_search"),
    ]
    router = ToolRouter()

    assert names(router.select_for_request(phrase, declarations)) == {
        "capture_and_analyze_screen"
    }
    assert names(router.select(phrase, declarations)) == {
        "capture_and_analyze_screen"
    }
    assert "screen_process" not in names(router.select_for_request(phrase, declarations))


def test_explicit_local_ocr_request_keeps_local_ocr_tools():
    declarations = [
        decl("capture_and_analyze_screen"),
        decl("screen_process"),
        decl("accessibility_read_screen"),
        decl("computer_perception"),
        decl("computer_read_screen"),
    ]

    assert names(
        ToolRouter().select_for_request(
            "Leggi il testo sullo schermo con OCR locale",
            declarations,
        )
    ) == {
        "accessibility_read_screen",
        "computer_perception",
        "computer_read_screen",
    }


@pytest.mark.parametrize("phrase", [
    "Leggi questa pagina HTML e clicca il link",
    "Leggi questa pagina e clicca il link",
    "Controlla la CPU, leggi questa pagina e clicca il link",
])
def test_page_interaction_routes_to_browser_without_forcing_screen_analysis(phrase):
    declarations = [decl("browser_control"), decl("capture_and_analyze_screen"), decl("check_cpu")]
    router = ToolRouter()
    for selected in (router.select_for_request(phrase, declarations), router.select(phrase, declarations)):
        assert "browser_control" in names(selected)
        assert "capture_and_analyze_screen" not in names(selected)
    if "CPU" in phrase:
        assert "check_cpu" in names(router.select_for_request(phrase, declarations))


def test_explicit_screen_analysis_still_takes_priority_over_page_interaction():
    declarations = [decl("browser_control"), decl("capture_and_analyze_screen")]
    phrase = "Analizza questa schermata, leggi questa pagina e clicca il link"
    assert names(ToolRouter().select_for_request(phrase, declarations)) == {
        "capture_and_analyze_screen"
    }


def test_agent_loop_is_selected_for_explicit_multi_step_requests():
    declarations = [decl("agent_loop"), decl("terminal_run")]
    router = ToolRouter()

    assert names(router.select_for_request("Automatizza questo obiettivo", declarations)) == {
        "agent_loop"
    }
    assert router.select_for_request("Dimmi una curiosità", declarations) == []


def test_fables_requests_select_workflow_and_existing_browser_tools():
    declarations = [
        decl("fables_workflow"),
        decl("browser_control"),
        decl("read_active_page"),
        decl("open_website"),
        decl("browser_automation"),
        decl("computer_settings"),
    ]

    selected = names(
        ToolRouter().select_for_request(
            "Jarvis, vai su Fables e accetta",
            declarations,
        )
    )

    assert {
        "fables_workflow",
        "browser_automation",
    } <= selected
    assert not {
        "browser_control",
        "read_active_page",
        "open_website",
    } & selected
    assert "computer_settings" not in selected


def test_local_selection_uses_only_tools_relevant_to_the_current_request():
    declarations = [
        decl("app_launcher"),
        decl("ui_layout"),
        decl("quick_notes"),
        decl("web_search"),
        decl("recall_memory"),
        decl("save_memory"),
        decl("system_status"),
    ]
    router = ToolRouter()

    assert router.select_for_request("Dimmi una curiosità", declarations) == []
    assert names(router.select_for_request("Apri il blocco note", declarations)) == {
        "app_launcher"
    }
    combined_request = names(
        router.select_for_request(
            "Apri il blocco note e ricordami di chiamare Marco",
            declarations + [decl("reminder")],
        )
    )
    assert {"app_launcher", "reminder", "quick_notes"} <= combined_request
    assert "ui_layout" not in combined_request
    assert names(router.select_for_request("Cosa ti ho detto sui miei orari?", declarations)) == {
        "recall_memory"
    }
    assert names(router.select_for_request("Memorizza che preferisco risposte brevi", declarations)) == {
        "save_memory"
    }
    assert names(router.select_for_request("Qual è lo stato del sistema?", declarations)) == {
        "system_status"
    }


def test_keywords_pick_matching_tools_in_italian_and_english():
    router = ToolRouter()
    assert {"generate_3d_model", "viewer_3d"} <= names(router.select("crea una sedia in 3D", SAMPLE))
    assert "weather_report" in names(router.select("che meteo fa domani", SAMPLE))
    assert "reminder" in names(router.select("ricordami di chiamare Marco", SAMPLE))
    assert "spotify_music_control" in names(router.select("play some music", SAMPLE))
    out = names(router.select("mostrami i terremoti di oggi", SAMPLE))
    assert "gev_mcp_get_earthquakes" in out and "weather_report" not in out


@pytest.mark.parametrize(
    ("phrase", "connector_id"),
    [
        ("Connetti GitHub", "github"),
        ("Collega GitHub", "github"),
        ("Accedi a GitHub", "github"),
        ("Connetti Spotify", "spotify"),
        ("Connect to Spotify", "spotify"),
    ],
)
def test_spoken_connector_requests_resolve_and_select_connect_action(
    phrase, connector_id
):
    connectors = [
        {"id": "github", "name": "GitHub"},
        {"id": "spotify", "name": "Spotify"},
    ]
    assert connector_connection_id(phrase, connectors) == connector_id
    declarations = [decl("connect_service"), decl("connector_call"), decl("spotify_music_control")]
    assert names(ToolRouter().select_for_request(phrase, declarations)) == {
        "connect_service"
    }


def test_connector_intent_requires_explicit_verb_and_rejects_ambiguous_services():
    connectors = [
        {"id": "github", "name": "GitHub"},
        {"id": "spotify", "name": "Spotify"},
    ]
    assert connector_connection_id("Come funziona GitHub?", connectors) is None
    assert connector_connection_id("Connetti GitHub e Spotify", connectors) is None


@pytest.mark.parametrize(
    "phrase",
    [
        "Quanti repository ho su GitHub?",
        "Quanti repo ho su GitHub?",
        "Elenca i miei repository GitHub",
        "Mostra i miei repo",
    ],
)
def test_authenticated_github_repository_request_selects_dedicated_tool(phrase):
    declarations = [
        decl("github_user_repositories"),
        decl("connector_call"),
        decl("connectors_status"),
    ]

    assert names(ToolRouter().select_for_request(phrase, declarations)) == {
        "github_user_repositories"
    }


@pytest.mark.parametrize(
    "phrase",
    [
        "Jarvis, cerca repository con la parola python",
        "Cerca repository su GitHub con python",
        "Trova repo GitHub che usano FastAPI",
    ],
)
def test_github_repository_search_beats_generic_web_search(phrase):
    declarations = [
        decl("github_search_repositories"),
        decl("connector_call"),
        decl("web_search"),
    ]

    router = ToolRouter()
    selected = names(router.select_for_request(phrase, declarations))
    session_selected = names(router.select(phrase, declarations))

    assert selected == {"github_search_repositories"}
    assert "web_search" not in selected
    assert "github_search_repositories" in session_selected
    assert "web_search" not in session_selected


def test_historical_story_request_selects_web_research_without_gev():
    declarations = [
        decl("web_search"),
        decl("research_agent"),
        decl("gev"),
        decl("gev_mcp_get_weather_map"),
        decl("browser_control"),
    ]

    selected = names(
        ToolRouter().select_for_request(
            "Raccontami la storia di Roma",
            declarations,
        )
    )

    assert selected == {"web_search"}


def test_spoken_connect_request_dispatches_action_without_model_guessing(monkeypatch):
    import main

    calls = []

    class UI:
        def write_log(self, message):
            calls.append(("log", message))

    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = UI()
    live._asst_name = "Iris"
    live._connector_registry = lambda: type(
        "Registry",
        (),
        {"view": lambda _self: [{"id": "github", "name": "GitHub"}]},
    )()
    live._action_registry = type(
        "ActionRegistry",
        (),
        {
            "run": lambda _self, name, args, ctx: (
                calls.append((name, args, ctx["player"])) or "OAuth avviato."
            )
        },
    )()
    live._hud = type(
        "Hud",
        (),
        {"push_chat": lambda _self, role, message: calls.append((role, message))},
    )()
    live.speak = lambda message: calls.append(("spoken", message))
    live._set_task_idle = lambda value: calls.append(("idle", value))

    async def dispatch():
        assert live._route_voice_transcript("Connetti GitHub") is True
        await asyncio.sleep(0.05)

    asyncio.run(dispatch())

    assert any(
        entry[0] == "connect_service" and entry[1] == {"connector_id": "github"}
        for entry in calls
    )
    assert ("spoken", "OAuth avviato.") in calls


def test_viewer_voice_commands_select_the_3d_tools():
    router = ToolRouter()
    for phrase in ("metti il globo in blueprint", "passa al materiale realistico", "spiega un motore",
                   "smonta il cambio", "cosa sto guardando?", "che cos'è questa?"):
        assert {"viewer_3d"} <= names(router.select(phrase, SAMPLE)), phrase


def test_flights_pulls_in_aircraft_tools_but_not_other_gev_tools():
    out = names(ToolRouter().select("traccia i voli sopra l'Europa", SAMPLE))
    assert {"flight_finder", "viewer_3d", "gev", "gev_mcp_aircraft_in_area"} <= out
    assert "gev_mcp_get_earthquakes" not in out


def test_always_tools_survive_and_used_tools_are_kept():
    out = names(ToolRouter().select("che meteo fa", SAMPLE, used={"file_controller"}))
    assert ALWAYS <= out and "file_controller" in out


def test_unmapped_tool_is_never_hidden():
    router = ToolRouter()
    assert not router.mapped("brand_new_tool")
    for text in ("", "meteo", "crea un modello 3d"):
        assert "brand_new_tool" in names(router.select(text, SAMPLE))


def test_order_is_preserved_and_input_not_mutated():
    before = [d["name"] for d in SAMPLE]
    out = ToolRouter().select("meteo", SAMPLE)
    assert [d["name"] for d in SAMPLE] == before
    order = {n: i for i, n in enumerate(before)}
    assert [order[d["name"]] for d in out] == sorted(order[d["name"]] for d in out)


def _core_names() -> list[str]:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TOOL_DECLARATIONS":
            return [t["name"] for t in ast.literal_eval(node.value)]
    raise AssertionError("TOOL_DECLARATIONS not found")


def test_every_real_core_and_action_tool_is_mapped():
    from core.action_loader import discover_actions
    core = _core_names()
    actions = sorted(discover_actions(ROOT / "actions", set(core), lambda m: None).names())
    router = ToolRouter()
    unmapped = [n for n in core + actions if not router.mapped(n)]
    # An unmapped tool still works (it is always sent), but then routing never trims it: map it on purpose.
    assert unmapped == []


def test_routing_shrinks_the_real_payload():
    from core.action_loader import discover_actions
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    core = next(ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TOOL_DECLARATIONS")
    reg = discover_actions(ROOT / "actions", {t["name"] for t in core}, lambda m: None)
    everything = core + reg.get_tool_declarations()
    full = len(json.dumps(everything))
    router = ToolRouter()
    for text in ("che meteo fa a Roma", "fai qualcosa", "genera una sedia 3d"):
        trimmed = router.select(text, everything)
        assert len(json.dumps(trimmed)) < full * 0.6, text
        assert ALWAYS <= names(trimmed)


def test_select_tool_declarations_is_opt_in(monkeypatch):
    import collections
    import main
    obj = main.JarvisLive.__new__(main.JarvisLive)
    obj._action_registry = type("R", (), {"get_tool_declarations": lambda s: []})()
    obj._plugin_registry = type("R", (), {"get_tool_declarations": lambda s: []})()
    obj._tool_router = main.ToolRouter()
    obj._recent_user_texts = collections.deque(["che meteo fa"], maxlen=6)
    obj._tools_used = set()
    monkeypatch.delenv("JARVIS_TOOL_ROUTING", raising=False)
    full = obj._select_tool_declarations()
    assert len(full) == len(main.TOOL_DECLARATIONS) + 4
    monkeypatch.setenv("JARVIS_TOOL_ROUTING", "1")
    assert len(obj._select_tool_declarations()) < len(full)
    obj._recent_user_texts.clear()
    assert len(obj._select_tool_declarations()) == len(full)
