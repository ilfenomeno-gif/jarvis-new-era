from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from ui import MainWindow


class _HudElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])


class _Stack:
    def __init__(self, current, split):
        self.current = current
        self.split = split

    def currentWidget(self):
        return self.current

    def setCurrentWidget(self, widget):
        self.current = widget

    def indexOf(self, widget):
        return 0 if widget is self.split else -1


class _Splitter:
    def __init__(self, widgets):
        self.widgets = widgets

    def width(self):
        return 1000

    def setSizes(self, sizes):
        self.sizes = sizes


class _Panel:
    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


def test_internal_browser_keeps_chat_controls_in_the_visible_hud_split():
    html = Path(__file__).resolve().parents[1] / "core" / "jarvis_hud.html"
    parser = _HudElements()
    parser.feed(html.read_text(encoding="utf-8"))
    assert {"chat", "q", "send"} <= parser.ids

    hud_view = object()
    browser_panel = _Panel()
    browser_split = _Splitter([hud_view, browser_panel])
    address = SimpleNamespace(setText=lambda value: None)
    browser = SimpleNamespace(setUrl=lambda value: None)
    window = SimpleNamespace(
        _main_content_stack=_Stack(browser_split, browser_split),
        _browser_split=browser_split,
        _browser_panel=browser_panel,
        _browser_return_widget=None,
        _browser_is_open=False,
        _browser_address=address,
        _browser_view=browser,
        _browser_status=SimpleNamespace(setText=lambda value: None),
        _update_browser_navigation=lambda: None,
    )

    MainWindow._open_url_in_webview(window, "https://www.netflix.com/")

    assert window._main_content_stack.currentWidget() is browser_split
    assert browser_split.widgets == [hud_view, browser_panel]
    assert browser_split.sizes == [550, 450]
    assert browser_panel.visible
    assert MainWindow._browser_panel_is_active(window)

    MainWindow.close_browser(window)

    assert not browser_panel.visible
    assert not MainWindow._browser_panel_is_active(window)
    assert browser_split.sizes == [1000, 0]
