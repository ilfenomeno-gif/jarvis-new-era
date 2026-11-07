from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.harness.capabilities import (
    Capability,
    ToolCapabilities,
    validate_arguments,
    validate_capability,
)

_RISK_ORDER = {"read": 0, "write": 1, "destructive": 2}


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    requires_confirm: bool
    reason: str
    risk_level: str


class ApprovalPolicy:
    def __init__(self, policy: dict[str, Any] | None = None) -> None:
        self.policy = (policy or {}).get("policy", policy or {})
        self.defaults = self.policy.get(
            "default",
            {"read": "auto", "write": "confirm", "destructive": "confirm_and_denylist"},
        )
        if not isinstance(self.defaults, dict):
            raise ValueError("Harness approval defaults must be a mapping.")

    def evaluate(
        self,
        tool_spec: dict[str, Any],
        args: dict[str, Any],
        session: Any,
        *,
        registry: Any = None,
    ) -> ApprovalDecision:
        del session
        if not isinstance(tool_spec, dict) or not isinstance(args, dict):
            raise TypeError("tool_spec and args must be dictionaries.")

        name = tool_spec.get("name")
        registry_capability = None
        registry_capability_error = ""
        if registry is not None:
            get_capability = getattr(registry, "get_capability", None)
            capability_error = getattr(registry, "capability_error", None)
            if callable(get_capability):
                registry_capability = get_capability(str(name))
            if callable(capability_error):
                registry_capability_error = capability_error(str(name))

        spec_capability = None
        try:
            if "capability" in tool_spec:
                declared_contract = tool_spec["capability"]
                if not isinstance(declared_contract, dict):
                    return _denied(
                        "Tool capability contract is invalid; approval fails closed."
                    )
                if (
                    "effects" not in declared_contract
                    or (
                        "risk_class" not in declared_contract
                        and "risk_class" not in tool_spec
                    )
                ):
                    return _denied(
                        "Tool capability contract must declare effects and risk_class."
                    )
                capability_tool = {**tool_spec, **declared_contract}
                capability_tool.pop("capability", None)
                spec_capability = Capability.from_tool_dict(capability_tool)
            elif "parameters_schema" in tool_spec and "effects" in tool_spec:
                spec_capability = Capability.from_tool_dict(tool_spec)
        except (TypeError, ValueError):
            return _denied("Tool capability contract is invalid; approval fails closed.")

        if registry_capability_error:
            return _denied("Registry capability contract is invalid; approval fails closed.")
        if registry_capability is not None and not validate_capability(registry_capability).valid:
            return _denied("Registry capability contract is invalid; approval fails closed.")
        if spec_capability is not None and not validate_capability(spec_capability).valid:
            return _denied("Tool capability contract is invalid; approval fails closed.")
        if registry_capability is not None and registry_capability.name != str(name):
            return _denied("Registry capability name does not match the requested tool.")
        if spec_capability is not None and spec_capability.name != str(name):
            return _denied("Tool capability name does not match the requested tool.")
        if (
            spec_capability is not None
            and registry_capability is not None
            and spec_capability != registry_capability
        ):
            return _denied("Tool capability declaration does not match the registry.")
        capability = spec_capability or registry_capability
        if capability is not None:
            validation = validate_arguments(capability, args)
            if not validation.valid:
                return _denied("Tool arguments do not satisfy the capability schema.")

        spec_capabilities = None
        spec_capabilities_invalid = False
        if "capabilities" in tool_spec:
            try:
                spec_capabilities = ToolCapabilities.from_value(tool_spec["capabilities"])
            except ValueError:
                spec_capabilities_invalid = True

        registry_capabilities = None
        registry_capabilities_declared = False
        registry_capabilities_error = ""
        if registry is not None:
            get_capabilities = getattr(registry, "capabilities", None)
            get_capabilities_error = getattr(registry, "capabilities_error", None)
            has_capabilities = getattr(registry, "capabilities_declared", None)
            if callable(has_capabilities):
                registry_capabilities_declared = has_capabilities(str(name))
            if callable(get_capabilities):
                registry_capabilities = get_capabilities(str(name))
            if callable(get_capabilities_error):
                registry_capabilities_error = get_capabilities_error(str(name))

        if spec_capabilities_invalid or registry_capabilities_error:
            return _denied("Tool capabilities are invalid; approval fails closed.")
        if (
            spec_capabilities is not None
            and registry_capabilities_declared
            and spec_capabilities != registry_capabilities
        ):
            return _denied("Tool capability declaration does not match the registry.")
        capabilities = spec_capabilities or registry_capabilities
        candidates = []
        if capability is not None:
            candidates.append(capability.risk_class)
        if capabilities is not None:
            candidates.append(capabilities.risk_level)
        if capability is None and capabilities is None:
            if registry_capabilities_declared:
                return _denied("Tool capabilities could not be validated.")
            if "risk_class" in tool_spec or "risk_level" in tool_spec:
                declared_risk = tool_spec.get("risk_class", tool_spec.get("risk_level"))
                candidates.append(_risk_or_destructive(declared_risk))
            if registry is not None:
                is_declared = getattr(registry, "risk_class_declared", None)
                get_risk = getattr(registry, "risk_class", None)
                if callable(is_declared) and is_declared(str(name)) and callable(get_risk):
                    registry_risk = get_risk(str(name))
                    candidates.append(_risk_or_destructive(registry_risk))
        risk = max(candidates, key=_RISK_ORDER.__getitem__) if candidates else "destructive"
        mode = self.defaults.get(risk, "confirm")
        serialized_args = repr(args)
        denylist = [
            *self.policy.get("denylist_patterns", []),
            *tool_spec.get("denylist_patterns", []),
        ]
        for pattern in denylist:
            try:
                matched = re.search(str(pattern), serialized_args, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid harness denylist pattern: {exc}") from exc
            if matched:
                return ApprovalDecision(
                    allowed=False,
                    requires_confirm=False,
                    reason="Arguments match the configured denylist.",
                    risk_level=risk,
                )
        if tool_spec.get("denylisted") is True or tool_spec.get("blocked") is True:
            return ApprovalDecision(
                allowed=False,
                requires_confirm=False,
                reason="Tool is explicitly denied by policy.",
                risk_level=risk,
            )
        sensitive_present = bool(
            (capabilities and any(argument in args for argument in capabilities.sensitive_arguments))
            or (
                capability
                and any(argument in args for argument in capability.sensitive_arguments)
            )
        )
        requires_confirm = capability.requires_confirmation if capability is not None else (
            sensitive_present or capabilities.requires_confirmation
            if capabilities is not None
            else not (risk == "read" and mode == "auto")
        )
        if capability is not None and capabilities is not None:
            requires_confirm = requires_confirm or capabilities.requires_confirmation
        requires_confirm = requires_confirm or sensitive_present
        return ApprovalDecision(
            allowed=True,
            requires_confirm=requires_confirm,
            reason="Explicit approval is required." if requires_confirm else "Allowed by policy.",
            risk_level=risk,
        )


def _risk_or_destructive(value: Any) -> str:
    return value if isinstance(value, str) and value in _RISK_ORDER else "destructive"


def _denied(reason: str) -> ApprovalDecision:
    return ApprovalDecision(False, False, reason, "destructive")
