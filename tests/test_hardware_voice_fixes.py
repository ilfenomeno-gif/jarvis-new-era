from types import SimpleNamespace

import pytest

from actions import check_wifi
from core.tts import normalize_text_for_tts


def test_italian_tts_normalization_preserves_punctuation_and_decimals():
    assert normalize_text_for_tts("chrome.exe: 92%. vs_code e my_app.py.") == (
        "cromo: novantadue per cento. visual studio code e my app."
    )
    assert normalize_text_for_tts("Versione 3.14.") == "Versione 3.14."


@pytest.mark.parametrize(("language", "expected"), [
    ("it", "cromo novantadue per cento"),
    ("en", "chrome.exe 92%"),
])
def test_pipeline_sends_normalized_text_only_for_italian(language, expected):
    import asyncio
    from providers.engine_pipeline import PipelineEngine

    spoken = []

    class Voice:
        async def speak(self, text):
            spoken.append(text)
            if False:
                yield b""

    engine = PipelineEngine(llm=None, stt=SimpleNamespace(detected_language=language), tts=Voice())
    asyncio.run(engine._speak("chrome.exe 92%"))
    assert spoken == [expected]


def test_wifi_name_is_only_spoken_locally(monkeypatch):
    spoken = []
    monitor = SimpleNamespace(snapshot=lambda: {"wifi": {
        "status": "available", "connected_interfaces": 1,
        "signal_percent": 92, "security": "WPA2",
    }})
    monkeypatch.setattr(check_wifi, "get_network_security_monitor", lambda: monitor)
    monkeypatch.setattr(check_wifi, "local_wifi_details", lambda: {
        "interfaces": [{"ssid": "private-network"}],
    })
    player = SimpleNamespace(_jarvis=SimpleNamespace(speak_private_local=spoken.append))
    result = check_wifi.check_wifi({}, player=player)
    assert spoken == ["Sei connesso a private-network."]
    assert "private-network" not in result
    assert "pronunciato localmente" in result


def test_wifi_local_speech_failure_is_reported_without_name(monkeypatch):
    monitor = SimpleNamespace(snapshot=lambda: {"wifi": {
        "status": "available", "connected_interfaces": 1,
        "signal_percent": 92, "security": "WPA2",
    }})
    monkeypatch.setattr(check_wifi, "get_network_security_monitor", lambda: monitor)
    monkeypatch.setattr(check_wifi, "local_wifi_details", lambda: {
        "interfaces": [{"ssid": "private-network"}],
    })
    def fail(_text):
        raise RuntimeError("private-network")
    player = SimpleNamespace(_jarvis=SimpleNamespace(speak_private_local=fail))
    result = check_wifi.check_wifi({}, player=player)
    assert "Impossibile" in result
    assert "private-network" not in result


def test_wifi_uncached_silent_mode_refreshes_and_displays_only_locally(monkeypatch):
    shown, spoken, scans = [], [], []
    wifi = {"status": "available", "connected_interfaces": 1,
            "signal_percent": 92, "security": "secure"}
    monitor = SimpleNamespace(
        snapshot=lambda: {"status": "not_checked", "wifi": {}},
        scan=lambda: scans.append(True) or {"status": "available", "wifi": wifi})
    monkeypatch.setattr(check_wifi, "get_network_security_monitor", lambda: monitor)
    monkeypatch.setattr(check_wifi, "local_wifi_details", lambda: {
        "interfaces": [{"ssid": "CasaTua_5G", "signal_percent": 92}]})
    player = SimpleNamespace(_jarvis=SimpleNamespace(
        _ambient=SimpleNamespace(is_silent=lambda: True),
        show_private_local=shown.append, speak_private_local=spoken.append))
    result = check_wifi.check_wifi({}, player=player)
    assert scans == [True]
    assert shown == ["Sei connesso a CasaTua_5G con segnale al 92%."]
    assert not spoken and "CasaTua_5G" not in result and "92%" in result
    assert "mostrato localmente" in result


def test_wifi_uncached_failure_is_reported_without_voice(monkeypatch):
    monitor = SimpleNamespace(
        snapshot=lambda: {"status": "not_checked", "wifi": {}},
        scan=lambda: {"status": "unavailable", "wifi": {}})
    monkeypatch.setattr(check_wifi, "get_network_security_monitor", lambda: monitor)
    assert "non disponibile" in check_wifi.check_wifi({})


