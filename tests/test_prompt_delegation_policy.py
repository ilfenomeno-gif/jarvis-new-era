from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_prompt_contains_background_delegation_policy():
    prompt = (PROJECT_ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
    normalized = prompt.casefold()

    assert "writer" in normalized
    assert "browser" in normalized
    assert "delegate_task" in prompt
    assert "list_tasks" in prompt
    assert "cancel_task" in prompt
    assert "get_task_result" in prompt
    assert "quando delegare" in normalized
    assert "quando non delegare" in normalized


def test_live_system_prompt_includes_policy_without_conflicting_duplicate(
    monkeypatch,
    tmp_path,
):
    main = importlib.import_module("main")
    prompt_path = PROJECT_ROOT / "core" / "prompt.txt"

    monkeypatch.setattr(main, "PROMPT_PATH", prompt_path)
    monkeypatch.setattr(main, "API_CONFIG_PATH", tmp_path / "api_keys.json")
    monkeypatch.setattr(main, "require_policy_file", lambda: "test security policy")
    monkeypatch.setattr(main, "load_memory", lambda: {})
    monkeypatch.setattr(main, "format_memory_for_prompt", lambda _memory: "")
    monkeypatch.setattr(
        main.pattern_learner,
        "add_hints_to_prompt",
        lambda prompt, _text: prompt,
    )

    orchestrator = SimpleNamespace(roles=lambda: ("writer", "browser"))
    jarvis = SimpleNamespace(
        _asst_name="JARVIS",
        _last_user_text="",
        _task_orchestrator=orchestrator,
        _resume_handle=None,
        _thinking_enabled=False,
        _enhanced_live=False,
        _speech_voice_name=lambda: "Charon",
        _select_tool_declarations=lambda: [],
    )

    config = main.JarvisLive._build_config(jarvis)
    final_prompt = config.system_instruction

    assert "## DELEGA DEI TASK IN BACKGROUND" in final_prompt
    assert "writer" in final_prompt.casefold()
    assert "browser" in final_prompt.casefold()
    assert "list_tasks" in final_prompt
    assert "cancel_task" in final_prompt
    assert "get_task_result" in final_prompt
    assert "test security policy" in final_prompt
    assert "[WEB RESEARCH]" in final_prompt
    assert "discursive response" in final_prompt
    assert "raw URLs, titles, snippets, or result dumps" in final_prompt
    assert config.response_modalities == ["AUDIO"]
    assert (
        "Per la politica di delega dei task in background, segui le "
        "istruzioni del system prompt."
    ) in final_prompt
    assert final_prompt.count("## DELEGA DEI TASK IN BACKGROUND") == 1
    assert "For work independent from the user's immediate question" not in final_prompt
