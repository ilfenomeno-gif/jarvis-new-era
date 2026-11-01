import asyncio

import pytest

from core.agent_loop import AgentLoop, resolve_max_steps


FOREGROUND = (123, "notepad.exe")


def _loop(
    tmp_path,
    plans,
    *,
    confirmed=True,
    max_steps=10,
    wait_results=None,
    kill_switch=lambda: False,
    foreground=lambda: FOREGROUND,
    uia_tree=lambda: {"controls": []},
):
    executed = []
    prompts = []
    captures = []
    waits = iter(wait_results or [])
    plan_values = iter(plans)

    def capture():
        captures.append(True)
        return "frame", {"left": 0, "top": 0}

    def planner(goal, elements, history, step, frame, timeout):
        return next(plan_values)

    def execute(parameters):
        executed.append(parameters)
        return {"result": "action completed"}

    def wait_for_change(**_kwargs):
        return next(waits, {"changed": True})

    loop = AgentLoop(
        max_steps=max_steps,
        confirm_session=lambda prompt: prompts.append(prompt) or confirmed,
        planner=planner,
        capture=capture,
        ocr=lambda **_kwargs: [{"text": "Test"}],
        uia_tree=uia_tree,
        execute_input=execute,
        wait_for_change=wait_for_change,
        foreground=foreground,
        hash_frame=lambda _frame: "0123456789abcdef",
        kill_switch=kill_switch,
        arm_kill_switch=lambda: None,
        log_dir=tmp_path / "logs",
    )
    return loop, executed, prompts, captures


def test_run_without_session_confirmation_is_cancelled(tmp_path):
    loop, executed, prompts, captures = _loop(
        tmp_path,
        [{"action": "done", "reason": "already complete"}],
        confirmed=False,
    )

    result = asyncio.run(loop.run("Complete the task"))

    assert result == {"result": "cancelled"}
    assert not executed
    assert not captures
    assert len(prompts) == 1
    assert "massimo di 10 azioni" in prompts[0]
    assert "Ctrl+Alt+Esc" in prompts[0]
    assert "Gemini cloud" in prompts[0]


def test_run_succeeds_when_gemini_returns_done_on_first_step(tmp_path):
    loop, executed, _prompts, captures = _loop(
        tmp_path,
        [{"action": "done", "reason": "The requested result is visible."}],
    )

    result = asyncio.run(loop.run("Inspect the current page"))

    assert result == {
        "result": "success",
        "steps": 0,
        "reason": "The requested result is visible.",
    }
    assert not executed
    assert captures == [True]
    assert len(list((tmp_path / "logs").glob("agent_loop_*.log"))) == 1


def test_run_executes_three_actions_then_succeeds(tmp_path):
    plans = [
        {"action": "type", "target": "focused field", "value": "one"},
        {"action": "hotkey", "target": "focused field", "value": "ctrl+a"},
        {"action": "scroll", "target": None, "value": "down"},
        {"action": "done", "reason": "Finished."},
    ]
    loop, executed, _prompts, _captures = _loop(
        tmp_path,
        plans,
        wait_results=[{"changed": True}] * 3,
    )

    result = asyncio.run(loop.run("Fill and inspect the form"))

    assert result["result"] == "success"
    assert result["steps"] == 3
    assert [item["action"] for item in executed] == ["type", "hotkey", "scroll"]
    assert all(item["_expected_window"] == FOREGROUND[0] for item in executed)


def test_run_stops_after_consecutive_no_change_steps(tmp_path):
    plans = [
        {"action": "click", "target": {"x": 20, "y": 30}, "value": None},
        {"action": "click", "target": {"bbox": [10, 10, 20, 20]}, "value": None},
        {"action": "click", "target": "Save", "value": None},
    ]
    loop, executed, _prompts, _captures = _loop(
        tmp_path,
        plans,
        wait_results=[{"changed": False}] * 3,
    )

    result = asyncio.run(loop.run("Save the document"))

    assert result["result"] == "no_change"
    assert result["steps"] == 3
    assert len(executed) == 3
    assert executed[0]["action"] == "click"
    assert (executed[0]["x"], executed[0]["y"]) == (20, 30)
    assert (executed[1]["x"], executed[1]["y"]) == (20, 20)
    assert executed[2]["action"] == "click_text"


def test_run_stops_immediately_when_kill_switch_is_set(tmp_path):
    loop, executed, _prompts, captures = _loop(
        tmp_path,
        [{"action": "type", "target": "focused field", "value": "unsafe"}],
        kill_switch=lambda: True,
    )

    result = asyncio.run(loop.run("Type text"))

    assert result == {"result": "killed"}
    assert not executed
    assert not captures


