import asyncio
import threading

import pytest


@pytest.mark.timeout(10)
def test_interrupt_during_playback_stops_queue_and_releases_listening(monkeypatch):
    import main
    from main import JarvisLive

    write_started = asyncio.Event()
    release_write = threading.Event()
    speaking = []
    logs = []
    loop = asyncio.new_event_loop()

    class BlockingOutputStream:
        def start(self):
            pass

        def write(self, _data):
            loop.call_soon_threadsafe(write_started.set)
            if not release_write.wait(timeout=5):
                raise TimeoutError("test output stream was not released")

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
    live._interrupted = False

    def set_speaking(value, **_kwargs):
        speaking.append(value)

    live.set_speaking = set_speaking
    monkeypatch.setattr(main, "get_output_device", lambda: None)
    monkeypatch.setattr(main.audio_devices, "select_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main.sd,
        "RawOutputStream",
        lambda **_kwargs: BlockingOutputStream(),
    )

    async def run():
        task = asyncio.create_task(live._play_audio())
        try:
            await write_started.wait()
            live.audio_in_queue.put_nowait(bytes(2_400))
            live.audio_in_queue.put_nowait(bytes(2_400))

            live.interrupt()

            assert live._interrupted
            assert live.audio_in_queue.empty()
            assert not live._turn_done_event.is_set()
            assert speaking[-1] is False
            assert any("Interrupted" in message for message in logs)
        finally:
            release_write.set()
            task.cancel()
            await task

    try:
        loop.run_until_complete(run())
    finally:
        release_write.set()
        loop.close()
