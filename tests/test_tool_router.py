import ast
import json
from pathlib import Path

import pytest

from core.tool_router import ALWAYS, BASE, ToolRouter

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
    declarations = [decl("computer_perception"), decl("computer_input")]
    router = ToolRouter()

    assert names(
        router.select_for_request("Leggi il testo sullo schermo con OCR", declarations)
    ) == {"computer_perception"}
    assert names(
        router.select_for_request("Clicca sul pulsante in Notepad", declarations)
    ) == {"computer_input"}
    assert router.select_for_request("Dimmi una curiosità", declarations) == []


def test_agent_loop_is_selected_for_explicit_multi_step_requests():
    declarations = [decl("agent_loop"), decl("terminal_run")]
    router = ToolRouter()

    assert names(router.select_for_request("Automatizza questo obiettivo", declarations)) == {
        "agent_loop"
    }
    assert router.select_for_request("Dimmi una curiosità", declarations) == []


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
    assert len(full) == len(main.TOOL_DECLARATIONS)
    monkeypatch.setenv("JARVIS_TOOL_ROUTING", "1")
    assert len(obj._select_tool_declarations()) < len(full)
    obj._recent_user_texts.clear()
    assert len(obj._select_tool_declarations()) == len(full)
