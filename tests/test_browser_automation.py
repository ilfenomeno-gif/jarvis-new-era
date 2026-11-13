import pytest

from core.browser_automation import (
    MAX_PAGE_TEXT_CHARS,
    BrowserAutomation,
    BrowserWaitTimeout,
    MockBrowser,
    PlaywrightBrowser,
)


def test_mock_browser_navigates_and_interacts_without_launching_real_browser():
    mock = MockBrowser(elements={"button.save"})
    browser = BrowserAutomation(mock)

    browser.start()
    browser.navigate("https://example.test/")
    browser.click("button.save")
    browser.type_text("button.save", "Draft")
    browser.press_key("button.save", "Enter")
    browser.close()

    assert mock.navigations == ["https://example.test/"]
    assert mock.actions == [
        ("click", "button.save"),
        ("type_text", "button.save", "Draft"),
        ("press_key", "button.save", "Enter"),
    ]
    assert mock.closed


def test_mock_browser_supports_page_zoom_commands():
    mock = MockBrowser()
    browser = BrowserAutomation(mock)

    assert browser.set_zoom("in") == "in"
    assert browser.set_zoom("out") == "out"
    assert browser.set_zoom("reset") == "reset"
    assert mock.actions == [
        ("set_zoom", "in"),
        ("set_zoom", "out"),
        ("set_zoom", "reset"),
    ]


def test_playwright_browser_zoom_changes_document_scale_and_resets():
    class _Page:
        def __init__(self):
            self.zoom_values = []

        def evaluate(self, _script, percent):
            self.zoom_values.append(percent)

    browser = PlaywrightBrowser()
    browser._page = _Page()

    assert browser.set_zoom("in") == "in"
    assert browser.set_zoom("in") == "in"
    assert browser.set_zoom("out") == "out"
    assert browser.set_zoom("reset") == "reset"
    assert browser._page.zoom_values == [110, 120, 110, 100]


def test_mock_browser_accessible_role_and_label_actions():
    mock = MockBrowser(elements={"button:Continue", "label:Name"})
    browser = BrowserAutomation(mock)

    browser.start()
    browser.click_role("button", "Continue")
    browser.fill_label("Name", "Ada")

    assert mock.actions == [
        ("click_role", "button", "Continue"),
        ("fill_label", "Name", "Ada"),
    ]
    assert mock.values["label:Name"] == "Ada"
    browser.close()


def test_mock_web_search_submits_query_and_reads_results():
    mock = MockBrowser()
    browser = BrowserAutomation(mock)

    result = browser.search_web("Jarvis")

    assert mock.navigations == ["https://www.google.com/"]
    assert mock.actions == [
        ("type_text", "textarea[name='q']", "Jarvis"),
        ("press_key", "textarea[name='q']", "Enter"),
    ]
    assert "Mock search result" in result


def test_mock_web_search_fails_when_results_are_empty():
    mock = MockBrowser()
    mock.text_by_selector["#search"] = " "
    browser = BrowserAutomation(mock)

    with pytest.raises(LookupError, match="no readable search results"):
        browser.search_web("Jarvis")


def test_mock_web_search_stops_for_explicit_google_consent():
    mock = MockBrowser()
    mock.text_by_selector["body"] = "Before you continue on Google"
    browser = BrowserAutomation(mock)

    with pytest.raises(PermissionError, match="explicit choice"):
        browser.search_web("Jarvis")


def test_mock_browser_youtube_playback_is_visible_and_command_scoped():
    mock = MockBrowser()
    browser = BrowserAutomation(mock)

    browser.start()
    result = browser.play_youtube_video("Daft Punk")

    assert result.startswith("https://www.youtube.com/results?")
    assert mock.actions == [("play_youtube_video", "Daft Punk")]
    browser.close()


def test_mock_web_search_does_not_bypass_google_human_verification():
    mock = MockBrowser()
    mock.text_by_selector["body"] = "Our systems have detected unusual traffic"
    mock.current_url = "https://www.google.com/sorry/index"

    def wait_for_challenge(_selector, _timeout_ms):
        raise BrowserWaitTimeout("Google challenge")

    mock.wait_for = wait_for_challenge
    browser = BrowserAutomation(mock)

    with pytest.raises(PermissionError, match="will not solve or bypass"):
        browser.search_web("Jarvis")


def test_page_text_is_truncated_to_the_context_limit():
    mock = MockBrowser(elements={"body"})
    mock.text_by_selector["body"] = "x" * (MAX_PAGE_TEXT_CHARS + 100)
    browser = BrowserAutomation(mock)

    browser.start()
    result = browser.get_text("body")

    assert result == "x" * MAX_PAGE_TEXT_CHARS + "\n[...page text truncated]"
    browser.close()


@pytest.mark.parametrize(
    "url",
    ["", "file:///C:/secret.txt", "javascript:alert(1)", "https://user:pass@example.com/"],
)
def test_browser_rejects_non_http_or_credential_urls(url):
    browser = BrowserAutomation(MockBrowser())
    with pytest.raises(ValueError):
        browser.navigate(url)


def test_playwright_browser_reports_missing_configured_executable(monkeypatch, tmp_path):
    executable = tmp_path / "missing-chromium.exe"
    monkeypatch.setenv("PLAYWRIGHT_EXECUTABLE_PATH", str(executable))
    with pytest.raises(FileNotFoundError, match="Playwright browser executable"):
        PlaywrightBrowser()
