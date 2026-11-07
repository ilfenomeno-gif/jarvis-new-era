"""Persistent, provider-injected planning, research, drafting, and critique."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from core.critic_loop import CriticLoop, RevisionRecord
from core.memory_store import MemoryStore

SourceType = Literal["primary", "secondary"]
ResearchProvider = Callable[[str], "ResearchResult"]


def _normalized_text(value: Any, label: str, *, maximum: int = 20_000) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text.")
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError(f"{label} must contain 1 to {maximum} characters.")
    return value


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    source_type: SourceType
    reliability: float
    evidence: str
    published_at: str | None = None

    def __post_init__(self) -> None:
        _normalized_text(self.title, "Source title", maximum=500)
        parsed = urlparse(self.url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Source URL must be an absolute HTTP(S) URL.")
        if self.source_type not in {"primary", "secondary"}:
            raise ValueError("source_type must be primary or secondary.")
        if (
            isinstance(self.reliability, bool)
            or not isinstance(self.reliability, (int, float))
            or not 0 <= self.reliability <= 1
        ):
            raise ValueError("reliability must be a numeric estimate from 0 to 1.")
        _normalized_text(self.evidence, "Source evidence", maximum=20_000)
        if self.published_at:
            try:
                date.fromisoformat(self.published_at[:10])
            except ValueError as exc:
                raise ValueError("published_at must begin with an ISO date.") from exc


@dataclass(frozen=True)
class ResearchResult:
    query: str
    sources: tuple[Source, ...]
    summary: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _normalized_text(self.query, "Research query")
        _normalized_text(self.summary, "Research summary")
        if not isinstance(self.sources, tuple) or any(
            not isinstance(source, Source) for source in self.sources
        ):
            raise TypeError("ResearchResult.sources must be a tuple of Source instances.")
        if not isinstance(self.limitations, tuple):
            raise TypeError("ResearchResult.limitations must be a tuple of text.")
        for limitation in self.limitations:
            _normalized_text(limitation, "Research limitation", maximum=2000)


@dataclass(frozen=True)
class Plan:
    id: str
    task: str
    objective: str
    steps: tuple[str, ...]
    created_at: str
    status: str = "planned"


@dataclass(frozen=True)
class Citation:
    source_title: str
    url: str
    date: str
    date_basis: str
    source_type: SourceType
    reliability: float
    evidence: str


@dataclass(frozen=True)
class Critique:
    draft_id: str
    draft_version: int
    issues: tuple[str, ...]
    suggestions: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class Draft:
    id: str
    objective: str
    outline: tuple[str, ...]
    content: str
    citations: tuple[Citation, ...]
    bibliography: tuple[str, ...]
    limitations: tuple[str, ...]
    uncertainties: tuple[str, ...]
    version: int = 1
    revision_history: tuple[RevisionRecord, ...] = ()

    def render(self) -> str:
        lines = [
            "# Obiettivo",
            self.objective,
            "",
            "# Indice",
            *[f"{index}. {heading}" for index, heading in enumerate(self.outline, 1)],
            "",
            "# Contenuto",
            self.content,
            "",
            "# Citazioni",
        ]
        if self.citations:
            lines.extend(
                f"- [{citation.source_type}; {citation.date_basis}: {citation.date}] "
                f"{citation.source_title} — {citation.url} "
                f"(attendibilità stimata: {citation.reliability:.2f}). "
                f"Evidenza: {citation.evidence}"
                for citation in self.citations
            )
        else:
            lines.append("- Nessuna fonte verificata disponibile.")
        lines.extend(["", "# Bibliografia"])
        lines.extend(f"- {item}" for item in self.bibliography or ("Nessuna fonte verificata.",))
        lines.extend(["", "# Limiti"])
        lines.extend(f"- {item}" for item in self.limitations or ("Nessun limite registrato.",))
        lines.extend(["", "# Incertezze"])
        lines.extend(
            f"- {item}" for item in self.uncertainties or ("Nessuna incertezza registrata.",)
        )
        lines.extend(["", "# Revisioni"])
        if self.revision_history:
            for record in self.revision_history:
                critique = record.critique
                issues = (
                    critique.get("issues", ())
                    if isinstance(critique, Mapping)
                    else getattr(critique, "issues", ())
                )
                score = (
                    critique.get("score")
                    if isinstance(critique, Mapping)
                    else getattr(critique, "score", None)
                )
                summary = "; ".join(issues) if issues else "nessuna criticità registrata"
                metric = f", punteggio {score:.2f}" if isinstance(score, (int, float)) else ""
                lines.append(
                    f"- Ciclo {record.cycle}: v{record.from_version} → "
                    f"critica ({summary}{metric}) → v{record.to_version}"
                )
        else:
            lines.append("- Nessuna revisione ancora eseguita.")
        return "\n".join(lines)


class IntellectualCore:
    """Deterministic-by-default intellectual core with injectable research."""

    _DEFAULT_OUTLINE = (
        "Obiettivo e ambito",
        "Contesto e informazioni disponibili",
        "Analisi e proposta",
        "Verifiche, limiti e prossimi passi",
    )
    _PLAN_STEPS = (
        "Definire obiettivo e vincoli",
        "Raccogliere contesto e fonti verificabili",
        "Preparare bozza con citazioni e limiti",
        "Criticare la prima versione",
        "Revisionare e verificare la coerenza",
        "Completare una seconda revisione e salvare checkpoint",
    )

    def __init__(
        self,
        store: MemoryStore | None = None,
        *,
        research_provider: ResearchProvider | None = None,
    ):
        self.store = store or MemoryStore()
        self.research_provider = research_provider

    def plan(self, task: str) -> Plan:
        task = _normalized_text(task, "Task")
        plan_id = _stable_id("plan", " ".join(task.split()).casefold())
        existing = self.store.load_record("plans", plan_id)
        if existing:
            return _plan_from_payload(existing)
        plan = Plan(
            id=plan_id,
            task=task,
            objective=task,
            steps=self._PLAN_STEPS,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        payload = asdict(plan)
        self.store.save_record("plans", plan_id, payload)
        self.store.record_event(f"{plan_id}:created", "plan_created", payload)
        self.store.checkpoint({"kind": "plan", "plan_id": plan_id, "status": plan.status})
        return plan

    def research(self, query: str) -> ResearchResult:
        query = _normalized_text(query, "Research query")
        cache_key = _stable_id("research", " ".join(query.split()).casefold())
        cached = self.store.load_record("research", cache_key)
        if cached:
            result = _research_from_payload(cached)
        elif self.research_provider is None:
            result = ResearchResult(
                query=query,
                sources=(),
                summary="Ricerca non eseguita: nessun provider di ricerca configurato.",
                limitations=("Fonti esterne non consultate; non formulare fatti come verificati.",),
            )
        else:
            result = self.research_provider(query)
            if not isinstance(result, ResearchResult):
                raise TypeError("research_provider must return ResearchResult.")
            if result.query != query:
                raise ValueError("Research provider returned a result for a different query.")
            if any(not isinstance(source, Source) for source in result.sources):
                raise TypeError("ResearchResult.sources must contain Source instances.")
            if len(result.sources) > 100:
                raise ValueError("Research provider returned more than 100 sources.")
            self.store.save_record("research", cache_key, _research_payload(result))
        self.store.record_event(
            f"{cache_key}:result",
            "research_result",
            _research_payload(result),
        )
        return result

    def write(self, spec: str | Plan | Mapping[str, Any]) -> Draft:
        data = _draft_spec(spec)
        objective = _normalized_text(data.get("objective", ""), "Draft objective")
        context = str(data.get("context", "") or "").strip()
        supplied_content = str(data.get("content", "") or "").strip()
        research_result = data.get("research_result")
        query = data.get("research_query")
        if research_result is not None and not isinstance(research_result, ResearchResult):
            raise TypeError("research_result must be a ResearchResult.")
        if query:
            research_result = self.research(_normalized_text(query, "Research query"))
        if research_result and research_result.query.strip() == "":
            raise ValueError("ResearchResult query cannot be empty.")
        if research_result and any(not isinstance(source, Source) for source in research_result.sources):
            raise TypeError("ResearchResult.sources must contain Source instances.")

        outline_raw = data.get("outline") or self._DEFAULT_OUTLINE
        if not isinstance(outline_raw, (list, tuple)) or not outline_raw:
            raise ValueError("outline must be a non-empty list of headings.")
        if any(not isinstance(value, str) for value in outline_raw):
            raise TypeError("outline headings must be text.")
        outline = tuple(_normalized_text(value, "Outline heading", maximum=300) for value in outline_raw)
        if len(outline) > 50:
            raise ValueError("outline must contain at most 50 headings.")

        sources = research_result.sources if research_result else ()
        citations = tuple(_citation_for(source) for source in sources)
        content = supplied_content or (
            f"Obiettivo: {objective}\n\n"
            + (f"Contesto fornito:\n{context}\n\n" if context else "")
            + "Proposta: sviluppare questa sezione usando esclusivamente il contesto "
            "fornito e le evidenze citate. I dettagli non supportati restano da verificare."
        )
        limitations = _text_items(data.get("limitations") or (), "limitations")
        uncertainties = _text_items(data.get("uncertainties") or (), "uncertainties")
        if not sources:
            limitations.append("Nessuna fonte esterna verificata è stata fornita o consultata.")
            uncertainties.append("Le affermazioni fattuali richiedono verifica con fonti primarie.")
        if research_result:
            limitations.extend(research_result.limitations)
            if not research_result.sources:
                uncertainties.append("La ricerca non ha prodotto fonti citabili.")
        limitations = tuple(dict.fromkeys(_text_items(limitations, "limitations")))
        uncertainties = tuple(dict.fromkeys(_text_items(uncertainties, "uncertainties")))
        bibliography = tuple(
            f"{citation.source_title}. {citation.url}. "
            f"{citation.date_basis}: {citation.date}. Tipo: {citation.source_type}."
            for citation in citations
        )
        identity = {
            "objective": objective,
            "outline": outline,
            "content": content,
            "citations": [asdict(citation) for citation in citations],
            "limitations": limitations,
            "uncertainties": uncertainties,
        }
        draft_id = _stable_id("draft", identity)
        existing = self.store.load_record("drafts", draft_id)
        if existing:
            return _draft_from_payload(existing)

        draft = Draft(
            id=draft_id,
            objective=objective,
            outline=outline,
            content=content,
            citations=citations,
            bibliography=bibliography,
            limitations=limitations,
            uncertainties=uncertainties,
        )
        payload = _draft_payload(draft)
        self.store.save_record("drafts", draft_id, payload)
        self.store.record_event(f"{draft_id}:v1", "draft_created", payload)
        self.store.checkpoint({"kind": "draft", "draft_id": draft_id, "version": 1})
        return draft

    def critique(self, draft: Draft) -> Critique:
        if not isinstance(draft, Draft):
            raise TypeError("draft must be a Draft.")
        issues: list[str] = []
        suggestions: list[str] = []
        if not draft.objective.strip():
            issues.append("Obiettivo mancante.")
            suggestions.append("Definire l'obiettivo in modo esplicito.")
        if not draft.outline:
            issues.append("Indice mancante.")
            suggestions.append("Aggiungere un indice coerente con l'obiettivo.")
        if not draft.content.strip():
            issues.append("Contenuto mancante.")
            suggestions.append("Aggiungere contenuto basato su contesto e fonti verificabili.")
        if not draft.citations:
            issues.append("Nessuna citazione verificabile.")
            suggestions.append("Aggiungere fonti verificabili oppure esplicitare il limite.")
        if not draft.bibliography:
            issues.append("Bibliografia mancante.")
            suggestions.append("Generare bibliografia dalle fonti citate.")
        if not draft.limitations:
            issues.append("Limiti non dichiarati.")
            suggestions.append("Dichiarare i limiti delle informazioni disponibili.")
        if not draft.uncertainties:
            issues.append("Incertezze non dichiarate.")
            suggestions.append("Separare i fatti supportati dalle incertezze.")
        score = round(max(0.0, 1.0 - len(issues) / 7.0), 2)
        critique = Critique(
            draft_id=draft.id,
            draft_version=draft.version,
            issues=tuple(issues),
            suggestions=tuple(suggestions),
            score=score,
        )
        self.store.record_event(
            f"{draft.id}:critique:v{draft.version}",
            "draft_critique",
            asdict(critique),
        )
        return critique

    def revise(self, draft: Draft, critique: Critique) -> Draft:
        if not isinstance(draft, Draft) or not isinstance(critique, Critique):
            raise TypeError("revise requires Draft and Critique instances.")
        if critique.draft_id != draft.id or critique.draft_version != draft.version:
            raise ValueError("Critique must refer to the supplied draft version.")

        saved = self.store.load_record("drafts", draft.id)
        current = _draft_from_payload(saved) if saved else draft
        if current.version > draft.version:
            draft = current
        if len(draft.revision_history) >= 2:
            return draft
        active_critique = critique if critique.draft_version == draft.version else self.critique(draft)
        remaining = 2 - len(draft.revision_history)
        loop = CriticLoop[Draft, Critique](cycles=remaining)
        history = list(draft.revision_history)

        def revise_once(current_draft: Draft, current_critique: Critique, cycle: int) -> Draft:
            revised_content = current_draft.content
            revision_notes = [
                f"Revisione {cycle}: "
                + (
                    "nessuna fonte inventata; "
                    if not current_draft.citations
                    else "citazioni mantenute aderenti alle fonti; "
                )
                + "limiti e incertezze esplicitati."
            ]
            if cycle == 1 and not current_draft.content.startswith("Nota di revisione"):
                revised_content = (
                    "Nota di revisione: i contenuti fattuali non supportati sono da "
                    "verificare.\n\n" + revised_content
                )
            elif cycle >= 2 and "Verifica finale:" not in current_draft.content:
                revised_content += (
                    "\n\nVerifica finale: distinguere fatti citati, contesto fornito "
                    "e punti ancora incerti prima dell'uso."
                )
            revision = RevisionRecord(
                cycle=len(history) + 1,
                from_version=current_draft.version,
                critique=asdict(current_critique),
                to_version=current_draft.version + 1,
            )
            next_draft = replace(
                current_draft,
                content=revised_content,
                limitations=tuple(dict.fromkeys((*current_draft.limitations, *revision_notes))),
                version=current_draft.version + 1,
                revision_history=(*history, revision),
            )
            history.append(revision)
            payload = _draft_payload(next_draft)
            self.store.save_record("drafts", next_draft.id, payload)
            self.store.record_event(
                f"{next_draft.id}:revision:{revision.cycle}",
                "draft_revision",
                {
                    "from_version": revision.from_version,
                    "to_version": revision.to_version,
                    "critique": asdict(current_critique),
                },
            )
            self.store.checkpoint(
                {
                    "kind": "draft_revision",
                    "draft_id": next_draft.id,
                    "version": next_draft.version,
                    "completed_cycles": len(history),
                }
            )
            return next_draft

        final, _ = loop.run(
            draft,
            active_critique,
            critique_fn=self.critique,
            revise_fn=revise_once,
        )
        if len(final.revision_history) < 2:
            raise RuntimeError("Draft revision acceptance requires at least two recorded cycles.")
        return final


def _text_items(values: Any, label: str) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise TypeError(f"{label} must be a list of text.")
    result = []
    for value in values:
        result.append(_normalized_text(value, label, maximum=2000))
    return result


def _draft_spec(spec: str | Plan | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(spec, Plan):
        return {"objective": spec.objective, "context": spec.task}
    if isinstance(spec, str):
        return {"objective": spec}
    if isinstance(spec, Mapping):
        return dict(spec)
    raise TypeError("spec must be text, Plan, or a mapping.")


def _citation_for(source: Source) -> Citation:
    if source.published_at:
        citation_date, date_basis = source.published_at[:10], "pubblicazione"
    else:
        citation_date = datetime.now(UTC).date().isoformat()
        date_basis = "consultazione"
    return Citation(
        source_title=source.title,
        url=source.url,
        date=citation_date,
        date_basis=date_basis,
        source_type=source.source_type,
        reliability=float(source.reliability),
        evidence=source.evidence,
    )


def _research_payload(result: ResearchResult) -> dict[str, Any]:
    return {
        "query": result.query,
        "sources": [asdict(source) for source in result.sources],
        "summary": result.summary,
        "limitations": result.limitations,
    }


def _plan_from_payload(payload: Mapping[str, Any]) -> Plan:
    return Plan(
        id=payload["id"],
        task=payload["task"],
        objective=payload["objective"],
        steps=tuple(payload["steps"]),
        created_at=payload["created_at"],
        status=payload.get("status", "planned"),
    )


def _research_from_payload(payload: Mapping[str, Any]) -> ResearchResult:
    return ResearchResult(
        query=payload["query"],
        sources=tuple(Source(**source) for source in payload["sources"]),
        summary=payload["summary"],
        limitations=tuple(payload.get("limitations", ())),
    )


def _draft_payload(draft: Draft) -> dict[str, Any]:
    return asdict(draft)


def _draft_from_payload(payload: Mapping[str, Any]) -> Draft:
    history = []
    for record in payload.get("revision_history", ()):
        critique = record["critique"]
        if isinstance(critique, Mapping):
            critique = {
                "draft_id": critique["draft_id"],
                "draft_version": critique["draft_version"],
                "issues": tuple(critique.get("issues", ())),
                "suggestions": tuple(critique.get("suggestions", ())),
                "score": critique["score"],
            }
        history.append(
            RevisionRecord(
                cycle=record["cycle"],
                from_version=record["from_version"],
                critique=critique,
                to_version=record["to_version"],
            )
        )
    return Draft(
        id=payload["id"],
        objective=payload["objective"],
        outline=tuple(payload["outline"]),
        content=payload["content"],
        citations=tuple(Citation(**citation) for citation in payload["citations"]),
        bibliography=tuple(payload["bibliography"]),
        limitations=tuple(payload["limitations"]),
        uncertainties=tuple(payload["uncertainties"]),
        version=payload["version"],
        revision_history=tuple(history),
    )
