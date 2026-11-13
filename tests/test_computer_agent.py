import pytest

from agents.computer_agent import ComputerAgent
from core.browser_automation import BrowserAutomation, MockBrowser
from core.computer_input import ComputerInput
from core.computer_vision import ComputerVision


def test_agent_uses_mock_browser_for_web_search():
    mock_browser = MockBrowser()
    agent = ComputerAgent(
        vision=ComputerVision(),
        computer_input=ComputerInput(),
        browser=BrowserAutomation(mock_browser),
    )

    result = agent.execute_task("Cerca 'Jarvis' su Google")

    assert result.success
    assert result.mode == "web"
    assert mock_browser.navigations == ["https://www.google.com/"]
    assert mock_browser.actions[0] == ("type_text", "textarea[name='q']", "Jarvis")
    assert "official API" in result.summary


def test_agent_uses_vision_and_mock_input_for_local_task():
    image = object()
    ocr = {
        "text": ["Save"],
        "left": [10],
        "top": [20],
        "width": [40],
        "height": [10],
        "conf": ["95"],
    }
    vision = ComputerVision(
        capture_provider=lambda: image,
        ocr_provider=lambda frame: ocr if frame is image else {},
    )
    actions = []
    computer_input = ComputerInput(
        dispatcher=lambda action, args: actions.append((action, args)),
        sleeper=lambda _delay: None,
        random_delay=lambda low, _high: low,
    )

    result = ComputerAgent(
        vision=vision,
        computer_input=computer_input,
        browser=BrowserAutomation(MockBrowser()),
    ).execute_task("local: type Save = Draft")

    assert result.success
    assert result.mode == "local"
    assert actions == [
        ("click", (30, 25)),
        ("type_text", ("Draft", 0.04)),
    ]


def test_agent_does_not_send_input_when_local_target_is_missing():
    calls = []
    vision = ComputerVision(
        capture_provider=lambda: object(),
        ocr_provider=lambda _: {
            "text": [], "left": [], "top": [], "width": [], "height": [], "conf": []
        },
    )
    computer_input = ComputerInput(
        dispatcher=lambda *args: calls.append(args),
        sleeper=lambda _delay: None,
        random_delay=lambda low, _high: low,
    )
    agent = ComputerAgent(
        vision=vision,
        computer_input=computer_input,
        browser=BrowserAutomation(MockBrowser()),
    )

    with pytest.raises(LookupError, match="no input was sent"):
        agent.execute_task("local: click Save")
    assert calls == []
