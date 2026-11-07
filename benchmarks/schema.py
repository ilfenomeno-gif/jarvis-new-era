"""Shared version contract for benchmark report readers and tests."""
from __future__ import annotations

CURRENT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({CURRENT_SCHEMA_VERSION})


def require_supported_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid benchmark schema version: {value!r}")
    if value not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(map(str, sorted(SUPPORTED_SCHEMA_VERSIONS)))
        raise ValueError(
            f"Unsupported benchmark schema version {value}; supported versions: {supported}."
        )
    return value
