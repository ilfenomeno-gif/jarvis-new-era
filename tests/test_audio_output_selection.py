import platform

import pytest
import sounddevice as sd

from core import audio_devices


@pytest.fixture
def windows_audio(monkeypatch):
    apis = [
        {"name": "MME", "default_output_device": 0},
        {"name": "Windows DirectSound", "default_output_device": 1},
        {"name": "Windows WASAPI", "default_output_device": 2},
    ]
    devices = [
        {"name": "Speakers", "hostapi": 0, "max_output_channels": 2},
        {"name": "Speakers", "hostapi": 1, "max_output_channels": 2},
        {"name": "Speakers", "hostapi": 2, "max_output_channels": 2},
        {"name": "Disconnected headset", "hostapi": 2, "max_output_channels": 2},
    ]
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.delenv("JARVIS_AUDIO_HOST_API_ORDER", raising=False)
    monkeypatch.setattr(
        sd, "query_devices",
        lambda device=None, kind=None: devices[0] if kind else (
            devices if device is None else devices[device]
        ),
    )
    monkeypatch.setattr(
        sd, "query_hostapis",
        lambda index=None: apis if index is None else apis[index],
    )
    return devices, apis


def test_default_prefers_working_wasapi_over_mme(windows_audio, monkeypatch, capsys):
    checked = []
    monkeypatch.setattr(
        audio_devices, "_transport_works",
        lambda idx, kind, key, **kwargs: checked.append(idx) or True,
    )

    assert audio_devices.select_output(sample_rate=24000) == 2
    assert checked == [2]
    assert "Dispositivo audio selezionato: Speakers tramite API Windows WASAPI" in capsys.readouterr().out


def test_disconnected_preference_falls_back_to_working_default(windows_audio, monkeypatch):
    checked = []
    monkeypatch.setattr(
        audio_devices, "_transport_works",
        lambda idx, kind, key, **kwargs: checked.append(idx) or idx != 3,
    )
    assert audio_devices.select_output("Disconnected headset") == 2
    assert checked == [3, 2]


def test_failed_wasapi_falls_back_to_directsound_before_mme(windows_audio, monkeypatch):
    monkeypatch.setattr(
        audio_devices, "_transport_works",
        lambda idx, kind, key, **kwargs: idx == 1,
    )
    assert audio_devices.select_output() == 1


def test_override_can_change_output_api_order(windows_audio, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIO_HOST_API_ORDER", "directsound,mme,wasapi")
    monkeypatch.setattr(audio_devices, "_transport_works", lambda *args, **kwargs: True)
    assert audio_devices.select_output() == 1


def test_no_working_device_reports_error(windows_audio, monkeypatch):
    monkeypatch.setattr(audio_devices, "_transport_works", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match="Impossibile riprodurre l'audio"):
        audio_devices.select_output()


def test_wasapi_probe_enables_rate_conversion(windows_audio, monkeypatch):
    streams = []
    settings = object()

    class Stream:
        def __init__(self, **kwargs):
            streams.append(kwargs)

        def start(self):
            pass

        def write(self, data):
            assert len(data) == 28800

        def stop(self):
            pass

        def close(self):
            pass

    ticks = iter((0.0, 0.6))
    monkeypatch.setattr(sd, "WasapiSettings", lambda **kwargs: (
        settings if kwargs == {"auto_convert": True} else None
    ))
    monkeypatch.setattr(sd, "RawOutputStream", Stream)
    monkeypatch.setattr(audio_devices.time, "monotonic", lambda: next(ticks))
    assert audio_devices._transport_works(2, "output", None, rate=24000, cache=False)
    assert streams[0]["extra_settings"] is settings


def test_tts_uses_selected_output_and_wasapi_settings(monkeypatch):
    import numpy as np
    from core import tts

    calls = []
    settings = object()
    monkeypatch.setattr(tts, "get_output_device", lambda: "Speakers")
    monkeypatch.setattr(
        audio_devices, "select_output",
        lambda name, **kwargs: calls.append((name, kwargs)) or 2,
    )
    monkeypatch.setattr(audio_devices, "output_extra_settings", lambda device: settings)
    monkeypatch.setattr(sd, "play", lambda samples, rate, **kwargs: calls.append((rate, kwargs)))
    monkeypatch.setattr(sd, "wait", lambda: None)
    tts._play_np(np.zeros(10), 24000)
    assert calls == [
        ("Speakers", {"sample_rate": 24000}),
        (24000, {"device": 2, "extra_settings": settings}),
    ]


def test_tts_wait_failure_reports_windows_error(monkeypatch, capsys):
    import numpy as np
    from core import tts

    monkeypatch.setattr(tts, "get_output_device", lambda: "")
    monkeypatch.setattr(audio_devices, "select_output", lambda *args, **kwargs: None)
    monkeypatch.setattr(sd, "play", lambda *args, **kwargs: None)

    def fail():
        raise sd.PortAudioError("test failure")

    monkeypatch.setattr(sd, "wait", fail)
    with pytest.raises(sd.PortAudioError):
        tts._play_np(np.zeros(10), 24000)
    assert "Impossibile riprodurre l'audio." in capsys.readouterr().out


def test_vision_output_uses_selected_device(monkeypatch):
    import asyncio
    from actions import screen_processor

    calls = []
    settings = object()

    class Stream:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def start(self):
            pass

        def write(self, data):
            raise sd.PortAudioError("test failure")

        def stop(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(screen_processor, "get_output_device", lambda: "Speakers")
    monkeypatch.setattr(audio_devices, "select_output", lambda *args, **kwargs: 2)
    monkeypatch.setattr(audio_devices, "output_extra_settings", lambda device: settings)
    monkeypatch.setattr(sd, "RawOutputStream", Stream)
    session = screen_processor._VisionSession.__new__(screen_processor._VisionSession)
    session._audio_in = asyncio.Queue()
    session._audio_in.put_nowait(bytes(16))
    with pytest.raises(sd.PortAudioError):
        asyncio.run(session._play_loop())
    assert calls[0]["device"] == 2
    assert calls[0]["extra_settings"] is settings
