import asyncio
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from agents.computer_agent import ComputerAgent
from core.action_loader import discover_actions
from core.browser_automation import BrowserAutomation, MockBrowser
from core.chat_orchestrator import ChatOrchestrator
from core.chatbot_bridge import MockChatbot
from core.computer_input import ComputerInput
from core.computer_vision import ComputerVision
from core.memory_store import MemoryStore
from core.terminal_agent import TerminalAgent
from core.tool_router import ToolRouter

ROOT = Path(__file__).resolve().parents[1]


def _registry():
    return discover_actions(ROOT / "actions", logger=lambda _message: None)


def test_new_action_modules_are_registered_and_routed_for_requests():
    registry = _registry()
    declarations = registry.get_tool_declarations()
    router = ToolRouter()

    assert {
        "terminal_run",
        "terminal_open",
        "browser_automation",
        "computer_task",
        "chatbot_plan",
    } <= registry.names()
    assert "terminal_run" in {
        item["name"]
        for item in router.select_for_request(
            "Esegui il comando echo hello", declarations
        )
    }
    assert "terminal_open" in {
        item["name"]
        for item in router.select_for_request("Apri il terminale", declarations)
    }
    assert "browser_automation" in {
        item["name"]
        for item in router.select_for_request(
            "Vai su Fables e clicca il pulsante World", declarations
        )
    }
    assert "computer_task" in {
        item["name"]
        for item in router.select_for_request(
            "Clicca sul testo Save sullo schermo", declarations
        )
    }
    assert "chatbot_plan" in {
        item["name"]
        for item in router.select_for_request(
            "Pianifica contenuti con il chatbot su botanica", declarations
        )
    }


def test_terminal_agent_output_flows_through_jarvis_live_tool_dispatch(monkeypatch, tmp_path):
    import main

    class FakeUI:
        muted = False

        def __init__(self):
            self.logs = []

        def set_state(self, _state):
            pass

        def write_log(self, text):
            self.logs.append(text)

    runner_calls = []
    finished = threading.Event()

    def runner(args, **kwargs):
        runner_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "hello from terminal\n", "")

    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = FakeUI()
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "Esegui il comando echo hello"
    live._action_registry = _registry()
    live._terminal_agent = TerminalAgent(
        database_path=tmp_path / "terminal.sqlite3",
        runner=runner,
    )
    live._browser_automation = BrowserAutomation(MockBrowser())
    live._computer_agent = None
    live._chat_orchestrator = None
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    live._observe_pattern_tool_result = lambda *_args: None
    live.speak = lambda _text: None
    original_write = live.ui.write_log
    def write_log(message):
        original_write(message)
        if message.startswith("JARVIS: Comando completato."):
            finished.set()
    live.ui.write_log = write_log

    async def run():
        return await live._execute_tool(
            SimpleNamespace(
                id="echo-call",
                name="terminal_run",
                args={"command": "echo hello", "confirmed": True},
            ),
            user_confirmed=True,
        )

    response = asyncio.run(run())

    assert response.response == {"result": "Sto eseguendo il comando. Il risultato arriverà appena pronto."}
    assert finished.wait(2)
    assert len(runner_calls) == 1
    assert runner_calls[0][1]["shell"] is False
    assert "TERM: hello from terminal\n" in live.ui.logs
    live._browser_automation.close()


def test_terminal_background_failure_is_shown_when_voice_disconnected():
    import main

    finished = threading.Event()
    logs = []

    def write_log(message):
        logs.append(message)
        if "voce non connessa" in message:
            finished.set()

    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = SimpleNamespace(write_log=write_log)
    live._asst_name = "JARVIS"
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live._action_registry = SimpleNamespace(
        run=lambda *_args, **_kwargs: {
            "stdout": "", "stderr": "Command timed out", "returncode": 126,
        }
    )
    live._start_terminal_background({"command": "ipconfig", "confirmed": True})
    assert finished.wait(2)
    assert any("Comando non riuscito (codice 126)" in message for message in logs)
    assert any("Command timed out" in message for message in logs)


def test_web_research_returns_narrative_without_displaying_raw_results(monkeypatch):
    import main

    query = "Raccontami la storia di Roma"
    narrative = (
        "Certo Signore. Roma nacque, secondo la tradizione, nell'VIII secolo "
        "avanti Cristo e divenne il centro di una repubblica e poi di un vasto impero."
    )
    searched = []
    logs = []

    class UI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, message):
            logs.append(message)

    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = UI()
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="gemini")
    live._last_user_text = query
    live._action_registry = SimpleNamespace(has=lambda _name: False)
    live._harness_approval_decision = lambda _name, _args: None
    live._observe_pattern_tool_result = lambda *_args: None
    live.speak = lambda _text: None
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    monkeypatch.setattr(
        main,
        "web_search_action",
        lambda parameters, player: (
            searched.append((parameters, player)) or narrative
        ),
    )

    response = asyncio.run(
        live._execute_tool(
            SimpleNamespace(
                id="history-search",
                name="web_search",
                args={"query": query, "mode": "research"},
            )
        )
    )

    declaration = next(
        tool for tool in main.TOOL_DECLARATIONS if tool["name"] == "web_search"
    )
    assert searched == [
        ({"query": query, "mode": "research"}, live.ui)
    ]
    assert response.response == {"result": narrative}
    assert "raw URLs" in declaration["description"]
    assert all("https://" not in message for message in logs)


