import sys
from types import ModuleType, SimpleNamespace

import pytest

from core.accessibility import (
    ACCESSIBILITY_HOTKEYS_ENV,
    AccessibilityController,
    accessibility_hotkeys_enabled,
)


class SpeechRecorder:
    def __init__(self):
        self.messages = []

    def speak(self, text):
        self.messages.append(text)


class KeyboardRecorder(ModuleType):
    def __init__(self, fail_on=None):
        super().__init__("keyboard")
        self.callbacks = {}
        self.removed = []
        self.fail_on = fail_on

    def add_hotkey(self, combination, callback):
        if combination == self.fail_on:
            raise RuntimeError("hook registration failed")
        self.callbacks[combination] = callback

    def remove_hotkey(self, combination):
        self.removed.append(combination)
        self.callbacks.pop(combination, None)


@pytest.mark.parametrize("value", ["1", "true", " TRUE ", "yes", "On"])
def test_accessibility_hotkeys_require_explicit_truthy_opt_in(value):
    assert accessibility_hotkeys_enabled({ACCESSIBILITY_HOTKEYS_ENV: value})


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enabled"])
def test_accessibility_hotkeys_are_disabled_without_supported_opt_in(value):
    assert not accessibility_hotkeys_enabled({ACCESSIBILITY_HOTKEYS_ENV: value})


def test_accessibility_hotkeys_default_to_disabled(monkeypatch):
    monkeypatch.delenv(ACCESSIBILITY_HOTKEYS_ENV, raising=False)

    assert not accessibility_hotkeys_enabled()


def test_read_screen_speaks_ocr_text_and_returns_full_result():
    speech = SpeechRecorder()
    controller = AccessibilityController(speech=speech, ocr=lambda **kwargs: "Pagina leggibile")

    assert controller.read_screen() == "Pagina leggibile"
    assert speech.messages == ["Analisi dello schermo in corso.", "Pagina leggibile"]


def test_read_screen_limits_spoken_text_but_returns_full_ocr_result():
    speech = SpeechRecorder()
    text = "x" * 350
    controller = AccessibilityController(speech=speech, ocr=lambda **kwargs: text)

    assert controller.read_screen() == text
    assert speech.messages[1].startswith("x" * 300)
    assert "Testo abbreviato" in speech.messages[1]


def test_read_screen_reports_ocr_errors_and_empty_results():
    speech = SpeechRecorder()

    def unavailable_ocr(**kwargs):
        raise RuntimeError("Tesseract non disponibile")

    controller = AccessibilityController(speech=speech, ocr=unavailable_ocr)
    assert controller.read_screen() == ""
    assert "Tesseract non disponibile" in speech.messages[-1]

    controller = AccessibilityController(speech=speech, ocr=lambda **kwargs: "")
    assert controller.read_screen() == ""
    assert "Nessun testo rilevato" in speech.messages[-1]


def test_hotkeys_register_callbacks_and_stop_idempotently(monkeypatch):
    keyboard = KeyboardRecorder()
    monkeypatch.setitem(sys.modules, "keyboard", keyboard)
    speech = SpeechRecorder()
    controller = AccessibilityController(speech=speech, ocr=lambda **kwargs: "Test")

    controller.start_hotkeys()
    controller.start_hotkeys()

    assert set(keyboard.callbacks) == {"ctrl+alt+r", "ctrl+alt+s"}
    keyboard.callbacks["ctrl+alt+r"]()
    keyboard.callbacks["ctrl+alt+s"]()
    assert "Test" in speech.messages
    assert "JARVIS e attivo e in ascolto." in speech.messages

    controller.stop_hotkeys()
    controller.stop_hotkeys()
    assert keyboard.removed == ["ctrl+alt+r", "ctrl+alt+s"]
    assert keyboard.callbacks == {}


def test_hotkey_registration_failure_rolls_back_already_registered_hook(monkeypatch):
    keyboard = KeyboardRecorder(fail_on="ctrl+alt+s")
    monkeypatch.setitem(sys.modules, "keyboard", keyboard)
    controller = AccessibilityController()

    with pytest.raises(RuntimeError, match="hook registration failed"):
        controller.start_hotkeys()

    assert keyboard.removed == ["ctrl+alt+r"]
    assert keyboard.callbacks == {}


@pytest.mark.parametrize("match_found", [True, False])
def test_click_and_type_only_types_after_ocr_match(monkeypatch, match_found):
    match = SimpleNamespace(center=(120, 80)) if match_found else None
    processor = ModuleType("actions.screen_processor")
    processor.find_text = lambda target: match
    pyautogui = ModuleType("pyautogui")
    pyautogui.clicks = []
    pyautogui.typed = []
    pyautogui.click = lambda *coords: pyautogui.clicks.append(coords)
    pyautogui.write = lambda text: pyautogui.typed.append(text)
    monkeypatch.setitem(sys.modules, "actions.screen_processor", processor)
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    controller = AccessibilityController(speech=SpeechRecorder())

    assert controller.click_and_type("Invia", "messaggio") is match_found
    assert pyautogui.clicks == ([(120, 80)] if match_found else [])
    assert pyautogui.typed == (["messaggio"] if match_found else [])
