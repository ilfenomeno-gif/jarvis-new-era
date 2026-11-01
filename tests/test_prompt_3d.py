"""Prompt translation/builder and candidate scoring for local 3D (no GPU needed)."""
import numpy as np
import pytest

from core import local_3d_worker as worker
from core.prompt_3d import build_image_prompt, to_english


@pytest.mark.parametrize("text, expected", [
    ("una sedia", "a chair"),
    ("una sedia di legno", "a wooden chair"),
    ("un motore a reazione", "a jet engine"),
    ("la spada laser", "a laser sword"),
    ("crea un ologramma di una macchina rossa", "a red car"),
    ("una scheda video", "a graphics card"),
    ("una sedia con il cuscino", "a chair with cushion"),
])
def test_italian_is_translated(text, expected):
    assert to_english(text) == (expected, True)


def test_english_is_left_alone():
    assert to_english("a simple chair") == ("a simple chair", False)
    assert to_english("a red dragon")[1] is False


def test_prompt_has_3d_friendly_suffix():
    prompt, report = build_image_prompt("una sedia")
    assert prompt.startswith("a chair")
    for part in ("isolated on a solid white background", "studio lighting", "high quality", "3D asset"):
        assert part in prompt
    assert report == {"original": "una sedia", "english": "a chair", "translated": True}


def test_prompt_forces_clean_geometry_and_boxy_wardrobe():
    prompt, _ = build_image_prompt("un armadio")
    assert prompt.startswith("a closed wooden wardrobe, simple box shape")
    for part in ("clean geometry", "single object", "no overlapping parts", "sharp edges", "solid structure"):
        assert part in prompt
    assert "simple box shape" in build_image_prompt("un armadio di legno")[0]
    assert "box shape" not in build_image_prompt("una sedia")[0]


def test_viewer_set_controls_is_validated():
    from core.viewer3d import build_call
    assert build_call("setControls", [False])[1] == "[false]"
    with pytest.raises(ValueError):
        build_call("setControls", ["yes"])


def _mask(boxes, size=100):
    alpha = np.zeros((size, size), dtype=np.uint8)
    for x0, y0, x1, y1 in boxes:
        alpha[y0:y1, x0:x1] = 255
    return alpha


def test_score_prefers_centred_single_object():
    good = worker.score_cutout(_mask([(30, 25, 70, 75)]))
    cropped = worker.score_cutout(_mask([(0, 0, 60, 60)]))
    scattered = worker.score_cutout(_mask([(5, 5, 25, 25), (70, 70, 95, 95), (5, 70, 25, 95)]))
    assert good > cropped
    assert good > scattered


def test_score_rejects_empty_mask():
    assert worker.score_cutout(_mask([])) == 0.0
    assert worker.score_cutout(_mask([(10, 10, 14, 14)])) == 0.0


def test_cutout_stats_reports_bbox():
    stats = worker.cutout_stats(_mask([(20, 30, 60, 80)]))
    assert stats["bbox"] == [20, 30, 59, 79]
    assert 0.19 < stats["object_ratio"] < 0.21
