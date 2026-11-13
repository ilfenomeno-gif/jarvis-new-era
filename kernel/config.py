"""Validated, secret-free runtime configuration for the application kernel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

ProviderMode = Literal["gemini", "pipeline"]
_PROVIDER_MODES = frozenset({"gemini", "pipeline"})


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Non-secret settings needed to compose a Jarvis runtime."""

    provider_mode: ProviderMode = "gemini"
    assistant_name: str = "JARVIS"
    user_name: str = ""

    def __post_init__(self) -> None:
        if self.provider_mode not in _PROVIDER_MODES:
            raise ValueError(f"Unsupported provider mode: {self.provider_mode!r}.")
        if not isinstance(self.assistant_name, str) or not self.assistant_name.strip():
            raise ValueError("assistant_name must not be empty.")
        if not isinstance(self.user_name, str):
            raise TypeError("user_name must be a string.")
        object.__setattr__(self, "assistant_name", self.assistant_name.strip())
        object.__setattr__(self, "user_name", self.user_name.strip())

    @classmethod
    def from_legacy_mapping(cls, data: Mapping[str, object]) -> RuntimeConfig:
        """Read public settings from the existing config shape, ignoring secrets."""
        if not isinstance(data, Mapping):
            raise TypeError("Runtime configuration must be a mapping.")

        providers = data.get("providers", {})
        if not isinstance(providers, Mapping):
            raise TypeError("The providers configuration must be a mapping.")
        raw_mode = providers.get("mode", "gemini")
        if not isinstance(raw_mode, str):
            raise TypeError("The provider mode must be a string.")
        mode = raw_mode.strip().lower()
        if mode not in _PROVIDER_MODES:
            raise ValueError(f"Unsupported provider mode: {raw_mode!r}.")

        assistant_name = data.get("assistant_name", "JARVIS") or "JARVIS"
        user_name = data.get("user_name", "")
        if not isinstance(assistant_name, str):
            raise TypeError("assistant_name must be a string.")
        if not isinstance(user_name, str):
            raise TypeError("user_name must be a string.")

        return cls(
            provider_mode=mode,
            assistant_name=assistant_name,
            user_name=user_name,
        )
