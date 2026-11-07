from __future__ import annotations

from typing import Any

from core.harness.capabilities import Capability, validate_capability

CONTRACT_VERSION = 1


def list_capabilities(registry: Any) -> dict[str, Any]:
    """Return a versioned, read-only snapshot of registry capabilities."""
    get_capability = getattr(registry, "get_capability", None)
    names = getattr(registry, "names", None)
    capability_error = getattr(registry, "capability_error", None)
    if not callable(get_capability) or not callable(names):
        raise TypeError("Capability registry must expose names() and get_capability(name).")

    capabilities = []
    for name in sorted(names()):
        error = capability_error(name) if callable(capability_error) else ""
        if error:
            raise ValueError(f"Capability {name!r} is invalid.")
        capability = get_capability(name)
        if capability is None:
            continue
        if (
            not isinstance(capability, Capability)
            or capability.name != name
            or not validate_capability(capability).valid
        ):
            raise ValueError(f"Capability {name!r} is invalid.")
        capabilities.append(capability.to_dict())
    return {"contractVersion": CONTRACT_VERSION, "capabilities": capabilities}
