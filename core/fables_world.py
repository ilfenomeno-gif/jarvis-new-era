"""Validated structured data model for a complete Fables world draft."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


WORLD_CATEGORIES = (
    "cosmology",
    "geography",
    "history",
    "factions",
    "politics",
    "economy",
    "magic",
    "technology",
    "races",
    "classes",
    "npcs",
    "monsters",
    "items",
    "spells",
    "feats",
    "characters",
    "relationships",
    "conflicts",
    "narrative_hooks",
)

EXCLUDED_CATEGORIES = {
    "areas": "Escluse su richiesta: non creare Aree senza autorizzazione esplicita.",
    "points_of_interest": (
        "Esclusi su richiesta: non creare punti di interesse senza autorizzazione esplicita."
    ),
    "5e_defaults": (
        "Esclusi su richiesta: non attivare i defaults 5e senza autorizzazione esplicita."
    ),
}


class WorldValidationError(ValueError):
    """The world draft is incomplete, inconsistent, or unsafe to execute."""


def _text(value: object, label: str, *, maximum: int = 20_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise WorldValidationError(f"{label} must contain 1 to {maximum} characters.")
    return value.strip()


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value):
        raise WorldValidationError(
            "Element IDs must use lowercase letters, digits, hyphens, or underscores."
        )
    return value


@dataclass(frozen=True)
class WorldElement:
    id: str
    category: str
    name: str
    card: dict[str, Any]
    consistency: str
    links: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.id)
        if self.category not in WORLD_CATEGORIES:
            raise WorldValidationError(f"Unknown world category: {self.category}.")
        _text(self.name, "Element name", maximum=300)
        _text(self.consistency, "Element consistency notes")
        if not isinstance(self.card, dict) or not self.card:
            raise WorldValidationError("Each world element must contain a non-empty card.")
        if any(not isinstance(key, str) or not key.strip() for key in self.card):
            raise WorldValidationError("Card fields must have non-empty text names.")
        try:
            encoded = json.dumps(self.card, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise WorldValidationError("Element cards must be JSON serializable.") from exc
        if len(encoded.encode("utf-8")) > 100_000:
            raise WorldValidationError("An element card must not exceed 100 KB.")
        if not isinstance(self.links, tuple) or any(
            not isinstance(link, str) or not link for link in self.links
        ):
            raise WorldValidationError("Element links must be a tuple of element IDs.")
        if len(set(self.links)) != len(self.links):
            raise WorldValidationError("Element links cannot contain duplicates.")


@dataclass(frozen=True)
class WorldExclusion:
    category: str
    state: str
    reason: str

    def __post_init__(self) -> None:
        if self.category not in EXCLUDED_CATEGORIES:
            raise WorldValidationError(f"Unknown excluded category: {self.category}.")
        if self.state != "excluded":
            raise WorldValidationError(
                f"{self.category} must remain in the excluded state."
            )
        _text(self.reason, "Exclusion reason", maximum=2000)


@dataclass(frozen=True)
class WorldModel:
    id: str
    name: str
    premise: str
    elements: tuple[WorldElement, ...]
    exclusions: tuple[WorldExclusion, ...] = field(
        default_factory=lambda: tuple(
            WorldExclusion(category, "excluded", reason)
            for category, reason in EXCLUDED_CATEGORIES.items()
        )
    )
    version: int = 1

    def __post_init__(self) -> None:
        _identifier(self.id)
        _text(self.name, "World name", maximum=300)
        _text(self.premise, "World premise")
        if self.version < 1:
            raise WorldValidationError("World version must be positive.")
        if not isinstance(self.elements, tuple) or any(
            not isinstance(element, WorldElement) for element in self.elements
        ):
            raise WorldValidationError("World elements must be a tuple of WorldElement.")
        if not isinstance(self.exclusions, tuple) or any(
            not isinstance(item, WorldExclusion) for item in self.exclusions
        ):
            raise WorldValidationError("World exclusions must be a tuple of WorldExclusion.")
        excluded = [item.category for item in self.exclusions]
        if len(set(excluded)) != len(excluded):
            raise WorldValidationError("Excluded categories cannot be duplicated.")
        if set(excluded) != set(EXCLUDED_CATEGORIES):
            raise WorldValidationError(
                "A world must explicitly exclude Aree, POI, and 5e Defaults."
            )

    def validate(self, *, require_complete: bool = True) -> None:
        if not self.elements:
            raise WorldValidationError("A world must contain at least one element.")
        ids = [element.id for element in self.elements]
        if len(set(ids)) != len(ids):
            raise WorldValidationError("World element IDs must be unique.")
        known_ids = set(ids)
        categories = {element.category for element in self.elements}
        if require_complete:
            missing = sorted(set(WORLD_CATEGORIES) - categories)
            if missing:
                raise WorldValidationError(
                    f"World is incomplete; missing categories: {', '.join(missing)}."
                )
        for element in self.elements:
            if not element.links:
                raise WorldValidationError(
                    f"{element.id} must link to at least one related world element."
                )
            missing_links = sorted(set(element.links) - known_ids)
            if missing_links:
                raise WorldValidationError(
                    f"{element.id} links to missing elements: {', '.join(missing_links)}."
                )
            if element.id in element.links:
                raise WorldValidationError(f"{element.id} cannot link to itself.")
            if not any(value.strip() for value in element.card.values() if isinstance(value, str)):
                raise WorldValidationError(
                    f"{element.id} must include at least one substantive text field."
                )

    def to_dict(self) -> dict[str, Any]:
        self.validate(require_complete=False)
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorldModel:
        try:
            elements = tuple(
                WorldElement(
                    id=item["id"],
                    category=item["category"],
                    name=item["name"],
                    card=item["card"],
                    consistency=item["consistency"],
                    links=tuple(item.get("links", ())),
                )
                for item in payload["elements"]
            )
            exclusions = tuple(
                WorldExclusion(
                    category=item["category"],
                    state=item["state"],
                    reason=item["reason"],
                )
                for item in payload.get("exclusions", [])
            )
            return cls(
                id=payload["id"],
                name=payload["name"],
                premise=payload["premise"],
                elements=elements,
                exclusions=exclusions,
                version=payload.get("version", 1),
            )
        except (KeyError, TypeError) as exc:
            raise WorldValidationError(f"Invalid world model shape: {exc}") from exc

    @property
    def fingerprint(self) -> str:
        serialized = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
