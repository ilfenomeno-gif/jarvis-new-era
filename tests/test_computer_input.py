import pytest

from core.computer_input import ComputerInput


def test_mouse_and_keyboard_actions_are_dispatched_after_random_delay():
    events = []
    controller = ComputerInput(
        dispatcher=lambda action, args: events.append(("dispatch", action, args)),
        sleeper=lambda delay: events.append(("sleep", delay)),
        random_delay=lambda low, high: (low + high) / 2,
    )

    controller.move_to(4, 9)
    controller.click(4, 9)
    controller.type_text("Jarvis")
    controller.press_key("Enter")

    assert [event[0] for event in events] == [
        "sleep", "dispatch", "sleep", "dispatch",
        "sleep", "dispatch", "sleep", "dispatch",
    ]
    assert all(0.1 <= event[1] <= 0.5 for event in events if event[0] == "sleep")
    assert events[1] == ("dispatch", "move_to", (4, 9))
    assert events[3] == ("dispatch", "click", (4, 9))
    assert events[5] == ("dispatch", "type_text", ("Jarvis", 0.04))
    assert events[7] == ("dispatch", "press_key", ("enter",))


def test_invalid_input_and_delays_are_rejected_without_dispatch():
    calls = []
    controller = ComputerInput(
        dispatcher=lambda *args: calls.append(args),
        sleeper=lambda _delay: None,
        random_delay=lambda _low, _high: 1.0,
    )
    with pytest.raises(ValueError, match="outside configured bounds"):
        controller.click(0, 0)
    with pytest.raises(ValueError, match="coordinates"):
        controller.move_to(-1, 0)
    with pytest.raises(ValueError, match="simple key"):
        controller.press_key("Enter; rm")
    assert calls == []
