"""Conservative extraction of geographic and historical requests."""

from __future__ import annotations

import re

from core.intent_router import classify_geo_history_intent

_TRAILING_PUNCTUATION = re.compile(r"[\s?.!,;:]+$")
_TRAILING_YEAR_CONTEXT = re.compile(
    r"\s+(?:nel|nell['’]anno)\s+-?\d{3,4}\b.*$",
    re.IGNORECASE,
)
_LEADING_ARTICLES = re.compile(
    r"^(?:(?:il|lo|la|i|gli|le|un|uno|una)\s+|l['’]\s*)+",
    re.IGNORECASE,
)
_GEO_LOCATION = re.compile(
    r"(?:dov['’](?:e|è)|dove\s+(?:si\s+trova|si\s+trovano|sta|stanno)|"
    r"mappa|posizione|coordinate|localizza|geografia)\s+"
    r"(?:(?:di|del|della|dei|delle)\s+|dell['’]\s*|"
    r"(?:il|la|lo)\s+|l['’]\s*)?(?P<location>.+)$",
    re.IGNORECASE,
)
_HISTORY_LOCATION = re.compile(
    r"(?:battaglia|storia|assedio|rivoluzione|guerra|caduta|impero|"
    r"massacro|trattato|conquista)\s+"
    r"(?:(?:di|del|della|dei|delle)\s+|dell['’]\s*)(?P<location>.+)$",
    re.IGNORECASE,
)
_HISTORY_PERSON = re.compile(
    r"\bchi\s+era\s+(?P<location>.+)$",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)(-?\d{3,4})(?!\d)")
_NAMED_EPOCH = re.compile(
    r"\b(antichità|medioevo|rinascimento|età moderna|età contemporanea|"
    r"prima guerra mondiale|seconda guerra mondiale|guerra fredda)\b",
    re.IGNORECASE,
)
_HISTORICAL_THEME = re.compile(
    r"\b(battaglia|storia|assedio|rivoluzione|guerra|caduta|impero|"
    r"massacro|trattato|conquista|storico|storica)\b",
    re.IGNORECASE,
)


def _clean_location(value: str) -> str:
    value = _TRAILING_YEAR_CONTEXT.sub("", value)
    value = _TRAILING_PUNCTUATION.sub("", value).strip()
    value = _LEADING_ARTICLES.sub("", value).strip()
    return value[:120].strip()


def classify_and_route(query: str) -> dict:
    """Return a routing decision; uncertain or incomplete matches do not route."""
    if not isinstance(query, str) or not query.strip():
        return {
            "intent": "none",
            "location": "",
            "confidence": 0.0,
            "epoch": "",
            "theme": "",
        }

    query = query.strip()
    intent = classify_geo_history_intent(query)
    if intent == "none":
        return {
            "intent": "none",
            "location": "",
            "confidence": 0.0,
            "epoch": "",
            "theme": "",
        }

    location_match = (
        _HISTORY_LOCATION.search(query) or _HISTORY_PERSON.search(query)
        if intent == "history"
        else _GEO_LOCATION.search(query)
    )
    location = (
        _clean_location(location_match.group("location"))
        if location_match is not None
        else ""
    )
    if not location:
        return {
            "intent": "none",
            "location": "",
            "confidence": 0.25,
            "epoch": "",
            "theme": query[:200],
        }

    year_match = _YEAR.search(query)
    epoch_match = _NAMED_EPOCH.search(query)
    year = int(year_match.group(1)) if year_match else None
    if year is not None and year > 0 and re.search(
        r"\b(?:a\.?\s*C\.?|avanti\s+Cristo)", query, re.IGNORECASE
    ):
        year = -year
    epoch = (
        str(year)
        if year is not None
        else epoch_match.group(1) if epoch_match else ""
    )
    theme_match = _HISTORICAL_THEME.search(query)
    theme = query[:200] if intent == "history" or theme_match else ""
    return {
        "intent": intent,
        "location": location,
        "confidence": 0.92,
        "epoch": epoch,
        "theme": theme,
    }
