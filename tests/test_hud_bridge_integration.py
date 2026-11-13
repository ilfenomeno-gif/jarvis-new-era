from __future__ import annotations

import asyncio
import json
import socket
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEngineSettings

import main
import core.gev_chrome
import core.hud_bridge
from core.hud_bridge import HudBridge
from ui import MainWindow, _configure_iris_page, _HudBrowserPage


class _Hud:
    def __init__(self):
        self.chat = []
        self.plugins = []
        self.speaking = []

    def push_chat(self, role, text):
        self.chat.append((role, text))

    def set_plugins(self, plugins):
        self.plugins = list(plugins)

    def set_speaking(self, on, level=None):
        self.speaking.append((on, level))


def test_hud_app_window_opens_normal_chrome_tab(monkeypatch):
    opened = []
    bridge = HudBridge(port=8765)
    monkeypatch.setattr(core.hud_bridge.sys, "platform", "win32")
    monkeypatch.setattr(
        core.gev_chrome, "open_chrome_url", lambda url: opened.append(url)
    )
    monkeypatch.setattr(
        core.hud_bridge.webbrowser,
        "open",
        lambda _url: (_ for _ in ()).throw(
            AssertionError("Chrome should be opened directly when available")
        ),
    )

    bridge.open_window("app")

    assert opened == ["http://127.0.0.1:8765/"]


def _live_with_fake_session(monkeypatch):
    sent = []

    class _Session:
        async def send_client_content(self, **payload):
            sent.append(payload)

    class _CompletedFuture:
        def __init__(self, coroutine):
            self.error = None
            try:
                asyncio.run(coroutine)
            except Exception as exc:
                self.error = exc

        def add_done_callback(self, callback):
            callback(self)

        def result(self):
            if self.error is not None:
                raise self.error

    jarvis = object.__new__(main.JarvisLive)
    jarvis._hud = _Hud()
    jarvis._schedule_geo_route = lambda _text, **_kwargs: False
    jarvis._loop = object()
    jarvis.session = _Session()
    jarvis._session_ready_event = asyncio.Event()
    jarvis._session_ready_event.set()
    jarvis._live_send_lock = asyncio.Lock()
    jarvis._brain_router = SimpleNamespace(backend="gemini")
    jarvis._observe_pattern_feedback = lambda _text: None
    jarvis._schedule_geo_route = lambda _text, **_kwargs: False
    jarvis._prompt_router = SimpleNamespace(
        instruction_for=lambda _text: "istruzione dinamica"
    )
    monkeypatch.setattr(main.pattern_learner, "get_hints_for", lambda _text: "")
    monkeypatch.setattr(
        main.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, _loop: _CompletedFuture(coroutine),
    )
    return jarvis, sent


def test_hud_message_uses_live_session_without_echoing_user_message(monkeypatch):
    jarvis, sent = _live_with_fake_session(monkeypatch)

    jarvis._on_hud_message("Ciao Jarvis")

    assert jarvis._hud.chat == []
    assert sent == [
        {
            "turns": {
                "parts": [
                    {"text": "istruzione dinamica"},
                    {"text": "Ciao Jarvis"},
                ]
            },
            "turn_complete": True,
        }
    ]


def test_desktop_text_command_is_mirrored_to_hud(monkeypatch):
    jarvis, _sent = _live_with_fake_session(monkeypatch)

    jarvis._on_text_command("Apri il browser")

    assert jarvis._hud.chat == [("user", "Apri il browser")]


def test_iris_hud_geographic_command_never_launches_chrome():
    hud = _Hud()
    logs = []
    jarvis = object.__new__(main.JarvisLive)
    jarvis._hud = hud
    jarvis._asst_name = "JARVIS"
    jarvis.session = None
    jarvis._loop = None
    jarvis.ui = SimpleNamespace(
        show_gev_chrome=lambda: (_ for _ in ()).throw(
            AssertionError("GEV navigation must not launch Chrome")
        ),
        write_log=logs.append,
    )
    jarvis._try_handle_fables_text = lambda _text: False
    jarvis._try_handle_copilot_handoff = lambda _text: False

    jarvis._on_hud_message("Vai a Roma")

    assert hud.chat == [
        ("system", "GEV non è connessa: impossibile navigare sulla mappa."),
    ]
    assert logs == [
        "ERR: GEV non è connessa: impossibile navigare sulla mappa."
    ]


