"""Tests for safe Netflix and Prime Video browser navigation."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins import streaming_services


@pytest.mark.parametrize(
    ("service", "action", "expected_host", "expected_path", "query_key"),
    [
        ("netflix", "search", "www.netflix.com", "/search", "q"),
        (
            "prime_video",
            "search",
            "www.primevideo.com",
            "/search/ref=atv_nb_sr",
            "phrase",
        ),
    ],
)
def test_search_url_encodes_title(
    service, action, expected_host, expected_path, query_key
):
    url = streaming_services._target_url(service, action, "Dune & Friends")
    parsed = urlsplit(url)

    assert parsed.scheme == "https"
    assert parsed.netloc == expected_host
    assert parsed.path == expected_path
    assert parse_qs(parsed.query) == {query_key: ["Dune & Friends"]}


def test_open_uses_fixed_service_homepage():
    assert streaming_services._target_url("netflix", "open") == (
        "https://www.netflix.com/"
    )
    assert streaming_services._target_url("prime_video", "open") == (
        "https://www.primevideo.com/"
    )


@pytest.mark.parametrize(
    ("service", "action", "query"),
    [
        ("unknown", "open", ""),
        ("netflix", "watch", ""),
        ("netflix", "search", ""),
    ],
)
def test_invalid_service_or_search_is_rejected(service, action, query):
    with pytest.raises(ValueError):
        streaming_services._target_url(service, action, query)


def test_play_opens_search_without_starting_playback(monkeypatch):
    browser_calls = []
    webview_calls = []
    confirmation_calls = []

    def fake_browser_control(parameters, player=None):
        browser_calls.append(parameters)
        return f"Opened in your default browser: {parameters['url']}"

    monkeypatch.setattr(streaming_services, "browser_control", fake_browser_control)
    player = type(
        "Player",
        (),
        {
            "open_url_in_webview": lambda self, url: webview_calls.append(url),
            "confirm_streaming_play_in_chrome": (
                lambda self, url: confirmation_calls.append(url) or True
            ),
        },
    )()

    result = streaming_services.run(
        {"service": "netflix", "action": "play", "query": "Arrival"},
        player=player,
    )

    assert webview_calls == ["https://www.netflix.com/search?q=Arrival"]
    assert confirmation_calls == ["https://www.netflix.com/search?q=Arrival"]
    assert browser_calls == [
        {
            "action": "go_to",
            "url": "https://www.netflix.com/search?q=Arrival",
            "browser": "chrome",
        }
    ]
    assert "DRM" in result
    assert "Chrome" in result


@pytest.mark.parametrize(
    ("service", "action", "url"),
    [
        ("netflix", "open", "https://www.netflix.com/"),
        (
            "prime_video",
            "search",
            "https://www.primevideo.com/search/ref=atv_nb_sr?phrase=Dune",
        ),
    ],
)
def test_open_and_search_use_internal_webview(monkeypatch, service, action, url):
    webview_calls = []

    def unexpected_browser_fallback(**_kwargs):
        pytest.fail("browser_control should not be used while the webview works")

    monkeypatch.setattr(
        streaming_services, "browser_control", unexpected_browser_fallback
    )
    player = type(
        "Player",
        (),
        {"open_url_in_webview": lambda self, target: webview_calls.append(target)},
    )()

    result = streaming_services.run(
        {"service": service, "action": action, "query": "Dune"},
        player=player,
    )

    assert webview_calls == [url]
    assert "internally in JARVIS" in result


def test_missing_webview_falls_back_to_browser_control(monkeypatch):
    browser_calls = []
    monkeypatch.setattr(
        streaming_services,
        "browser_control",
        lambda parameters, player=None: (
            browser_calls.append(parameters) or "Opened in your default browser"
        ),
    )

    result = streaming_services.run(
        {"service": "netflix", "action": "open"},
        player=object(),
    )

    assert browser_calls == [
        {"action": "go_to", "url": "https://www.netflix.com/"}
    ]
    assert result == "Opened in your default browser"


def test_webview_error_logs_and_falls_back(monkeypatch):
    logged = []
    browser_calls = []
    monkeypatch.setattr(
        streaming_services,
        "browser_control",
        lambda parameters, player=None: (
            browser_calls.append(parameters) or "Opened externally"
        ),
    )

    class _Player:
        def open_url_in_webview(self, _url):
            raise RuntimeError("webview unavailable")

        def write_log(self, message):
            logged.append(message)

    result = streaming_services.run(
        {"service": "prime_video", "action": "open"},
        player=_Player(),
    )

    assert result == "Opened externally"
    assert browser_calls[0]["url"] == "https://www.primevideo.com/"
    assert any("uso il browser esterno" in message for message in logged)


def test_cancelled_play_does_not_open_chrome(monkeypatch):
    browser_calls = []
    webview_calls = []
    monkeypatch.setattr(
        streaming_services,
        "browser_control",
        lambda parameters, player=None: (
            browser_calls.append(parameters) or "Opened externally"
        ),
    )
    player = type(
        "Player",
        (),
        {
            "open_url_in_webview": lambda self, url: webview_calls.append(url),
            "confirm_streaming_play_in_chrome": lambda self, _url: False,
        },
    )()

    result = streaming_services.run(
        {"service": "prime_video", "action": "play", "query": "Dune"},
        player=player,
    )

    assert webview_calls == [
        "https://www.primevideo.com/search/ref=atv_nb_sr?phrase=Dune"
    ]
    assert browser_calls == []
    assert "annullata" in result


def test_play_without_confirmation_does_not_launch_browser(monkeypatch):
    browser_calls = []
    logged = []
    monkeypatch.setattr(
        streaming_services,
        "browser_control",
        lambda parameters, player=None: (
            browser_calls.append(parameters) or "Opened externally"
        ),
    )

    class _Player:
        def open_url_in_webview(self, _url):
            pass

        def write_log(self, message):
            logged.append(message)

    result = streaming_services.run(
        {"service": "netflix", "action": "play", "query": "Arrival"},
        player=_Player(),
    )

    assert browser_calls == []
    assert "conferma non è disponibile" in result
    assert logged


def test_play_without_webview_or_confirmation_does_not_launch_browser(monkeypatch):
    browser_calls = []
    monkeypatch.setattr(
        streaming_services,
        "browser_control",
        lambda parameters, player=None: (
            browser_calls.append(parameters) or "Opened externally"
        ),
    )

    result = streaming_services.run(
        {"service": "netflix", "action": "play", "query": "Arrival"},
        player=object(),
    )

    assert browser_calls == []
    assert "non è stato aperto alcun browser" in result


@pytest.mark.parametrize("confirmed", [False, True])
def test_play_without_webview_waits_for_confirmation_before_browser(
    monkeypatch, confirmed
):
    calls = []
    browser_calls = []

    def fake_browser_control(parameters, player=None):
        browser_calls.append(parameters)
        calls.append("browser")
        return f"Opened in Chrome: {parameters['url']}"

    monkeypatch.setattr(
        streaming_services, "browser_control", fake_browser_control
    )

    class _Player:
        def confirm_streaming_play_in_chrome(self, url):
            calls.append(("confirm", url))
            return confirmed

    result = streaming_services.run(
        {"service": "netflix", "action": "play", "query": "Arrival"},
        player=_Player(),
    )

    assert calls[0] == (
        "confirm",
        "https://www.netflix.com/search?q=Arrival",
    )
    if confirmed:
        assert browser_calls == [
            {
                "action": "go_to",
                "url": "https://www.netflix.com/search?q=Arrival",
                "browser": "chrome",
            }
        ]
        assert calls[1] == "browser"
    else:
        assert browser_calls == []
        assert "annullata" in result
