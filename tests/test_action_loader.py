"""Tests for the built-in action registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.action_loader import discover_actions


def _write_action(directory: Path, filename: str, name: str, result: str) -> None:
    (directory / filename).write_text(
        "def run(parameters, player=None, speak=None):\n"
        f"    return {result!r} + ':' + str(parameters['value']) + ':' + str(player)\n"
        "\n"
        "TOOL = {\n"
        f"    'name': {name!r},\n"
        "    'description': 'Test action',\n"
        "    'parameters': {'type': 'OBJECT', 'properties': {}},\n"
        "    'handler': run,\n"
        "}\n",
        encoding="utf-8",
    )


def test_discovery_registers_actions_and_rejects_reserved_or_duplicate_names(
    tmp_path, monkeypatch
):
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    _write_action(actions_dir, "a_reserved.py", "protected", "reserved")
    _write_action(actions_dir, "b_first.py", "sample_action", "first")
    _write_action(actions_dir, "c_duplicate.py", "sample_action", "duplicate")
    messages: list[str] = []
    for module_name in (
        "actions.a_reserved",
        "actions.b_first",
        "actions.c_duplicate",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    registry = discover_actions(
        actions_dir,
        reserved_names={"protected"},
        logger=messages.append,
    )

    assert registry.names() == {"sample_action"}
    assert [item["name"] for item in registry.get_tool_declarations()] == [
        "sample_action"
    ]
    assert registry.run(
        "sample_action",
        {"value": 7},
        ctx={"player": "ui", "speak": "speech"},
    ) == "first:7:ui"
    assert any("collides with a reserved core tool" in message for message in messages)
    assert any("already used by action" in message for message in messages)


def test_destructive_actions_require_confirmation(tmp_path, monkeypatch):
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "wipe.py").write_text(
        "def run(parameters):\n    return 'wiped'\n\n"
        "TOOL = {'name': 'wipe', 'description': 'x', 'risk_class': 'destructive',\n"
        "        'parameters': {'type': 'OBJECT', 'properties': {}}, 'handler': run}\n",
        encoding="utf-8",
    )
    (actions_dir / "bad.py").write_text(
        "TOOL = {'name': 'bad', 'description': 'x', 'risk_class': 'nope',\n"
        "        'handler': lambda parameters: ''}\n",
        encoding="utf-8",
    )
    for module_name in ("actions.wipe", "actions.bad"):
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    registry = discover_actions(actions_dir, logger=lambda _m: None)

    assert registry.names() == {"wipe"}
    assert registry.risk_class("wipe") == "destructive"
    declared = registry.get_tool_declarations()[0]["parameters"]["properties"]
    assert "confirmed" in declared
    assert "confirmation" in registry.run("wipe", {})
    assert registry.run("wipe", {"confirmed": True}) == "wiped"


def test_bundled_actions_are_discovered():
    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions", logger=lambda _m: None
    )

    assert {"weather_report", "send_message", "reminder"} <= registry.names()
    assert registry.risk_class("weather_report") == "read"