def test_browser_action_uses_isolated_browser_with_confirmation_and_mock():
    registry = _registry()
    mock = MockBrowser(elements={"button.world"})
    browser = BrowserAutomation(mock)
    ctx = {"browser_automation_client": browser}

    pending = registry.run(
        "browser_automation",
        {"action": "navigate", "url": "https://play.fables.gg/worlds"},
        ctx=ctx,
    )
    assert "explicit confirmation" in pending
    assert mock.navigations == []

    result = registry.run(
        "browser_automation",
        {
            "action": "navigate",
            "url": "https://play.fables.gg/worlds",
            "confirmed": True,
        },
        ctx=ctx,
    )
    assert "Navigated" in result
    click_result = registry.run(
        "browser_automation",
        {
            "action": "click",
            "selector": "button.world",
            "confirmed": True,
        },
        ctx=ctx,
    )
    assert "Clicked" in click_result
    assert mock.navigations == ["https://play.fables.gg/worlds"]
    assert mock.actions == [("click", "button.world")]
    browser.close()


def test_browser_action_reads_bounded_page_text_after_confirmation():
    registry = _registry()
    mock = MockBrowser(elements={"body"})
    mock.text_by_selector["body"] = "The page says hello."
    browser = BrowserAutomation(mock)
    browser.start()
    ctx = {"browser_automation_client": browser}

    pending = registry.run("browser_automation", {"action": "read"}, ctx=ctx)
    result = registry.run(
        "browser_automation",
        {"action": "read", "confirmed": True},
        ctx=ctx,
    )

    assert "explicit confirmation" in pending
    assert result == "The page says hello."
    browser.close()


def test_browser_action_can_click_exact_accessible_text_after_confirmation():
    registry = _registry()
    mock = MockBrowser(elements={"Rifiuta tutto"})
    browser = BrowserAutomation(mock)
    browser.start()
    ctx = {"browser_automation_client": browser}

    result = registry.run(
        "browser_automation",
        {"action": "click", "text": "Rifiuta tutto", "confirmed": True},
        ctx=ctx,
    )

    assert "Rifiuta tutto" in result
    assert mock.actions == [("click_text", "Rifiuta tutto")]
    browser.close()


def test_jarvis_live_requires_matching_confirmation_before_browser_action(
    monkeypatch,
):
    import main

    class FakeUI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, _text):
            pass

    mock = MockBrowser()
    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = FakeUI()
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "Vai su Fables"
    live._action_registry = _registry()
    live._terminal_agent = None
    live._browser_automation = BrowserAutomation(mock)
    live._computer_agent = None
    live._chat_orchestrator = None
    live._local_pending_confirmation = None
    live._observe_pattern_tool_result = lambda *_args: None
    monkeypatch.setattr(main, "require_policy_file", lambda: None)

    def call(call_id):
        return SimpleNamespace(
            id=call_id,
            name="browser_automation",
            args={"action": "navigate", "url": "https://play.fables.gg/worlds"},
        )

    async def run():
        pending = await live._execute_tool(call("browser-pending"))
        assert pending.response["result"] == "Ask the user for explicit confirmation"
        assert mock.navigations == []

        live._last_user_text = "Sì, confermo"
        completed = await live._execute_tool(
            SimpleNamespace(
                id="browser-confirmed",
                name="browser_automation",
                args={
                    "action": "navigate",
                    "url": "https://play.fables.gg/worlds",
                    "confirmed": True,
                },
            )
        )
        assert "Navigated" in completed.response["result"]

    asyncio.run(run())
    assert mock.navigations == ["https://play.fables.gg/worlds"]
    live._browser_automation.close()


def test_computer_agent_and_chatbot_plan_are_injected_into_action_registry(tmp_path, monkeypatch):
    import core.computer_use as computer_use
    import core.confirm as confirm

    registry = _registry()
    image = object()
    vision = ComputerVision(
        capture_provider=lambda: image,
        ocr_provider=lambda _image: {
            "text": ["Save"],
            "left": [10],
            "top": [20],
            "width": [40],
            "height": [10],
            "conf": ["90"],
        },
    )
    input_events = []
    computer_agent = ComputerAgent(
        vision=vision,
        computer_input=ComputerInput(
            dispatcher=lambda action, args: input_events.append((action, args)),
            sleeper=lambda _delay: None,
            random_delay=lambda low, _high: low,
        ),
        browser=BrowserAutomation(MockBrowser()),
    )
    confirmed_results = []

    def request_confirmation(_key, _title, _detail, run, **_kwargs):
        confirmed_results.append(run())
        return "[CONFIRMATION_PENDING] test confirmation"

    monkeypatch.setattr(confirm, "request", request_confirmation)
    monkeypatch.setattr(confirm, "pending_title", lambda: "")
    import core.computer_action_support as computer_action_support
    monkeypatch.setattr(computer_action_support, "audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(computer_use, "require_allowed_foreground", lambda: (1, "code.exe"))
    import actions.computer_task as computer_task_action
    monkeypatch.setattr(computer_task_action, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_task_action, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(computer_task_action, "require_allowed_foreground", lambda: (1, "code.exe"))
    computer_result = registry.run(
        "computer_task",
        {"task": "local: click Save", "confirmed": True},
        ctx={"computer_agent": computer_agent},
    )
    assert computer_result["pending"] is True
    assert "visible element 'Save'" in confirmed_results[0]
    assert input_events == [("click", (30, 25))]

    orchestrator = ChatOrchestrator(
        MemoryStore(tmp_path / "memory.sqlite3"),
        session_id="main-wiring",
        chatbots={"MockChatbot": MockChatbot()},
    )
    plan = registry.run(
        "chatbot_plan",
        {"topic": "botanica", "user_preferences": {"tone": "semplice"}},
        ctx={"chat_orchestrator": orchestrator},
    )
    assert '"topic": "botanica"' in plan
    assert "MockChatbot" in plan
    assert orchestrator.messages[0].source == "user"
    assert orchestrator.messages[-1].source == "jarvis"
