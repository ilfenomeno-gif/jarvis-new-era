from __future__ import annotations

from types import SimpleNamespace

from actions import github_search_repositories as action


def test_github_repository_search_forwards_explicit_query(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "total_count": 1234567,
                "items": [
                    {"full_name": "python/one"},
                    {"full_name": "python/two"},
                    {"full_name": "python/three"},
                    {"full_name": "python/four"},
                    {"full_name": "python/five"},
                ],
            }

    connectors = SimpleNamespace(
        tool_ready=lambda tool: (True, ""),
        access_token=lambda connector: "fake-pat",
    )
    monkeypatch.setattr(
        action.requests,
        "get",
        lambda url, **kwargs: calls.append((url, kwargs)) or Response(),
    )
    monkeypatch.setattr(
        action,
        "get_runtime",
        lambda: SimpleNamespace(connectors=connectors),
    )

    result = action.github_search_repositories({"query": "python"})

    assert "Ho trovato 1234567 repository per python." in result
    assert "Ecco i primi 5 più rilevanti:" in result
    assert result.count("- python/") == 5
    assert calls == [(
        "https://api.github.com/search/repositories",
        {
            "params": {"q": "python", "per_page": 5},
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer fake-pat",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            "timeout": (10, 30),
        },
    )]


def test_github_repository_search_returns_logged_clear_error(monkeypatch, caplog):
    class Response:
        status_code = 422
        text = '{"message":"Validation Failed"}'

        def raise_for_status(self):
            error = action.requests.HTTPError("422 Unprocessable Entity")
            error.response = self
            raise error

    connectors = SimpleNamespace(
        tool_ready=lambda _tool: (True, ""),
        access_token=lambda _connector: "fake-pat",
    )
    monkeypatch.setattr(
        action.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )
    monkeypatch.setattr(
        action,
        "get_runtime",
        lambda: SimpleNamespace(connectors=connectors),
    )

    result = action.github_search_repositories({"query": "python"})

    assert result == (
        "C'è stato un errore nella ricerca su GitHub: "
        'HTTP 422: {"message":"Validation Failed"}'
    )
    assert "GitHub repository search failed" in caplog.text
    assert "web_search" not in result


def test_github_repository_search_redacts_pat_from_error(monkeypatch):
    class Response:
        status_code = 401
        text = "unauthorized fake-pat"

        def raise_for_status(self):
            error = action.requests.HTTPError("401 Unauthorized")
            error.response = self
            raise error

    monkeypatch.setattr(
        action,
        "get_runtime",
        lambda: SimpleNamespace(
            connectors=SimpleNamespace(
                tool_ready=lambda _tool: (True, ""),
                access_token=lambda _connector: "fake-pat",
            )
        ),
    )
    monkeypatch.setattr(
        action.requests,
        "get",
        lambda *_args, **_kwargs: Response(),
    )

    result = action.github_search_repositories({"query": "python"})

    assert "HTTP 401" in result
    assert "[REDACTED]" in result
    assert "fake-pat" not in result


def test_github_repository_search_rejects_empty_query_without_calling_runtime(
    monkeypatch,
):
    monkeypatch.setattr(
        action,
        "get_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("runtime should not be used")),
    )

    assert "Specifica una parola" in action.github_search_repositories(
        {"query": " "}
    )
