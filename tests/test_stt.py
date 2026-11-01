import sys
from types import SimpleNamespace

import numpy as np
import pytest

from core.stt import DictationBuffer, route_microphone_audio


def test_dictation_buffer_is_bounded_and_cleared_after_stop():
    capture = DictationBuffer(max_seconds=1, sample_rate=4)
    capture.start()
    first = np.array([[32767], [0], [-32768]], dtype=np.int16)
    assert capture.append(first)
    first[:] = 1
    assert capture.append(np.array([100, 200], dtype=np.int16))

    audio = capture.stop()

    assert audio.dtype == np.float32
    assert audio.shape == (4,)
    assert audio[0] == pytest.approx(32767 / 32768)
    assert audio[-1] == pytest.approx(100 / 32768)
    assert not capture.is_recording
    assert not capture.append(np.array([1], dtype=np.int16))


def test_dictation_buffer_rejects_overlapping_start_and_bad_audio():
    capture = DictationBuffer(max_seconds=1, sample_rate=4)
    capture.start()

    with pytest.raises(RuntimeError, match="already recording"):
        capture.start()
    with pytest.raises(TypeError, match="int16"):
        capture.append(np.array([0.5], dtype=np.float32))

    capture.stop()


def test_dictation_buffer_validates_limits_and_empty_stop():
    with pytest.raises(ValueError, match="positive"):
        DictationBuffer(max_seconds=0)

    capture = DictationBuffer()
    capture.start()
    assert capture.stop().size == 0


def test_dictation_audio_is_not_forwarded_to_wake_or_live_stream():
    capture = DictationBuffer(max_seconds=1, sample_rate=4)
    capture.start()

    class WakeGateRecorder:
        def __init__(self):
            self.seen = []

        def process_frame(self, frame):
            self.seen.append(frame)
            return (frame.tobytes(),)

    gate = WakeGateRecorder()
    frame = np.array([[1], [2]], dtype=np.int16)

    assert route_microphone_audio(frame, capture, gate) == ()
    assert gate.seen == []
    assert np.array_equal(capture.stop(), np.array([1, 2], dtype=np.float32) / 32768)


def test_normal_mic_frames_keep_existing_wake_and_live_routes():
    capture = DictationBuffer()
    frame = np.array([[3], [4]], dtype=np.int16)
    assert route_microphone_audio(frame, capture) == (frame.tobytes(),)

    class WakeGateRecorder:
        def process_frame(self, value):
            return (b"wake-gated", value.tobytes())

    assert route_microphone_audio(
        frame,
        capture,
        WakeGateRecorder(),
    ) == (b"wake-gated", frame.tobytes())


def test_whisper_local_only_mode_never_retries_with_download(monkeypatch):
    calls = []

    def unavailable_model(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("model files unavailable")

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=unavailable_model),
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            set_num_threads=lambda _count: None,
            set_num_interop_threads=lambda _count: None,
        ),
    )

    from core.stt import WhisperSTT

    with pytest.raises(RuntimeError, match="not available in the local cache"):
        WhisperSTT(local_files_only=True)

    assert len(calls) == 1
    assert calls[0][1]["local_files_only"] is True


def test_dictation_result_is_reviewed_in_command_input_not_sent():
    from ui import MainWindow

    sent = []
    log = []

    class InputRecorder:
        def __init__(self):
            self.value = "existing command"

        def text(self):
            return self.value

        def setText(self, value):
            self.value = value

        def setFocus(self):
            pass

    window = SimpleNamespace(
        _dictation_btn=SimpleNamespace(
            setEnabled=lambda _enabled: None,
            blockSignals=lambda _blocked: None,
            setChecked=lambda _checked: None,
            setText=lambda _text: None,
        ),
        _input=InputRecorder(),
        _log_sig=SimpleNamespace(emit=log.append),
        _set_dictation_busy=lambda _busy: None,
        _send=lambda: sent.append(True),
    )

    MainWindow._on_dictation_result(window, True, "new words")

    assert window._input.value == "existing command new words"
    assert not sent
    assert "not been sent" in log[0]


def test_dictation_buffer_releases_frame_references_after_stop():
    capture = DictationBuffer(max_seconds=1, sample_rate=4)
    capture.start()
    capture.append(np.array([10, 20], dtype=np.int16))
    capture.stop()

    assert capture._frames == []
    assert capture._sample_count == 0


def test_dictation_discard_drops_audio_without_returning_a_transcript_buffer():
    capture = DictationBuffer(max_seconds=1, sample_rate=4)
    capture.start()
    capture.append(np.array([10, 20], dtype=np.int16))

    capture.discard()

    assert not capture.is_recording
    assert capture._frames == []
    assert capture._sample_count == 0


def test_set_dictation_refuses_before_recording_when_whisper_missing(monkeypatch):
    import main
    import core.stt as stt

    monkeypatch.setattr(stt, "whisper_available", lambda: False)
    logs, started = [], []
    self = SimpleNamespace(
        ui=SimpleNamespace(write_log=logs.append, muted=False),
        _dictation_capture=SimpleNamespace(start=lambda: started.append(1)),
    )

    assert main.JarvisLive._set_dictation(self, True) is False
    assert not started
    assert "faster-whisper" in logs[0]