def test_wifi_italian_netsh_parses_ssid_not_bssid(monkeypatch):
    from core import network_security
    monkeypatch.setattr(network_security, "_run_netsh", lambda *_args: (
        "Nome : Wi-Fi\nStato : connesso\nSSID : CasaTua_5G\n"
        "BSSID : 00:11:22:33:44:55\nSegnale : 92%\n"
        "Nome : Wi-Fi 2\nStato : disconnesso\nSSID : altra\n"))
    entries = network_security.local_wifi_details()["interfaces"]
    assert entries[0]["ssid"] == "CasaTua_5G" and entries[0]["signal_percent"] == 92
    assert entries[1]["ssid"] is None


@pytest.mark.parametrize(("name", "allowed"), [
    ("notepad.exe", True), ("CalculatorApp.exe", True), ("explorer.exe", False),
    ("csrss.exe", False), ("winlogon.exe", False), ("lsass.exe", False),
])
def test_close_app_checks_actual_process_name(monkeypatch, name, allowed):
    import sys
    from actions import computer_settings
    sent = []
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        GetForegroundWindow=lambda: 77, IsWindow=lambda _: True,
        PostMessage=lambda *args: sent.append(args)))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _: (1, 4321)))
    monkeypatch.setattr("psutil.Process", lambda _: SimpleNamespace(
        name=lambda: name, create_time=lambda: 123.0))
    if allowed:
        computer_settings._close_app_target()()
        assert sent == [(77, 0x0010, 0, 0)]
    else:
        with pytest.raises(RuntimeError, match="protetto"):
            computer_settings._close_app_target()
        assert not sent


def test_close_app_denies_unverifiable_process(monkeypatch):
    import psutil
    import sys
    from actions import computer_settings
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        GetForegroundWindow=lambda: 77, IsWindow=lambda _: True))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _: (1, 4321)))
    def denied(_):
        raise psutil.AccessDenied(4321)
    monkeypatch.setattr(psutil, "Process", denied)
    with pytest.raises(RuntimeError, match="non è verificabile"):
        computer_settings._close_app_target()


def test_private_local_voice_respects_silent_mode(monkeypatch):
    from main import JarvisLive
    from providers import audio, tts_system
    from core import tts

    spoken = []
    played = []
    monkeypatch.setattr(tts_system.SystemTTS, "_synth_blocking",
                        lambda _self, text: spoken.append(text) or b"wav")
    monkeypatch.setattr(audio, "wav_to_pcm", lambda *_args: b"\x00\x00")
    monkeypatch.setattr(tts, "_play_np", lambda samples, rate: played.append((len(samples), rate)))
    instance = SimpleNamespace(_ambient=SimpleNamespace(is_silent=lambda: False))
    JarvisLive.speak_private_local(instance, "nome privato")
    assert spoken == ["nome privato"] and played == [(1, audio.SPEAKER_RATE)]
    instance._ambient.is_silent = lambda: True
    with pytest.raises(RuntimeError, match="silenziosa"):
        JarvisLive.speak_private_local(instance, "altro")
    assert spoken == ["nome privato"] and played == [(1, audio.SPEAKER_RATE)]


@pytest.mark.parametrize("layout", ["swap", "jarvis_left", "jarvis_right"])
def test_swap_places_both_windows(monkeypatch, layout):
    import os
    import sys
    from core import multi_monitor as module

    jarvis = {"hwnd": 11, "pid": os.getpid(), "left": 0, "top": 0, "width": 500, "height": 700}
    other = {"hwnd": 12, "pid": 8765, "left": 500, "top": 0, "width": 500, "height": 700}
    placed = []
    gui = SimpleNamespace(IsWindow=lambda _h: True, IsIconic=lambda _h: False, IsZoomed=lambda _h: False)
    monkeypatch.setattr(module, "_enum_windows", lambda: [jarvis, other])
    monkeypatch.setattr(module, "_foreground_window", lambda: (12, 8765))
    monkeypatch.setattr(module, "_load_win32gui", lambda: gui)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda h: (1, jarvis["pid"] if h == 11 else 8765)))
    monkeypatch.setattr(module, "_is_protected_process", lambda _pid: False)
    monkeypatch.setattr(module, "_place_window", lambda hwnd, *pos: placed.append((hwnd, pos)))
    monkeypatch.setattr(module, "list_monitors", lambda: [{
        "index": 0, "left": 0, "top": 0, "width": 1000, "height": 700,
    }])
    assert module.swap_active_window(layout) == {"ok": True}
    assert [item[0] for item in placed] == [11, 12]
    assert placed[0][1][0] == (0 if layout == "jarvis_left" else 500)
    assert placed[1][1][0] == (500 if layout == "jarvis_left" else 0)


