import pytest

from core.computer_vision import ComputerVision, ScreenElement


def _ocr_result(words, boxes):
    return {
        "text": words,
        "left": [box[0] for box in boxes],
        "top": [box[1] for box in boxes],
        "width": [box[2] for box in boxes],
        "height": [box[3] for box in boxes],
        "conf": ["90"] * len(words),
    }


def test_capture_and_ocr_extract_visible_text_from_mock_image():
    image = object()
    vision = ComputerVision(
        capture_provider=lambda: image,
        ocr_provider=lambda frame: (
            _ocr_result(["Search", "Jarvis"], [(10, 20, 40, 12), (60, 20, 35, 12)])
            if frame is image
            else _ocr_result([], [])
        ),
    )

    captured = vision.capture_screen()

    assert captured is image
    assert vision.extract_text(captured) == "Search Jarvis"
    assert vision.find_element_on_screen(captured, "search") == ScreenElement(
        "Search", 10, 20, 40, 12, 90.0
    )


def test_find_multiword_target_returns_combined_bounds():
    vision = ComputerVision(
        capture_provider=lambda: object(),
        ocr_provider=lambda _: _ocr_result(
            ["Open", "File"], [(3, 5, 20, 10), (27, 5, 18, 10)]
        ),
    )

    assert vision.find_element_on_screen(object(), "Open File") == ScreenElement(
        "Open File", 3, 5, 42, 10, 90.0
    )


def test_capture_and_target_validation_fail_explicitly():
    with pytest.raises(RuntimeError, match="no image"):
        ComputerVision(capture_provider=lambda: None).capture_screen()
    vision = ComputerVision(
        capture_provider=lambda: object(),
        ocr_provider=lambda _: _ocr_result([], []),
    )
    with pytest.raises(ValueError, match="target_description"):
        vision.find_element_on_screen(object(), " ")
