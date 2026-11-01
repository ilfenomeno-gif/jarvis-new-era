import numpy as np
import pytest

from core.echo import EchoGuard, FullDuplexAudioGate


def _frame(value):
    return np.array([value], dtype=np.int16)


def _tone(sample_count, sample_rate, frequency, amplitude):
    time = np.arange(sample_count, dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * time)).astype(np.int16)


def test_echo_guard_rejects_echo_and_requires_consecutive_voice_blocks():
    guard = EchoGuard()
    output = _tone(1536, 24000, 440, 8000)
    echo = _tone(1024, 16000, 440, 8000)
    overlapping_voice = np.clip(
        echo.astype(np.int32) + _tone(1024, 16000, 1800, 5000).astype(np.int32),
        -32768,
        32767,
    ).astype(np.int16)

    for index in range(24):
        timestamp = index * 0.064
        guard.note_output(output, 24000, 0.4, when=timestamp)
        assert not guard.is_user_speech(
            echo,
            16000,
            0.4,
            when=timestamp + 0.01,
        )
    assert guard.calibrated

    required_blocks = guard.required_blocks
    for index in range(required_blocks - 1):
        timestamp = (24 + index) * 0.064
        guard.note_output(output, 24000, 0.4, when=timestamp)
        assert not guard.is_user_speech(
            overlapping_voice,
            16000,
            0.4,
            when=timestamp + 0.01,
        )

    timestamp = (24 + required_blocks - 1) * 0.064
    guard.note_output(output, 24000, 0.4, when=timestamp)
    assert guard.is_user_speech(
        overlapping_voice,
        16000,
        0.4,
        when=timestamp + 0.01,
    )


def test_echo_guard_requires_consecutive_blocks_without_output_reference():
    guard = EchoGuard()
    voice = _tone(1024, 16000, 700, 8000)

    for index in range(guard.required_blocks - 1):
        assert not guard.is_user_speech(voice, 16000, 0.4, when=index * 0.064)

    assert guard.is_user_speech(
        voice,
        16000,
        0.4,
        when=(guard.required_blocks - 1) * 0.064,
    )


def test_full_duplex_gate_holds_audio_until_speech_detection():
    gate = FullDuplexAudioGate(max_buffered_frames=3)

    for value in range(5):
        assert gate.process(
            _frame(value),
            assistant_speaking=True,
        ) == ()

    opened = gate.process(
        _frame(5),
        assistant_speaking=True,
        user_speech=True,
    )
    assert [int(frame[0]) for frame in opened] == [3, 4, 5]
    assert gate.is_open


def test_full_duplex_gate_stays_open_until_assistant_stops():
    gate = FullDuplexAudioGate()
    gate.process(_frame(1), assistant_speaking=True, user_speech=True)
    assert gate.is_open

    passed = gate.process(_frame(2), assistant_speaking=True)
    assert [int(frame[0]) for frame in passed] == [2]

    assert gate.process(_frame(3), assistant_speaking=False) == ()
    assert not gate.is_open
    assert gate.process(_frame(4), assistant_speaking=True) == ()


def test_full_duplex_gate_rejects_unbounded_or_empty_buffer():
    with pytest.raises(ValueError, match="positive"):
        FullDuplexAudioGate(max_buffered_frames=0)
