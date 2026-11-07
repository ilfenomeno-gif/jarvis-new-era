"""Explicitly confirmed Fables world submission through browser and desktop input."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from core.fables_diagnoser import (
    FablesDiagnosis,
    FablesDiagnoser,
    FablesEvidence,
    RequestState,
)
from core.fables_world import EXCLUDED_CATEGORIES, WorldElement, WorldModel
from core.internal_workflow import default_database_path

BrowserAction = Callable[[dict[str, Any]], Any]
InputAction = Callable[[dict[str, Any]], Any]


class LiveExecutionBlocked(RuntimeError):
    """Live execution was not explicitly authorized or lacks required setup."""


class LiveExecutionError(RuntimeError):
    """A guarded live action failed or could not be verified."""


def select_world_url(urls: list[str] | tuple[str, ...], fallback: str = "") -> str:
    """Prefer a Fables /worlds/ URL over a homepage, regardless of input order."""
    for candidate in urls:
        parsed = urlparse(candidate.strip())
        host = (parsed.hostname or "").casefold()
        if (
            parsed.scheme == "https"
            and (host == "fables.gg" or host.endswith(".fables.gg"))
            and re.search(r"/worlds(?:/|$)", parsed.path, re.IGNORECASE)
        ):
            return candidate.strip().rstrip(".,;!?)")
    if fallback:
        parsed = urlparse(fallback.strip())
        host = (parsed.hostname or "").casefold()
        if (
            parsed.scheme == "https"
            and (host == "fables.gg" or host.endswith(".fables.gg"))
            and re.search(r"/worlds(?:/|$)", parsed.path, re.IGNORECASE)
        ):
            return fallback.strip().rstrip(".,;!?)")
    raise ValueError("A valid https://*.fables.gg/worlds/ URL is required.")


@dataclass(frozen=True)
class FablesFormMapping:
    create_label: str
    name_label: str
    card_label: str
    submit_label: str

    def __post_init__(self) -> None:
        for field_name in ("create_label", "name_label", "card_label", "submit_label"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty UI label.")


@dataclass(frozen=True)
class ElementExecution:
    element_id: str
    category: str
    request_state: str
    diagnosis: FablesDiagnosis


@dataclass(frozen=True)
class LiveExecutionResult:
    workflow_id: str
    world_url: str
    state: str
    executions: tuple[ElementExecution, ...]
    excluded: tuple[str, ...]
    stop_reason: str = ""


@dataclass(frozen=True)
class RequestTransitionResult:
    request_id: str
    before_url: str
    after_url: str
    request_state: str
    diagnosis: FablesDiagnosis


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _result_ok(value: Any) -> bool:
    if not isinstance(value, str):
        return value is not None
    lowered = value.casefold()
    return not any(
        phrase in lowered
        for phrase in (
            "error:",
            "could not",
            "not found",
            "failed",
            "non trovato",
            "impossibile",
        )
    )


def _diagnostics(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


class FablesLiveExecutor:
    """Execute one mapped world draft with bounded, resumable, evidence-backed actions."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        diagnoser: FablesDiagnoser | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self.diagnoser = diagnoser or FablesDiagnoser(self.database_path)
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
                CREATE TABLE IF NOT EXISTS fables_live_actions (
                    workflow_id TEXT NOT NULL,
                    element_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    state TEXT NOT NULL,
                    element_hash TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workflow_id, element_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fables_live_requests (
                    request_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    request_page_url TEXT NOT NULL,
                    expected_world_url TEXT NOT NULL,
                    state TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    diagnosis_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(fables_live_actions)"
                ).fetchall()
            }
            if "element_hash" not in columns:
                connection.execute(
                    "ALTER TABLE fables_live_actions "
                    "ADD COLUMN element_hash TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _workflow_id(world: WorldModel, world_url: str) -> str:
        value = hashlib.sha256(
            f"{world.id}\0{world_url}".encode("utf-8")
        ).hexdigest()
        return f"fables_live_{value[:24]}"

    @staticmethod
    def _verify_authorization(
        world_url: str,
        *,
        live_flag: bool,
        confirm_live: bool,
        runtime_confirmation: str,
    ) -> None:
        if not live_flag:
            raise LiveExecutionBlocked(
                "Live execution requires --live-fables-workflow."
            )
        if not confirm_live:
            raise LiveExecutionBlocked("Live execution requires --confirm-live.")
        expected = f"AUTORIZZO ESECUZIONE FABLES {world_url}"
        if runtime_confirmation.strip() != expected:
            raise LiveExecutionBlocked(
                "Runtime confirmation does not match the requested Fables world."
            )

    def _prior_state(
        self, workflow_id: str, element_id: str
    ) -> tuple[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state, element_hash FROM fables_live_actions "
                "WHERE workflow_id = ? AND element_id = ?",
                (workflow_id, element_id),
            ).fetchone()
        return (str(row["state"]), str(row["element_hash"])) if row else None

    def _save_state(
        self,
        workflow_id: str,
        element: WorldElement,
        state: str,
        evidence: dict[str, Any],
    ) -> None:
        payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if len(payload.encode("utf-8")) > 100_000:
            raise LiveExecutionError("Per-element live evidence exceeds 100 KB.")
        element_json = json.dumps(
            asdict(element), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        element_hash = hashlib.sha256(element_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO fables_live_actions (
                    workflow_id, element_id, category, state, element_hash,
                    evidence_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, element_id) DO UPDATE SET
                    state = excluded.state,
                    element_hash = excluded.element_hash,
                    evidence_json = excluded.evidence_json,
                    updated_at = excluded.updated_at
                """,
                (
                    workflow_id,
                    element.id,
                    element.category,
                    state,
                    element_hash,
                    payload,
                    _utc_now(),
                ),
            )

    def diagnose_request_transition(
        self,
        request_page_url: str,
        expected_world_url: str,
        request_id: str,
        accept_label: str,
        *,
        live_flag: bool,
        confirm_live: bool,
        runtime_confirmation: str,
        browser_action: BrowserAction,
        input_action: InputAction,
    ) -> RequestTransitionResult:
        """Click one explicitly mapped request control and diagnose its transition."""
        expected_world_url = select_world_url((expected_world_url,))
        request_page = urlparse(request_page_url.strip())
        request_host = (request_page.hostname or "").casefold()
        if (
            request_page.scheme != "https"
            or not (
                request_host == "fables.gg"
                or request_host.endswith(".fables.gg")
            )
        ):
            raise LiveExecutionBlocked(
                "The request page must be an https://*.fables.gg URL."
            )
        request_id = request_id.strip()
        accept_label = accept_label.strip()
        if not request_id or len(request_id) > 200:
            raise LiveExecutionBlocked("A request ID of 1–200 characters is required.")
        if not accept_label or len(accept_label) > 300:
            raise LiveExecutionBlocked("A verified accept-button label is required.")
        expected_confirmation = (
            "AUTORIZZO DIAGNOSI RICHIESTA FABLES "
            f"{request_page_url.strip()} -> {expected_world_url} [{request_id}]"
        )
        if not live_flag:
            raise LiveExecutionBlocked("Live execution requires --live-fables-workflow.")
        if not confirm_live:
            raise LiveExecutionBlocked("Live execution requires --confirm-live.")
        if runtime_confirmation.strip() != expected_confirmation:
            raise LiveExecutionBlocked(
                "Runtime confirmation does not match the request and target world."
            )

        request_key = hashlib.sha256(
            f"{request_page_url.strip()}\0{expected_world_url}\0{request_id}".encode("utf-8")
        ).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT state FROM fables_live_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            if existing is not None:
                raise LiveExecutionBlocked(
                    f"Request {request_id} was already checkpointed as "
                    f"{existing['state']}; it will not be clicked again."
                )
            connection.execute(
                """
                INSERT INTO fables_live_requests (
                    request_key, request_id, request_page_url, expected_world_url,
                    state, evidence_json, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', '{}', ?)
                """,
                (
                    request_key,
                    request_id,
                    request_page_url.strip(),
                    expected_world_url,
                    _utc_now(),
                ),
            )

        before_url = ""
        try:
            if not _result_ok(browser_action({"action": "clear_diagnostics"})):
                raise LiveExecutionError("Could not clear previous browser diagnostics.")
            if not _result_ok(
                browser_action(
                    {"action": "go_to", "url": request_page_url.strip()}
                )
            ):
                raise LiveExecutionError("Could not open the Fables request page.")
            before_url = browser_action({"action": "get_url"})
            current_page = urlparse(before_url) if isinstance(before_url, str) else None
            current_host = (current_page.hostname or "").casefold() if current_page else ""
            if not current_page or current_host != request_host:
                raise LiveExecutionError(
                    f"Browser did not reach the confirmed request page: {before_url!r}"
                )
            if not _result_ok(browser_action({"action": "clear_diagnostics"})):
                raise LiveExecutionError("Could not isolate request diagnostics.")
            submit = input_action(
                {"action": "screen_click", "description": accept_label}
            )
            if not _result_ok(submit):
                raise LiveExecutionError(
                    f"Could not activate the mapped request control: {submit}"
                )
            if not _result_ok(browser_action({"action": "wait", "seconds": 2})):
                raise LiveExecutionError("Could not wait for the request transition.")
            after_url = browser_action({"action": "get_url"})
            page_text = browser_action({"action": "get_text"})
            diagnostics = _diagnostics(browser_action({"action": "get_diagnostics"}))
            network = self._network_responses(diagnostics)
            dom_errors = self._errors(diagnostics, "dom_errors")
            console_errors = self._errors(diagnostics, "console_errors")
            write_responses = tuple(
                response
                for response in network
                if str(response.get("method", "")).upper() in {"POST", "PUT", "PATCH"}
            )
            statuses = [
                response["status"]
                for response in write_responses
                if isinstance(response.get("status"), int)
                and not isinstance(response.get("status"), bool)
            ]
            if (
                any(status >= 400 for status in statuses)
                or any("failure" in response for response in write_responses)
                or dom_errors
            ):
                request_state: RequestState = "error"
            elif any(200 <= status < 300 for status in statuses):
                request_state = "accepted"
            else:
                request_state = "pending"
            evidence = FablesEvidence(
                before_url=before_url if isinstance(before_url, str) else "",
                after_url=after_url if isinstance(after_url, str) else "",
                request_state=request_state,
                expected_transition=True,
                expected_url=expected_world_url,
                before_text_sha256="",
                after_text_sha256=(
                    hashlib.sha256(page_text.encode("utf-8")).hexdigest()
                    if isinstance(page_text, str)
                    else ""
                ),
                network_responses=network,
                dom_errors=dom_errors,
                console_errors=console_errors,
            )
            diagnosis = self.diagnoser.diagnose(evidence)
            payload = json.dumps(asdict(evidence), ensure_ascii=False, sort_keys=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE fables_live_requests SET state = ?, evidence_json = ?,
                        diagnosis_id = ?, updated_at = ? WHERE request_key = ?
                    """,
                    (
                        request_state,
                        payload,
                        diagnosis.id,
                        _utc_now(),
                        request_key,
                    ),
                )
            return RequestTransitionResult(
                request_id=request_id,
                before_url=evidence.before_url,
                after_url=evidence.after_url,
                request_state=request_state,
                diagnosis=diagnosis,
            )
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE fables_live_requests SET state = 'error',
                        evidence_json = ?, updated_at = ? WHERE request_key = ?
                    """,
                    (
                        json.dumps(
                            {
                                "before_url": before_url,
                                "error": str(exc)[:2000],
                                "observed_at": _utc_now(),
                            },
                            ensure_ascii=False,
                        ),
                        _utc_now(),
                        request_key,
                    ),
                )
            if isinstance(exc, LiveExecutionError):
                raise
            raise LiveExecutionError(
                f"Fables request diagnosis stopped; inspect checkpoint {request_id}: {exc}"
            ) from exc

    @staticmethod
    def _network_responses(diagnostics: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        responses = diagnostics.get("network_responses", ())
        if not isinstance(responses, (list, tuple)):
            return ()
        return tuple(item for item in responses if isinstance(item, dict))[-50:]

    @staticmethod
    def _errors(diagnostics: dict[str, Any], key: str) -> tuple[str, ...]:
        values = diagnostics.get(key, ())
        if not isinstance(values, (list, tuple)):
            return ()
        return tuple(str(item)[:2000] for item in values if item)

    def execute(
        self,
        world: WorldModel,
        world_url: str,
        form_mappings: Mapping[str, FablesFormMapping],
        *,
        live_flag: bool,
        confirm_live: bool,
        runtime_confirmation: str,
        browser_action: BrowserAction,
        input_action: InputAction,
    ) -> LiveExecutionResult:
        if not isinstance(world, WorldModel):
            raise TypeError("execute requires a WorldModel.")
        world.validate(require_complete=True)
        world_url = select_world_url((world_url,))
        self._verify_authorization(
            world_url,
            live_flag=live_flag,
            confirm_live=confirm_live,
            runtime_confirmation=runtime_confirmation,
        )
        enabled_elements = tuple(
            element for element in world.elements if element.category not in EXCLUDED_CATEGORIES
        )
        required_mappings = {element.category for element in enabled_elements}
        missing_mappings = sorted(required_mappings - set(form_mappings))
        if missing_mappings:
            raise LiveExecutionBlocked(
                "No verified Fables UI mapping is configured for: "
                + ", ".join(missing_mappings)
                + ". No browser or input action was performed."
            )
        workflow_id = self._workflow_id(world, world_url)

        before_url = browser_action({"action": "get_url"})
        if not isinstance(before_url, str):
            raise LiveExecutionError("Browser get_url returned a non-text result.")
        if not _result_ok(browser_action({"action": "clear_diagnostics"})):
            raise LiveExecutionError("Could not clear previous browser diagnostics.")
        if not _result_ok(browser_action({"action": "go_to", "url": world_url})):
            raise LiveExecutionError("Could not navigate to the requested Fables world.")
        current_url = browser_action({"action": "get_url"})
        try:
            if not isinstance(current_url, str):
                raise ValueError
            select_world_url((current_url,))
        except ValueError as exc:
            raise LiveExecutionError(
                f"Navigation did not reach a Fables /worlds/ page: {current_url!r}"
            ) from exc

        executions: list[ElementExecution] = []
        excluded = tuple(
            f"{category}: {reason}" for category, reason in EXCLUDED_CATEGORIES.items()
        )
        for element in enabled_elements:
            prior = self._prior_state(workflow_id, element.id)
            if prior is not None:
                element_json = json.dumps(
                    asdict(element),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                current_hash = hashlib.sha256(element_json.encode("utf-8")).hexdigest()
                if prior[1] != current_hash:
                    return LiveExecutionResult(
                        workflow_id,
                        world_url,
                        "blocked",
                        tuple(executions),
                        excluded,
                        f"Element {element.id} changed after checkpoint; manual review required.",
                    )
                if prior[0] == "accepted":
                    continue
                return LiveExecutionResult(
                    workflow_id,
                    world_url,
                    "blocked",
                    tuple(executions),
                    excluded,
                    f"Element {element.id} is checkpointed as {prior[0]}; diagnose before retry.",
                )

            mapping = form_mappings[element.category]
            self._save_state(workflow_id, element, "pending", {"checkpoint": "before-submit"})
            if not _result_ok(browser_action({"action": "clear_diagnostics"})):
                raise LiveExecutionError("Could not isolate diagnostics for this element.")
            visible_before = browser_action({"action": "get_text"})
            if not isinstance(visible_before, str):
                raise LiveExecutionError(
                    f"Could not capture page text before submitting {element.id}."
                )
            create_result = browser_action(
                {"action": "smart_click", "description": mapping.create_label}
            )
            if not _result_ok(create_result):
                raise LiveExecutionError(
                    f"Could not open form for {element.category}: {create_result}"
                )
            card_payload = json.dumps(
                {
                    "id": element.id,
                    "category": element.category,
                    "card": element.card,
                    "consistency": element.consistency,
                    "links": list(element.links),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            name_result = browser_action(
                {
                    "action": "smart_type",
                    "description": mapping.name_label,
                    "text": element.name,
                }
            )
            card_result = browser_action(
                {
                    "action": "smart_type",
                    "description": mapping.card_label,
                    "text": card_payload,
                }
            )
            if not _result_ok(name_result) or not _result_ok(card_result):
                self._save_state(
                    workflow_id,
                    element,
                    "error",
                    {"name_result": str(name_result), "card_result": str(card_result)},
                )
                raise LiveExecutionError(
                    f"Could not fill the mapped {element.category} form."
                )

            submit_result = input_action(
                {"action": "screen_click", "description": mapping.submit_label}
            )
            if not _result_ok(submit_result):
                self._save_state(
                    workflow_id,
                    element,
                    "error",
                    {"submit_result": str(submit_result)},
                )
                raise LiveExecutionError(
                    f"Could not activate submit control for {element.id}: {submit_result}"
                )

            after_url = browser_action({"action": "get_url"})
            visible_text = browser_action({"action": "get_text"})
            diagnostics = _diagnostics(browser_action({"action": "get_diagnostics"}))
            network = self._network_responses(diagnostics)
            dom_errors = self._errors(diagnostics, "dom_errors")
            console_errors = self._errors(diagnostics, "console_errors")
            status_codes = [
                value
                for response in network
                if str(response.get("method", "")).upper() in {"POST", "PUT", "PATCH"}
                if isinstance((value := response.get("status")), int)
                and not isinstance(value, bool)
            ]
            write_request_failed = any(
                "failure" in response
                and str(response.get("method", "")).upper() in {"POST", "PUT", "PATCH"}
                for response in network
            )
            request_state: RequestState
            if (
                any(status >= 400 for status in status_codes)
                or write_request_failed
                or dom_errors
            ):
                request_state = "error"
            elif (
                any(200 <= status < 300 for status in status_codes)
                and isinstance(visible_text, str)
                and element.name.casefold() not in visible_before.casefold()
                and element.name.casefold() in visible_text.casefold()
            ):
                request_state = "accepted"
            else:
                request_state = "pending"
            evidence = FablesEvidence(
                before_url=before_url,
                after_url=after_url if isinstance(after_url, str) else "",
                request_state=request_state,
                before_text_sha256=hashlib.sha256(
                    visible_before.encode("utf-8")
                ).hexdigest(),
                after_text_sha256=hashlib.sha256(
                    visible_text.encode("utf-8")
                    if isinstance(visible_text, str)
                    else b""
                ).hexdigest(),
                network_responses=network,
                dom_errors=dom_errors,
                console_errors=console_errors,
            )
            diagnosis = self.diagnoser.diagnose(evidence)
            self._save_state(
                workflow_id,
                element,
                request_state,
                {
                    "evidence": asdict(evidence),
                    "diagnosis_id": diagnosis.id,
                    "submit_result": str(submit_result)[:2000],
                },
            )
            executions.append(
                ElementExecution(element.id, element.category, request_state, diagnosis)
            )
            if request_state != "accepted":
                return LiveExecutionResult(
                    workflow_id,
                    world_url,
                    "blocked",
                    tuple(executions),
                    excluded,
                    f"Stop on {element.id}: request state is {request_state}; inspect evidence.",
                )
            before_url = after_url if isinstance(after_url, str) else before_url

        return LiveExecutionResult(
            workflow_id,
            world_url,
            "completed",
            tuple(executions),
            excluded,
        )