def test_run_stops_when_foreground_process_is_not_allowlisted(tmp_path):
    def denied_foreground():
        raise PermissionError("Input blocked for powershell.exe")

    loop, executed, _prompts, captures = _loop(
        tmp_path,
        [{"action": "done"}],
        foreground=denied_foreground,
    )

    result = asyncio.run(loop.run("Inspect the terminal"))

    assert result["result"] == "failed"
    assert "powershell.exe" in result["reason"]
    assert not executed
    assert not captures


def test_run_honors_the_hard_maximum_step_limit(tmp_path):
    action = {"action": "type", "target": "focused field", "value": "x"}
    loop, executed, _prompts, _captures = _loop(
        tmp_path,
        [action] * 2,
        max_steps=2,
        wait_results=[{"changed": True}] * 2,
    )

    result = asyncio.run(loop.run("Keep typing"))

    assert result["result"] == "max_steps"
    assert result["steps"] == 2
    assert len(executed) == 2


def test_environment_max_steps_is_a_hard_cap(monkeypatch):
    monkeypatch.setenv("JARVIS_AGENT_MAX_STEPS", "3")

    assert resolve_max_steps() == 3
    assert resolve_max_steps(10) == 3
    assert resolve_max_steps(2) == 2
    with pytest.raises(ValueError, match="between 1 and"):
        monkeypatch.setenv("JARVIS_AGENT_MAX_STEPS", "0")
        resolve_max_steps()


def test_agent_loop_action_is_registered_as_a_write_tool():
    from pathlib import Path

    from core.action_loader import discover_actions

    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions",
        logger=lambda _message: None,
    )
    declarations = {
        declaration["name"]: declaration
        for declaration in registry.get_tool_declarations()
    }

    assert registry.risk_class("agent_loop") == "write"
    assert "agent_loop" in declarations
    assert {"goal", "max_steps"} <= set(
        declarations["agent_loop"]["parameters"]["properties"]
    )


def test_foreground_change_before_action_stops_without_input(tmp_path):
    current = {"foreground": FOREGROUND}

    def planner(*_args):
        current["foreground"] = (456, "chrome.exe")
        return {"action": "click", "target": {"x": 20, "y": 30}}

    loop, executed, _prompts, _captures = _loop(
        tmp_path,
        [],
        foreground=lambda: current["foreground"],
    )
    loop._planner = planner

    result = asyncio.run(loop.run("Click the button"))

    assert result["result"] == "failed"
    assert "foreground window changed" in result["reason"]
    assert not executed


def test_foreground_change_during_uia_collection_stops_before_planning(tmp_path):
    current = {"foreground": FOREGROUND}
    planned = []

    def collect_uia():
        current["foreground"] = (456, "chrome.exe")
        return {"controls": []}

    loop, executed, _prompts, _captures = _loop(
        tmp_path,
        [{"action": "click", "target": {"x": 20, "y": 30}}],
        foreground=lambda: current["foreground"],
        uia_tree=collect_uia,
    )
    loop._planner = lambda *_args: planned.append(True)

    result = asyncio.run(loop.run("Click the button"))

    assert result["result"] == "failed"
    assert "foreground window changed" in result["reason"]
    assert not planned
    assert not executed


def test_kill_switch_during_loop_prevents_the_next_action(tmp_path):
    state = {"stopped": False}
    action = {"action": "type", "target": "focused field", "value": "one"}

    def wait_for_change(**_kwargs):
        state["stopped"] = True
        return {"changed": True}

    loop, executed, _prompts, _captures = _loop(
        tmp_path,
        [action, action],
        max_steps=2,
        wait_results=[{"changed": True}],
        kill_switch=lambda: state["stopped"],
    )
    loop._wait_for_change = wait_for_change

    result = asyncio.run(loop.run("Type text twice"))

    assert result["result"] == "killed"
    assert len(executed) == 1


@pytest.mark.parametrize(
    "changed_args",
    [
        {"goal": "Submit the form", "max_steps": 3},
        {"goal": "Fill the form", "max_steps": 4},
    ],
)
def test_session_approval_is_bound_to_goal_and_max_steps(monkeypatch, changed_args):
    import main
    from types import SimpleNamespace

    from core import computer_use
    from main import JarvisLive

    class FakeUI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, _text):
            pass

    class ActionRegistry:
        def __init__(self):
            self.calls = []

        def has(self, name):
            return name == "agent_loop"

        def run(self, name, args, ctx=None):
            self.calls.append((name, args.copy()))
            return '{"result":"success"}'

    live = JarvisLive.__new__(JarvisLive)
    live.ui = FakeUI()
    live._brain_router = SimpleNamespace(backend="local")
    live._asst_name = "JARVIS"
    live._last_user_text = "Automatizza e completa l'obiettivo"
    live._local_pending_confirmation = None
    live._action_registry = ActionRegistry()
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: (17, "notepad.exe"),
    )

    async def execute(call, user_confirmed=False):
        return await live._execute_tool(call, user_confirmed=user_confirmed)

    first = asyncio.run(execute(SimpleNamespace(
        id="agent-call-1",
        name="agent_loop",
        args={
            "goal": "Fill the form",
            "max_steps": 3,
            "confirmed": True,
            "_session_approved": True,
        },
    )))
    assert first.response["result"] == "Ask the user for explicit confirmation"
    assert "massimo di 3 azioni" in first.response["prompt"]
    assert live._local_pending_confirmation == {
        "id": "agent-call-1",
        "name": "agent_loop",
        "args": {"goal": "Fill the form", "max_steps": 3},
        "window_handle": 17,
        "process_name": "notepad.exe",
    }
    assert live._action_registry.calls == []

    live._last_user_text = "Sì, procedo"
    changed = asyncio.run(execute(SimpleNamespace(
        id="agent-call-2",
        name="agent_loop",
        args=changed_args,
    )))
    assert changed.response["result"] == "cancelled"
    assert "new session confirmation" in changed.response["reason"]
    assert live._local_pending_confirmation is None
    assert live._action_registry.calls == []