def test_live_text_command_waits_for_reconnect_and_uses_ready_session():
    async def scenario():
        old_sent = []
        new_sent = []

        class _Session:
            def __init__(self, sent):
                self.sent = sent

            async def send_client_content(self, **payload):
                self.sent.append(payload)

        jarvis = object.__new__(main.JarvisLive)
        jarvis.session = _Session(old_sent)
        jarvis._session_ready_event = asyncio.Event()
        jarvis._live_send_lock = asyncio.Lock()
        pending = asyncio.create_task(
            jarvis._send_live_text_content(
                {"parts": [{"text": "second prompt"}]}
            )
        )
        await asyncio.sleep(0)

        jarvis.session = _Session(new_sent)
        jarvis._session_ready_event.set()
        await pending

        assert old_sent == []
        assert new_sent == [{
            "turns": {"parts": [{"text": "second prompt"}]},
            "turn_complete": True,
        }]

    asyncio.run(scenario())


def test_live_text_commands_are_sent_sequentially():
    async def scenario():
        send_started = []
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        class _Session:
            async def send_client_content(self, *, turns, turn_complete):
                send_started.append(turns["parts"][0]["text"])
                if len(send_started) == 1:
                    await release_first.wait()
                else:
                    second_started.set()

        jarvis = object.__new__(main.JarvisLive)
        jarvis.session = _Session()
        jarvis._session_ready_event = asyncio.Event()
        jarvis._session_ready_event.set()
        jarvis._live_send_lock = asyncio.Lock()

        first = asyncio.create_task(
            jarvis._send_live_text_content({"parts": [{"text": "first"}]})
        )
        await asyncio.sleep(0)
        second = asyncio.create_task(
            jarvis._send_live_text_content({"parts": [{"text": "second"}]})
        )
        await asyncio.sleep(0)

        assert send_started == ["first"]
        assert not second_started.is_set()

        release_first.set()
        await asyncio.gather(first, second)

        assert send_started == ["first", "second"]
        assert second_started.is_set()

    asyncio.run(scenario())


def test_live_chat_send_error_is_reported_to_log_and_hud():
    messages = []
    idle_states = []
    jarvis = object.__new__(main.JarvisLive)
    jarvis.ui = SimpleNamespace(write_log=messages.append)
    jarvis._hud = _Hud()
    jarvis._set_task_idle = idle_states.append

    class _FailedFuture:
        def result(self):
            raise RuntimeError("session closed")

    jarvis._report_live_chat_error(_FailedFuture())

    assert any("session closed" in message for message in messages)
    assert jarvis._hud.chat == [
        (
            "system",
            "JARVIS non ha potuto inviare il messaggio alla sessione Live. "
            "Controllare la connessione e riprovare.",
        )
    ]
    assert idle_states == [True]


def test_plugin_toggle_persists_state_updates_hud_and_reconnects(monkeypatch):
    enabled = {"calendar": True}
    jarvis = object.__new__(main.JarvisLive)
    jarvis._hud = _Hud()
    jarvis._plugin_registry = SimpleNamespace(
        list_for_ui=lambda: [
            {
                "name": "calendar",
                "valid": True,
                "enabled": enabled["calendar"],
            },
            {"name": "broken", "valid": False, "enabled": False},
        ]
    )
    jarvis.ui = SimpleNamespace(write_log=lambda _message: None)
    jarvis.session = object()
    reconnects = []
    jarvis.request_reconnect = lambda **kwargs: reconnects.append(kwargs)

    def save_plugin_enabled(name, value):
        enabled[name] = value

    monkeypatch.setattr(
        "memory.config_manager.save_plugin_enabled",
        save_plugin_enabled,
    )

    jarvis._on_hud_plugin_toggle("calendar")

    assert enabled["calendar"] is False
    assert jarvis._hud.plugins == [{"name": "calendar", "active": False}]
    assert reconnects == [
        {"keep_context": True, "reason": "HUD plugin calendar disabled"}
    ]