def test_swap_selects_largest_eligible_window_when_jarvis_is_active(monkeypatch):
    import os
    import sys
    from core import multi_monitor as module

    jarvis = {"hwnd": 11, "pid": os.getpid(), "left": 0, "top": 0, "width": 300, "height": 400}
    small = {"hwnd": 12, "pid": 1001, "left": 300, "top": 0, "width": 200, "height": 400}
    large = {"hwnd": 13, "pid": 1002, "left": 500, "top": 0, "width": 500, "height": 600}
    placed = []
    monkeypatch.setattr(module, "_enum_windows", lambda: [
        jarvis, small, large,
    ])
    monkeypatch.setattr(module, "_foreground_window", lambda: (11, os.getpid()))
    monkeypatch.setattr(module, "_load_win32gui", lambda: SimpleNamespace(
        IsWindow=lambda _: True, IsIconic=lambda _: False, IsZoomed=lambda _: False))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda h: (1, {11: os.getpid(), 12: 1001, 13: 1002}[h])))
    monkeypatch.setattr(module, "_is_protected_process", lambda _: False)
    monkeypatch.setattr(module, "_place_window", lambda hwnd, *pos: placed.append((hwnd, pos)))
    assert module.swap_active_window() == {"ok": True}
    assert [handle for handle, _ in placed] == [11, 13]


def test_swap_restores_maximized_window_before_moving(monkeypatch):
    import os
    import sys
    from core import multi_monitor as module

    jarvis = {"hwnd": 11, "pid": os.getpid(), "left": 0, "top": 0, "width": 300, "height": 400}
    other = {"hwnd": 12, "pid": 4321, "left": 300, "top": 0, "width": 900, "height": 700}
    events = []
    gui = SimpleNamespace(
        IsWindow=lambda _: True, IsIconic=lambda _: False, IsZoomed=lambda h: h == 12,
        GetWindowPlacement=lambda _: "saved",
        ShowWindow=lambda hwnd, state: events.append(("restore", hwnd, state)),
        SetWindowPlacement=lambda hwnd, state: events.append(("placement", hwnd, state)))
    monkeypatch.setattr(module, "_enum_windows", lambda: [jarvis, other])
    monkeypatch.setattr(module, "_foreground_window", lambda: (11, os.getpid()))
    monkeypatch.setattr(module, "_load_win32gui", lambda: gui)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda h: (1, os.getpid() if h == 11 else 4321)))
    monkeypatch.setattr(module, "_is_protected_process", lambda _: False)
    monkeypatch.setattr(module, "_place_window", lambda hwnd, *pos: events.append(("move", hwnd)))
    assert module.swap_active_window() == {"ok": True}
    assert events == [("move", 11), ("restore", 12, 9), ("move", 12)]


def test_swap_rolls_back_if_other_window_changes_owner(monkeypatch):
    import os
    import sys
    from core import multi_monitor as module

    jarvis = {"hwnd": 11, "pid": os.getpid(), "left": 0, "top": 0, "width": 500, "height": 700}
    other = {"hwnd": 12, "pid": 8765, "left": 500, "top": 0, "width": 500, "height": 700}
    placed = []
    monkeypatch.setattr(module, "_enum_windows", lambda: [jarvis, other])
    monkeypatch.setattr(module, "_foreground_window", lambda: (12, 8765))
    monkeypatch.setattr(module, "_load_win32gui", lambda: SimpleNamespace(
        IsWindow=lambda _: True, IsIconic=lambda _: False, IsZoomed=lambda _: False))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda h: (1, os.getpid() if h == 11 else 9999)))
    monkeypatch.setattr(module, "_is_protected_process", lambda _: False)
    monkeypatch.setattr(module, "_place_window", lambda hwnd, *pos: placed.append((hwnd, pos)))
    with pytest.raises(module.MultiMonitorError, match="ripristinata"):
        module.swap_active_window()
    assert placed == [(11, (500, 0, 500, 700)), (11, (0, 0, 500, 700))]


