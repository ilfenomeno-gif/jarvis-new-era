import re
from html.parser import HTMLParser
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures"


class BodyTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_body = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.in_body = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        if self.in_body:
            self.parts.append(data)


def _body_text(name: str) -> str:
    parser = BodyTextParser()
    parser.feed((FIXTURES / name).read_text(encoding="utf-8"))
    return " ".join(parser.parts)


def test_page_simple_has_link_button_and_visible_message_target():
    page = (FIXTURES / "page_simple.html").read_text(encoding="utf-8")

    assert "<title>Jarvis fixture semplice</title>" in page
    assert "Pagina semplice di test" in _body_text("page_simple.html")
    assert 'href="/page_simple_2.html"' in page
    assert "onclick=" in page
    assert "Pulsante premuto correttamente." in page


def test_snake_fixture_is_twenty_by_twenty_with_controls_and_restart():
    page = (FIXTURES / "snake.html").read_text(encoding="utf-8")

    assert 'width="400" height="400"' in page
    assert "const GRID_SIZE = 20;" in page
    for direction in ("ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft"):
        assert direction in page
    assert "Game over" in page
    assert ">Restart<" in page


def test_long_fixture_has_at_least_five_hundred_words():
    words = re.findall(r"\b[\w'-]+\b", _body_text("page_long.html"))

    assert len(words) >= 500


def test_empty_fixture_has_an_empty_body():
    assert _body_text("page_empty.html").strip() == ""
