"""Recognize explicit browser commands opened in the user's Chrome profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

_VIDEO_COMMAND = re.compile(
    r"^(?:per\s+favore\s+)?(?:metti|riproduci|avvia)\s+"
    r"(?:il\s+)?video\s+(?P<query>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_SEARCH_COMMAND = re.compile(
    r"^(?:per\s+favore\s+)?(?:cerca|ricerca)\s+(?P<query>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_SITE_COMMAND = re.compile(
    r"^(?:per\s+favore\s+)?(?:apri|vai\s+su)\s+"
    r"(?P<site>youtube(?:\.com)?|google(?:\.com)?|maps(?:\.google\.com)?)\s*[?.!]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BrowserCommand:
    action: str
    url: str
    query: str = ""


def classify_browser_command(text: str) -> BrowserCommand | None:
    """Return a fixed-site browser action only for clear, direct commands."""
    if not isinstance(text, str):
        return None
    command = text.strip()
    if not command:
        return None

    match = _VIDEO_COMMAND.fullmatch(command)
    if match:
        query = match.group("query").strip()[:300]
        if query:
            return BrowserCommand(
                "play_video",
                "https://www.youtube.com/results?search_query=" + quote_plus(query),
                query,
            )

    match = _SEARCH_COMMAND.fullmatch(command)
    if match:
        query = match.group("query").strip()[:500]
        if query:
            return BrowserCommand(
                "search",
                "https://www.google.com/search?q=" + quote_plus(query),
                query,
            )

    match = _SITE_COMMAND.fullmatch(command)
    if match:
        site = match.group("site").casefold()
        host = (
            "www.google.com/maps"
            if site.startswith("maps")
            else "www.youtube.com"
            if site.startswith("youtube")
            else "www.google.com"
        )
        return BrowserCommand("navigate", f"https://{host}")
    return None
