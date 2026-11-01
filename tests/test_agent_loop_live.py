import asyncio
import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def live_notepad_file(tmp_path):
    if os.name != "nt" or os.environ.get("JARVIS_LIVE_TESTS") != "1":
        pytest.skip("Set JARVIS_LIVE_TESTS=1 in an interactive Windows session.")

    path = tmp_path / "jarvis-agent-loop-live.txt"
    path.write_text("", encoding="utf-8")
    process = subprocess.Popen(["notepad.exe", str(path)])
    window = None
    try:
        from pywinauto import Application

        window = Application(backend="uia").connect(process=process.pid).top_window()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                window.set_focus()
                if window.is_active():
                    break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.fail("Notepad did not become the foreground window.")
        yield path, process
    finally:
        if window is not None:
            window.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_agent_loop_writes_and_saves_text_in_notepad(live_notepad_file):
    from core.agent_loop import AgentLoop

    path, _process = live_notepad_file
    loop = AgentLoop(
        max_steps=6,
        step_timeout=30,
        confirm_session=lambda _prompt: True,
    )

    result = asyncio.run(
        loop.run(
            "Nel documento aperto in Blocco note, scrivi esattamente la parola "
            "'test' e salva il file."
        )
    )

    assert result["result"] == "success", result
    assert "test" in path.read_text(encoding="utf-8").casefold()
