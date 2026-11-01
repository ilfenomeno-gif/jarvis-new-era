"""Optional accessibility bridge for JARVIS.

The module is deliberately opt-in: importing it never installs global hotkeys,
starts a speech engine, or captures the screen.  It combines local OCR,
keyboard shortcuts, a lightweight speech fallback, and the NVDA controller
client when that client is available on Windows.
"""
from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from typing import Callable, Mapping, Protocol


ACCESSIBILITY_HOTKEYS_ENV = "JARVIS_ACCESSIBILITY_HOTKEYS"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_MAX_SPOKEN_SCREEN_CHARS = 300


def accessibility_hotkeys_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether the user explicitly enabled global accessibility hotkeys."""
    values = os.environ if environ is None else environ
    return values.get(ACCESSIBILITY_HOTKEYS_ENV, "").strip().casefold() in _TRUE_VALUES


class SpeechBackend(Protocol):
    def speak(self, text: str) -> None: ...


class NVDAClient:
    """Speak through nvdaControllerClient.dll when NVDA is installed."""

    def __init__(self, dll_path: str | os.PathLike[str] | None = None) -> None:
        if os.name != "nt":
            raise OSError("NVDA Controller Client is supported on Windows only")
        path = Path(dll_path) if dll_path else self._find_dll()
        if path is None:
            raise FileNotFoundError("nvdaControllerClient.dll was not found")
        self._dll = ctypes.WinDLL(str(path))
        self._dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
        self._dll.nvdaController_speakText.restype = ctypes.c_int

    @staticmethod
    def _find_dll() -> Path | None:
        candidates = [
            Path(__file__).resolve().parent.parent / "nvdaControllerClient.dll",
            Path(os.environ.get("ProgramFiles", "")) / "NVDA" / "nvdaControllerClient.dll",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "NVDA" / "nvdaControllerClient.dll",
        ]
        return next((path for path in candidates if path.is_file()), None)

    def speak(self, text: str) -> None:
        if text.strip():
            result = self._dll.nvdaController_speakText(text)
            if result != 0:
                raise RuntimeError(f"NVDA speech request failed with code {result}")

    def cancel(self) -> None:
        self._dll.nvdaController_cancelSpeech()


class Pyttsx3Backend:
    """Small offline fallback; imported only when this backend is selected."""

    def __init__(self, voice: str | None = None, rate: int | None = None) -> None:
        import pyttsx3

        self._engine = pyttsx3.init()
        if voice:
            self._engine.setProperty("voice", voice)
        if rate is not None:
            self._engine.setProperty("rate", rate)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        self._engine.say(text)
        self._engine.runAndWait()

    def speak_interruptibly(
        self,
        text: str,
        stop_event: threading.Event,
    ) -> None:
        if not text.strip():
            return
        self._engine.say(text)
        self._engine.startLoop(False)
        try:
            while self._engine.isBusy():
                if stop_event.is_set():
                    self._engine.stop()
                    break
                self._engine.iterate()
                stop_event.wait(0.01)
        finally:
            self._engine.endLoop()

    def cancel(self) -> None:
        self._engine.stop()


def create_speech_backend(
    preferred: str = "jarvis",
    jarvis_tts: SpeechBackend | None = None,
    *,
    voice: str = "if_sara",
    speed: float = 1.0,
) -> SpeechBackend:
    """Select a local reader backend or the existing JARVIS speech backend."""
    name = preferred.casefold().strip()
    if name == "nvda":
        return NVDAClient()
    if name in {"pyttsx3", "system"}:
        return Pyttsx3Backend()
    if name == "kokoro":
        from core.tts import KokoroTTSEngine

        return KokoroTTSEngine(voice=voice, speed=speed)
    if jarvis_tts is not None:
        return jarvis_tts
    raise RuntimeError("No speech backend is configured")


def _capture_region(bbox: tuple[int, int, int, int] | None = None):
    import pyautogui

    return pyautogui.screenshot(region=bbox) if bbox else pyautogui.screenshot()


def ocr_screen_region(
    bbox: tuple[int, int, int, int] | None = None,
    language: str = "ita",
    min_confidence: float = 0.0,
) -> str:
    """Read a full screen or ``(x, y, width, height)`` region locally."""
    import pytesseract

    image = _capture_region(bbox)
    text = pytesseract.image_to_string(image, lang=language)
    if min_confidence <= 0:
        return text.strip()

    data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
    words = []
    for word, confidence in zip(data.get("text", []), data.get("conf", [])):
        try:
            accepted = float(confidence) >= min_confidence
        except (TypeError, ValueError):
            accepted = False
        if accepted and word.strip():
            words.append(word.strip())
    return " ".join(words)


class AccessibilityController:
    """Coordinate OCR, speech output, and opt-in keyboard shortcuts."""

    def __init__(
        self,
        speech: SpeechBackend | None = None,
        ocr: Callable[..., str] = ocr_screen_region,
    ) -> None:
        self.speech = speech
        self.ocr = ocr
        self._hotkeys: list[str] = []
        self._keyboard = None

    def speak(self, text: str) -> None:
        message = str(text).strip()
        if not message:
            return
        print(f"[ScreenReader] {message}")
        if self.speech:
            self.speech.speak(message)

    def read_screen(self, bbox: tuple[int, int, int, int] | None = None, language: str = "ita") -> str:
        self.speak("Analisi dello schermo in corso.")
        try:
            text = self.ocr(bbox=bbox, language=language)
        except Exception as exc:
            self.speak(f"Lettura dello schermo non disponibile: {exc}")
            return ""
        if text:
            spoken_text = text[:_MAX_SPOKEN_SCREEN_CHARS]
            if len(text) > _MAX_SPOKEN_SCREEN_CHARS:
                spoken_text += " Testo abbreviato; il risultato completo è disponibile al chiamante."
            self.speak(spoken_text)
        else:
            self.speak("Nessun testo rilevato sullo schermo.")
        return text

    def click_and_type(self, target_text: str, text_to_type: str) -> bool:
        """Find visible text with OCR, click its center, and type only on success."""
        target = str(target_text).strip()
        if not target:
            self.speak("Specificare il testo dell'elemento da cercare.")
            return False
        self.speak(f"Cerco l'elemento {target} sullo schermo.")
        try:
            from actions.screen_processor import find_text
            import pyautogui

            match = find_text(target)
            if match is None:
                self.speak(f"Non ho trovato {target} sullo schermo.")
                return False
            pyautogui.click(*match.center)
            pyautogui.write(str(text_to_type))
        except Exception as exc:
            self.speak(f"Interazione con {target} non disponibile: {exc}")
            return False
        self.speak("Fatto.")
        return True

    def start_hotkeys(
        self,
        read_combination: str = "ctrl+alt+r",
        status_combination: str = "ctrl+alt+s",
    ) -> None:
        """Install global shortcuts explicitly; requires the optional keyboard package."""
        if self._keyboard is not None:
            return
        import keyboard

        registered: list[str] = []
        try:
            keyboard.add_hotkey(read_combination, self.read_screen)
            registered.append(read_combination)
            keyboard.add_hotkey(
                status_combination,
                lambda: self.speak("JARVIS e attivo e in ascolto."),
            )
            registered.append(status_combination)
        except Exception:
            for combination in reversed(registered):
                keyboard.remove_hotkey(combination)
            raise
        self._keyboard = keyboard
        self._hotkeys = registered

    def stop_hotkeys(self) -> None:
        if self._keyboard is None:
            return
        keyboard = self._keyboard
        hotkeys, self._hotkeys = self._hotkeys, []
        self._keyboard = None
        errors: list[Exception] = []
        for combination in hotkeys:
            try:
                keyboard.remove_hotkey(combination)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError(
                f"Could not remove {len(errors)} accessibility hotkey(s)"
            ) from errors[0]
