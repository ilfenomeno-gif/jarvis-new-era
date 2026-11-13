from __future__ import annotations

from core import audio_devices


def test_windows_host_api_order_defaults_to_measured_safe_order(monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIO_HOST_API_ORDER", raising=False)

    assert audio_devices._api_preference_order("Windows") == (
        "directsound",
        "mme",
        "wasapi",
    )


def test_windows_host_api_order_can_be_overridden(monkeypatch):
    monkeypatch.setenv(
        "JARVIS_AUDIO_HOST_API_ORDER",
        " WASAPI, directsound,wasapi,mme ",
    )

    assert audio_devices._api_preference_order("Windows") == (
        "wasapi",
        "directsound",
        "mme",
    )


def test_invalid_windows_host_api_order_warns_and_uses_default(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_AUDIO_HOST_API_ORDER", "unknown")

    assert audio_devices._api_preference_order("Windows") == (
        "directsound",
        "mme",
        "wasapi",
    )
    assert "Invalid JARVIS_AUDIO_HOST_API_ORDER" in capsys.readouterr().out


def test_host_api_override_is_windows_only(monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIO_HOST_API_ORDER", "wasapi")

    assert audio_devices._api_preference_order("Darwin") == ("core audio",)
