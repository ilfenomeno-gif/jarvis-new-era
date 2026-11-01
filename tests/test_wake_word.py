import numpy as np
import pytest

from core.wake_word import WakeWordAudioGate


class DetectorRecorder:
    def __init__(self):
        self.frames = []

    def feed(self, frame):
        self.frames.append(frame.copy())


def _frame(value):
    return np.array([value], dtype=np.int16)


def test_wake_gate_keeps_audio_local_until_detection_and_bounds_buffer():
    detector = DetectorRecorder()
    gate = WakeWordAudioGate(detector, max_buffered_frames=3)

    for value in range(5):
        assert gate.process_frame(_frame(value)) == ()

    assert [int(frame[0]) for frame in detector.frames] == list(range(5))
    assert gate.is_armed

    gate.activate()
    forwarded = gate.process_frame(_frame(5))

    assert [
        int(np.frombuffer(data, dtype=np.int16)[0]) for data in forwarded
    ] == [3, 4, 5]
    assert not gate.is_armed


def test_wake_gate_rearms_and_discards_old_audio_at_turn_end():
    detector = DetectorRecorder()
    gate = WakeWordAudioGate(detector, max_buffered_frames=3)
    gate.process_frame(_frame(1))
    gate.activate()
    gate.process_frame(_frame(2))

    gate.rearm()

    assert gate.is_armed
    assert gate.process_frame(_frame(3)) == ()
    gate.activate()
    forwarded = gate.process_frame(_frame(4))
    assert [
        int(np.frombuffer(data, dtype=np.int16)[0]) for data in forwarded
    ] == [3, 4]


def test_disabled_wake_gate_preserves_existing_audio_path():
    detector = DetectorRecorder()
    gate = WakeWordAudioGate(detector, enabled=False)
    frame = _frame(7)

    assert gate.process_frame(frame) == (frame.tobytes(),)
    assert detector.frames == []
    assert not gate.is_armed


def test_unavailable_detector_keeps_remote_microphone_gated():
    gate = WakeWordAudioGate(None)

    for value in range(25):
        assert gate.process_frame(_frame(value)) == ()

    assert gate.is_armed


def test_wake_gate_requires_positive_buffer_size():
    with pytest.raises(ValueError, match="positive"):
        WakeWordAudioGate(None, max_buffered_frames=0)
