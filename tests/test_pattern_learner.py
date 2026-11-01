import json

import pytest

from core import pattern_learner
from core import registry_cli


@pytest.fixture
def pattern_store(tmp_path, monkeypatch):
    path = tmp_path / "learned_patterns.json"
    monkeypatch.setattr(pattern_learner, "PATTERNS_PATH", path)
    monkeypatch.delenv(pattern_learner.ENABLED_ENV, raising=False)
    return path


def test_extract_patterns_aggregates_three_identical_observations(pattern_store):
    observation = {
        "type": "style_preference",
        "context": "auto",
        "observation": "preferred:realistic;previous:blueprint",
    }

    result = pattern_learner.extract_patterns([observation] * 3)

    assert len(result) == 3
    patterns = pattern_learner.list_patterns()
    assert len(patterns) == 1
    assert patterns[0]["occurrences"] == 3
    assert patterns[0]["confidence"] == 0.9
    assert set(patterns[0]) == {
        "id", "type", "context", "observation", "confidence", "occurrences", "last_seen"
    }
    assert json.loads(pattern_store.read_text(encoding="utf-8"))["patterns"] == patterns


def test_hints_are_confident_and_bounded_to_three_and_200_characters(pattern_store):
    for context in ("auto", "sedia", "mela", "3d"):
        for _ in range(3):
            pattern_learner.observe_tool_failure(context)

    hints = pattern_learner.get_hints_for()

    assert len(hints.split(" | ")) <= 3
    assert len(hints) <= 200
    assert all(item["confidence"] >= 0.7 for item in pattern_learner.list_patterns())


def test_three_style_corrections_are_injected_for_the_next_similar_object(pattern_store):
    for _ in range(3):
        pattern_learner.observe_correction("auto", "No, rifai in realistico", "blueprint")

    prompt = pattern_learner.add_hints_to_prompt("system prompt", "a similar car")

    assert "LEARNED PREFERENCES" in prompt
    assert "prefer realistic over blueprint" in prompt
    assert len(prompt.split("\n\n", 1)[0]) <= 200
    assert len(pattern_learner.get_hints_for("a similar car")) <= 200


def test_model_context_uses_cad_filename_and_none_is_a_valid_previous_style(pattern_store):
    assert pattern_learner.model_context_for("cad/pc.glb") == "pc"
    assert pattern_learner.model_context_for(r"cad\pc.glb") == "pc"

    pattern = pattern_learner.observe_style_preference("pc", "realistic", previous_style=None)[0]

    assert pattern["context"] == "pc"
    assert pattern["observation"] == "preferred:realistic;previous:none"
    assert pattern["occurrences"] == 1


def test_live_dispatcher_tracks_loaded_pc_style_observations(pattern_store):
    import main as jarvis_main

    jarvis = object.__new__(jarvis_main.JarvisLive)
    jarvis._last_user_text = "carica il PC CAD"
    jarvis._observe_pattern_tool_result(
        "viewer_3d",
        {"mode": "load_model", "model": "cad/pc.glb"},
        "Model cad/pc.glb loaded.",
    )
    for style in ("realistic", "blueprint", "realistic"):
        jarvis._observe_pattern_tool_result(
            "viewer_3d",
            {"mode": "set_material_style", "style": style},
            f"Material style set to {style}.",
        )

    realistic = next(
        item for item in pattern_learner.list_patterns()
        if item["observation"].startswith("preferred:realistic;")
    )
    assert realistic["context"] == "pc"
    assert realistic["observation"] == "preferred:realistic;previous:none"
    assert realistic["occurrences"] == 2
    assert realistic["confidence"] == 0.6

    jarvis._observe_pattern_tool_result(
        "viewer_3d",
        {"mode": "set_material_style", "style": "realistic"},
        "Material style set to realistic.",
    )
    realistic = next(
        item for item in pattern_learner.list_patterns()
        if item["observation"].startswith("preferred:realistic;")
    )
    assert realistic["occurrences"] == 3
    assert realistic["confidence"] == 0.9
    assert "prefer realistic style" in pattern_learner.get_hints_for("cad/pc.glb")