def test_speaking_level_is_forwarded_to_hud():
    jarvis = object.__new__(main.JarvisLive)
    jarvis._hud = _Hud()
    jarvis._speaking_lock = threading.Lock()
    jarvis._is_speaking = False
    jarvis.ui = SimpleNamespace(
        muted=False,
        set_state=lambda _state: None,
    )

    jarvis.set_speaking(True, level=0.65)

    assert jarvis._hud.speaking == [(True, 0.65)]


def test_task_completion_is_injected_after_idle_and_releases_idle_state():
    from core.task_manager import Task

    async def scenario():
        sent = []

        class _Session:
            async def send_client_content(self, **payload):
                sent.append(payload)

        jarvis = object.__new__(main.JarvisLive)
        jarvis._task_idle_event = asyncio.Event()
        jarvis._task_idle_lock = threading.Lock()
        jarvis._task_idle_state = False
        jarvis._loop = asyncio.get_running_loop()
        jarvis.session = _Session()
        jarvis._hud = SimpleNamespace(say=lambda *_args, **_kwargs: None)
        jarvis.ui = SimpleNamespace(write_log=lambda _message: None)
        task = Task(
            task_id="a" * 32,
            role="writer",
            prompt="Write a poem",
            status="done",
            created_at=1.0,
            updated_at=2.0,
            started_at=1.0,
            finished_at=2.0,
            progress=1.0,
            progress_message="File pronto",
            notify_when_done=True,
            timeout_seconds=30.0,
            result="Written to: poem.txt",
            error=None,
            revision=2,
        )

        pending = asyncio.create_task(jarvis._notify_task_group([task]))
        await asyncio.sleep(0)
        assert sent == []

        jarvis._set_task_idle(True)
        await pending

        assert len(sent) == 1
        instruction = sent[0]["turns"]["parts"][0]["text"]
        assert "writer: completato" in instruction
        assert "risultato completo disponibile" in instruction
        assert "Written to: poem.txt" not in instruction
        assert not jarvis._task_idle_event.is_set()

    asyncio.run(scenario())


def test_task_meta_tools_survive_live_and_local_tool_routing(monkeypatch):
    from core.task_orchestrator import TASK_TOOL_DECLARATIONS

    jarvis = object.__new__(main.JarvisLive)
    jarvis._recent_user_texts = ["Explain atoms"]
    jarvis._tools_used = set()
    jarvis._tool_router = SimpleNamespace(
        select=lambda *_args: [],
        select_for_request=lambda *_args: [],
    )
    jarvis._all_tool_declarations = lambda: []
    monkeypatch.setenv("JARVIS_TOOL_ROUTING", "1")

    expected = {tool["name"] for tool in TASK_TOOL_DECLARATIONS}
    live = {tool["name"] for tool in jarvis._select_tool_declarations()}
    local = {tool["name"] for tool in jarvis._select_local_tool_declarations("Explain atoms")}

    assert live == expected
    assert local == expected


def test_execute_tool_dispatches_task_meta_tools(monkeypatch):
    async def scenario():
        jarvis = object.__new__(main.JarvisLive)
        jarvis._harness_approval_decision = lambda _name, _args: None
        jarvis._brain_router = SimpleNamespace(backend="local")
        jarvis._action_registry = SimpleNamespace(has=lambda _name: False)
        jarvis._last_user_text = ""
        jarvis._task_orchestrator = SimpleNamespace(
            handle_tool=lambda name, args: _return_task_tool_result(name, args)
        )
        jarvis.ui = SimpleNamespace(
            muted=False,
            set_state=lambda _state: None,
            write_log=lambda _message: None,
        )
        response = await jarvis._execute_tool(
            SimpleNamespace(id="call-1", name="list_tasks", args={"status": "running"})
        )

        assert response.name == "list_tasks"
        assert response.response == {
            "result": {
                "tasks": [{"task_id": "task-1", "status": "running"}]
            }
        }

    async def run():
        await scenario()

    async def _return_task_tool_result(name, args):
        return {"tasks": [{"task_id": "task-1", "status": args["status"]}]}

    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    asyncio.run(run())


