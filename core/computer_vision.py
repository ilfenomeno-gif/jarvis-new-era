"""Screen capture and OCR-backed element lookup with injectable providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ScreenElement:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float | None = None

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


def _capture_screen() -> Any:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("Screen capture requires Pillow.") from exc
    return ImageGrab.grab()


def _ocr_data(image: Any) -> Mapping[str, Sequence[Any]]:
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires pytesseract; install it or inject an ocr_provider."
        ) from exc
    return pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)


CaptureProvider = Callable[[], Any]
OCRProvider = Callable[[Any], Mapping[str, Sequence[Any]]]


class ComputerVision:
    """Capture a screen and locate visible text using local OCR."""

    def __init__(
        self,
        capture_provider: CaptureProvider | None = None,
        ocr_provider: OCRProvider | None = None,
    ) -> None:
        self.capture_provider = capture_provider or _capture_screen
        self.ocr_provider = ocr_provider or _ocr_data

    def capture_screen(self) -> Any:
        image = self.capture_provider()
        if image is None:
            raise RuntimeError("The screen capture provider returned no image.")
        return image

    def _records(self, image: Any) -> list[dict[str, Any]]:
        raw = self.ocr_provider(image)
        if not isinstance(raw, Mapping):
            raise TypeError("The OCR provider must return a mapping of OCR fields.")
        words = raw.get("text", ())
        if isinstance(words, (str, bytes)):
            raise TypeError("The OCR 'text' field must be a sequence of words.")
        records: list[dict[str, Any]] = []
        for index, value in enumerate(words):
            text = str(value).strip()
            if not text:
                continue
            try:
                x = int(raw.get("left", ())[index])
                y = int(raw.get("top", ())[index])
                width = int(raw.get("width", ())[index])
                height = int(raw.get("height", ())[index])
            except (IndexError, TypeError, ValueError) as exc:
                raise ValueError("OCR bounding boxes are missing or invalid.") from exc
            confidence_values = raw.get("conf", ())
            confidence: float | None = None
            if index < len(confidence_values):
                try:
                    value_conf = float(confidence_values[index])
                    if value_conf >= 0:
                        confidence = value_conf
                except (TypeError, ValueError):
                    pass
            records.append(
                {
                    "text": text,
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "confidence": confidence,
                }
            )
        return records

    def extract_text(self, image: Any) -> str:
        return " ".join(record["text"] for record in self._records(image))

    def find_element_on_screen(
        self,
        image: Any,
        target_description: str,
    ) -> ScreenElement | None:
        if not isinstance(target_description, str) or not target_description.strip():
            raise ValueError("target_description must be non-empty text.")
        target = " ".join(target_description.casefold().split())
        records = self._records(image)
        for record in records:
            normalized = " ".join(record["text"].casefold().split())
            if target in normalized:
                return ScreenElement(**record)

        words = target.split()
        if len(words) > 1:
            for start in range(len(records) - len(words) + 1):
                group = records[start : start + len(words)]
                if [item["text"].casefold() for item in group] == words:
                    left = min(item["x"] for item in group)
                    top = min(item["y"] for item in group)
                    right = max(item["x"] + item["width"] for item in group)
                    bottom = max(item["y"] + item["height"] for item in group)
                    confidences = [
                        item["confidence"]
                        for item in group
                        if item["confidence"] is not None
                    ]
                    return ScreenElement(
                        text=target_description,
                        x=left,
                        y=top,
                        width=right - left,
                        height=bottom - top,
                        confidence=min(confidences) if confidences else None,
                    )
        return None