def test_session_approval_executes_only_the_bound_agent_request(monkeypatch):
    import main
    from types import SimpleNamespace

    from core import computer_use
    from main import JarvisLive

    class FakeUI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, _text):
            pass

    class ActionRegistry:
        def __init__(self):
            self.calls = []

        def has(self, name):
            return name == "agent_loop"

        def run(self, name, args, ctx=None):
            self.calls.append((name, args.copy()))
            return '{"result":"success"}'

    live = JarvisLive.__new__(JarvisLive)
    live.ui = FakeUI()
    live._brain_router = SimpleNamespace(backend="local")
    live._asst_name = "JARVIS"
    live._last_user_text = "Automatizza questo obiettivo"
    live._local_pending_confirmation = None
    live._action_registry = ActionRegistry()
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: (17, "notepad.exe"),
    )

    async def execute(call, user_confirmed=False):
        return await live._execute_tool(call, user_confirmed=user_confirmed)

    request = {"goal": "Fill the form", "max_steps": 3}
    asyncio.run(execute(SimpleNamespace(
        id="agent-call-1",
        name="agent_loop",
        args=request,
    )))
    live._last_user_text = "Sì, procedo"
    result = asyncio.run(execute(SimpleNamespace(
        id="agent-call-2",
        name="agent_loop",
        args={**request, "confirmed": True},
    )))

    assert result.response == {"result": '{"result":"success"}'}
    assert live._action_registry.calls == [
        (
            "agent_loop",
            {
                "goal": "Fill the form",
                "max_steps": 3,
                "_session_approved": True,
            },
        )
    ]
    assert live._local_pending_confirmation is None


def test_local_confirmation_preserves_focus_binding_and_runs_agent_once(monkeypatch):
    import main
    from types import SimpleNamespace

    from core import computer_use
    from main import JarvisLive

    class FakeUI:
        muted = False

        def __init__(self):
            self.logs = []

        def set_state(self, _state):
            pass

        def write_log(self, text):
            self.logs.append(text)

    class FakeRouter:
        backend = "local"

        def stream_chat(self, _messages, tools=None):
            return iter([
                {
                    "type": "tool_call",
                    "id": "agent-local-call",
                    "name": "agent_loop",
                    "args": {"goal": "Fill the form", "max_steps": 2},
                },
                {"type": "done"},
            ])

    class ActionRegistry:
        def __init__(self):
            self.calls = []

        def has(self, name):
            return name == "agent_loop"

        def run(self, name, args, ctx=None):
            self.calls.append((name, args.copy()))
            return '{"result":"success"}'

    live = JarvisLive.__new__(JarvisLive)
    live.ui = FakeUI()
    live._brain_router = FakeRouter()
    live._asst_name = "JARVIS"
    live._local_messages = [{"role": "system", "content": "test"}]
    live._local_chat_lock = asyncio.Lock()
    live._local_pending_confirmation = None
    live._computer_input_confirmation_available = False
    live._session_log = []
    live._action_registry = ActionRegistry()
    live._select_local_tool_declarations = lambda _text: [{
        "name": "agent_loop",
        "risk_class": "write",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING"},
                "max_steps": {"type": "INTEGER"},
            },
            "required": ["goal"],
        },
    }]
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: (17, "notepad.exe"),
    )

    asyncio.run(live._handle_local_text("Automatizza questo obiettivo"))

    assert live._local_pending_confirmation == {
        "id": "agent-local-call",
        "name": "agent_loop",
        "args": {"goal": "Fill the form", "max_steps": 2},
        "window_handle": 17,
        "process_name": "notepad.exe",
    }
    assert not live._action_registry.calls

    asyncio.run(live._handle_local_text("Sì, procedo"))

    assert live._local_pending_confirmation is None
    assert live._action_registry.calls == [
        (
            "agent_loop",
            {
                "goal": "Fill the form",
                "max_steps": 2,
                "_session_approved": True,
            },
        )
    ]
    assert any("success" in line for line in live.ui.logs)
