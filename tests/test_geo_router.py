from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.geo_router import classify_and_route
from core.intent_router import classify_geo_history_intent


def test_geographic_query_extracts_place():
    decision = classify_and_route("Dov'è Roma?")

    assert decision["intent"] == "geo"
    assert decision["location"] == "Roma"
    assert decision["confidence"] >= 0.7


def test_geographic_query_strips_article_and_year_from_place():
    decision = classify_and_route("Dov'è l'Italia nel 1944?")

    assert decision["intent"] == "geo"
    assert decision["location"] == "Italia"
    assert decision["epoch"] == "1944"


def test_historical_query_extracts_event_location():
    decision = classify_and_route("La battaglia di Waterloo")

    assert decision["intent"] == "history"
    assert decision["location"] == "Waterloo"
    assert decision["confidence"] >= 0.7


def test_unrelated_query_does_not_route():
    decision = classify_and_route("Come stai?")

    assert decision["intent"] == "none"
    assert decision["location"] == ""
    assert classify_geo_history_intent("Come stai?") == "none"


def test_ambiguous_geographic_query_does_not_route():
    decision = classify_and_route("Dove?")

    assert decision["intent"] == "none"
    assert decision["confidence"] < 0.7
    assert decision["location"] == ""


def test_historical_query_extracts_explicit_year():
    decision = classify_and_route("La battaglia di Waterloo nel 1815")

    assert decision["location"] == "Waterloo"
    assert decision["epoch"] == "1815"
    assert decision["theme"]
