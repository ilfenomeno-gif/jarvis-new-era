from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Literal

_LEGACY_EFFECT_RISK = {"read": 0, "write": 1, "destructive": 2}
_RISK_ORDER = {"read": 0, "write": 1, "destructive": 2}
_EFFECTS = {
    "approval",
    "delete",
    "desktop",
    "filesystem",
    "network",
    "read",
    "subprocess",
    "write",
}
_JSON_TYPES = {
    "ARRAY": "array",
    "BOOLEAN": "boolean",
    "INTEGER": "integer",
    "NULL": "null",
    "NUMBER": "number",
    "OBJECT": "object",
    "STRING": "string",
}
RiskClass = Literal["read", "write", "destructive"]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.valid


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    version: str
    parameters_schema: dict[str, Any]
    effects: list[str]
    risk_class: RiskClass
    requires_confirmation: bool
    scope: str
    rate_limit: str | None = None
    deprecated: bool = False
    sensitive_arguments: list[str] = field(default_factory=list)

    @classmethod
    def from_tool_dict(cls, tool_dict: dict[str, Any]) -> Capability:
        if not isinstance(tool_dict, dict):
            raise ValueError("Tool declaration must be a mapping.")
        name = tool_dict.get("name")
        description = tool_dict.get("description", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Capability name must be non-empty text.")
        if not isinstance(description, str):
            raise ValueError("Capability description must be text.")

        nested = tool_dict.get("capabilities")
        nested = nested if isinstance(nested, dict) else {}
        contract = tool_dict.get("capability")
        if "capability" in tool_dict and not isinstance(contract, dict):
            raise ValueError("Capability contract must be a mapping.")
        contract = contract if isinstance(contract, dict) else {}
        if contract and (
            "effects" not in contract
            or (
                "risk_class" not in contract
                and "risk_class" not in tool_dict
            )
        ):
            raise ValueError("Capability contract must declare effects and risk_class.")
        metadata = {**nested, **contract}
        schema = tool_dict.get(
            "parameters_schema",
            metadata.get("parameters_schema", tool_dict.get("parameters", {})),
        )
        if not isinstance(schema, dict):
            raise ValueError("Capability parameters_schema must be a mapping.")
        schema = _normalize_schema(schema)
        schema_errors = _schema_definition_errors(schema)
        if schema_errors:
            raise ValueError("Invalid capability parameters_schema: " + "; ".join(schema_errors))

        raw_effects = tool_dict.get("effects", metadata.get("effects"))
        legacy_effects = (
            nested.get("effects")
            if nested and set(nested).issubset(
                {"effects", "sensitive_arguments", "requires_confirmation"}
            )
            else None
        )
        if legacy_effects is not None or raw_effects is None:
            effects = _infer_effects(name, description, tool_dict.get("risk_class"))
        else:
            if (
                not isinstance(raw_effects, (list, tuple))
                or not raw_effects
                or any(not isinstance(effect, str) or effect not in _EFFECTS for effect in raw_effects)
                or len(set(raw_effects)) != len(raw_effects)
            ):
                raise ValueError("Capability effects must be a non-empty list of known effects.")
            effects = list(raw_effects)

        risk = tool_dict.get("risk_class", metadata.get("risk_class"))
        if risk is None and legacy_effects is not None:
            legacy_risks = legacy_effects
            if (
                isinstance(legacy_risks, (list, tuple))
                and legacy_risks
                and all(item in _LEGACY_EFFECT_RISK for item in legacy_risks)
            ):
                risk = max(legacy_risks, key=_LEGACY_EFFECT_RISK.__getitem__)
        if risk is None:
            risk = _risk_from_effects(effects)
        if not isinstance(risk, str) or risk not in _RISK_ORDER:
            raise ValueError("Capability risk_class must be read, write, or destructive.")

        sensitive = metadata.get(
            "sensitive_arguments",
            tool_dict.get("sensitive_arguments", []),
        )
        if (
            not isinstance(sensitive, (list, tuple))
            or any(not isinstance(item, str) or not item for item in sensitive)
            or len(set(sensitive)) != len(sensitive)
        ):
            raise ValueError("Capability sensitive_arguments must be unique non-empty strings.")
        requires_confirmation = metadata.get(
            "requires_confirmation",
            tool_dict.get("requires_confirmation", risk != "read"),
        )
        if not isinstance(requires_confirmation, bool):
            raise ValueError("Capability requires_confirmation must be a boolean.")
        if risk == "destructive" and not requires_confirmation:
            raise ValueError("Destructive capabilities require confirmation.")

        scope = metadata.get("scope", tool_dict.get("scope"))
        if scope is None:
            scope = _infer_scope(name, description, effects)
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("Capability scope must be non-empty text.")
        rate_limit = metadata.get("rate_limit", tool_dict.get("rate_limit"))
        if rate_limit is not None and (not isinstance(rate_limit, str) or not rate_limit.strip()):
            raise ValueError("Capability rate_limit must be non-empty text or null.")
        deprecated = metadata.get("deprecated", tool_dict.get("deprecated", False))
        if not isinstance(deprecated, bool):
            raise ValueError("Capability deprecated must be a boolean.")
        version = metadata.get("version", tool_dict.get("version", "1.0.0"))
        if not isinstance(version, (str, int, float)) or not str(version).strip():
            raise ValueError("Capability version must be non-empty text.")

        return cls(
            name=name.strip(),
            description=description.strip(),
            version=str(version),
            parameters_schema=schema,
            effects=list(effects),
            risk_class=risk,  # type: ignore[arg-type]
            requires_confirmation=requires_confirmation,
            scope=scope.strip(),
            rate_limit=rate_limit.strip() if isinstance(rate_limit, str) else None,
            deprecated=deprecated,
            sensitive_arguments=list(sensitive),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "parameters_schema": self.parameters_schema,
            "effects": list(self.effects),
            "risk_class": self.risk_class,
            "requires_confirmation": self.requires_confirmation,
            "scope": self.scope,
            "rate_limit": self.rate_limit,
            "deprecated": self.deprecated,
            "sensitive_arguments": list(self.sensitive_arguments),
        }


def validate_arguments(capability: Capability, args: Any) -> ValidationResult:
    errors = _capability_definition_errors(capability)
    if errors:
        return ValidationResult(False, errors)
    if not isinstance(args, dict):
        return ValidationResult(False, ["Arguments must be a JSON object."])
    argument_errors = _validate_value(capability.parameters_schema, args, "$")
    return ValidationResult(not argument_errors, argument_errors)


def validate_capability(capability: Any) -> ValidationResult:
    errors = _capability_definition_errors(capability)
    return ValidationResult(not errors, errors)


def _capability_definition_errors(capability: Any) -> list[str]:
    if not isinstance(capability, Capability):
        return ["Capability has an invalid type."]
    errors: list[str] = []
    if not isinstance(capability.name, str) or not capability.name.strip():
        errors.append("Capability name is missing.")
    if not isinstance(capability.description, str):
        errors.append("Capability description must be text.")
    if not isinstance(capability.version, str) or not capability.version.strip():
        errors.append("Capability version is missing.")
    if not isinstance(capability.parameters_schema, dict):
        errors.append("Capability parameters_schema must be a mapping.")
    else:
        errors.extend(_schema_definition_errors(capability.parameters_schema))
    if not isinstance(capability.effects, list) or not capability.effects or any(
        not isinstance(effect, str) or effect not in _EFFECTS
        for effect in capability.effects
    ) or len(set(capability.effects)) != len(capability.effects):
        errors.append("Capability effects are missing or invalid.")
    if not isinstance(capability.risk_class, str) or capability.risk_class not in _RISK_ORDER:
        errors.append("Capability risk_class is missing or invalid.")
    if not isinstance(capability.requires_confirmation, bool):
        errors.append("Capability requires_confirmation must be a boolean.")
    elif capability.risk_class == "destructive" and not capability.requires_confirmation:
        errors.append("Destructive capabilities require confirmation.")
    if not isinstance(capability.scope, str) or not capability.scope.strip():
        errors.append("Capability scope is missing.")
    if capability.rate_limit is not None and not isinstance(capability.rate_limit, str):
        errors.append("Capability rate_limit must be text or null.")
    if not isinstance(capability.deprecated, bool):
        errors.append("Capability deprecated must be a boolean.")
    if not isinstance(capability.sensitive_arguments, list) or any(
        not isinstance(item, str) or not item for item in capability.sensitive_arguments
    ) or len(set(capability.sensitive_arguments)) != len(capability.sensitive_arguments):
        errors.append("Capability sensitive_arguments are invalid.")
    return errors


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            result[key] = _JSON_TYPES.get(value.upper(), value.lower())
        elif key == "type" and isinstance(value, list):
            result[key] = [
                _JSON_TYPES.get(item.upper(), item.lower()) if isinstance(item, str) else item
                for item in value
            ]
        elif key == "properties" and isinstance(value, dict):
            result[key] = {
                name: _normalize_schema(child) if isinstance(child, dict) else child
                for name, child in value.items()
            }
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            result[key] = _normalize_schema(value)
        else:
            result[key] = value
    return result


def _schema_definition_errors(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    supported_keywords = {
        "type", "properties", "required", "enum", "pattern", "items",
        "additionalProperties", "minLength", "maxLength", "minimum", "maximum",
        "minItems", "maxItems", "title", "description", "default", "nullable",
    }
    unsupported = [key for key in schema if key not in supported_keywords]
    if unsupported:
        errors.append(
            "unsupported schema keywords: " + ", ".join(sorted(map(str, unsupported)))
        )
    if any(not isinstance(key, str) for key in schema):
        errors.append("schema keyword names must be strings.")
    supported_types = {"array", "boolean", "integer", "null", "number", "object", "string"}
    schema_type = schema.get("type")
    if schema_type is not None:
        types = schema_type if isinstance(schema_type, list) else [schema_type]
        if not types or any(
            not isinstance(value, str) or value not in supported_types
            for value in types
        ) or len(set(types)) != len(types):
            errors.append("schema type is invalid.")
    if "nullable" in schema and not isinstance(schema["nullable"], bool):
        errors.append("schema nullable must be a boolean.")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or any(
        not isinstance(name, str) or not isinstance(child, dict)
        for name, child in properties.items()
    ):
        errors.append("schema properties must map names to schemas.")
    else:
        for name, child in properties.items():
            errors.extend(f"property {name}: {error}" for error in _schema_definition_errors(child))
    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or any(not isinstance(name, str) for name in required)
        or len(set(required)) != len(required)
        or (isinstance(properties, dict) and any(name not in properties for name in required))
    ):
        errors.append("schema required must name declared properties.")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        errors.append("schema enum must be a non-empty list.")
    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            errors.append("schema pattern must be text.")
        else:
            try:
                re.compile(pattern)
            except re.error:
                errors.append("schema pattern is not a valid regular expression.")
    for key in ("items", "additionalProperties"):
        child = schema.get(key)
        if isinstance(child, dict):
            errors.extend(f"{key}: {error}" for error in _schema_definition_errors(child))
        elif key == "items" and child is not None:
            errors.append("schema items must be a schema mapping.")
        elif key == "additionalProperties" and not isinstance(child, (bool, type(None))):
            errors.append("schema additionalProperties must be a schema or boolean.")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        bound = schema.get(key)
        if bound is not None and (
            not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
        ):
            errors.append(f"schema {key} must be a non-negative integer.")
    for key in ("minimum", "maximum"):
        bound = schema.get(key)
        if bound is not None and (
            not isinstance(bound, (int, float))
            or isinstance(bound, bool)
            or not isfinite(bound)
        ):
            errors.append(f"schema {key} must be a finite number.")
    for lower, upper in (
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
        ("minimum", "maximum"),
    ):
        if (
            lower in schema
            and upper in schema
            and isinstance(schema[lower], (int, float))
            and isinstance(schema[upper], (int, float))
            and schema[lower] > schema[upper]
        ):
            errors.append(f"schema {lower} must not exceed {upper}.")
    return errors


def _validate_value(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
    if (
        expected_type is not None
        and not (
            schema.get("nullable") is True
            and value is None
            or any(_matches_type(item, value) for item in allowed_types)
        )
    ):
        return [f"{path} must have type {expected_type}."]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of the declared enum values.")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name} is required.")
        properties = schema.get("properties", {})
        for name, child in properties.items():
            if name in value:
                errors.extend(_validate_value(child, value[name], f"{path}.{name}"))
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name not in properties:
                if additional is False:
                    errors.append(f"{path}.{name} is not allowed.")
                elif isinstance(additional, dict):
                    errors.extend(_validate_value(additional, item, f"{path}.{name}"))
    if isinstance(value, str):
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(f"{path} does not match the required pattern.")
        for bound, predicate in (
            ("minLength", lambda limit: len(value) >= limit),
            ("maxLength", lambda limit: len(value) <= limit),
        ):
            if bound in schema and not predicate(schema[bound]):
                errors.append(f"{path} violates {bound}.")
    if isinstance(value, list):
        for bound, predicate in (
            ("minItems", lambda limit: len(value) >= limit),
            ("maxItems", lambda limit: len(value) <= limit),
        ):
            if bound in schema and not predicate(schema[bound]):
                errors.append(f"{path} violates {bound}.")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(_validate_value(schema["items"], item, f"{path}[{index}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for bound, predicate in (
            ("minimum", lambda limit: value >= limit),
            ("maximum", lambda limit: value <= limit),
        ):
            if bound in schema and not predicate(schema[bound]):
                errors.append(f"{path} violates {bound}.")
    return errors


def _matches_type(schema_type: Any, value: Any) -> bool:
    return {
        "array": lambda: isinstance(value, list),
        "boolean": lambda: isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "null": lambda: value is None,
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "object": lambda: isinstance(value, dict),
        "string": lambda: isinstance(value, str),
    }.get(schema_type, lambda: False)()


def _risk_from_effects(effects: list[str]) -> RiskClass:
    if "delete" in effects:
        return "destructive"
    if effects and set(effects).issubset({"read"}):
        return "read"
    if "approval" in effects and len(effects) == 1:
        return "destructive"
    if not effects:
        return "destructive"
    return "write"


def _infer_effects(name: str, description: str, risk: Any) -> list[str]:
    text = f"{name} {description}".casefold()
    effects = []
    if any(word in text for word in ("file", "folder", "workspace", "path", "disk")):
        effects.append("filesystem")
    if any(word in text for word in ("desktop", "screen", "computer", "click", "keyboard")):
        effects.append("desktop")
    if any(word in text for word in ("network", "http", "web", "browser", "proxy", "url")):
        effects.append("network")
    if any(word in text for word in ("shell", "command", "process", "subprocess", "terminal", "shutdown")):
        effects.append("subprocess")
    destructive = risk == "destructive" or any(
        word in text for word in ("delete", "remove", "shutdown", "kill", "execute", "run command")
    )
    if destructive:
        effects.append("delete")
    if risk == "read" or any(word in text for word in ("read", "list", "inspect", "status", "search")):
        effects.append("read")
    if risk == "write" or any(word in text for word in ("write", "create", "update", "organize", "edit")):
        effects.append("write")
    if not effects:
        effects.append("write" if risk == "write" else "read" if risk == "read" else "approval")
    return list(dict.fromkeys(effects))


def _infer_scope(name: str, description: str, effects: list[str]) -> str:
    del description
    if "filesystem" in effects:
        return "filesystem:workspace"
    if "desktop" in effects:
        return "desktop:screen"
    if "network" in effects:
        return "network:external"
    if "subprocess" in effects:
        return "subprocess:local"
    return f"tool:{name}"


@dataclass(frozen=True)
class ToolCapabilities:
    effects: tuple[str, ...]
    sensitive_arguments: tuple[str, ...] = ()
    requires_confirmation: bool = True

    @classmethod
    def from_value(cls, value: Any) -> ToolCapabilities:
        if not isinstance(value, dict):
            raise ValueError("Tool capabilities must be a mapping.")
        effects = value.get("effects")
        sensitive = value.get("sensitive_arguments", [])
        confirm = value.get("requires_confirmation")
        if (
            not isinstance(effects, (list, tuple))
            or not effects
            or any(not isinstance(effect, str) or effect not in _LEGACY_EFFECT_RISK for effect in effects)
            or len(set(effects)) != len(effects)
        ):
            raise ValueError("Tool capabilities must declare valid, unique effects.")
        if (
            not isinstance(sensitive, (list, tuple))
            or any(not isinstance(name, str) or not name for name in sensitive)
            or len(set(sensitive)) != len(sensitive)
        ):
            raise ValueError("Sensitive arguments must be unique non-empty strings.")
        if not isinstance(confirm, bool):
            raise ValueError("requires_confirmation must be a boolean.")
        if "destructive" in effects and not confirm:
            raise ValueError("Destructive effects always require confirmation.")
        return cls(tuple(effects), tuple(sensitive), confirm)

    @property
    def risk_level(self) -> str:
        return max(self.effects, key=_LEGACY_EFFECT_RISK.__getitem__)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effects": list(self.effects),
            "sensitive_arguments": list(self.sensitive_arguments),
            "requires_confirmation": self.requires_confirmation,
        }
