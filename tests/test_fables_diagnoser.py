from __future__ import annotations

import sqlite3

import pytest

from core.fables_diagnoser import (
    FablesDiagnoser,
    FablesEvidence,
    InsufficientFablesEvidence,
)


def _evidence(**overrides) -> FablesEvidence:
    values = {
        "before_url": "https://play.fables.gg/requests/123",
        "after_url": "https://play.fables.gg/worlds/abc",
        "request_state": "pending",
        "network_responses": ({"method": "POST", "status": 202, "url": "/api/request"},),
        "dom_errors": (),
        "console_errors": (),
        "observed_at": "2026-11-04T10:00:00+00:00",
    }
    values.update(overrides)
    return FablesEvidence(**values)


def test_diagnosis_contains_three_concrete_evidences_and_is_saved_privately(tmp_path):
    database = tmp_path / "jarvis.sqlite3"
    diagnoser = FablesDiagnoser(database)

    diagnosis = diagnoser.diagnose(_evidence())

    assert len(diagnosis.evidence) >= 3
    assert any("URL prima" in item for item in diagnosis.evidence)
    assert any("URL dopo" in item for item in diagnosis.evidence)
    assert any("Risposta network" in item for item in diagnosis.evidence)
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT cause, evidence_json FROM fables_diagnostics"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == diagnosis.cause
    assert not list(tmp_path.rglob("*.txt"))


def test_diagnosis_requires_at_least_three_evidence_items(tmp_path):
    evidence = FablesEvidence(
        before_url="",
        after_url="",
        request_state="unknown",
    )

    with pytest.raises(InsufficientFablesEvidence, match="received 1"):
        FablesDiagnoser(tmp_path / "state.sqlite3").diagnose(evidence)


@pytest.mark.parametrize(
    ("evidence", "expected_cause"),
    [
        (_evidence(dom_errors=("Element not found for selector #submit",)), "selector_error"),
        (
            _evidence(
                request_state="error",
                network_responses=({"status": 403, "url": "/api/request"},),
            ),
            "permissions",
        ),
        (
            _evidence(
                request_state="error",
                network_responses=({"status": 429, "url": "/api/request"},),
            ),
            "rate_limit",
        ),
        (
            _evidence(
                request_state="error",
                network_responses=(
                    {"status": 400, "message": "invalid world state"},
                ),
            ),
            "invalid_world_state",
        ),
        (
            _evidence(
                request_state="accepted",
                expected_transition=True,
                before_url="https://play.fables.gg/requests/123",
                after_url="https://play.fables.gg/requests/123",
            ),
            "backend_ignored",
        ),
        (_evidence(request_state="error", console_errors=("Uncaught TypeError",)), "other"),
        (_evidence(request_state="unknown", network_responses=()), "not_determinable"),
    ],
)
def test_classifies_known_failure_signatures(tmp_path, evidence, expected_cause):
    diagnosis = FablesDiagnoser(tmp_path / f"{expected_cause}.sqlite3").diagnose(evidence)

    assert diagnosis.cause == expected_cause
    assert diagnosis.summary


def test_same_evidence_is_idempotently_recorded(tmp_path):
    database = tmp_path / "state.sqlite3"
    diagnoser = FablesDiagnoser(database)
    evidence = _evidence()

    first = diagnoser.diagnose(evidence)
    second = diagnoser.diagnose(evidence)
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM fables_diagnostics").fetchone()[0]

    assert first.id == second.id
    assert count == 1

