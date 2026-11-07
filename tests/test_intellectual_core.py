from __future__ import annotations

import pytest

from core.critic_loop import CriticLoop
from core.intellectual_core import (
    Critique,
    Draft,
    IntellectualCore,
    ResearchResult,
    Source,
)
from core.memory_store import MemoryStore


def _source() -> Source:
    return Source(
        title="Official reference",
        url="https://example.org/reference",
        source_type="primary",
        reliability=0.9,
        evidence="The supplied official reference states the supported fact.",
        published_at="2025-01-02",
    )


def test_memory_is_persistent_and_scoped_between_store_instances(tmp_path):
    database = tmp_path / "jarvis.sqlite3"
    first = MemoryStore(database)
    first.remember("session", "active", {"step": 2})
    first.remember("project", "name", "Jarvis")
    first.remember("long_term", "format", ["concise", "cited"])

    restarted = MemoryStore(database)

    assert restarted.recall("session", "active") == {"step": 2}
    assert restarted.recall("project", "name") == "Jarvis"
    assert restarted.recall("long_term", "format") == ["concise", "cited"]
    assert restarted.recall("session", "name") is None


def test_memory_upsert_is_idempotent_for_identical_values(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    store.remember("project", "state", {"step": "draft"})
    before = store.recall("project", "state")
    store.remember("project", "state", {"step": "draft"})

    assert before == {"step": "draft"}
    assert store.recall("project", "state") == before


@pytest.mark.parametrize("scope", ["user", "", None])
def test_memory_rejects_unknown_scopes(tmp_path, scope):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    with pytest.raises(ValueError, match="scope"):
        store.remember(scope, "key", "value")


def test_memory_rejects_non_json_values_and_oversized_keys(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    with pytest.raises(ValueError, match="JSON serializable"):
        store.remember("session", "bad", object())
    with pytest.raises(ValueError, match="500 characters"):
        store.remember("session", "x" * 501, "value")


def test_checkpoint_snapshots_scoped_memory_and_resumes_after_restart(tmp_path):
    database = tmp_path / "memory.sqlite3"
    first = MemoryStore(database)
    first.remember("project", "cursor", {"step": "research"})

    checkpoint_id = first.checkpoint()
    assert first.checkpoint() == checkpoint_id

    restarted = MemoryStore(database)
    assert restarted.resume(checkpoint_id) == {
        "memory": [{"scope": "project", "key": "cursor", "value": {"step": "research"}}]
    }
    assert restarted.resume() == restarted.resume(checkpoint_id)


def test_explicit_checkpoint_is_idempotent_and_missing_resume_is_none(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    state = {"workflow": "w-1", "checkpoint": 3}

    checkpoint_id = store.checkpoint(state)

    assert store.checkpoint(state) == checkpoint_id
    assert store.resume(checkpoint_id) == state
    assert store.resume("missing") is None


def test_plan_is_persisted_and_idempotent(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    core = IntellectualCore(store)

    first = core.plan("Prepare a source-grounded report.")
    second = IntellectualCore(MemoryStore(store.path)).plan(
        "  Prepare   a source-grounded report.  "
    )

    assert first == second
    assert first.status == "planned"
    assert len(first.steps) >= 5
    assert store.resume() is not None


def test_research_without_provider_does_not_invent_sources(tmp_path):
    result = IntellectualCore(MemoryStore(tmp_path / "memory.sqlite3")).research(
        "A topic without configured search"
    )

    assert result.sources == ()
    assert "nessun provider" in result.summary
    assert result.limitations


def test_research_provider_sources_are_validated_cached_and_persisted(tmp_path):
    calls = []

    def provider(query):
        calls.append(query)
        return ResearchResult(query, (_source(),), "Provider-supplied evidence.")

    database = tmp_path / "memory.sqlite3"
    core = IntellectualCore(MemoryStore(database), research_provider=provider)

    first = core.research("A verifiable question")
    second = IntellectualCore(
        MemoryStore(database),
        research_provider=lambda _query: pytest.fail("cached result should be reused"),
    ).research("A verifiable question")

    assert first == second
    assert calls == ["A verifiable question"]
    assert second.sources[0].source_type == "primary"
    assert second.sources[0].reliability == 0.9


def test_research_provider_must_return_result_for_requested_query(tmp_path):
    core = IntellectualCore(
        MemoryStore(tmp_path / "memory.sqlite3"),
        research_provider=lambda _query: ResearchResult("different", (), "No sources."),
    )

    with pytest.raises(ValueError, match="different query"):
        core.research("requested")


@pytest.mark.parametrize(
    ("source_type", "reliability"),
    [("tertiary", 0.5), ("primary", -0.1), ("secondary", 1.1), ("primary", True)],
)
def test_source_rejects_invalid_kind_or_reliability(source_type, reliability):
    with pytest.raises(ValueError, match="source_type|reliability"):
        Source(
            title="Invalid",
            url="https://example.org/source",
            source_type=source_type,
            reliability=reliability,
            evidence="Evidence.",
        )


def test_write_produces_structured_artifact_with_dated_typed_citations(tmp_path):
    core = IntellectualCore(MemoryStore(tmp_path / "memory.sqlite3"))
    result = ResearchResult("topic", (_source(),), "One source.")
    draft = core.write(
        {
            "objective": "Explain a supported fact",
            "context": "User-provided context.",
            "research_result": result,
        }
    )
    rendered = draft.render()

    for section in (
        "# Obiettivo",
        "# Indice",
        "# Contenuto",
        "# Citazioni",
        "# Bibliografia",
        "# Limiti",
        "# Incertezze",
    ):
        assert section in rendered
    assert "2025-01-02" in rendered
    assert "primary" in rendered
    assert "https://example.org/reference" in rendered


def test_write_without_sources_declares_limit_and_uncertainty(tmp_path):
    draft = IntellectualCore(MemoryStore(tmp_path / "memory.sqlite3")).write(
        {"objective": "Prepare a careful draft"}
    )

    assert not draft.citations
    assert any("Nessuna fonte" in item for item in draft.limitations)
    assert any("richiedono verifica" in item for item in draft.uncertainties)
    assert "Nessuna fonte verificata disponibile." in draft.render()


def test_write_rejects_malformed_outline_and_limit_collections(tmp_path):
    core = IntellectualCore(MemoryStore(tmp_path / "memory.sqlite3"))

    with pytest.raises(TypeError, match="headings must be text"):
        core.write({"objective": "Objective", "outline": ["Valid", 42]})
    with pytest.raises(TypeError, match="must be a list of text"):
        core.write({"objective": "Objective", "limitations": "not a list"})


def test_critique_reports_missing_sources_and_scoring_metric(tmp_path):
    core = IntellectualCore(MemoryStore(tmp_path / "memory.sqlite3"))
    critique = core.critique(core.write("Draft without external evidence"))

    assert "Nessuna citazione verificabile." in critique.issues
    assert 0.0 <= critique.score <= 1.0
    assert critique.draft_version == 1


def test_revise_records_two_cycles_and_creates_v3(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    core = IntellectualCore(store)
    draft = core.write({"objective": "Prepare a cautious answer"})

    revised = core.revise(draft, core.critique(draft))
    events = store.list_events(f"{draft.id}:revision:")

    assert revised.version == 3
    assert [(item.from_version, item.to_version) for item in revised.revision_history] == [
        (1, 2),
        (2, 3),
    ]
    assert len(events) == 2
    assert "Verifica finale:" in revised.content
    assert "Ciclo 1" in revised.render()
    assert "Ciclo 2" in revised.render()


def test_revision_is_idempotent_and_resumes_from_saved_artifact(tmp_path):
    database = tmp_path / "memory.sqlite3"
    core = IntellectualCore(MemoryStore(database))
    draft = core.write({"objective": "Resume a saved revision"})
    final = core.revise(draft, core.critique(draft))

    restarted = IntellectualCore(MemoryStore(database))
    repeated = restarted.revise(draft, restarted.critique(draft))

    assert repeated == final
    assert repeated.version == 3
    assert len(restarted.store.list_events(f"{draft.id}:revision:")) == 2


def test_revision_resumes_from_persisted_intermediate_version(tmp_path):
    from dataclasses import replace

    from core.critic_loop import RevisionRecord
    from core.intellectual_core import _draft_payload

    store = MemoryStore(tmp_path / "memory.sqlite3")
    core = IntellectualCore(store)
    draft = core.write({"objective": "Resume after one revision"})
    first_critique = core.critique(draft)
    intermediate = replace(
        draft,
        version=2,
        content="Nota di revisione: i contenuti fattuali non supportati sono da verificare.\n\n"
        + draft.content,
        revision_history=(
            RevisionRecord(1, 1, {
                "draft_id": draft.id,
                "draft_version": 1,
                "issues": first_critique.issues,
                "suggestions": first_critique.suggestions,
                "score": first_critique.score,
            }, 2),
        ),
    )
    store.save_record("drafts", draft.id, _draft_payload(intermediate))

    resumed = core.revise(draft, first_critique)

    assert resumed.version == 3
    assert [record.cycle for record in resumed.revision_history] == [1, 2]
    assert len(store.list_events(f"{draft.id}:revision:")) == 1


def test_revise_rejects_critique_for_another_draft_or_version(tmp_path):
    core = IntellectualCore(MemoryStore(tmp_path / "memory.sqlite3"))
    draft = core.write("First draft")
    other = core.write("Other draft")
    stale = Critique(
        draft_id=other.id,
        draft_version=other.version,
        issues=(),
        suggestions=(),
        score=1.0,
    )

    with pytest.raises(ValueError, match="refer to"):
        core.revise(draft, stale)


def test_critic_loop_requires_one_version_increment_per_cycle():
    loop = CriticLoop[Draft, str](cycles=2)
    draft = Draft(
        id="d",
        objective="o",
        outline=("Heading",),
        content="Content",
        citations=(),
        bibliography=(),
        limitations=("Limits",),
        uncertainties=("Uncertainties",),
    )

    with pytest.raises(ValueError, match="advance"):
        loop.run(
            draft,
            "initial",
            critique_fn=lambda _draft: "next",
            revise_fn=lambda current, _critique, _cycle: current,
        )
