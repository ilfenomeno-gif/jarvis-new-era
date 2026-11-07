"""Private, resumable workflow state for Jarvis."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_MAX_CYCLES = 24
MAX_CONFIGURED_CYCLES = 50
FABLES_WORLD_URL = "https://play.fables.gg/worlds/01a18d96-5091-7c68-9144-2039b73fe2d3"

FABLES_CHECKLIST = (
    {
        "key": "unique_modes",
        "title": "Profilo del mondo e valutazione delle altre modalità uniche",
        "enabled": True,
        "owner": "supervisor_agent",
    },
    {
        "key": "5e_defaults",
        "title": "D&D 5e defaults",
        "enabled": False,
        "owner": "supervisor_agent",
    },
    {"key": "races", "title": "Razze", "enabled": True, "owner": "research_agent"},
    {"key": "classes", "title": "Classi", "enabled": True, "owner": "research_agent"},
    {"key": "feats", "title": "Talenti (feats)", "enabled": True, "owner": "research_agent"},
    {"key": "monsters", "title": "Mostri", "enabled": True, "owner": "research_agent"},
    {"key": "items", "title": "Oggetti", "enabled": True, "owner": "research_agent"},
    {
        "key": "spells",
        "title": "Incantesimi",
        "enabled": True,
        "owner": "research_agent",
    },
    {
        "key": "characters",
        "title": "Personaggi",
        "enabled": True,
        "owner": "supervisor_agent",
    },
    {
        "key": "factions",
        "title": "Fazioni",
        "enabled": True,
        "owner": "supervisor_agent",
    },
    {
        "key": "areas",
        "title": "Aree",
        "enabled": False,
        "owner": "supervisor_agent",
    },
    {
        "key": "points_of_interest",
        "title": "Punti di interesse (POI)",
        "enabled": False,
        "owner": "supervisor_agent",
    },
)

_SIMULATION_PHASES = (
    ("request_received", "Ricezione richiesta Fables", "supervisor_agent"),
    ("request_accepted", "Accettazione richiesta (solo simulata)", "supervisor_agent"),
    ("world_transition", "Verifica transizione al mondo", "debugger_agent"),
    ("diagnosis", "Diagnosi del mancato avanzamento", "debugger_agent"),
)


def configured_max_cycles() -> int:
    raw = os.environ.get("JARVIS_WORKFLOW_MAX_CYCLES")
    if raw is None:
        return DEFAULT_MAX_CYCLES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("JARVIS_WORKFLOW_MAX_CYCLES must be an integer.") from exc
    if not 1 <= value <= MAX_CONFIGURED_CYCLES:
        raise ValueError(
            f"JARVIS_WORKFLOW_MAX_CYCLES must be between 1 and {MAX_CONFIGURED_CYCLES}."
        )
    return value


def default_database_path() -> Path:
    override = os.environ.get("JARVIS_WORKFLOW_DB")
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "Jarvis VII" / "state" / "workflows.sqlite3"
    return Path.home() / ".jarvis-vii" / "state" / "workflows.sqlite3"


def is_fables_request(text: str) -> bool:
    if not isinstance(text, str):
        return False
    mentions_fables = re.search(
        r"\bfables(?:\.gg)?\b|play\.fables\.gg",
        text,
        re.IGNORECASE,
    )
    asks_about_worlds = re.search(
        r"\b(?:mond[oi]|worlds?|campaign|richiest[ae]|request|invitation|"
        r"accett\w*|accept\w*)\b",
        text,
        re.IGNORECASE,
    )
    return bool(mentions_fables and asks_about_worlds)


def _validate_fables_url(value: str | None) -> str:
    url = (value or FABLES_WORLD_URL).strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not (
            parsed.hostname.casefold() == "fables.gg"
            or parsed.hostname.casefold().endswith(".fables.gg")
        )
    ):
        raise ValueError("Fables workflow URLs must use an https://*.fables.gg host.")
    return url


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class InternalWorkflowStore:
    """SQLite-backed workflow checkpoints kept outside Jarvis's visible workspace."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    world_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    simulated INTEGER NOT NULL,
                    max_cycles INTEGER NOT NULL,
                    cycles INTEGER NOT NULL DEFAULT 0,
                    checkpoint TEXT NOT NULL DEFAULT '',
                    stop_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_steps (
                    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                    step_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workflow_id, step_key),
                    UNIQUE (workflow_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                    event_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    evidence TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (workflow_id, event_key)
                );
                CREATE TABLE IF NOT EXISTS workflow_context (
                    workflow_id TEXT PRIMARY KEY REFERENCES workflows(id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def create_fables_plan(
        self,
        objective: str,
        world_url: str | None = None,
        *,
        simulated: bool = False,
        max_cycles: int | None = None,
    ) -> dict:
        objective = " ".join(str(objective or "").split())
        if not objective or len(objective) > 2000:
            raise ValueError("Fables objective must contain 1 to 2000 characters.")
        canonical_url = _validate_fables_url(world_url)
        cycle_limit = configured_max_cycles() if max_cycles is None else max_cycles
        if (
            isinstance(cycle_limit, bool)
            or not isinstance(cycle_limit, int)
            or not 1 <= cycle_limit <= MAX_CONFIGURED_CYCLES
        ):
            raise ValueError(f"max_cycles must be an integer from 1 to {MAX_CONFIGURED_CYCLES}.")

        stable_key = hashlib.sha256(
            f"fables\0{canonical_url}\0world-creation\0{int(simulated)}".encode()
        ).hexdigest()
        now = _utc_now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM workflows WHERE idempotency_key = ?",
                (stable_key,),
            ).fetchone()
            if existing is None:
                workflow_id = uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO workflows (
                        id, idempotency_key, kind, objective, world_url, status,
                        simulated, max_cycles, checkpoint, created_at, updated_at
                    ) VALUES (?, ?, 'fables', ?, ?, 'planned', ?, ?, 'plan-created', ?, ?)
                    """,
                    (
                        workflow_id,
                        stable_key,
                        objective,
                        canonical_url,
                        int(simulated),
                        cycle_limit,
                        now,
                        now,
                    ),
                )
                rows = [
                    (
                        workflow_id,
                        item["key"],
                        "category",
                        item["title"],
                        item["owner"],
                        int(item["enabled"]),
                        "planned" if item["enabled"] else "excluded",
                        index,
                        f"category:{item['key']}",
                        (
                            "Pianificata; nessun contenuto Fables creato."
                            if item["enabled"]
                            else (
                                "Operazione esclusa dal piano per vincolo esplicito; "
                                "stato live non verificato."
                            )
                        ),
                        now,
                    )
                    for index, item in enumerate(FABLES_CHECKLIST)
                ]
                rows.extend(
                    (
                        workflow_id,
                        key,
                        "simulation",
                        title,
                        owner,
                        1,
                        "pending",
                        len(FABLES_CHECKLIST) + index,
                        f"simulation:{key}",
                        "",
                        now,
                    )
                    for index, (key, title, owner) in enumerate(_SIMULATION_PHASES)
                )
                connection.executemany(
                    """
                    INSERT INTO workflow_steps (
                        workflow_id, step_key, kind, title, owner, enabled,
                        state, sequence, idempotency_key, evidence, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                connection.execute(
                    """
                    INSERT INTO workflow_context (workflow_id, payload_json)
                    VALUES (?, ?)
                    """,
                    (
                        workflow_id,
                        json.dumps(
                            {
                                "role": "Consulente neutrale, analitico e orientato a soluzioni pratiche.",
                                "task": objective,
                                "context": {
                                    "world_url": canonical_url,
                                    "execution": (
                                        "simulazione locale"
                                        if simulated
                                        else "pianificazione; nessuna azione live"
                                    ),
                                },
                                "output_format": [
                                    "riepilogo",
                                    "checklist con stati verificabili",
                                    "limiti e incertezze",
                                ],
                                "warnings": [
                                    "Non inferire il guasto tecnico senza prove live.",
                                    "Non attivare 5e Defaults, Aree o POI.",
                                    "Non dichiarare creati contenuti Fables durante una simulazione.",
                                ],
                                "agent_roles": {
                                    "coordinator": "supervisor_agent",
                                    "source_review": "research_agent",
                                    "transition_diagnosis": "debugger_agent",
                                    "ai_calls_in_fast_path": False,
                                },
                                "decisions": {
                                    "other_unique_modes": (
                                        "solo valutazione e piano; nessuna implementazione"
                                    ),
                                    "areas": "non creare; stato live non verificato",
                                    "points_of_interest": "non creare; stato live non verificato",
                                    "5e_defaults": "non attivare; stato live non verificato",
                                },
                                "reasoning_policy": (
                                    "Ragionamento interno strutturato; non esporre catene "
                                    "di pensiero dettagliate. Registrare solo decisioni, "
                                    "prove, limiti e checkpoint."
                                ),
                                "review": "Rivedere il piano su richiesta dell'utente o su nuove prove.",
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workflow_events (
                        workflow_id, event_key, event_type, cycle, evidence, created_at
                    ) VALUES (?, 'plan-created', 'checkpoint', 0, ?, ?)
                    """,
                    (
                        workflow_id,
                        "Workflow Fables pianificato; altre modalità uniche solo in valutazione; "
                        "attivazione 5e e creazione di Aree/POI escluse dal piano.",
                        now,
                    ),
                )
            else:
                workflow_id = str(existing["id"])
        return self.get(workflow_id)

    def get(self, workflow_id: str) -> dict:
        with self._connect() as connection:
            workflow = connection.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            if workflow is None:
                raise KeyError(f"Unknown workflow: {workflow_id}")
            steps = connection.execute(
                """
                SELECT step_key, kind, title, owner, enabled, state, sequence, evidence
                FROM workflow_steps WHERE workflow_id = ? ORDER BY sequence
                """,
                (workflow_id,),
            ).fetchall()
            events = connection.execute(
                """
                SELECT event_key, event_type, cycle, evidence, created_at
                FROM workflow_events WHERE workflow_id = ? ORDER BY id
                """,
                (workflow_id,),
            ).fetchall()
            context = connection.execute(
                "SELECT payload_json FROM workflow_context WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        result = dict(workflow)
        result["simulated"] = bool(result["simulated"])
        result["steps"] = [dict(step) | {"enabled": bool(step["enabled"])} for step in steps]
        result["categories"] = [step for step in result["steps"] if step["kind"] == "category"]
        result["simulation_steps"] = [
            step for step in result["steps"] if step["kind"] == "simulation"
        ]
        result["events"] = [dict(event) for event in events]
        result["plan"] = json.loads(context["payload_json"]) if context else {}
        return result

    def run_fables_simulation(self, workflow_id: str) -> dict:
        """Advance a deterministic dry-run; no browser, network, or agent API calls."""
        with self._connect() as connection:
            workflow = connection.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            if workflow is None:
                raise KeyError(f"Unknown workflow: {workflow_id}")
            if workflow["status"] == "blocked":
                return self.get(workflow_id)
            if workflow["status"] not in {"planned", "paused", "running"}:
                return self.get(workflow_id)
            if not workflow["simulated"]:
                raise ValueError("Simulation must be explicitly enabled for this workflow.")
            connection.execute(
                """
                UPDATE workflows SET status = 'running', stop_reason = '',
                    updated_at = ? WHERE id = ?
                """,
                (_utc_now(), workflow_id),
            )

        cycle_limit = int(workflow["max_cycles"])
        while True:
            current = self.get(workflow_id)
            pending = next(
                (step for step in current["simulation_steps"] if step["state"] == "pending"),
                None,
            )
            if pending is None:
                break
            if current["cycles"] >= cycle_limit:
                self._set_terminal(
                    workflow_id,
                    "paused",
                    "Limite configurato di cicli raggiunto.",
                )
                return self.get(workflow_id)
            self._advance_simulation_step(workflow_id, pending)

        current = self.get(workflow_id)
        unverified = any(step["state"] == "needs_review" for step in current["simulation_steps"])
        self._set_terminal(
            workflow_id,
            "blocked" if unverified else "completed",
            (
                "La richiesta risulta accettata, ma la transizione al mondo non è "
                "verificata; stop senza ripetere l'accettazione."
                if unverified
                else "Simulazione completata."
            ),
        )
        return self.get(workflow_id)

    def resume_fables_simulation(self, workflow_id: str) -> dict:
        workflow = self.get(workflow_id)
        if workflow["status"] not in {"paused", "running"}:
            raise ValueError("Only a paused or interrupted workflow can be resumed.")
        return self.run_fables_simulation(workflow_id)

    def _advance_simulation_step(self, workflow_id: str, step: dict) -> None:
        key = step["step_key"]
        if key == "request_received":
            state = "done"
            evidence = "Richiesta ricevuta nel caso simulato; nessun evento live letto."
        elif key == "request_accepted":
            state = "done"
            evidence = "Accettazione simulata; nessun click o invio a Fables."
        elif key == "world_transition":
            state = "needs_review"
            evidence = (
                "Scenario simulato: il provider segnala accettazione, ma non è "
                "disponibile una prova di navigazione o cambio di stato."
            )
        elif key == "diagnosis":
            state = "done"
            evidence = (
                "Punto di rottura individuato tra accettazione e transizione verificata. "
                "Causa tecnica radice non determinabile senza evidenza live."
            )
        else:
            raise ValueError(f"Unsupported Fables simulation step: {key}")

        now = _utc_now()
        event_key = f"simulation:{key}"
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state FROM workflow_steps
                WHERE workflow_id = ? AND step_key = ? AND kind = 'simulation'
                """,
                (workflow_id, key),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown simulation step: {key}")
            if row["state"] != "pending":
                return
            cycle = connection.execute(
                "SELECT cycles, max_cycles FROM workflows WHERE id = ?",
                (workflow_id,),
            ).fetchone()
            if cycle is None:
                raise KeyError(f"Unknown workflow: {workflow_id}")
            if cycle["cycles"] >= cycle["max_cycles"]:
                return
            next_cycle = int(cycle["cycles"]) + 1
            connection.execute(
                """
                UPDATE workflow_steps SET state = ?, evidence = ?, updated_at = ?
                WHERE workflow_id = ? AND step_key = ? AND state = 'pending'
                """,
                (state, evidence, now, workflow_id, key),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO workflow_events (
                    workflow_id, event_key, event_type, cycle, evidence, created_at
                ) VALUES (?, ?, 'simulation', ?, ?, ?)
                """,
                (workflow_id, event_key, next_cycle, evidence, now),
            )
            connection.execute(
                """
                UPDATE workflows SET cycles = ?, checkpoint = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_cycle, key, now, workflow_id),
            )

    def pause(self, workflow_id: str, reason: str) -> dict:
        reason = " ".join(str(reason or "").split())
        if not reason:
            raise ValueError("A pause reason is required.")
        now = _utc_now()
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE workflows SET status = 'paused', stop_reason = ?, updated_at = ?
                WHERE id = ? AND status IN ('planned', 'running', 'paused')
                """,
                (reason, now, workflow_id),
            ).rowcount
            if not updated:
                raise ValueError("Only a planned or active workflow can be paused.")
            connection.execute(
                """
                INSERT OR IGNORE INTO workflow_events (
                    workflow_id, event_key, event_type, cycle, evidence, created_at
                ) VALUES (?, ?, 'checkpoint', (SELECT cycles FROM workflows WHERE id = ?), ?, ?)
                """,
                (workflow_id, f"pause:{uuid.uuid4().hex}", workflow_id, reason, now),
            )
        return self.get(workflow_id)

    def record_live_observation(self, workflow_id: str, evidence: dict) -> dict:
        workflow = self.get(workflow_id)
        if workflow["simulated"]:
            raise ValueError("Live observations cannot be attached to a simulated workflow.")
        if workflow["status"] != "planned":
            raise ValueError("Live preflight requires a new planned workflow.")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("Live observation evidence must be a non-empty object.")

        payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if len(payload) > 12_000:
            raise ValueError("Live observation evidence exceeds the storage limit.")
        now = _utc_now()
        reason = "Preflight live in sola lettura; richiesta non verificata; nessuna azione."
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_events (
                    workflow_id, event_key, event_type, cycle, evidence, created_at
                ) VALUES (?, 'live-preflight', 'live_observation', 0, ?, ?)
                """,
                (workflow_id, payload, now),
            )
            connection.execute(
                """
                UPDATE workflows SET status = 'blocked', checkpoint = 'live-preflight',
                    stop_reason = ?, updated_at = ? WHERE id = ? AND status = 'planned'
                """,
                (reason, now, workflow_id),
            )
        return self.get(workflow_id)

    def _set_terminal(self, workflow_id: str, status: str, reason: str) -> None:
        if status not in {"completed", "blocked", "paused"}:
            raise ValueError(f"Unsupported workflow status: {status}")
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE workflows SET status = ?, stop_reason = ?, updated_at = ? WHERE id = ?",
                (status, reason, now, workflow_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO workflow_events (
                    workflow_id, event_key, event_type, cycle, evidence, created_at
                ) SELECT ?, ?, 'stop', cycles, ?, ? FROM workflows WHERE id = ?
                """,
                (workflow_id, f"stop:{status}", reason, now, workflow_id),
            )


def format_workflow_summary(workflow: dict) -> str:
    categories = workflow["categories"]
    blocked = [step["title"] for step in categories if not step["enabled"]]
    planned = [step["title"] for step in categories if step["enabled"]]
    phases = workflow["simulation_steps"]
    diagnosis = next(
        (step["evidence"] for step in phases if step["step_key"] == "diagnosis"),
        "",
    )
    lines = [
        f"Workflow Fables {workflow['status']} — {len(categories)} voci pianificate; "
        f"{workflow['cycles']}/{workflow['max_cycles']} cicli usati.",
        "Attivazione 5e e creazione di Aree/POI: escluse dal piano; "
        "nessuna modifica al mondo.",
        "Ruoli: supervisor_agent (coordinamento), research_agent (fonti), "
        "debugger_agent (diagnosi); nessuna API degli agenti è stata chiamata.",
    ]
    if workflow["status"] == "blocked":
        lines.append(f"Stop: {workflow['stop_reason']}")
    if diagnosis:
        lines.append(f"Diagnosi: {diagnosis}")
    if planned:
        lines.append(f"Pianificato: {', '.join(planned)}.")
    if blocked:
        lines.append(f"Escluso: {', '.join(blocked)}.")
    return "\n".join(lines)


def simulate_fables_workflow(
    path: str | Path | None = None,
    *,
    world_url: str = FABLES_WORLD_URL,
) -> dict:
    store = InternalWorkflowStore(path)
    plan = store.create_fables_plan(
        "Simulazione: ricevere e accettare una richiesta Fables, verificare la transizione.",
        world_url,
        simulated=True,
    )
    return store.run_fables_simulation(plan["id"])
