import asyncio
from types import SimpleNamespace

from main import JarvisLive


class FakeUI:
    muted = False

    def __init__(self):
        self.logs = []
        self.states = []

    def set_state(self, state):
        self.states.append(state)

    def write_log(self, text):
        self.logs.append(text)


class FakeRouter:
    backend = "local"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def stream_chat(self, messages, tools=None):
        self.calls.append((messages.copy(), tools))
        return next(self.responses)

    def model_name(self):
        return "qwen2.5:7b"

    def switch(self, backend):
        self.backend = backend


def _live(router):
    live = JarvisLive.__new__(JarvisLive)
    live.ui = FakeUI()
    live._brain_router = router
    live._local_messages = [{"role": "system", "content": "test system prompt"}]
    live._local_chat_lock = asyncio.Lock()
    live._local_pending_confirmation = None
    live._asst_name = "JARVIS"
    live._session_log = []
    live._select_local_tool_declarations = lambda _text: [{
        "name": "open_app",
        "description": "Open an app",
        "parameters": {
            "type": "OBJECT",
            "properties": {"app_name": {"type": "STRING"}},
            "required": ["app_name"],
        },
    }]
    return live


def test_local_text_runs_model_tool_call_and_logs_final_response():
    router = FakeRouter([
        [
            {
                "type": "tool_call",
                "id": "call-1",
                "name": "open_app",
                "args": {"app_name": "Notepad"},
            },
            {"type": "done", "full_text": ""},
        ],
        [
            {"type": "content", "text": "Notepad aperto."},
            {"type": "done", "full_text": "Notepad aperto."},
        ],
    ])
    live = _live(router)
    executed = []

    async def execute_tool(call):
        executed.append((call.id, call.name, call.args))
        return SimpleNamespace(response={"result": "opened"})

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Apri Notepad"))

    assert executed == [("call-1", "open_app", {"app_name": "Notepad"})]
    assert router.calls[0][1][0]["function"]["parameters"]["type"] == "object"
    assert live.ui.logs == ["JARVIS: Notepad aperto."]
    assert live._local_messages[-1] == {
        "role": "assistant",
        "content": "Notepad aperto.",
    }


def test_local_model_cannot_run_a_tool_not_selected_for_the_request():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-1",
            "name": "quick_notes",
            "args": {"text": "nota non richiesta"},
        },
        {"type": "done", "full_text": ""},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: []
    executed = []

    async def execute_tool(call):
        executed.append(call.name)
        return SimpleNamespace(response={"result": "unexpected"})

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Dimmi una curiosità"))

    assert router.calls[0][1] == []
    assert executed == []
    assert live.ui.logs == [
        "JARVIS: Non posso eseguire uno strumento non pertinente alla richiesta."
    ]


def test_local_state_changing_tool_is_not_repeated_in_one_request():
    router = FakeRouter([
        [
            {
                "type": "tool_call",
                "id": "call-1",
                "name": "quick_notes",
                "args": {"text": "prima nota"},
            },
            {"type": "done", "full_text": ""},
        ],
        [
            {
                "type": "tool_call",
                "id": "call-2",
                "name": "quick_notes",
                "args": {"text": "nota duplicata"},
            },
            {"type": "done", "full_text": ""},
        ],
    ])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [{"name": "quick_notes"}]
    executed = []

    async def execute_tool(call):
        executed.append(call.args["text"])
        return SimpleNamespace(response={"result": "Nota salvata."})

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Prendi nota"))

    assert executed == ["prima nota"]
    assert live.ui.logs == [
        "JARVIS: Ho interrotto un tentativo di ripetere la stessa azione."
    ]


def test_local_explicit_app_launch_does_not_require_redundant_confirmation():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-1",
            "name": "app_launcher",
            "args": {"name": "Notepad", "confirmed": True},
        },
        {"type": "done", "full_text": ""},
    ], [
        {"type": "content", "text": "Notepad aperto."},
        {"type": "done", "full_text": "Notepad aperto."},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [{
        "name": "app_launcher",
        "risk_class": "destructive",
    }]
    executed = []

    async def execute_tool(call):
        executed.append((call.name, call.args.copy()))
        if call.args.get("confirmed") is True:
            return SimpleNamespace(response={"result": "Launch completed for Notepad."})
        return SimpleNamespace(response={
            "result": (
                "Action 'app_launcher' is destructive. Ask the user for explicit "
                "confirmation, then call it again with confirmed=true."
            )
        })

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Apri il blocco note"))
    assert live._local_pending_confirmation is None
    assert executed == [("app_launcher", {"name": "Notepad", "confirmed": True})]
    assert live.ui.logs[-1] == "JARVIS: Notepad aperto."


def test_local_ambiguous_app_launch_still_requires_separate_confirmation():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-1",
            "name": "app_launcher",
            "args": {"name": "Notepad", "confirmed": True},
        },
        {"type": "done", "full_text": ""},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [{
        "name": "app_launcher",
        "risk_class": "destructive",
    }]
    executed = []

    async def execute_tool(call):
        executed.append((call.name, call.args.copy()))
        if call.args.get("confirmed") is True:
            return SimpleNamespace(response={"result": "Launch completed for Notepad."})
        return SimpleNamespace(response={
            "result": (
                "Action 'app_launcher' is destructive. Ask the user for explicit "
                "confirmation, then call it again with confirmed=true."
            )
        })

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Il blocco note sarebbe utile"))
    assert live._local_pending_confirmation == {
        "id": "call-1",
        "name": "app_launcher",
        "args": {"name": "Notepad"},
    }
    assert executed == [("app_launcher", {"name": "Notepad"})]

    asyncio.run(live._handle_local_text("Sì, confermo"))

    assert executed == [
        ("app_launcher", {"name": "Notepad"}),
        ("app_launcher", {"name": "Notepad", "confirmed": True}),
    ]
    assert live._local_pending_confirmation is None
    assert live.ui.logs[-1] == "JARVIS: Launch completed for Notepad."