def test_iris_visibility_switches_between_feminine_and_masculine_voice(monkeypatch):
    jarvis = object.__new__(main.JarvisLive)
    reconnects = []
    jarvis.request_reconnect = lambda **kwargs: reconnects.append(kwargs)
    monkeypatch.setattr(main, "get_jarvis_voice", lambda: "Charon")
    monkeypatch.setattr(main, "get_iris_voice", lambda: "Kore")

    assert jarvis._speech_voice_name() == "Charon"
    jarvis._on_hud_iris_visibility(True)
    assert jarvis._speech_voice_name() == "Kore"
    assert jarvis._asst_name == "Iris"
    assert jarvis._local_identity_dirty
    jarvis._on_hud_iris_visibility(True)
    jarvis._on_hud_iris_visibility(False)
    assert jarvis._speech_voice_name() == "Charon"
    assert jarvis._asst_name == "Jarvis"
    assert reconnects == [
        {"keep_context": False, "reason": "Iris feminine voice"},
        {"keep_context": False, "reason": "Jarvis masculine voice"},
    ]


def test_iris_reveal_command_selects_identity_and_restores_jarvis():
    jarvis = object.__new__(main.JarvisLive)
    sent = []
    jarvis._hud = SimpleNamespace(command=lambda action, **kwargs: sent.append((action, kwargs)))
    jarvis.ui = SimpleNamespace(write_log=lambda _message: None)
    jarvis.request_reconnect = lambda **_kwargs: None
    for text, expected in [("Iris rivelati", "Iris"), ("Iris nasconditi", "Jarvis")]:
        jarvis._set_hud_humanoid_visible(jarvis._hud_visibility_request(text))
        assert jarvis._asst_name == expected
    assert sent == [("reveal", {"on": True}), ("reveal", {"on": False})]


