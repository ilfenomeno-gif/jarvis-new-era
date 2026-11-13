"""Provider-neutral ports required by the computer-use agent."""

from __future__ import annotations

from typing import Protocol


class ScreenElement(Protocol):
    @property
    def center(self) -> tuple[int, int]: ...


class ScreenVision(Protocol):
    def capture_screen(self) -> object: ...

    def find_element_on_screen(
        self,
        image: object,
        target_description: str,
    ) -> ScreenElement | None: ...


class DesktopInput(Protocol):
    def click(self, x: int, y: int) -> None: ...

    def type_text(self, text: str) -> None: ...


class WebSearch(Protocol):
    def search_web(self, query: str) -> str: ...