def test_local_compound_open_and_type_runs_with_one_explicit_request():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-input",
            "name": "computer_input",
            "args": {"action": "type", "text": "model-proposed text"},
        },
        {
            "type": "tool_call",
            "id": "call-app",
            "name": "app_launcher",
            "args": {"name": "Notepad"},
        },
        {"type": "done", "full_text": ""},
    ], [
        {"type": "content", "text": "Ho scritto ciao nel Blocco note."},
        {"type": "done", "full_text": "Ho scritto ciao nel Blocco note."},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [
        {"name": "app_launcher", "risk_class": "destructive"},
        {"name": "computer_input", "risk_class": "destructive"},
    ]
    executed = []

    async def execute_tool(call):
        executed.append((call.name, call.args.copy()))
        if call.name == "app_launcher":
            return SimpleNamespace(response={"result": "Launch completed for Notepad."})
        return SimpleNamespace(response={"result": "Typed 4 characters."})

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Apri blocco note e scrivi ciao"))

    assert executed == [
        ("app_launcher", {"name": "Notepad", "confirmed": True}),
        (
            "computer_input",
            {"action": "type_text", "text": "ciao", "confirmed": True},
        ),
    ]
    assert live._local_pending_confirmation is None


def test_local_compound_typing_stops_if_the_app_does_not_get_focus():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-input",
            "name": "computer_input",
            "args": {"action": "type", "text": "ciao"},
        },
        {
            "type": "tool_call",
            "id": "call-app",
            "name": "app_launcher",
            "args": {"name": "Notepad"},
        },
        {"type": "done", "full_text": ""},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [
        {"name": "app_launcher", "risk_class": "destructive"},
        {"name": "computer_input", "risk_class": "destructive"},
    ]
    executed = []

    async def execute_tool(call):
        executed.append((call.name, call.args.copy()))
        return SimpleNamespace(response={
            "result": (
                "Could not continue with Notepad: its window did not become "
                "foreground within 3 seconds."
            )
        })

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Apri blocco note e scrivi ciao"))

    assert executed == [("app_launcher", {"name": "Notepad", "confirmed": True})]
    assert live._local_pending_confirmation is None


def test_local_write_into_named_app_runs_without_a_confirmation_round():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-input",
            "name": "computer_input",
            "args": {"action": "type", "text": "model-proposed text"},
        },
        {"type": "done", "full_text": ""},
    ], [
        {"type": "content", "text": "Ho scritto ciao nel Blocco note."},
        {"type": "done", "full_text": "Ho scritto ciao nel Blocco note."},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [{
        "name": "computer_input",
        "risk_class": "destructive",
    }]
    executed = []

    async def execute_tool(call):
        executed.append((call.name, call.args.copy()))
        return SimpleNamespace(response={"result": "Typed 4 characters."})

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Scrivi ciao in blocco note"))

    assert executed == [
        (
            "computer_input",
            {"action": "type_text", "text": "ciao", "confirmed": True},
        )
    ]
    assert live._local_pending_confirmation is None


def test_execute_tool_accepts_only_the_explicit_named_app_text_input(monkeypatch):
    import main
    from core import computer_use

    live = _live(FakeRouter([]))
    live._last_user_text = "Scrivi ciao in blocco note"
    executed = []

    class ActionRegistry:
        def has(self, name):
            return name == "computer_input"

        def run(self, name, args, ctx=None):
            executed.append((name, args.copy()))
            return {"result": "Typed 4 characters.", "process": "notepad.exe"}

    live._action_registry = ActionRegistry()
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: (17, "notepad.exe"),
    )

    result = asyncio.run(live._execute_tool(SimpleNamespace(
        id="call-input",
        name="computer_input",
        args={"action": "type", "text": "model-proposed text"},
    )))

    assert result.response["result"] == {
        "result": "Typed 4 characters.",
        "process": "notepad.exe",
    }
    assert executed == [(
        "computer_input",
        {
            "action": "type_text",
            "text": "ciao",
            "confirmed": True,
            "_expected_window": 17,
            "_expected_process": "notepad.exe",
        },
    )]
    assert live._local_pending_confirmation is None