def test_bridge_serves_hud_forwards_chat_and_releases_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    received = []
    received_visibility = []
    received_event = threading.Event()
    visibility_event = threading.Event()
    bridge = HudBridge(port=port)
    bridge.on_message = lambda text: (received.append(text), received_event.set())
    bridge.on_iris_visibility = lambda visible: (
        received_visibility.append(visible),
        visibility_event.set(),
    )

    try:
        bridge.start(window="none")
        with urlopen(bridge.url, timeout=2) as response:
            assert response.status == 200
            html = response.read()
            assert b"JARVIS Mark-LIV" in html
            assert b"<body>" in html
            assert b'id="humanoidWrap" hidden' in html
            assert b'src="about:blank"' in html
            assert b'const HUMANOID_URL="https://mira-humanoid.vercel.app/"' in html

        payload = json.dumps({"text": "  ciao  "}).encode()
        request = Request(
            bridge.url + "api/chat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-HUD": "1",
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            assert response.status == 204
        assert received_event.wait(2)
        assert received == ["ciao"]

        payload = json.dumps({"visible": True}).encode()
        request = Request(
            bridge.url + "api/iris",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-HUD": "1",
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            assert response.status == 204
        assert visibility_event.wait(2)
        assert received_visibility == [True]
    finally:
        bridge.stop()


def test_hud_browser_allows_only_local_main_page_and_mira_https_iframe():
    allow = _HudBrowserPage.navigation_allowed
    assert allow(QUrl("http://127.0.0.1:8765/"), True)
    assert allow(QUrl("http://localhost:8765/"), True)
    assert not allow(QUrl("https://mira-humanoid.vercel.app/"), True)
    assert allow(QUrl("https://mira-humanoid.vercel.app/"), False)
    assert not allow(QUrl("https://example.com/"), False)
    assert not allow(QUrl("http://mira-humanoid.vercel.app/"), False)
    assert not allow(QUrl("https://mira-humanoid.vercel.app:444/"), False)


def test_iris_page_enters_directly_without_camera_or_microphone_automation():
    class Settings:
        def __init__(self):
            self.attributes = {}

        def setAttribute(self, attribute, value):
            self.attributes[attribute] = value

    class Scripts:
        def __init__(self):
            self.items = []

        def insert(self, script):
            self.items.append(script)

    class Page:
        def __init__(self):
            self._settings = Settings()
            self._scripts = Scripts()

        def settings(self):
            return self._settings

        def scripts(self):
            return self._scripts

    page = Page()
    _configure_iris_page(page)

    assert page._settings.attributes == {
        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture: False,
    }
    assert len(page._scripts.items) == 1
    script = page._scripts.items[0]
    assert script.name() == "jarvis-iris-direct-entry"
    assert script.runsOnSubFrames()
    assert "location.origin !== \"https://mira-humanoid.vercel.app\"" in script.sourceCode()
    assert 'button.textContent.trim() === "ENTER"' in script.sourceCode()
    assert "enter.click()" in script.sourceCode()
    assert "ENABLE CAMERA" not in script.sourceCode()
    assert "getUserMedia" not in script.sourceCode()


def test_bridge_hud_receives_runtime_and_assistant_state():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    bridge = HudBridge(port=port)
    bridge.set_runtime(
        {
            "skills": {"active": 2, "total": 4},
            "task": {
                "status": "awaiting_confirmation",
                "completed": 1,
                "total": 2,
                "progress": 50,
            },
        }
    )
    bridge.set_state("THINKING")
    bridge._stats_loop = lambda: bridge._stop.wait()

    try:
        bridge.start(window="none")
        with urlopen(bridge.url + "events", timeout=2) as response:
            event = json.loads(response.readline().decode("utf-8")[6:])
        assert event["type"] == "hello"
        assert event["state"] == "thinking"
        assert event["runtime"]["task"]["progress"] == 50
        assert event["runtime"]["skills"] == {"active": 2, "total": 4}
        assert event["stats"]["cpu"] is None
        assert event["stats"]["temperature"] is None
    finally:
        bridge.stop()


def test_supplied_hud_has_live_telemetry_and_persistent_layout():
    html = HudBridge().html_path.read_text(encoding="utf-8")

    assert 'new EventSource(API.events)' in html
    assert 'post(API.chat,{text})' in html
    assert 'post(API.plugin,{name:plugin.name})' in html
    assert "function renderStats(stats)" in html
    assert "function tickG" not in html
    assert 'const HUD_LAYOUT_KEY="jarvis.hud.layout.v1"' in html
    assert "function saveHudLayout()" in html
    assert "getWithRetry" in html


def test_hud_panel_visibility_is_persistent_and_iris_chat_is_centered():
    html = HudBridge().html_path.read_text(encoding="utf-8")

    assert 'data-panel-target="left"' in html
    assert 'data-panel-target="info"' in html
    assert 'data-panel-target="bar"' in html
    assert (
        'panels:{left:!document.body.classList.contains("hud-panel-left-hidden"),'
        'info:!document.body.classList.contains("hud-panel-info-hidden"),'
        'bar:!document.body.classList.contains("hud-panel-bar-hidden")}'
    ) in html
    assert "body.hud-panel-left-hidden #left,body.hud-panel-info-hidden #info" in html
    assert "visibility:hidden!important;opacity:0!important;pointer-events:none!important" in html
    assert "body.iris-mode #info{display:flex!important;visibility:visible!important" in html
    assert "contain:layout style paint" in html
    assert 'placeholder="Chiedi a Jarvis"' in html
    assert "body.iris-mode #msgs,body.iris-mode #task-dots{display:none!important}" in html
    assert "body.iris-mode .m small{display:none!important}" in html


def test_hud_bridge_publishes_incremental_chat_events():
    bridge = HudBridge()
    events = []
    bridge._broadcast = events.append

    bridge.push_chat_stream("start")
    bridge.push_chat_stream("append", "Ciao")
    bridge.push_chat_stream("end")

    assert events == [
        {"type": "chat_stream", "phase": "start", "text": ""},
        {"type": "chat_stream", "phase": "append", "text": "Ciao"},
        {"type": "chat_stream", "phase": "end", "text": ""},
    ]
    html = bridge.html_path.read_text(encoding="utf-8")
    assert 'case"chat_stream"' in html
    assert "renderChatMarkdown(streamingChatNode" in html


def test_hud_bridge_forwards_chat_events_to_gev_jarvis_panel():
    bridge = HudBridge()
    received = []
    bridge.set_chat_listener(lambda role, text: received.append((role, text)))

    bridge.push_chat("assistant", "Ho aperto la mappa.")
    bridge.push_chat_stream("start")
    bridge.push_chat_stream("append", "Risposta")
    bridge.push_chat_stream("end")

    assert received == [
        ("assistant", "Ho aperto la mappa."),
        ("stream", "start\n"),
        ("stream", "append\nRisposta"),
        ("stream", "end\n"),
    ]


def test_task_hud_snapshot_and_result_endpoints_are_local_and_redacted():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    task_id = "a" * 32
    bridge = HudBridge(port=port)
    bridge.set_task_snapshot([{
        "task_id": task_id,
        "role": "writer",
        "status": "done",
        "progress": 1.0,
        "progress_message": "File pronto",
        "created_at": 1.0,
        "updated_at": 2.0,
        "prompt": "private prompt",
        "result": "Written to: poem.txt",
        "error": None,
    }])

    try:
        bridge.start(window="none")
        request = Request(bridge.url + "api/tasks", headers={"X-HUD": "1"})
        with urlopen(request, timeout=2) as response:
            tasks = json.loads(response.read())["tasks"]
        assert tasks == [{
            "task_id": task_id,
            "role": "writer",
            "status": "done",
            "progress": 1.0,
            "progress_message": "File pronto",
            "created_at": 1.0,
            "updated_at": 2.0,
        }]

        request = Request(
            bridge.url + f"api/tasks/{task_id}",
            headers={"X-HUD": "1"},
        )
        with urlopen(request, timeout=2) as response:
            task = json.loads(response.read())["task"]
        assert task["result"] == "Written to: poem.txt"
        assert "prompt" not in task

        try:
            urlopen(bridge.url + f"api/tasks/{task_id}", timeout=2)
        except HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("Task API accepted a request without X-HUD")
    finally:
        bridge.stop()


def test_hud_renders_clickable_background_task_indicators():
    html = HudBridge().html_path.read_text(encoding="utf-8")

    assert 'id="task-dots"' in html
    assert "function renderTaskDots()" in html
    assert 'case"task_event"' in html
    assert "showTaskDetails(task.task_id)" in html


class _Stack:
    def __init__(self):
        self.current = None

    def setCurrentWidget(self, widget):
        self.current = widget


class _View:
    def __init__(self):
        self.urls = []

    def load(self, url):
        self.urls.append(url)


class _Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


def test_embedded_hud_loads_only_from_local_bridge():
    window = SimpleNamespace(
        _hud_browser_view=_View(),
        _log_sig=_Signal(),
    )

    MainWindow._load_hud_browser(window, "http://127.0.0.1:8765/")
    MainWindow._load_hud_browser(window, "https://example.com/")

    assert len(window._hud_browser_view.urls) == 1
    assert window._hud_browser_view.urls[0].toString() == (
        "http://127.0.0.1:8765/"
    )
    assert window._log_sig.messages == [
        "SYS: HUD browser URL must use the local Jarvis bridge."
    ]


def test_embedded_hud_remains_active_when_load_fails():
    class _Panel:
        def __init__(self):
            self.hidden = False

        def hide(self):
            self.hidden = True

    class _Browser:
        target = QUrl("http://127.0.0.1:8765/")

        def url(self):
            return self.target

    browser, main_stack, center_stack = _Browser(), _Stack(), _Stack()
    browser_split = object()
    header, content, footer = _Panel(), _Panel(), _Panel()
    window = SimpleNamespace(
        _hud_browser_view=browser,
        _hud_browser_requested=False,
        _hud_browser_loaded=False,
        _hud_cam_stack=center_stack,
        _browser_split=browser_split,
        _main_content_stack=main_stack,
        _header_panel=header,
        _content_panel=content,
        _footer_panel=footer,
        _center_split=SimpleNamespace(setSizes=lambda _sizes: None, height=lambda: 600),
        setWindowTitle=lambda _title: None,
        _log_sig=_Signal(),
    )

    browser.target = QUrl("about:blank")
    MainWindow._on_hud_browser_load_finished(window, True)
    assert not window._hud_browser_loaded
    assert center_stack.current is None

    window._hud_browser_requested = True
    browser.target = QUrl("http://127.0.0.1:8765/")
    MainWindow._on_hud_browser_load_finished(window, True)
    assert window._hud_browser_loaded
    assert center_stack.current is browser
    assert main_stack.current is browser_split
    assert header.hidden and content.hidden and footer.hidden

    MainWindow._on_hud_browser_load_finished(window, False)
    assert not window._hud_browser_loaded
    assert center_stack.current is browser
    assert MainWindow._active_hud_widget(window) is browser
    assert window._log_sig.messages == [
        "ERR: Embedded HUD failed to load; the legacy HUD remains disabled."
    ]
