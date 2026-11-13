"""Explicit, headless-by-default Playwright automation with a deterministic mock."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

MAX_PAGE_TEXT_CHARS = 6000


class BrowserWaitTimeout(TimeoutError):
    """A browser locator did not become visible before its deadline."""


def _bounded_page_text(text: str) -> str:
    if len(text) > MAX_PAGE_TEXT_CHARS:
        return text[:MAX_PAGE_TEXT_CHARS] + "\n[...page text truncated]"
    return text


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        raise ValueError("URL must be non-empty text of at most 4096 characters.")
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP and HTTPS URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    return url.strip()


class BrowserBackend(Protocol):
    def start(self) -> None: ...
    def navigate(self, url: str) -> Any: ...
    def find_element(self, selector: str) -> Any | None: ...
    def click(self, selector: str) -> None: ...
    def click_text(self, text: str) -> None: ...
    def click_role(self, role: str, name: str) -> None: ...
    def fill_label(self, label: str, text: str) -> None: ...
    def type_text(self, selector: str, text: str) -> None: ...
    def press_key(self, selector: str, key: str) -> None: ...
    def submit_form(self, selector: str) -> None: ...
    def get_url(self) -> str: ...
    def get_title(self) -> str: ...
    def get_text(self, selector: str) -> str: ...
    def get_input_value(self, selector: str) -> str: ...
    def go_back(self) -> str: ...
    def set_zoom(self, direction: str) -> str: ...
    def wait_for(self, selector: str, timeout_ms: int) -> None: ...
    def screenshot(self, path: str) -> None: ...
    def video_control(self, selector: str, control: str, value: float | None) -> dict: ...
    def play_youtube_video(self, query: str) -> str: ...
    def select_text(self, selector: str) -> None: ...
    def copy_selection(self) -> str: ...
    def paste_text(self, selector: str, text: str) -> None: ...
    def close(self) -> None: ...


class PlaywrightBrowser:
    """A fresh isolated Chromium instance; no user profile, cookies, or visible UI."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 10_000,
        executable_path: str | None = None,
    ) -> None:
        if not isinstance(headless, bool):
            raise TypeError("headless must be a boolean.")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= 30_000
        ):
            raise ValueError("timeout_ms must be between 1 and 30000.")
        if executable_path is not None and (
            not isinstance(executable_path, str) or not executable_path.strip()
        ):
            raise ValueError("executable_path must be non-empty text when supplied.")
        if executable_path is None:
            executable_path = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
        if executable_path is not None and not Path(executable_path).is_file():
            raise FileNotFoundError(
                f"Playwright browser executable does not exist: {executable_path}"
            )
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.executable_path = executable_path
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._zoom_percent = 100

    def start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Browser automation requires Playwright and its Chromium browser."
            ) from exc
        self._playwright = sync_playwright().start()
        try:
            launch_options: dict[str, Any] = {"headless": self.headless}
            if self.executable_path is not None:
                launch_options["executable_path"] = self.executable_path
            self._browser = self._playwright.chromium.launch(**launch_options)
            self._context = self._browser.new_context()
            self._context.grant_permissions(["clipboard-read", "clipboard-write"])
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)
        except Exception:
            self.close()
            raise

    def _require_page(self) -> Any:
        if self._page is None:
            raise RuntimeError("Browser is not started; call start() explicitly.")
        return self._page

    def navigate(self, url: str) -> Any:
        page = self._require_page()
        result = page.goto(_validate_url(url), wait_until="domcontentloaded")
        self._apply_zoom(page)
        return result

    def find_element(self, selector: str) -> Any | None:
        if not isinstance(selector, str) or not selector.strip():
            raise ValueError("selector must be non-empty text.")
        locator = self._require_page().locator(selector).first
        return locator if locator.count() > 0 else None

    def click(self, selector: str) -> None:
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        element.click()

    def click_text(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be non-empty.")
        locator = self._require_page().get_by_text(text.strip(), exact=True).first
        if locator.count() == 0:
            raise LookupError(f"Browser text not found: {text}")
        locator.click()

    def click_role(self, role: str, name: str) -> None:
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role must be non-empty text.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("accessible name must be non-empty text.")
        locator = self._require_page().get_by_role(
            role.strip(),
            name=name.strip(),
            exact=True,
        ).first
        if locator.count() == 0:
            raise LookupError(f"Browser role/name not found: {role} {name!r}")
        locator.click()

    def fill_label(self, label: str, text: str) -> None:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label must be non-empty text.")
        if not isinstance(text, str):
            raise TypeError("text must be a string.")
        locator = self._require_page().get_by_label(label.strip(), exact=True).first
        if locator.count() == 0:
            raise LookupError(f"Browser label not found: {label}")
        locator.fill(text)

    def type_text(self, selector: str, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("text must be a string.")
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        element.fill(text)

    def submit_form(self, selector: str) -> None:
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser form not found: {selector}")
        page = self._require_page()
        with page.expect_navigation(wait_until="domcontentloaded"):
            element.evaluate("(form) => form.requestSubmit()")

    def press_key(self, selector: str, key: str) -> None:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_+-]{1,32}", key):
            raise ValueError("key must be a simple key name.")
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        element.press(key)

    def get_url(self) -> str:
        return self._require_page().url

    def get_title(self) -> str:
        return self._require_page().title()

    def get_text(self, selector: str) -> str:
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        return element.inner_text()

    def get_input_value(self, selector: str) -> str:
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        return element.input_value()

    def go_back(self) -> str:
        page = self._require_page()
        page.go_back(wait_until="domcontentloaded")
        return page.url

    def set_zoom(self, direction: str) -> str:
        if direction not in {"in", "out", "reset"}:
            raise ValueError("Zoom direction must be 'in', 'out', or 'reset'.") from None
        if direction == "in":
            self._zoom_percent = min(500, self._zoom_percent + 10)
        elif direction == "out":
            self._zoom_percent = max(25, self._zoom_percent - 10)
        else:
            self._zoom_percent = 100
        self._apply_zoom(self._require_page())
        return direction

    def _apply_zoom(self, page: Any) -> None:
        page.evaluate(
            """percent => {
                if (percent === 100) {
                    document.documentElement.style.removeProperty("zoom");
                } else {
                    document.documentElement.style.setProperty("zoom", `${percent}%`, "important");
                }
            }""",
            self._zoom_percent,
        )

    def wait_for(self, selector: str, timeout_ms: int) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer.")
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        except ImportError as exc:
            raise RuntimeError(
                "Browser automation requires Playwright and its Chromium browser."
            ) from exc
        try:
            self._require_page().locator(selector).first.wait_for(
                state="visible",
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise BrowserWaitTimeout(
                f"Browser element did not become visible: {selector}"
            ) from exc

    def screenshot(self, path: str) -> None:
        self._require_page().screenshot(path=path, full_page=True)

    def video_control(
        self,
        selector: str,
        control: str,
        value: float | None = None,
    ) -> dict:
        if control not in {"play", "pause", "seek", "fullscreen", "state"}:
            raise ValueError(
                "video control must be play, pause, seek, fullscreen, or state."
            )
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser video not found: {selector}")
        return element.evaluate(
            """async (video, args) => {
                if (!(video instanceof HTMLVideoElement)) {
                    throw new Error("Target is not an HTMLVideoElement.");
                }
                if (args.control === "play") await video.play();
                if (args.control === "pause") video.pause();
                if (args.control === "fullscreen") {
                    await video.requestFullscreen();
                }
                if (args.control === "seek") {
                    if (typeof args.value !== "number" || args.value < 0) {
                        throw new Error("Seek time must be a non-negative number.");
                    }
                    video.currentTime = args.value;
                }
                return {
                    paused: video.paused,
                    currentTime: video.currentTime,
                    duration: video.duration,
                    fullscreen: document.fullscreenElement === video,
                };
            }""",
            {"control": control, "value": value},
        )

    def play_youtube_video(self, query: str) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("YouTube search query must be non-empty text.")
        from urllib.parse import quote_plus

        page = self._require_page()
        page.goto(
            "https://www.youtube.com/results?search_query="
            + quote_plus(query.strip()[:300]),
            wait_until="domcontentloaded",
        )
        first_result = page.locator("a#video-title").first
        first_result.wait_for(state="visible", timeout=self.timeout_ms)
        first_result.click()
        return page.url

    def copy_selection(self) -> str:
        return self._require_page().evaluate(
            "() => window.getSelection()?.toString() ?? ''"
        )

    def select_text(self, selector: str) -> None:
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        element.evaluate(
            """node => {
                const range = document.createRange();
                range.selectNodeContents(node);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )

    def paste_text(self, selector: str, text: str) -> None:
        self._require_page().evaluate(
            "(value) => navigator.clipboard.writeText(value)",
            text,
        )
        element = self.find_element(selector)
        if element is None:
            raise LookupError(f"Browser element not found: {selector}")
        element.focus()
        self._require_page().keyboard.press("Control+V")

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            self._browser = None
            self._context = None
            self._page = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None


class MockBrowser:
    """In-memory browser backend that never launches a browser or opens a URL."""

    def __init__(self, elements: set[str] | None = None) -> None:
        self.elements = set(elements or {
            "textarea[name='q']",
            "input[name='q']",
            "#search",
            "#search a:has(h3)",
            "body",
        })
        self.started = False
        self.closed = False
        self.current_url: str | None = None
        self.navigations: list[str] = []
        self.actions: list[tuple[str, ...]] = []
        self.title = "Mock browser"
        self.text_by_selector: dict[str, str] = {"#search": "Mock search result"}
        self.values: dict[str, str] = {}
        self.history: list[str] = []
        self.clipboard_text = ""
        self.selection_text = ""
        self.video_state = {"paused": True, "currentTime": 0.0, "duration": 1.0}

    def start(self) -> None:
        self.started = True
        self.closed = False

    def navigate(self, url: str) -> str:
        if not self.started:
            raise RuntimeError("Browser is not started.")
        validated = _validate_url(url)
        self.current_url = validated
        self.history.append(validated)
        self.navigations.append(validated)
        return validated

    def find_element(self, selector: str) -> str | None:
        if not self.started:
            raise RuntimeError("Browser is not started.")
        return selector if selector in self.elements else None

    def click(self, selector: str) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        self.actions.append(("click", selector))

    def click_text(self, text: str) -> None:
        if text not in self.elements:
            raise LookupError(f"Browser text not found: {text}")
        self.actions.append(("click_text", text))

    def click_role(self, role: str, name: str) -> None:
        key = f"{role}:{name}"
        if key not in self.elements:
            raise LookupError(f"Browser role/name not found: {role} {name!r}")
        self.actions.append(("click_role", role, name))

    def fill_label(self, label: str, text: str) -> None:
        key = f"label:{label}"
        if key not in self.elements:
            raise LookupError(f"Browser label not found: {label}")
        self.actions.append(("fill_label", label, text))
        self.values[key] = text

    def type_text(self, selector: str, text: str) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        self.actions.append(("type_text", selector, text))
        self.values[selector] = text

    def submit_form(self, selector: str) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser form not found: {selector}")
        self.actions.append(("submit_form", selector))

    def press_key(self, selector: str, key: str) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        self.actions.append(("press_key", selector, key))

    def get_url(self) -> str:
        return self.current_url or "about:blank"

    def get_title(self) -> str:
        return self.title

    def get_text(self, selector: str) -> str:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        return self.text_by_selector.get(selector, "")

    def get_input_value(self, selector: str) -> str:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        return self.values.get(selector, "")

    def go_back(self) -> str:
        if len(self.history) > 1:
            self.history.pop()
            self.current_url = self.history[-1]
        self.actions.append(("go_back",))
        return self.get_url()

    def set_zoom(self, direction: str) -> str:
        if direction not in {"in", "out", "reset"}:
            raise ValueError("Zoom direction must be 'in', 'out', or 'reset'.")
        self.actions.append(("set_zoom", direction))
        return direction

    def wait_for(self, selector: str, timeout_ms: int) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")

    def screenshot(self, path: str) -> None:
        from pathlib import Path

        Path(path).write_bytes(b"mock screenshot")
        self.actions.append(("screenshot", path))

    def video_control(
        self,
        selector: str,
        control: str,
        value: float | None = None,
    ) -> dict:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser video not found: {selector}")
        if control == "play":
            self.video_state["paused"] = False
        elif control == "pause":
            self.video_state["paused"] = True
        elif control == "seek":
            if value is None or value < 0:
                raise ValueError("Seek time must be non-negative.")
            self.video_state["currentTime"] = value
        elif control == "fullscreen":
            self.video_state["fullscreen"] = True
        return dict(self.video_state)

    def play_youtube_video(self, query: str) -> str:
        if not self.started:
            raise RuntimeError("Browser is not started.")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("YouTube search query must be non-empty text.")
        url = (
            "https://www.youtube.com/results?search_query="
            + query.strip().replace(" ", "+")
        )
        self.navigations.append(url)
        self.current_url = url
        self.actions.append(("play_youtube_video", query.strip()))
        return url

    def copy_selection(self) -> str:
        return self.selection_text

    def select_text(self, selector: str) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        self.selection_text = self.text_by_selector.get(selector, "")

    def paste_text(self, selector: str, text: str) -> None:
        if self.find_element(selector) is None:
            raise LookupError(f"Browser element not found: {selector}")
        self.clipboard_text = text
        self.values[selector] = text
        self.actions.append(("paste_text", selector, text))

    def close(self) -> None:
        self.closed = True
        self.started = False


class BrowserAutomation:
    """Stable browser interface serialized onto one Playwright-owning thread."""

    def __init__(self, backend: BrowserBackend | None = None) -> None:
        self.backend = backend or PlaywrightBrowser()
        self._executor: ThreadPoolExecutor | None = None

    def _call(self, method, *args):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="jarvis-browser",
            )
        return self._executor.submit(method, *args).result()

    def start(self) -> None:
        self._call(self.backend.start)

    def navigate(self, url: str) -> Any:
        return self._call(self.backend.navigate, _validate_url(url))

    def find_element(self, selector: str) -> Any | None:
        return self._call(self.backend.find_element, selector)

    def click(self, selector: str) -> None:
        self._call(self.backend.click, selector)

    def type_text(self, selector: str, text: str) -> None:
        self._call(self.backend.type_text, selector, text)

    def press_key(self, selector: str, key: str) -> None:
        self._call(self.backend.press_key, selector, key)

    def click_text(self, text: str) -> None:
        self._call(self.backend.click_text, text)

    def click_role(self, role: str, name: str) -> None:
        self._call(self.backend.click_role, role, name)

    def fill_label(self, label: str, text: str) -> None:
        self._call(self.backend.fill_label, label, text)

    def submit_form(self, selector: str) -> None:
        self._call(self.backend.submit_form, selector)

    def get_url(self) -> str:
        return self._call(self.backend.get_url)

    def get_title(self) -> str:
        return self._call(self.backend.get_title)

    def get_text(self, selector: str) -> str:
        return _bounded_page_text(self._call(self.backend.get_text, selector).strip())

    def get_input_value(self, selector: str) -> str:
        return self._call(self.backend.get_input_value, selector)

    def go_back(self) -> str:
        return self._call(self.backend.go_back)

    def set_zoom(self, direction: str) -> str:
        if direction not in {"in", "out", "reset"}:
            raise ValueError("Zoom direction must be 'in', 'out', or 'reset'.")
        return self._call(self.backend.set_zoom, direction)

    def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        if not isinstance(selector, str) or not selector.strip():
            raise ValueError("selector must be non-empty text.")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1 <= timeout_ms <= 30_000
        ):
            raise ValueError("timeout_ms must be between 1 and 30000.")
        self._call(self.backend.wait_for, selector, timeout_ms)

    def screenshot(self, path: str) -> None:
        self._call(self.backend.screenshot, path)

    def video_control(
        self,
        selector: str,
        control: str,
        value: float | None = None,
    ) -> dict:
        return self._call(self.backend.video_control, selector, control, value)

    def play_youtube_video(self, query: str) -> str:
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("YouTube query must contain between 1 and 300 characters.")
        method = getattr(self.backend, "play_youtube_video", None)
        if not callable(method):
            raise RuntimeError("The configured browser does not support YouTube playback.")
        return self._call(method, query.strip())

    def copy_selection(self) -> str:
        return self._call(self.backend.copy_selection)

    def select_text(self, selector: str) -> None:
        self._call(self.backend.select_text, selector)

    def paste_text(self, selector: str, text: str) -> None:
        self._call(self.backend.paste_text, selector, text)

    def search_web(self, query: str, *, engine: str = "google") -> str:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError("query must contain between 1 and 1000 characters.")
        if engine != "google":
            raise ValueError("Only the Google search UI is currently supported.")
        return self._call(self._search_web, query.strip(), engine)

    def _search_web(self, query: str, engine: str) -> str:
        self.backend.start()
        self.backend.navigate("https://www.google.com/")
        selectors = ("textarea[name='q']", "input[name='q']")
        selector = next(
            (item for item in selectors if self.backend.find_element(item)),
            None,
        )
        if selector is None:
            raise LookupError("Search field was not found on the page.")
        self.backend.type_text(selector, query)
        self.backend.press_key(selector, "Enter")
        page_text = self.backend.get_text("body").casefold()
        if (
            "before you continue on google" in page_text
            or "prima di continuare su google" in page_text
        ):
            raise PermissionError(
                "Google requires an explicit choice on its consent page; "
                "inspect it and select an option before retrying the search."
            )
        try:
            self.backend.wait_for("#search a:has(h3)", 10_000)
        except BrowserWaitTimeout as exc:
            url = self.backend.get_url().casefold()
            page_text = self.backend.get_text("body").casefold()
            if (
                "/sorry/" in url
                or "unusual traffic" in page_text
                or "automated queries" in page_text
            ):
                raise PermissionError(
                    "Google requires human verification; Jarvis will not solve "
                    "or bypass the challenge."
                ) from exc
            raise
        results = self.backend.get_text("#search").strip()
        if not results:
            raise LookupError(f"{engine} returned no readable search results.")
        results = _bounded_page_text(results)
        return f"Search results from {engine} for {query}:\n{results}"

    def close(self) -> None:
        executor = self._executor
        if executor is None:
            return
        try:
            self._call(self.backend.close)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