def test_local_unscoped_or_incomplete_type_requests_are_not_auto_confirmed():
    for text in ("Scrivi qualcosa", "Apri blocco note e scrivi"):
        router = FakeRouter([[
            {
                "type": "tool_call",
                "id": "call-input",
                "name": "computer_input",
                "args": {"action": "type", "text": "suggested text"},
            },
            {"type": "done", "full_text": ""},
        ]])
        live = _live(router)
        live._select_local_tool_declarations = lambda _text: [{
            "name": "computer_input",
            "risk_class": "destructive",
        }]
        executed = []

        async def execute_tool(call):
            executed.append((call.name, call.args.copy()))
            return SimpleNamespace(response={
                "result": (
                    "Ask the user for explicit confirmation before typing."
                )
            })

        live._execute_tool = execute_tool
        asyncio.run(live._handle_local_text(text))

        assert executed == [
            ("computer_input", {"action": "type", "text": "suggested text"})
        ]
        assert live._local_pending_confirmation is not None
        assert live._local_pending_confirmation["name"] == "computer_input"


def test_local_terminal_command_runs_only_after_separate_confirmation():
    router = FakeRouter([[
        {
            "type": "tool_call",
            "id": "call-terminal",
            "name": "terminal_run",
            "args": {"command": "echo hello", "confirmed": True},
        },
        {"type": "done", "full_text": ""},
    ]])
    live = _live(router)
    live._select_local_tool_declarations = lambda _text: [{
        "name": "terminal_run",
        "risk_class": "write",
    }]
    executed = []

    async def execute_tool(call, **kwargs):
        executed.append((call.name, call.args.copy()))
        if kwargs:
            executed[-1] = (call.name, call.args.copy(), kwargs)
        if call.args.get("confirmed") is True:
            return SimpleNamespace(response={
                "stdout": "hello\n",
                "stderr": "",
                "returncode": 0,
            })
        return SimpleNamespace(response={
            "result": "Ask the user for explicit confirmation",
            "command": call.args["command"],
        })

    live._execute_tool = execute_tool
    asyncio.run(live._handle_local_text("Esegui il comando echo hello"))

    assert executed == [("terminal_run", {"command": "echo hello"})]
    assert live._local_pending_confirmation == {
        "id": "call-terminal",
        "name": "terminal_run",
        "args": {"command": "echo hello"},
    }
    assert "echo hello" in live.ui.logs[-1]

    asyncio.run(live._handle_local_text("Sì, confermo"))

    assert executed == [
        ("terminal_run", {"command": "echo hello"}),
        (
            "terminal_run",
            {"command": "echo hello", "confirmed": True},
            {"user_confirmed": True},
        ),
    ]
    assert live._local_pending_confirmation is None
    assert '"stdout": "hello\\n"' in live.ui.logs[-1]


def test_terminal_tool_rejects_model_confirmation_and_binds_command_to_user_approval(
    monkeypatch,
):
    import main

    live = _live(FakeRouter([]))
    live._last_user_text = "Esegui il comando echo hello"
    executed = []

    class ActionRegistry:
        def has(self, name):
            return name == "terminal_run"

        def run(self, name, args, ctx=None):
            executed.append((name, args.copy()))
            return {"stdout": "hello\n", "stderr": "", "returncode": 0}

    live._action_registry = ActionRegistry()
    monkeypatch.setattr(main, "require_policy_file", lambda: None)

    async def run():
        pending = await live._execute_tool(SimpleNamespace(
            id="call-terminal",
            name="terminal_run",
            args={"command": "echo hello", "confirmed": True},
        ))
        assert pending.response == {
            "result": "Ask the user for explicit confirmation",
            "command": "echo hello",
        }
        assert executed == []
        assert live._local_pending_confirmation == {
            "id": "call-terminal",
            "name": "terminal_run",
            "args": {"command": "echo hello"},
        }

        live._last_user_text = "Sì, confermo"
        result = await live._execute_tool(SimpleNamespace(
            id="call-confirmed",
            name="terminal_run",
            args={"command": "echo hello", "confirmed": True},
        ))
        assert result.response == {
            "stdout": "hello\n",
            "stderr": "",
            "returncode": 0,
        }

    asyncio.run(run())
    assert executed == [
        ("terminal_run", {"command": "echo hello", "confirmed": True})
    ]


def test_local_voice_transcript_is_routed_to_local_model():
    live = _live(FakeRouter([]))
    handled = []

    async def handle_local_text(text):
        handled.append(text)

    live._handle_local_text = handle_local_text

    async def run():
        assert live._route_voice_transcript("Dimmi una curiosità")
        await asyncio.sleep(0)

    asyncio.run(run())
    assert handled == ["Dimmi una curiosità"]


def test_switching_to_cloud_cancels_pending_local_confirmation():
    live = _live(FakeRouter([]))
    live._local_pending_confirmation = {
        "id": "call-1",
        "name": "app_launcher",
        "args": {"name": "Notepad"},
    }

    assert live._route_voice_transcript("Torna al cloud")
    assert live._brain_router.backend == "gemini"
    assert live._local_pending_confirmation is None
