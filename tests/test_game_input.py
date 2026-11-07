import pytest

from core.game_input import GameInput


@pytest.mark.parametrize(
    ("method", "expected_key"),
    [
        ("swipe_left", "left"),
        ("swipe_right", "right"),
        ("jump", "up"),
        ("roll", "down"),
    ],
)
def test_commands_dispatch_with_configured_human_delay(method, expected_key):
    events = []
    controller = GameInput(
        dispatcher=lambda key: events.append(("key", key)),
        min_delay=0.1,
        max_delay=0.4,
        sleeper=lambda delay: events.append(("sleep", delay)),
        random_delay=lambda low, high: (low + high) / 2,
    )

    getattr(controller, method)()

    assert events == [("sleep", 0.25), ("key", expected_key)]


def test_game_input_rejects_invalid_delays_and_random_source():
    with pytest.raises(ValueError, match="Delays"):
        GameInput(min_delay=0.5, max_delay=0.1)
    controller = GameInput(
        dispatcher=lambda _key: None,
        min_delay=0.1,
        max_delay=0.2,
        sleeper=lambda _delay: None,
        random_delay=lambda _low, _high: 0.3,
    )
    with pytest.raises(ValueError, match="outside"):
        controller.jump()
