from __future__ import annotations

import pytest

from agents.world_designer_agent import WorldDesignerAgent
from core.fables_world import (
    EXCLUDED_CATEGORIES,
    WORLD_CATEGORIES,
    WorldElement,
    WorldModel,
    WorldValidationError,
)


def _world() -> WorldModel:
    elements = tuple(
        WorldElement(
            id=f"entry-{category}",
            category=category,
            name=f"Entry {category}",
            card={"summary": f"Verified design notes for {category}."},
            consistency="Consistent with the stated world premise and internal rules.",
            links=(
                f"entry-{WORLD_CATEGORIES[(index + 1) % len(WORLD_CATEGORIES)]}",
            ),
        )
        for index, category in enumerate(WORLD_CATEGORIES)
    )
    return WorldModel(
        id="test-world",
        name="The Meridian",
        premise="A world whose settlements orbit a luminous inland sea.",
        elements=elements,
    )


def test_complete_world_has_every_required_design_category_and_element_cards():
    world = _world()

    world.validate()

    assert {element.category for element in world.elements} == set(WORLD_CATEGORIES)
    assert all(element.card and element.consistency for element in world.elements)
    assert all(element.links for element in world.elements)


def test_world_model_round_trips_and_fingerprint_is_stable():
    world = _world()

    restored = WorldModel.from_dict(world.to_dict())

    assert restored == world
    assert restored.fingerprint == world.fingerprint


def test_areas_poi_and_5e_defaults_are_excluded_with_reasons():
    world = _world()

    excluded = {item.category: item for item in world.exclusions}

    assert set(excluded) == set(EXCLUDED_CATEGORIES)
    assert all(item.state == "excluded" and item.reason for item in excluded.values())


def test_complete_world_rejects_missing_categories():
    world = _world()
    incomplete = WorldModel(
        id=world.id,
        name=world.name,
        premise=world.premise,
        elements=tuple(item for item in world.elements if item.category != "feats"),
        exclusions=world.exclusions,
    )

    with pytest.raises(WorldValidationError, match="feats"):
        incomplete.validate()


def test_world_rejects_missing_relationship_targets():
    elements = list(_world().elements)
    target = elements[0]
    elements[0] = WorldElement(
        id=target.id,
        category=target.category,
        name=target.name,
        card=target.card,
        consistency=target.consistency,
        links=("does-not-exist",),
    )
    world = WorldModel(
        id="test-world",
        name="The Meridian",
        premise="A world with interlinked records.",
        elements=tuple(elements),
    )

    with pytest.raises(WorldValidationError, match="missing elements"):
        world.validate()


def test_world_rejects_duplicate_ids_and_self_links():
    world = _world()
    first = world.elements[0]
    duplicate = WorldElement(
        id=first.id,
        category="geography",
        name="Duplicate",
        card={"summary": "Duplicate ID."},
        consistency="Not unique.",
    )
    duplicate_world = WorldModel(
        id="test-world",
        name="The Meridian",
        premise="Duplicate IDs are invalid.",
        elements=(*world.elements, duplicate),
    )
    with pytest.raises(WorldValidationError, match="unique"):
        duplicate_world.validate()

    self_link_world = WorldModel(
        id="test-world",
        name="The Meridian",
        premise="Self-links are invalid.",
        elements=(
            WorldElement(
                id="entry",
                category="cosmology",
                name="Origin",
                card={"summary": "A cosmological origin."},
                consistency="Consistent.",
                links=("entry",),
            ),
        ),
        exclusions=world.exclusions,
    )
    with pytest.raises(WorldValidationError, match="cannot link to itself"):
        self_link_world.validate(require_complete=False)


def test_world_designer_invokes_injected_agents_and_persists_checkpoint(tmp_path):
    calls = []

    def supervisor(task):
        calls.append(("supervisor", task))
        return {"plan_summary": "Review all linked categories."}

    def research(topic):
        calls.append(("research", topic))
        return {"sources": []}

    def critic(world, cycle):
        calls.append(("critic", cycle))
        return {"issues": []}

    database = tmp_path / "private.sqlite3"
    agent = WorldDesignerAgent(
        database,
        plan_agent=supervisor,
        research_agent=research,
        critic_agent=critic,
    )
    record = agent.design(_world(), research_topics=("map consistency",))
    resumed = WorldDesignerAgent(database).resume(record.id)

    assert record.status == "planned"
    assert record.invoked_agents == (
        "supervisor_agent",
        "research_agent",
        "critic_agent",
    )
    assert [entry[0] for entry in calls] == [
        "supervisor",
        "research",
        "critic",
        "critic",
    ]
    assert len(record.critiques) == 2
    assert resumed is not None and resumed.world == record.world
    assert resumed.research == record.research
    assert not list(tmp_path.rglob("*.txt"))


def test_world_designer_save_is_idempotent_and_invalid_world_never_saves(tmp_path):
    database = tmp_path / "private.sqlite3"
    agent = WorldDesignerAgent(database)

    first = agent.design(_world())
    second = agent.design(_world())
    with pytest.raises(WorldValidationError):
        agent.design(
            WorldModel(
                id="incomplete",
                name="Incomplete",
                premise="An incomplete design is rejected.",
                elements=(),
            )
        )

    assert first.id == second.id
    assert first.id == agent.resume(first.id).id
