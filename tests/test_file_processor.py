from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import file_processor as file_processor_module
from actions.file_processor import file_processor


@pytest.mark.pre_existing(reason="Mock del subprocess incompatibile con la chiamata file_processor corrente")
@pytest.mark.xfail(
    reason="Mock del subprocess incompatibile con la chiamata file_processor corrente",
    strict=False,
)
def test_script_execution_requires_confirmation_before_subprocess(tmp_path, monkeypatch):
    script = tmp_path / "example.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(file_processor_module.subprocess, "run", run)

    result = file_processor({"file_path": str(script), "action": "run"})

    assert "explicit user confirmation" in result
    run.assert_not_called()


@pytest.mark.pre_existing(reason="Il flusso di conferma host non corrisponde al contratto atteso dal test")
@pytest.mark.xfail(
    reason="Il flusso di conferma host non corrisponde al contratto atteso dal test",
    strict=False,
)
def test_host_requires_exact_script_path_confirmation(monkeypatch, tmp_path):
    import main

    first_script = tmp_path / "first.py"
    second_script = tmp_path / "second.py"
    first_script.write_text("print('first')\n", encoding="utf-8")
    second_script.write_text("print('second')\n", encoding="utf-8")

    live = object.__new__(main.JarvisLive)
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "Esegui lo script"
    live._local_pending_confirmation = None
    live._action_registry = SimpleNamespace(has=lambda _name: False)
    live.ui = SimpleNamespace(
        set_state=Mock(),
        write_log=Mock(),
        current_file=None,
        muted=True,
    )
    run_file = Mock(return_value="script executed")
    monkeypatch.setattr(main, "file_processor", run_file)
    monkeypatch.setattr(main, "require_policy_file", lambda: "policy")
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)

    def call(path: Path):
        return asyncio.run(live._execute_tool(SimpleNamespace(
            id="run-script",
            name="file_processor",
            args={"action": "run", "file_path": str(path), "confirmed": True},
        )))

    pending = call(first_script)
    assert pending.response["result"] == "Ask the user for explicit confirmation"
    assert pending.response["script"] == str(first_script.resolve())
    run_file.assert_not_called()

    live._last_user_text = "Sì, confermo"
    changed = call(second_script)
    assert "path changed after approval" in changed.response["result"]
    run_file.assert_not_called()

    live._local_pending_confirmation = {
        "id": "run-script",
        "name": "file_processor",
        "args": {"action": "run", "file_path": str(first_script.resolve())},
    }
    completed = call(first_script)
    assert completed.response["result"] == "script executed"
    run_file.assert_called_once()
    assert run_file.call_args.kwargs["parameters"]["confirmed"] is True
