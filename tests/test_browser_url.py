import ast
from pathlib import Path

import pytest

from core.browser_url import is_allowed_http_scheme, normalize_http_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("YouTube", "https://www.youtube.com/"),
        ("example.com", "https://example.com/"),
        ("example.com/path?q=jarvis#top", "https://example.com/path?q=jarvis#top"),
        ("http://example.com", "http://example.com/"),
        ("HTTPS://example.com", "https://example.com/"),
        ("localhost:8080/health", "https://localhost:8080/health"),
        ("//example.com/path", "https://example.com/path"),
    ],
)
def test_normalize_http_url_accepts_web_addresses(value, expected):
    assert normalize_http_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "file:///C:/secret.txt",
        "javascript:alert(1)",
        "data:text/html,hello",
        "ftp://example.com",
        "mailto:user@example.com",
        "https:example.com",
        "https://",
        "https://user:password@example.com",
        "https://example.com:70000",
        "https://example.com:not-a-port",
        "https://example.com/\r\nInjected-Header: value",
    ],
)
def test_normalize_http_url_rejects_unsafe_or_invalid_addresses(value):
    with pytest.raises(ValueError):
        normalize_http_url(value)


def test_normalize_http_url_rejects_non_text():
    with pytest.raises(TypeError, match="URL must be text"):
        normalize_http_url(None)


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [
        ("http", True),
        ("https", True),
        ("HTTP", True),
        ("file", False),
        ("javascript", False),
        ("data", False),
        ("ftp", False),
        ("", False),
    ],
)
def test_browser_navigation_scheme_policy(scheme, expected):
    assert is_allowed_http_scheme(scheme) is expected


def test_jarvis_ui_browser_request_uses_qt_signal():
    from types import SimpleNamespace

    from ui import JarvisUI

    class SignalRecorder:
        def __init__(self):
            self.value = None

        def emit(self, value):
            self.value = value

    signal = SignalRecorder()
    jarvis_ui = JarvisUI.__new__(JarvisUI)
    jarvis_ui._win = SimpleNamespace(_browser_open_sig=signal)

    assert jarvis_ui.open_url_in_webview("YouTube") == "https://www.youtube.com/"
    assert signal.value == "https://www.youtube.com/"


def test_integrated_browser_open_and_close_restore_previous_stack():
    from types import SimpleNamespace

    from ui import MainWindow

    class StackRecorder:
        def __init__(self, current, return_widget):
            self.current = current
            self.return_widget = return_widget

        def currentWidget(self):
            return self.current

        def setCurrentWidget(self, widget):
            self.current = widget

        def indexOf(self, widget):
            return 0 if widget is self.return_widget else 1 if widget is browser_split else -1

    class AddressRecorder:
        def setText(self, value):
            self.value = value

    class BrowserRecorder:
        def setUrl(self, value):
            self.url = value

    class SplitterRecorder:
        def width(self):
            return 1000

        def setSizes(self, sizes):
            self.sizes = sizes

    class PanelRecorder:
        def __init__(self):
            self.visible = False

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

    return_widget = object()
    browser_panel = PanelRecorder()
    browser_split = SplitterRecorder()
    stack = StackRecorder(return_widget, return_widget)
    address = AddressRecorder()
    browser = BrowserRecorder()
    status = AddressRecorder()
    window = SimpleNamespace(
        _main_content_stack=stack,
        _browser_split=browser_split,
        _browser_panel=browser_panel,
        _browser_return_widget=None,
        _browser_is_open=False,
        _browser_address=address,
        _browser_view=browser,
        _browser_status=status,
        _update_browser_navigation=lambda: None,
        _hud_cam_stack=return_widget,
    )

    MainWindow._open_url_in_webview(window, "example.com")
    MainWindow._open_url_in_webview(window, "https://example.org")

    assert stack.current is browser_split
    assert window._browser_is_open
    assert browser_panel.visible
    assert browser_split.sizes == [550, 450]
    assert address.value == "https://example.org/"
    assert browser.url.toString() == "https://example.org/"
    assert window._browser_return_widget is return_widget

    MainWindow.close_browser(window)
    assert stack.current is return_widget
    assert not window._browser_is_open
    assert not browser_panel.visible
    assert window._browser_return_widget is None


