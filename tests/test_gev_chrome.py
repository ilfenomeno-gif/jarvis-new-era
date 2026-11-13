from core import gev_chrome


def test_chrome_url_uses_default_profile_without_isolation_flags(monkeypatch, tmp_path):
    executable = tmp_path / "chrome.exe"
    executable.touch()
    calls = []

    class Process:
        pass

    monkeypatch.setattr(
        gev_chrome.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)) or Process(),
    )

    process = gev_chrome.open_chrome_url(
        "https://example.org/path", executable_path=executable
    )

    assert isinstance(process, Process)
    assert calls[0][0] == [str(executable), "https://example.org/path"]
    assert not any(
        argument.startswith(("--app=", "--user-data-dir=", "--incognito", "--new-window"))
        or argument.startswith("--remote-debugging-")
        for argument in calls[0][0][1:]
    )


def test_chrome_launcher_rejects_non_http_urls(tmp_path):
    executable = tmp_path / "chrome.exe"
    executable.touch()

    try:
        gev_chrome.open_chrome_url(
            "javascript:alert(1)", executable_path=executable
        )
    except ValueError as exc:
        assert "Only http and https" in str(exc)
    else:
        raise AssertionError("Unsafe URL schemes must be rejected.")
