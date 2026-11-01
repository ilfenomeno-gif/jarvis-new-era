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
        def __init__(self, current):
            self.current = current

        def currentWidget(self):
            return self.current

        def setCurrentWidget(self, widget):
            self.current = widget

        def indexOf(self, widget):
            return 0 if widget is hud_view else 1 if widget is browser_panel else -1

    class AddressRecorder:
        def setText(self, value):
            self.value = value

    class BrowserRecorder:
        def setUrl(self, value):
            self.url = value

    hud_view = object()
    browser_panel = object()
    stack = StackRecorder(hud_view)
    address = AddressRecorder()
    browser = BrowserRecorder()
    status = AddressRecorder()
    window = SimpleNamespace(
        _main_content_stack=stack,
        _browser_panel=browser_panel,
        _browser_return_widget=None,
        _browser_address=address,
        _browser_view=browser,
        _browser_status=status,
        _update_browser_navigation=lambda: None,
        _hud_cam_stack=hud_view,
    )

    MainWindow._open_url_in_webview(window, "example.com")
    MainWindow._open_url_in_webview(window, "https://example.org")

    assert stack.current is browser_panel
    assert address.value == "https://example.org/"
    assert browser.url.toString() == "https://example.org/"
    assert window._browser_return_widget is hud_view

    MainWindow.close_browser(window)
    assert stack.current is hud_view
    assert window._browser_return_widget is None


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

    assert browser_tool["parameters"]["required"] == ["url"]
    assert "integrated browser" in browser_tool["description"]