def test_external_browser_action_opens_current_webview_url(monkeypatch):
    from types import SimpleNamespace

    from ui import MainWindow

    calls = []
    messages = []
    window = SimpleNamespace(
        _browser_view=SimpleNamespace(
            url=lambda: SimpleNamespace(
                toString=lambda: "https://www.youtube.com/watch?v=example"
            )
        ),
        _browser_status=SimpleNamespace(setText=messages.append),
        _log_sig=SimpleNamespace(emit=messages.append),
    )
    monkeypatch.setattr(
        "ui.webbrowser.open",
        lambda url, new=0: calls.append((url, new)) or True,
    )

    assert MainWindow._open_current_browser_externally(window) is True
    assert calls == [("https://www.youtube.com/watch?v=example", 2)]
    assert messages == [
        "Browser esterno: apertura richiesta per "
        "https://www.youtube.com/watch?v=example",
        "URL aperto nel browser esterno.",
    ]


def test_external_browser_button_opens_loaded_url(monkeypatch):
    import os
    import sys
    from types import SimpleNamespace

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from ui import JarvisUI

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = JarvisUI("")
    window = jarvis._win
    opened = []
    monkeypatch.setattr(
        "ui.webbrowser.open",
        lambda url, new=0: opened.append((url, new)) or True,
    )
    try:
        window._browser_view = SimpleNamespace(
            url=lambda: SimpleNamespace(
                toString=lambda: "https://www.youtube.com/watch?v=example"
            )
        )
        window._browser_external_button.click()

        assert opened == [
            ("https://www.youtube.com/watch?v=example", 2)
        ]
    finally:
        window._layout_timer.stop()
        window.close()


def test_external_browser_action_reports_rejected_webview_scheme(monkeypatch):
    from types import SimpleNamespace

    from ui import MainWindow

    messages = []
    window = SimpleNamespace(
        _browser_view=SimpleNamespace(
            url=lambda: SimpleNamespace(
                toString=lambda: "javascript:alert(1)"
            )
        ),
        _browser_status=SimpleNamespace(setText=messages.append),
        _log_sig=SimpleNamespace(emit=messages.append),
    )
    monkeypatch.setattr(
        "ui.webbrowser.open",
        lambda *_args, **_kwargs: pytest.fail("Unsafe URL must not be opened"),
    )

    assert MainWindow._open_current_browser_externally(window) is False
    assert len(messages) == 2
    assert "Only http and https" in messages[0]


def test_external_browser_action_uses_desktop_fallback(monkeypatch):
    from types import SimpleNamespace

    import ui
    from ui import MainWindow

    calls = []
    messages = []
    window = SimpleNamespace(
        _browser_view=SimpleNamespace(
            url=lambda: SimpleNamespace(
                toString=lambda: "https://example.org"
            )
        ),
        _browser_status=SimpleNamespace(setText=messages.append),
        _log_sig=SimpleNamespace(emit=messages.append),
    )
    monkeypatch.setattr("ui.webbrowser.open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        ui.QDesktopServices,
        "openUrl",
        lambda url: calls.append(url.toString()) or True,
    )

    assert MainWindow._open_current_browser_externally(window) is True
    assert calls == ["https://example.org/"]
    assert messages[-1] == "URL aperto nel browser esterno."


def test_open_website_tool_is_declared_with_required_url():
    main_file = Path(__file__).resolve().parents[1] / "main.py"
    module = ast.parse(main_file.read_text(encoding="utf-8"))
    declarations_assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TOOL_DECLARATIONS"
            for target in node.targets
        )
    )
    declarations = ast.literal_eval(declarations_assignment.value)
    browser_tool = next(item for item in declarations if item["name"] == "open_website")
    youtube_tool = next(item for item in declarations if item["name"] == "youtube_video")

    assert browser_tool["parameters"]["required"] == ["url"]
    assert "default Chrome profile" in browser_tool["description"]
    assert "only asks to open YouTube" in browser_tool["description"]
    assert "only asks to open YouTube" in youtube_tool["description"]
    assert "use open_website" in youtube_tool["description"]
