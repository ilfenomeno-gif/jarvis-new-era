"""Evidence-based diagnosis for Fables requests accepted without a world transition."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from core.internal_workflow import default_database_path

RequestState = Literal["pending", "accepted", "error", "unknown"]
Cause = Literal[
    "selector_error",
    "permissions",
    "rate_limit",
    "invalid_world_state",
    "backend_ignored",
    "other",
    "not_determinable",
]


class InsufficientFablesEvidence(ValueError):
    """A diagnosis cannot be made from fewer than three concrete observations."""


@dataclass(frozen=True)
class FablesEvidence:
    before_url: str
    after_url: str
    request_state: RequestState
    expected_transition: bool = False
    expected_url: str = ""
    before_text_sha256: str = ""
    after_text_sha256: str = ""
    network_responses: tuple[dict[str, Any], ...] = ()
    dom_errors: tuple[str, ...] = ()
    console_errors: tuple[str, ...] = ()
    observed_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds")
    )

    def __post_init__(self) -> None:
        if self.request_state not in {"pending", "accepted", "error", "unknown"}:
            raise ValueError(f"Unsupported request state: {self.request_state}.")
        if not isinstance(self.expected_transition, bool):
            raise TypeError("expected_transition must be a boolean.")
        if not isinstance(self.network_responses, tuple) or any(
            not isinstance(item, dict) for item in self.network_responses
        ):
            raise TypeError("network_responses must be a tuple of objects.")
        if not isinstance(self.dom_errors, tuple) or any(
            not isinstance(item, str) for item in self.dom_errors
        ):
            raise TypeError("dom_errors must be a tuple of strings.")
        if not isinstance(self.console_errors, tuple) or any(
            not isinstance(item, str) for item in self.console_errors
        ):
            raise TypeError("console_errors must be a tuple of strings.")

    def concrete_items(self) -> tuple[str, ...]:
        values = [
            f"URL prima: {self.before_url}" if self.before_url else "",
            f"URL dopo: {self.after_url}" if self.after_url else "",
            f"Stato richiesta osservato: {self.request_state}",
            f"Timestamp UTC: {self.observed_at}",
            f"URL attesa: {self.expected_url}" if self.expected_url else "",
            f"Hash testo prima: {self.before_text_sha256}" if self.before_text_sha256 else "",
            f"Hash testo dopo: {self.after_text_sha256}" if self.after_text_sha256 else "",
        ]
        values.extend(
            "Risposta network: "
            + json.dumps(response, ensure_ascii=False, sort_keys=True)
            for response in self.network_responses
        )
        values.extend(f"Errore DOM: {item}" for item in self.dom_errors if item)
        values.extend(f"Errore console: {item}" for item in self.console_errors if item)
        return tuple(value for value in values if value)


@dataclass(frozen=True)
class FablesDiagnosis:
    id: str
    cause: Cause
    confidence: str
    summary: str
    evidence: tuple[str, ...]
    observed_at: str


_SELECTOR_ERROR = re.compile(
    r"selector|locator|element not found|could not find|selettore|elemento non trovato",
    re.IGNORECASE,
)
_PERMISSION_ERROR = re.compile(
    r"\b(?:401|403|unauthori[sz]ed|forbidden|permission|access denied|permesso negato)\b",
    re.IGNORECASE,
)
_RATE_LIMIT_ERROR = re.compile(
    r"\b(?:429|rate[\s_-]?limit|too many requests|retry-after)\b",
    re.IGNORECASE,
)
_INVALID_WORLD_ERROR = re.compile(
    r"\b(?:invalid world|world not found|invalid state|mondo non valido|"
    r"mondo inesistente|stato non valido)\b",
    re.IGNORECASE,
)


class FablesDiagnoser:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fables_diagnostics (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    cause TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def classify(evidence: FablesEvidence) -> tuple[Cause, str, str]:
        text = "\n".join(
            [
                *(str(item) for item in evidence.dom_errors),
                *(str(item) for item in evidence.console_errors),
                *(
                    json.dumps(item, ensure_ascii=False, sort_keys=True)
                    for item in evidence.network_responses
                ),
            ]
        )
        if _SELECTOR_ERROR.search(text):
            return "selector_error", "high", "Interazione UI o selettore non trovato."
        if _PERMISSION_ERROR.search(text):
            return "permissions", "high", "La risposta indica un problema di autorizzazione."
        if _RATE_LIMIT_ERROR.search(text):
            return "rate_limit", "high", "La risposta indica un limite di frequenza."
        if _INVALID_WORLD_ERROR.search(text):
            return "invalid_world_state", "high", "Il mondo o il suo stato non è valido."

        if (
            evidence.request_state == "accepted"
            and evidence.expected_transition
            and evidence.before_url
            and evidence.after_url
            and (
                (
                    evidence.expected_url
                    and urlparse(evidence.after_url).path
                    != urlparse(evidence.expected_url).path
                )
                or urlparse(evidence.before_url).path
                == urlparse(evidence.after_url).path
            )
        ):
            return (
                "backend_ignored",
                "medium",
                "La richiesta risulta accettata ma l'URL non mostra la transizione attesa.",
            )
        if evidence.request_state == "error" or evidence.dom_errors or evidence.console_errors:
            return "other", "low", "Sono presenti errori senza una causa specifica identificabile."
        return (
            "not_determinable",
            "low",
            "Le evidenze disponibili non consentono di attribuire una causa.",
        )

    def diagnose(self, evidence: FablesEvidence) -> FablesDiagnosis:
        if not isinstance(evidence, FablesEvidence):
            raise TypeError("diagnose requires FablesEvidence.")
        concrete = evidence.concrete_items()
        substantive = tuple(
            item for item in concrete if not item.startswith("Timestamp UTC: ")
        )
        if len(substantive) < 3:
            raise InsufficientFablesEvidence(
                "At least 3 concrete evidence items are required; "
                f"received {len(substantive)}."
            )
        cause, confidence, summary = self.classify(evidence)
        payload = asdict(evidence)
        serialized = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        record_id = f"fables_diagnosis_{fingerprint[:24]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO fables_diagnostics (
                    id, fingerprint, cause, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (record_id, fingerprint, cause, serialized, evidence.observed_at),
            )
            row = connection.execute(
                "SELECT id, cause, evidence_json, created_at FROM fables_diagnostics "
                "WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return the Fables diagnosis.")
        stored = json.loads(row["evidence_json"])
        stored_evidence = FablesEvidence(
            before_url=stored["before_url"],
            after_url=stored["after_url"],
            request_state=stored["request_state"],
            expected_transition=stored.get("expected_transition", False),
            expected_url=stored.get("expected_url", ""),
            before_text_sha256=stored.get("before_text_sha256", ""),
            after_text_sha256=stored.get("after_text_sha256", ""),
            network_responses=tuple(stored["network_responses"]),
            dom_errors=tuple(stored["dom_errors"]),
            console_errors=tuple(stored["console_errors"]),
            observed_at=stored["observed_at"],
        )
        return FablesDiagnosis(
            id=row["id"],
            cause=row["cause"],
            confidence=confidence,
            summary=summary,
            evidence=stored_evidence.concrete_items(),
            observed_at=row["created_at"],
        )
