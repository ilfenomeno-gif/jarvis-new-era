import os
import re
import time
import uuid

import pytest


@pytest.fixture
def live_environment():
    if os.name != "nt" or os.environ.get("JARVIS_RUN_COMPUTER_USE_E2E") != "1":
        pytest.skip(
            "Set JARVIS_RUN_COMPUTER_USE_E2E=1 in an interactive Windows session."
        )


@pytest.mark.live
def test_jarvis_opens_terminal_types_and_submits_command(live_environment):
    import psutil
    from pywinauto import Desktop

    from actions.terminal_open import open_terminal
    from core import computer_use

    result = open_terminal({"confirmed": True})
    match = re.search(r"\(PID (\d+)\)", result)
    assert match, result
    process_id = int(match.group(1))
    process = psutil.Process(process_id)
    try:
        time.sleep(0.5)
        hwnd, process_name = computer_use.require_allowed_foreground()
        assert process_name in {
            "cmd.exe",
            "conhost.exe",
            "openconsole.exe",
            "windowsterminal.exe",
        }
        window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        window.set_focus()

        marker = f"JARVIS_E2E_{uuid.uuid4().hex[:8]}"
        command = f"title {marker}"
        computer_use.execute_input({
            "action": "type_text",
            "text": command,
            "confirmed": True,
            "_expected_window": hwnd,
            "_expected_process": process_name,
        })
        computer_use.execute_input({
            "action": "press",
            "key": "enter",
            "confirmed": True,
            "_expected_window": hwnd,
            "_expected_process": process_name,
        })

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and window.window_text() != marker:
            time.sleep(0.1)
        assert window.window_text() == marker
    finally:
        try:
            computer_use.stop_emergency_stop()
        finally:
            if process.is_running():
                process.terminate()
                process.wait(timeout=5)


@pytest.mark.live
def test_jarvis_searches_google_clicks_result_and_reads_page(live_environment):
    from urllib.parse import urlsplit

    from core.browser_automation import BrowserAutomation

    browser = BrowserAutomation()
    try:
        query = 'site:example.com "Example Domain"'
        try:
            results = browser.search_web(query)
        except PermissionError as exc:
            if "consent page" not in str(exc):
                assert "human verification" in str(exc)
                assert "/sorry/" in browser.get_url()
                pytest.skip("Google requires human verification; no bypass was attempted.")
            consent_text = browser.get_text("body")
            choices = ("Rifiuta tutto", "Reject all")
            choice = next((item for item in choices if item in consent_text), None)
            if choice is None:
                raise
            browser.click_role("button", choice)
            try:
                results = browser.search_web(query)
            except PermissionError as verification_error:
                assert "human verification" in str(verification_error)
                assert "/sorry/" in browser.get_url()
                pytest.skip("Google requires human verification; no bypass was attempted.")
        assert "Example Domain" in results

        browser.click("div#search a:has(h3)")
        browser.wait_for("body", 10_000)
        assert urlsplit(browser.get_url()).hostname in {"example.com", "www.example.com"}
        assert "Example Domain" in browser.get_text("body")
    finally:
        browser.close()


@pytest.mark.live
def test_jarvis_clicks_and_reads_documentation_page(live_environment):
    from core.browser_automation import BrowserAutomation

    browser = BrowserAutomation()
    try:
        browser.start()
        browser.navigate("https://www.python.org/")
        assert browser.get_title() == "Welcome to Python.org"
        assert "Python" in browser.get_text("body")
        browser.click_role("link", "Documentation")
        browser.wait_for("body", 10_000)
        assert "python.org/doc/" in browser.get_url()
        assert "Python's documentation" in browser.get_text("body")
    finally:
        browser.close()