def test_live_system_prompt_uses_repeated_style_corrections(pattern_store, tmp_path, monkeypatch):
    import main as jarvis_main

    monkeypatch.setattr(jarvis_main, "API_CONFIG_PATH", tmp_path / "missing-config.json")
    monkeypatch.setattr(jarvis_main, "load_memory", lambda: {})
    monkeypatch.setattr(jarvis_main, "format_memory_for_prompt", lambda _memory: "")
    monkeypatch.setattr(jarvis_main, "_load_system_prompt", lambda: "BASE SYSTEM PROMPT")
    monkeypatch.setattr(jarvis_main, "get_voice", lambda: "Kore")

    jarvis = object.__new__(jarvis_main.JarvisLive)
    jarvis._pattern_context = "auto"
    jarvis._pattern_style = "blueprint"
    jarvis._last_user_text = "create another car"
    jarvis._asst_name = "JARVIS"
    jarvis._resume_handle = None
    jarvis._enhanced_live = False
    jarvis._thinking_enabled = False
    jarvis._select_tool_declarations = lambda: []

    for previous_style in ("blueprint", "realistic", "realistic"):
        jarvis._pattern_style = previous_style
        jarvis._observe_pattern_feedback("No, rifai in realistico")

    config = jarvis._build_config()

    assert "prefer realistic over blueprint" in config.system_instruction


def test_search_failure_hint_appears_after_three_failures(pattern_store):
    pattern_learner.observe_tool_failure("auto")
    pattern_learner.observe_tool_failure("auto")
    assert pattern_learner.get_hints_for("car") == ""

    pattern_learner.observe_tool_failure("auto")

    assert "use generate_3d_model" in pattern_learner.get_hints_for("car")


def test_generic_corrections_are_learned_without_3d_context(pattern_store):
    for _ in range(3):
        pattern_learner.observe_correction("general", "No, rifai", None)

    assert "incorporate it before repeating" in pattern_learner.get_hints_for("summarize this")


def test_live_dispatcher_learns_repeated_search_failures(pattern_store):
    import main as jarvis_main

    jarvis = object.__new__(jarvis_main.JarvisLive)
    jarvis._last_user_text = "find a car model"
    for _ in range(3):
        jarvis._observe_pattern_tool_result(
            "search_3d_model",
            {"query": "car"},
            "No exact ready-made 3D model found for 'car'.",
        )

    assert "use generate_3d_model" in pattern_learner.get_hints_for("car")


def test_live_dispatcher_learns_only_corrected_style_not_generation_baseline(pattern_store):
    import main as jarvis_main

    jarvis = object.__new__(jarvis_main.JarvisLive)
    for model in ("Ferrari", "Lamborghini", "Porsche"):
        jarvis._last_user_text = f"create a {model}"
        jarvis._observe_pattern_tool_result(
            "generate_3d_model",
            {"prompt": f"{model} car", "style": "blueprint"},
            "Model generated successfully",
        )
        jarvis._observe_pattern_tool_result(
            "viewer_3d",
            {"mode": "set_material_style", "style": "realistic"},
            "Style updated",
        )

    patterns = pattern_learner.list_patterns()
    assert len(patterns) == 1
    assert patterns[0]["type"] == "style_preference"
    assert patterns[0]["context"] == "auto"
    assert patterns[0]["observation"] == "preferred:realistic;previous:blueprint"
    assert patterns[0]["occurrences"] == 3
    assert patterns[0]["confidence"] == 0.9
    hints = pattern_learner.get_hints_for("create another car")
    assert hints == "For auto models, prefer realistic over blueprint."


def test_pattern_cli_list_delete_and_confirmed_clear(pattern_store):
    for _ in range(3):
        pattern_learner.observe_tool_failure("auto")
    pattern = pattern_learner.list_patterns()[0]

    listing = registry_cli.run(["patterns-list"], None)
    assert pattern["id"] in listing and "tool_failure" in listing
    assert registry_cli.run(["patterns-delete", pattern["id"]], None) == f"{pattern['id']}: deleted"
    assert registry_cli.run(["patterns-delete", pattern["id"]], None).startswith("error:")

    pattern_learner.observe_tool_failure("auto")
    assert registry_cli.run(["patterns-clear"], None).startswith("error:")
    assert registry_cli.run(["patterns-clear", "--yes"], None) == "learned patterns cleared (1 patterns removed)"
    assert registry_cli.run(["patterns-list"], None) == "No learned patterns"


def test_opt_out_disables_learning_and_prompt_injection(pattern_store, monkeypatch):
    monkeypatch.setenv(pattern_learner.ENABLED_ENV, "0")
    pattern_learner.observe_tool_failure("auto")

    assert pattern_learner.list_patterns() == []
    assert pattern_learner.get_hints_for() == ""
