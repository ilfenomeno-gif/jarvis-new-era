"""Agent implementations with lazy compatibility exports for legacy callers."""

from importlib import import_module

_LEGACY_EXPORTS = {
    "supervisor_action": "supervisor_agent",
    "research_action": "research_agent",
    "coder_action": "coder_agent",
    "debugger_action": "debugger_agent",
}

__all__ = list(_LEGACY_EXPORTS)


def __getattr__(name: str):
    module_name = _LEGACY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value