@pytest.mark.parametrize("utterance", [
    "sostituisciti con la pagina accanto",
    "sposta Jarvis a destra e l'altra pagina a sinistra",
])
def test_window_swap_is_routed_for_user_requests(utterance):
    from core.tool_router import ToolRouter
    assert "symbiosis_monitor" in ToolRouter().matched_groups(utterance)
    declarations = [{"name": "swap_active_window"}]
    assert ToolRouter().select_for_request(utterance, declarations) == declarations


def test_close_app_confirmation_targets_original_window_not_hud(monkeypatch):
    import os
    import sys
    from actions import computer_settings
    from core import confirm, multi_monitor

    sent = []
    current_pid = [4321]
    gui = SimpleNamespace(GetForegroundWindow=lambda: 77, IsWindow=lambda _: True,
                          PostMessage=lambda *args: sent.append(args))
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _: (1, current_pid[0])))
    monkeypatch.setattr(multi_monitor, "_is_protected_process", lambda pid, name=None: pid == os.getpid())
    monkeypatch.setattr("psutil.Process", lambda _: SimpleNamespace(
        name=lambda: "notepad.exe", create_time=lambda: 123.0))
    monkeypatch.setattr(computer_settings, "_OS", "Windows")
    monkeypatch.setattr(computer_settings, "_PYAUTOGUI", True)
    monkeypatch.setitem(computer_settings.ACTION_MAP, "close_app", computer_settings.close_app)
    monkeypatch.setattr(confirm, "pending_title", lambda: "")
    callbacks = []
    monkeypatch.setattr(confirm, "request", lambda **kwargs: callbacks.append(kwargs["run"]) or "[CONFIRMATION_PENDING]")
    assert "[CONFIRMATION_PENDING]" in computer_settings.computer_settings({"action": "close_app"})
    assert sent == []
    gui.GetForegroundWindow = lambda: 999
    callbacks.pop()()
    assert sent == [(77, 0x0010, 0, 0)]

    computer_settings.computer_settings({"action": "close_app"})
    current_pid[0] = os.getpid()
    with pytest.raises(RuntimeError, match="verificabile"):
        callbacks.pop()()
    assert len(sent) == 1


def test_close_app_refuses_jarvis_window(monkeypatch):
    import os
    import sys
    from actions import computer_settings
    from core import multi_monitor

    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        GetForegroundWindow=lambda: 77, IsWindow=lambda _: True))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _: (1, os.getpid())))
    monkeypatch.setattr(multi_monitor, "_is_protected_process", lambda _: False)
    with pytest.raises(RuntimeError, match="Jarvis"):
        computer_settings._close_app_target()


def test_close_app_real_confirmation_keeps_event_loop_running(monkeypatch):
    import asyncio
    import threading
    from actions import computer_settings
    from core import confirm

    done = threading.Event()
    monkeypatch.setattr(computer_settings, "_OS", "Windows")
    monkeypatch.setattr(computer_settings, "_PYAUTOGUI", True)
    monkeypatch.setitem(computer_settings.ACTION_MAP, "close_app", computer_settings.close_app)
    monkeypatch.setattr(computer_settings, "_close_app_target", lambda: lambda: done.set() or "OK")
    monkeypatch.setattr(confirm, "_pending", None)
    monkeypatch.setattr(confirm, "_show_cb", lambda *_args: None)
    monkeypatch.setattr(confirm, "_hide_cb", lambda *_args: None)
    monkeypatch.setattr(confirm, "_log_cb", None)
    monkeypatch.setattr(confirm, "_keyed_bind", False)

    async def turn():
        task = asyncio.current_task()
        result = await asyncio.to_thread(computer_settings.computer_settings, {"action": "close_app"})
        assert "[CONFIRMATION_PENDING]" in result
        assert not done.is_set()
        confirm.resolve(True)
        assert await asyncio.to_thread(done.wait, 2)
        await asyncio.sleep(0)
        assert not task.cancelled()

    asyncio.run(turn())
