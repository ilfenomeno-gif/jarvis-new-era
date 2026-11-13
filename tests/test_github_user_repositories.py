from __future__ import annotations

import json
from types import SimpleNamespace

from actions import github_user_repositories as action


def test_lists_all_authenticated_users_owned_repositories(monkeypatch):
    calls = []

    class Response:
        def __init__(self, repos, next_url=""):
            self._repos = repos
            self.links = {"next": {"url": next_url}} if next_url else {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._repos

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return Response(
                [{"full_name": "alice/one"}],
                "https://api.github.com/user/repos?page=2",
            )
        return Response([{"full_name": "alice/two"}])

    monkeypatch.setattr(action.requests, "get", get)
    monkeypatch.setattr(
        action,
        "get_runtime",
        lambda: SimpleNamespace(
            connectors=SimpleNamespace(
                status=lambda _connector: "connected",
                scopes=SimpleNamespace(
                    allows=lambda _connector, _scope: True,
                ),
                access_token=lambda _connector: "fake-pat",
            )
        ),
    )

    result = json.loads(action.github_user_repositories({}))

    assert result == {
        "count": 2,
        "repositories": ["alice/one", "alice/two"],
    }
    assert [call[0] for call in calls] == [
        "https://api.github.com/user/repos",
        "https://api.github.com/user/repos?page=2",
    ]
    assert calls[0][1]["params"] == {"affiliation": "owner", "per_page": 100}
    assert all(
        call[1]["headers"]["Authorization"] == "Bearer fake-pat"
        for call in calls
    )


def test_repository_action_requires_connected_and_authorized_connector(monkeypatch):
    runtime = SimpleNamespace(
        connectors=SimpleNamespace(
            status=lambda _connector: "connected",
            scopes=SimpleNamespace(allows=lambda _connector, _scope: False),
            access_token=lambda _connector: "fake-pat",
        )
    )
    monkeypatch.setattr(action, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        action.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )

    result = action.github_user_repositories({})

    assert "repo.read" in result
