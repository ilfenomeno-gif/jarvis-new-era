import io
import sys
from types import SimpleNamespace

import google.genai
import pytest
from PIL import Image

from actions import capture_and_analyze_screen as vision
from actions import screen_processor


@pytest.fixture(autouse=True)
def reset_vision_state(monkeypatch):
    monkeypatch.setattr(vision, "_vision_in_progress", False)
    monkeypatch.setattr(vision, "_vision_finished_at", None)
    monkeypatch.setattr(vision, "_vision_internal_errors", 0)


def _mock_capture(monkeypatch, window=None):
    targets = []
    desktop = {"left": -1000, "top": 0, "width": 3560, "height": 1440}
    primary = {"left": 0, "top": 0, "width": 2560, "height": 1440}

    class Capture:
        monitors = [desktop, primary]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def grab(self, target):
            targets.append(target)
            size = (target["width"], target["height"])
            return SimpleNamespace(size=size, rgb=Image.new("RGB", size, "blue").tobytes())

    def to_png(rgb, size):
        output = io.BytesIO()
        Image.frombytes("RGB", size, rgb).save(output, "PNG")
        return output.getvalue()

    monkeypatch.setattr(screen_processor, "_MSS", True)
    monkeypatch.setattr(screen_processor, "mss", SimpleNamespace(
        mss=Capture, tools=SimpleNamespace(to_png=to_png)
    ))
    monkeypatch.setitem(sys.modules, "pygetwindow", SimpleNamespace(
        getActiveWindow=lambda: window
    ))
    return targets


def test_real_capture_pipeline_sends_1024px_image_to_gemma(monkeypatch):
    targets = _mock_capture(monkeypatch)
    calls = []

    class QuotaError(Exception):
        code = 429

    def generate_content(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise QuotaError("RESOURCE_EXHAUSTED")
        return SimpleNamespace(text="Il browser è a destra.")

    monkeypatch.setattr(vision, "_run_isolated", vision._capture_and_analyze_screen)
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ))

    assert vision.capture_and_analyze_screen() == "Il browser è a destra."
    assert targets == [{"left": 0, "top": 0, "width": 2560, "height": 1440}]
    assert calls[1]["model"] == vision.GEMMA_VISION_MODEL
    assert calls[0]["contents"] == calls[1]["contents"]
    image = Image.open(io.BytesIO(calls[1]["contents"][0].inline_data.data))
    assert image.size == (1024, 576)
    assert "sinistra, destra, centro" in calls[1]["contents"][1]


def test_active_window_capture_clips_to_virtual_desktop(monkeypatch):
    window = SimpleNamespace(left=-1100, top=100, width=500, height=800, isMinimized=False)
    targets = _mock_capture(monkeypatch, window)
    image_bytes, mime_type = screen_processor._capture_vision_screen("active_window")
    assert targets == [{"left": -1000, "top": 100, "width": 400, "height": 800}]
    assert mime_type == "image/png"
    assert Image.open(io.BytesIO(image_bytes)).size == (400, 800)


def test_active_window_mode_sends_only_window_image(monkeypatch):
    window = SimpleNamespace(left=20, top=30, width=1600, height=900, isMinimized=False)
    targets = _mock_capture(monkeypatch, window)
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="Vedo una finestra.")

    monkeypatch.setattr(vision, "_run_isolated", vision._capture_and_analyze_screen)
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ))
    assert vision.capture_and_analyze_screen({"capture_mode": "active_window"}) == "Vedo una finestra."
    assert targets == [{"left": 20, "top": 30, "width": 1600, "height": 900}]
    image = Image.open(io.BytesIO(calls[0]["contents"][0].inline_data.data))
    assert image.size == (1024, 576)


@pytest.mark.parametrize("window", [
    None,
    SimpleNamespace(left=0, top=0, width=500, height=500, isMinimized=True),
    SimpleNamespace(left=5000, top=0, width=500, height=500, isMinimized=False),
])
def test_active_window_capture_never_falls_back_to_full_screen(monkeypatch, window):
    targets = _mock_capture(monkeypatch, window)
    with pytest.raises(RuntimeError, match="finestra"):
        screen_processor._capture_vision_screen("active_window")
    assert targets == []


def test_invalid_capture_mode_is_rejected(monkeypatch):
    targets = _mock_capture(monkeypatch)
    with pytest.raises(ValueError, match="Modalità"):
        screen_processor._capture_vision_screen("unknown")
    assert targets == []
