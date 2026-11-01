from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.prompt_router import PromptRouter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ITALIAN_DIRECTIVE = (
    "Lingua di risposta: italiano. Rispondi SEMPRE in italiano, "
    "indipendentemente dal contesto precedente. Non mescolare mai lingue "
    "diverse nella stessa risposta."
)


def test_prompt_router_assigns_high_thinking_to_complex_profiles():
    router = PromptRouter()

    assert router.thinking_level_for("debug this Python error") == "high"
    assert router.profile_for("analizza il piano").thinking_level == "high"


def test_prompt_router_assigns_low_thinking_to_quick_commands():
    router = PromptRouter()

    assert router.thinking_level_for("apri Gemini") == "low"


def test_active_system_prompt_requires_italian():
    prompt = (PROJECT_ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")

    assert ITALIAN_DIRECTIVE in prompt


def _load_system_prompt_function(prompt_path, policy_loader, logger):
    main_path = PROJECT_ROOT / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_system_prompt"
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {
        "PROMPT_PATH": prompt_path,
        "require_policy_file": policy_loader,
        "logging": SimpleNamespace(getLogger=Mock(return_value=logger)),
        "__name__": "main",
    }
    exec(compile(module, str(main_path), "exec"), namespace)
    return namespace["_load_system_prompt"]


def test_system_prompt_fallback_is_italian_and_logs_provenance(tmp_path):
    logger = Mock()

    def fail_policy_load():
        raise OSError("policy file unavailable")

    load_system_prompt = _load_system_prompt_function(
        tmp_path / "missing-prompt.txt",
        fail_policy_load,
        logger,
    )

    prompt = load_system_prompt()

    assert ITALIAN_DIRECTIVE in prompt
    logger.info.assert_called_once_with(
        "Prompt caricato: fallback. Lingua forzata: italiano."
    )


def test_system_prompt_logs_path_without_logging_prompt_contents(tmp_path):
    logger = Mock()
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("prompt body must not be logged", encoding="utf-8")
    load_system_prompt = _load_system_prompt_function(
        prompt_path,
        lambda: "policy",
        logger,
    )

    prompt = load_system_prompt()

    assert "prompt body must not be logged" in prompt
    logger.info.assert_called_once_with(
        "Prompt caricato: %s. Lingua forzata: italiano.", prompt_path
    )


def test_startup_briefing_uses_italian_despite_saved_language():
    main_path = PROJECT_ROOT / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_build_startup_briefing_language_prompts"
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {"__name__": "main"}
    exec(compile(module, str(main_path), "exec"), namespace)

    greeting_prompt, language_instruction = namespace[
        "_build_startup_briefing_language_prompts"
    ](
        "08:30",
        {
            "language": {"value": "Traditional Chinese"},
            "name": {"value": "Marco"},
        },
        "",
    )

    assert "translated naturally into Italian" in greeting_prompt
    assert "Speak only in Italian" in greeting_prompt
    assert "Speak only in Italian" in language_instruction
    assert "Traditional Chinese" not in greeting_prompt + language_instruction
    assert "Marco" in greeting_prompt
