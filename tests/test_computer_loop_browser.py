import threading

from core import clipboard
from core.audit_log import AuditLog
from core.browser_automation import BrowserAutomation, MockBrowser
from core.computer_loop import ComputerLoop
from core.memory_store import MemoryStore


def _auto_confirm(_key, _title, _detail, run, *, on_cancel):
    run()
    return "[CONFIRMATION_PENDING]"


def _loop(tmp_path, planner, browser, **kwargs):
    return ComputerLoop(
        memory_store=MemoryStore(tmp_path / "memory.sqlite3"),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        browser_automation=browser,
        planner=planner,
        confirmation_requester=_auto_confirm,
        **kwargs,
    )


def test_browser_loop_clicks_and_verifies_in_one_plan(tmp_path):
    mock = MockBrowser(elements={"Continue", "#status"})
    mock.text_by_selector["#status"] = "Ready"
    browser = BrowserAutomation(mock)
    plan = [
        {
            "description": "Open the local fixture",
            "action": {
                "type": "browser",
                "operation": "navigate",
                "url": "https://example.test/",
            },
            "verify": {"title_contains": "Mock"},
        },
        {
            "description": "Click the continue control",
            "action": {
                "type": "browser",
                "operation": "click",
                "text": "Continue",
            },
            "verify": {"stdout_contains": "Clicked text"},
        },
    ]
    loop = _loop(tmp_path, lambda *_: plan, browser)
    try:
        result = loop.run("Continue in the fixture", workspace=tmp_path)
        assert result.status == "completed"
        assert mock.actions == [("click_text", "Continue")]
    finally:
        loop.close()
        browser.close()


def test_browser_submit_requires_confirmation_and_verifies_form_result(tmp_path):
    mock = MockBrowser(elements={"form#sample", "#status"})
    browser = BrowserAutomation(mock)
    loop = _loop(
        tmp_path,
        lambda *_: [
            {
                "description": "Submit the fixture form",
                "action": {
                    "type": "browser",
                    "operation": "submit_form",
                    "selector": "form#sample",
                },
                "verify": {"stdout_contains": "Submitted form"},
            }
        ],
        browser,
    )
    try:
        result = loop.run("Submit the harmless fixture form", workspace=tmp_path)
        assert result.status == "completed"
        assert ("submit_form", "form#sample") in mock.actions
    finally:
        loop.close()
        browser.close()


def test_clipboard_copies_between_terminal_and_browser(tmp_path):
    class MemoryClipboard:
        value = ""

        def get(self):
            return self.value

        def set(self, text):
            self.value = text

    previous = clipboard.set_backend(MemoryClipboard())
    mock = MockBrowser(elements={"textarea#target", "#source"})
    mock.text_by_selector["#source"] = "copied from browser"
    mock.selection_text = "copied from browser"
    browser = BrowserAutomation(mock)
    try:
        browser.start()
        clipboard.set("copied from terminal")
        clipboard.paste_into("textarea#target", browser=browser)
        assert mock.values["textarea#target"] == "copied from terminal"

        mock.start()
        mock.current_url = "https://example.test/"
        assert clipboard.copy_selection(browser) == "copied from browser"
        assert clipboard.get() == "copied from browser"
    finally:
        browser.close()
        clipboard.set_backend(previous)


def test_browser_loop_replans_after_dom_verification_failure(tmp_path):
    mock = MockBrowser(elements={"#present"})
    browser = BrowserAutomation(mock)
    plans = iter(
        [
            [
                {
                    "description": "Wait for a missing element",
                    "action": {
                        "type": "browser",
                        "operation": "wait_for",
                        "selector": "#missing",
                        "timeout_ms": 50,
                    },
                }
            ],
            [
                {
                    "description": "Wait for the visible element",
                    "action": {
                        "type": "browser",
                        "operation": "wait_for",
                        "selector": "#present",
                    },
                    "verify": {"selector_visible": "#present"},
                }
            ],
        ]
    )
    loop = _loop(tmp_path, lambda *_: next(plans), browser, max_retries=1)
    try:
        result = loop.run("Wait for a visible element", workspace=tmp_path)
        assert result.status == "completed"
        assert result.attempts == 2
        assert result.steps[0].success is False
        assert result.steps[-1].success is True
    finally:
        loop.close()
        browser.close()


def test_browser_click_uses_confirmation_banner_callbacks(tmp_path, monkeypatch):
    from core import confirm

    shown = threading.Event()
    accepted_result = []

    def show(_title, _detail):
        shown.set()

    confirm.bind(show, lambda: None)
    monkeypatch.setattr(confirm, "_pending", None)
    browser_backend = MockBrowser(elements={"Continue"})
    browser = BrowserAutomation(browser_backend)
    loop = ComputerLoop(
        memory_store=MemoryStore(tmp_path / "memory.sqlite3"),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        browser_automation=browser,
        planner=lambda *_: [
            {
                "description": "Click the confirmed control",
                "action": {
                    "type": "browser",
                    "operation": "click",
                    "text": "Continue",
                },
            }
        ],
        max_retries=0,
    )
    worker = threading.Thread(
        target=lambda: accepted_result.append(
            loop.run("Click with an explicit confirmation", workspace=tmp_path)
        )
    )
    try:
        worker.start()
        assert shown.wait(2)
        confirm.resolve(True)
        worker.join(3)
        assert not worker.is_alive()
        assert accepted_result[0].status == "completed"
        assert browser_backend.actions == [("click_text", "Continue")]
    finally:
        if worker.is_alive():
            confirm.resolve(False)
            worker.join(3)
        confirm.bind(None, None)
        loop.close()
        browser.close()


def test_browser_click_is_cancelled_without_running_action(tmp_path, monkeypatch):
    from core import confirm

    shown = threading.Event()
    result = []
    confirm.bind(lambda *_args: shown.set(), lambda: None)
    monkeypatch.setattr(confirm, "_pending", None)
    backend = MockBrowser(elements={"Delete"})
    browser = BrowserAutomation(backend)
    loop = ComputerLoop(
        memory_store=MemoryStore(tmp_path / "memory.sqlite3"),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        browser_automation=browser,
        planner=lambda *_: [
            {
                "description": "Click a control",
                "action": {
                    "type": "browser",
                    "operation": "click",
                    "text": "Delete",
                },
            }
        ],
        max_retries=0,
    )
    worker = threading.Thread(
        target=lambda: result.append(
            loop.run("Cancel this browser action", workspace=tmp_path)
        )
    )
    try:
        worker.start()
        assert shown.wait(2)
        confirm.resolve(False)
        worker.join(3)
        assert not worker.is_alive()
        assert result[0].status == "failed"
        assert "declined" in result[0].steps[0].stderr
        assert backend.actions == []
    finally:
        if worker.is_alive():
            confirm.resolve(False)
            worker.join(3)
        confirm.bind(None, None)
        loop.close()
        browser.close()
