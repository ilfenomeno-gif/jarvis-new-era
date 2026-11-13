from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from core import confirm


@pytest.fixture
def keyed_gate(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    monkeypatch.setattr(confirm, "_show_cb", None)
    monkeypatch.setattr(confirm, "_hide_cb", None)
    monkeypatch.setattr(confirm, "_log_cb", None)
    monkeypatch.setattr(confirm, "_keyed_bind", False)
    shown, hidden = [], []
    confirm.bind(lambda *args: shown.append(args), hidden.append, keyed=True)
    yield shown, hidden
    with confirm._lock:
        confirm._pending = None


def test_stale_hud_key_and_unkeyed_cannot_resolve_new_request(keyed_gate):
    shown, hidden = keyed_gate
    executed = []
    confirm.request("same", "one", "", lambda: executed.append("one"))
    old = shown[-1][0]
    confirm.resolve(False, key=old)
    confirm.request("same", "two", "", lambda: executed.append("two"))
    current = shown[-1][0]
    assert old != current
    confirm.resolve(True, key=old)
    confirm.resolve(True)
    assert confirm.pending_title() == "two"
    assert hidden == [old]
    assert executed == []
    confirm.resolve(False, key=current)
    assert hidden == [old, current]


def test_voice_and_hud_race_only_one_wins(keyed_gate):
    shown, hidden = keyed_gate
    done = threading.Event()
    actions = []
    confirm.request(
        "process-master-one", "one", "",
        lambda: (actions.append("executed"), done.set(), "done")[-1],
        process_voice=True,
    )
    token, _ = confirm.process_voice_candidate()
    captured = time.monotonic()
    barrier = threading.Barrier(3)

    def hud():
        barrier.wait()
        confirm.resolve(True, key=token)

    def voice():
        barrier.wait()
        confirm.resolve_process_voice(token, True, captured)

    threads = [threading.Thread(target=hud), threading.Thread(target=voice)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2)
    assert done.wait(2)
    assert actions == ["executed"]
    assert hidden == [token]
    assert shown[0][0] == token


def test_stale_voice_and_non_process_request_fail_closed(keyed_gate):
    shown, _ = keyed_gate
    confirm.request("process-master-a", "one", "", lambda: None, process_voice=True)
    token, requested = confirm.process_voice_candidate()
    assert not confirm.resolve_process_voice(token, True, requested)
    confirm.resolve(False, key=token)
    confirm.request("process-master-a", "two", "", lambda: None, process_voice=True)
    replacement = shown[-1][0]
    assert not confirm.resolve_process_voice(token, True, time.monotonic())
    assert confirm.pending_title() == "two"
    confirm.resolve(False, key=replacement)
    confirm.request("other", "other", "", lambda: None)
    assert confirm.process_voice_candidate() is None
    assert not confirm.resolve_process_voice(shown[-1][0], True, time.monotonic())
    confirm.resolve(False, key=shown[-1][0])


def test_legacy_interface_supports_legacy_gate_but_not_voice(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    monkeypatch.setattr(confirm, "_show_cb", None)
    monkeypatch.setattr(confirm, "_hide_cb", None)
    monkeypatch.setattr(confirm, "_log_cb", None)
    monkeypatch.setattr(confirm, "_keyed_bind", False)
    shown, hidden = [], []
    confirm.bind(lambda *args: shown.append(args), lambda: hidden.append(True))
    confirm.request("process-master-one", "one", "", lambda: None, process_voice=True)
    assert shown == [("one", "")]
    assert not confirm.keyed_interface_active()
    assert confirm.process_voice_candidate() is None
    confirm.resolve(False)
    assert hidden == [True]


def test_ui_ignores_stale_show_hide_and_answers(monkeypatch):
    import ui

    class Signal:
        def connect(self, callback):
            self.callback = callback

        def emit(self, value):
            self.callback(value)

    class Banner:
        def __init__(self, title, detail, parent):
            self.answered = Signal()
            self.hidden = False

        def hide(self):
            self.hidden = True

        def deleteLater(self):
            pass

    monkeypatch.setattr(ui, "ConfirmBanner", Banner)
    monkeypatch.setattr(confirm, "_pending", None)
    monkeypatch.setattr(confirm, "_show_cb", None)
    monkeypatch.setattr(confirm, "_hide_cb", None)
    monkeypatch.setattr(confirm, "_log_cb", None)
    monkeypatch.setattr(confirm, "_keyed_bind", False)
    window = SimpleNamespace(
        _confirm_overlay=None, _confirm_overlay_key=None,
        centralWidget=lambda: None, _centre_overlay=lambda _overlay: None,
        _log=SimpleNamespace(append_log=lambda _msg: None),
    )
    window._hide_confirm_banner = lambda key=None: ui.MainWindow._hide_confirm_banner(window, key)
    window._on_confirm_answered = lambda key, accepted: ui.MainWindow._on_confirm_answered(
        window, key, accepted
    )
    queued = []
    confirm.bind(lambda *args: queued.append(args), lambda key: queued.append(("hide", key)),
                 keyed=True)
    confirm.request("same", "old", "", lambda: None)
    old = queued[-1]
    ui.MainWindow._show_confirm_banner(window, *old)
    old_banner = window._confirm_overlay
    confirm.resolve(False, key=old[0])
    confirm.request("same", "new", "", lambda: None)
    new = queued[-1]
    ui.MainWindow._show_confirm_banner(window, *new)
    new_banner = window._confirm_overlay
    ui.MainWindow._hide_confirm_banner(window, old[0])
    ui.MainWindow._show_confirm_banner(window, *old)
    old_banner.answered.emit(True)
    assert window._confirm_overlay is new_banner and not new_banner.hidden
    assert confirm.pending_title() == "new"
    new_banner.answered.emit(False)
    assert confirm.pending_title() == ""
    ui.MainWindow._hide_confirm_banner(window, new[0])
    assert window._confirm_overlay is None


@pytest.mark.parametrize(
    ("info", "status", "calibration", "expected"),
    [
        (SimpleNamespace(inputBufferAdcTime=49.9, currentTime=50.1), False, (100.0, 50.0), 99.8),
        (SimpleNamespace(inputBufferAdcTime=49.9, currentTime=50.1), True, (100.0, 50.0), 0.0),
        (SimpleNamespace(inputBufferAdcTime=49.9, currentTime=50.1), False, None, 0.0),
        (SimpleNamespace(inputBufferAdcTime=49.9, currentTime=50.1), False, (98.0, 50.0), 0.0),
        (SimpleNamespace(inputBufferAdcTime=float("nan"), currentTime=50.1), False, (100.0, 50.0), 0.0),
        (SimpleNamespace(inputBufferAdcTime=52, currentTime=50.1), False, (100.0, 50.0), 0.0),
    ],
)
def test_audio_clock_mapping_rejects_unverifiable_frames(info, status, calibration, expected):
    from main import _process_voice_frame_time

    assert _process_voice_frame_time(info, status, calibration, 100.2) == pytest.approx(expected)


def test_inflight_voice_discarded_when_mic_becomes_unavailable(keyed_gate, monkeypatch):
    import numpy as np

    import main

    shown, _ = keyed_gate
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    executed = []

    class SlowSTT:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, _audio):
            started.set()
            release.wait(2)
            finished.set()
            return "confermo"

    monkeypatch.setattr(main, "WhisperSTT", SlowSTT)
    confirm.request("process-master-test", "target", "",
                    lambda: executed.append(True), process_voice=True)
    capture = main._ProcessVoiceCapture()
    silence = np.zeros(1024, dtype=np.int16)
    speech = np.full(1024, 3000, dtype=np.int16)
    for frame in [silence] * 7 + [speech] * 4 + [silence] * 10:
        capture.feed(frame, allowed=True, speaking=False, captured_at=time.monotonic())
    assert started.wait(2)
    capture.feed(silence, allowed=False, speaking=False, captured_at=time.monotonic())
    release.set()
    assert finished.wait(2)
    deadline = time.monotonic() + 2
    while capture._working and time.monotonic() < deadline:
        time.sleep(0.01)
    assert executed == []
    assert confirm.pending_title() == "target"
    confirm.resolve(False, key=shown[0][0])


def test_missing_local_stt_preserves_hud_confirmation(keyed_gate, monkeypatch):
    import numpy as np

    import main

    shown, _ = keyed_gate
    attempted = threading.Event()
    executed = []

    def unavailable(**options):
        assert options["local_files_only"] is True
        attempted.set()
        raise RuntimeError("local model missing")

    monkeypatch.setattr(main, "WhisperSTT", unavailable)
    confirm.request("process-master-test", "target", "",
                    lambda: executed.append(True), process_voice=True)
    capture = main._ProcessVoiceCapture()
    silence = np.zeros(1024, dtype=np.int16)
    speech = np.full(1024, 3000, dtype=np.int16)
    for frame in [silence] * 7 + [speech] * 4 + [silence] * 10:
        capture.feed(frame, allowed=True, speaking=False, captured_at=time.monotonic())
    assert attempted.wait(2)
    assert confirm.pending_title() == "target"
    assert executed == []
    confirm.resolve(False, key=shown[0][0])
