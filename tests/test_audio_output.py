import asyncio
import threading

import pytest


def test_play_audio_survives_portaudio_write_failure(monkeypatch):
    import main
    from main import JarvisLive

    write_attempted = threading.Event()
    failure_reported = threading.Event()
    logs = []

    class BrokenOutputStream:
        def start(self):
            pass

        def write(self, data):
            write_attempted.set()
            raise main.sd.PortAudioError(
                "No audio driver", -9999, (0, 0, "No driver")
            )

        def stop(self):
            pass

        def close(self):
            pass

    class UIRecorder:
        def write_log(self, message):
            logs.append(message)
            if "Audio output unavailable" in message:
                failure_reported.set()

        def set_audio_level(self, level):
            pass

    live = JarvisLive.__new__(JarvisLive)
    live.ui = UIRecorder()
    live.audio_in_queue = asyncio.Queue()
    live.audio_in_queue.put_nowait(bytes(2_400))
    live._page_reader_audio_active = threading.Event()
    live._echo_guard = None
    live._turn_done_event = None
    live.set_speaking = lambda *_args, **_kwargs: None
    monkeypatch.setattr(main, "get_output_device", lambda: "System default")
    monkeypatch.setattr(main.audio_devices, "resolve", lambda *_args: None)
    monkeypatch.setattr(main.sd, "RawOutputStream", lambda **_kwargs: BrokenOutputStream())

    async def run():
        task = asyncio.create_task(live._play_audio())
        try:
            assert await asyncio.to_thread(write_attempted.wait, 1)
            assert await asyncio.to_thread(failure_reported.wait, 1)
            assert live.audio_in_queue.empty()
            assert any("Audio output unavailable" in message for message in logs)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())


def test_play_audio_retries_selected_speaker_failure_on_system_default(monkeypatch):
    import main
    from main import JarvisLive

    fallback_write = threading.Event()
    logs = []

    class OutputStream:
        def __init__(self, device):
            self.device = device

        def start(self):
            pass

        def write(self, _data):
            if self.device == 7:
                raise main.sd.PortAudioError(
                    "Selected device failed", -9999, (0, 0, "No driver")
                )
            fallback_write.set()

        def stop(self):
            pass

        def close(self):
            pass

    class UIRecorder:
        def write_log(self, message):
            logs.append(message)

        def set_audio_level(self, _level):
            pass

    live = JarvisLive.__new__(JarvisLive)
    live.ui = UIRecorder()
    live.audio_in_queue = asyncio.Queue()
    live.audio_in_queue.put_nowait(bytes(2_400))
    live._page_reader_audio_active = threading.Event()
    live._echo_guard = None
    live._turn_done_event = asyncio.Event()
    live._turn_done_event.set()
    live.set_speaking = lambda *_args, **_kwargs: None
    monkeypatch.setattr(main, "get_output_device", lambda: "Selected speaker")
    monkeypatch.setattr(main.audio_devices, "resolve", lambda *_args: 7)
    monkeypatch.setattr(
        main.sd,
        "RawOutputStream",
        lambda **kwargs: OutputStream(kwargs["device"]),
    )

    async def run():
        task = asyncio.create_task(live._play_audio())
        try:
            assert await asyncio.to_thread(fallback_write.wait, 1)
            assert any("system default output" in message for message in logs)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
