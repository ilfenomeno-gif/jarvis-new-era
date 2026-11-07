"""Orchestration and private persistence for validated Fables world drafts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from core.fables_world import WorldModel
from core.internal_workflow import default_database_path

PlanAgent = Callable[[str], Any]
ResearchAgent = Callable[[str], Any]
CriticAgent = Callable[[WorldModel, int], Any]


class WorldDesignError(ValueError):
    """World design orchestration could not produce a valid saved draft."""


@dataclass(frozen=True)
class WorldDesignRecord:
    id: str
    world: WorldModel
    status: str
    plan: Any
    research: tuple[dict[str, Any], ...]
    critiques: tuple[Any, ...]
    created_at: str
    invoked_agents: tuple[str, ...]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _jsonable(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 500_000:
            raise WorldDesignError(f"{label} exceeds the 500 KB storage limit.")
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, WorldDesignError):
            raise
        raise WorldDesignError(f"{label} must be JSON serializable.") from exc


class WorldDesignerAgent:
    """Validate, optionally delegate, checkpoint, and resume complete world drafts."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        plan_agent: PlanAgent | None = None,
        research_agent: ResearchAgent | None = None,
        critic_agent: CriticAgent | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self.plan_agent = plan_agent
        self.research_agent = research_agent
        self.critic_agent = critic_agent
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
                CREATE TABLE IF NOT EXISTS fables_world_designs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    world_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def design(
        self,
        world: WorldModel,
        *,
        research_topics: Sequence[str] = (),
    ) -> WorldDesignRecord:
        if not isinstance(world, WorldModel):
            raise WorldDesignError("design requires a WorldModel.")
        world.validate(require_complete=True)
        if len(research_topics) > 20 or any(
            not isinstance(topic, str) or not topic.strip() for topic in research_topics
        ):
            raise WorldDesignError("Provide at most 20 non-empty research topics.")

        invoked: list[str] = []
        task = f"Design and validate the Fables world '{world.name}': {world.premise}"
        plan: Any = {
            "task": task,
            "categories": list(dict.fromkeys(element.category for element in world.elements)),
            "excluded": [item.category for item in world.exclusions],
            "stop_conditions": [
                "pause on invalid world data",
                "never create excluded categories",
                "never execute live actions from the design agent",
            ],
        }
        if self.plan_agent is not None:
            plan = _jsonable(self.plan_agent(task), "Supervisor plan")
            invoked.append("supervisor_agent")

        research: list[dict[str, Any]] = []
        if self.research_agent is not None:
            for topic in research_topics:
                result = _jsonable(self.research_agent(topic.strip()), "Research result")
                research.append({"topic": topic.strip(), "result": result})
            if research_topics:
                invoked.append("research_agent")

        critiques: list[Any] = []
        if self.critic_agent is not None:
            for cycle in (1, 2):
                critiques.append(
                    _jsonable(self.critic_agent(world, cycle), f"Critique cycle {cycle}")
                )
            invoked.append("critic_agent")

        state = {
            "plan": plan,
            "research": research,
            "critiques": critiques,
            "invoked_agents": invoked,
        }
        world_json = json.dumps(
            world.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        state_json = json.dumps(
            state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        fingerprint = hashlib.sha256(
            f"{world.fingerprint}\0{state_json}".encode("utf-8")
        ).hexdigest()
        record_id = f"world_{fingerprint[:24]}"
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO fables_world_designs (
                    id, fingerprint, world_json, state_json, status, checkpoint,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'planned', 'design-complete', ?, ?)
                """,
                (record_id, fingerprint, world_json, state_json, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM fables_world_designs WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            raise RuntimeError("SQLite did not return the saved world design.")
        return self._record(row)

    def resume(self, record_id: str) -> WorldDesignRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM fables_world_designs WHERE id = ?", (record_id,)
            ).fetchone()
        return self._record(row) if row else None

    def resume_latest(self) -> WorldDesignRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM fables_world_designs ORDER BY updated_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return self._record(row) if row else None

    @staticmethod
    def _record(row: sqlite3.Row) -> WorldDesignRecord:
        state = json.loads(row["state_json"])
        return WorldDesignRecord(
            id=row["id"],
            world=WorldModel.from_dict(json.loads(row["world_json"])),
            status=row["status"],
            plan=state["plan"],
            research=tuple(state["research"]),
            critiques=tuple(state["critiques"]),
            created_at=row["created_at"],
            invoked_agents=tuple(state["invoked_agents"]),
        )
