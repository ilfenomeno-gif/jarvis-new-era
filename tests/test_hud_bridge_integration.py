from __future__ import annotations

import asyncio
import json
import socket
import threading
from types import SimpleNamespace
from urllib.request import Request, urlopen

import main
from PyQt6.QtCore import QUrl
from core.hud_bridge import HudBridge
from ui import MainWindow, _HudBrowserPage


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


def _live_with_fake_session(monkeypatch):
    sent = []

    class _Session:
        async def send_client_content(self, **payload):
            sent.append(payload)

    jarvis = object.__new__(main.JarvisLive)
    jarvis._hud = _Hud()
    jarvis._loop = object()
    jarvis.session = _Session()
    jarvis._brain_router = SimpleNamespace(backend="gemini")
    jarvis._observe_pattern_feedback = lambda _text: None
    jarvis._schedule_geo_route = lambda _text: None
    jarvis._prompt_router = SimpleNamespace(
        instruction_for=lambda _text: "istruzione dinamica"
    )
    monkeypatch.setattr(main.pattern_learner, "get_hints_for", lambda _text: "")
    monkeypatch.setattr(
        main.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, _loop: asyncio.run(coroutine),
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


def test_bridge_serves_hud_forwards_chat_and_releases_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    received = []
    received_event = threading.Event()
    bridge = HudBridge(port=port)
    bridge.on_message = lambda text: (received.append(text), received_event.set())

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


def test_supplied_hud_has_live_telemetry_and_no_fake_gauges():
    html = HudBridge().html_path.read_text(encoding="utf-8")

    assert 'new EventSource(API.events)' in html
    assert 'post(API.chat,{text})' in html
    assert 'post(API.plugin,{name:plugin.name})' in html
    assert "function renderStats(stats)" in html
    assert "function tickG" not in html
    assert "localStorage" not in html


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


def test_embedded_hud_becomes_active_and_falls_back_on_load_error():
    class _Panel:
        def __init__(self):
            self.hidden = False

        def hide(self):
            self.hidden = True

    browser, native, main_stack, center_stack = (
        object(),
        object(),
        _Stack(),
        _Stack(),
    )
    header, content, footer = _Panel(), _Panel(), _Panel()
    window = SimpleNamespace(
        _hud_browser_view=browser,
        _hud_browser_loaded=False,
        hud=native,
        _hud_cam_stack=center_stack,
        _main_content_stack=main_stack,
        _header_panel=header,
        _content_panel=content,
        _footer_panel=footer,
        _center_split=SimpleNamespace(setSizes=lambda _sizes: None, height=lambda: 600),
        setWindowTitle=lambda _title: None,
        _log_sig=_Signal(),
    )

    MainWindow._on_hud_browser_load_finished(window, True)
    assert window._hud_browser_loaded
    assert center_stack.current is browser
    assert main_stack.current is center_stack
    assert header.hidden and content.hidden and footer.hidden

    MainWindow._on_hud_browser_load_finished(window, False)
    assert not window._hud_browser_loaded
    assert center_stack.current is native
    assert window._log_sig.messages == [
        "SYS: Embedded HUD failed to load; using the native HUD instead."
    ]
