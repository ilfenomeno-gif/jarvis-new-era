"""
core/widget_registry.py — Widget Registry for JARVIS

Manages widget type registration, spec validation, and per-widget throttling.
No PyQt imports here — this module is UI-framework-agnostic by design.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional, Type

# ── Constants ────────────────────────────────────────────────────────────────
_MAX_TEXT_CHARS  = 4000
_MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB
_MAX_TABLE_ROWS  = 500
_MAX_LIST_ITEMS  = 200
_THROTTLE_MS     = 100               # minimum ms between updates for same id


# ── Internal throttle tracker ─────────────────────────────────────────────────
_last_update: dict[str, float] = {}


def _is_throttled(widget_id: str) -> bool:
    now = time.monotonic() * 1000
    last = _last_update.get(widget_id, 0.0)
    if now - last < _THROTTLE_MS:
        return True
    _last_update[widget_id] = now
    return False


# ── Validator helpers ─────────────────────────────────────────────────────────
def _require(payload: dict, key: str, expected_type: type, label: str) -> Optional[str]:
    if key not in payload:
        return f"payload missing required field '{key}' for {label}"
    if not isinstance(payload[key], expected_type):
        return f"payload field '{key}' must be {expected_type.__name__} for {label}"
    return None


# ── Built-in validators ───────────────────────────────────────────────────────
def _validate_text(payload: dict) -> Optional[str]:
    err = _require(payload, "text", str, "text widget")
    if err:
        return err
    if len(payload["text"]) > _MAX_TEXT_CHARS:
        payload["text"] = payload["text"][:_MAX_TEXT_CHARS]  # auto-truncate
    return None


def _validate_progress(payload: dict) -> Optional[str]:
    err = _require(payload, "value", (int, float), "progress widget")
    if err:
        err = _require(payload, "value", int, "progress widget")
        if err:
            return err
    v = payload["value"]
    if not (0 <= v <= 100):
        return f"progress value must be 0–100, got {v}"
    return None


def _validate_image(payload: dict) -> Optional[str]:
    has_path  = "path" in payload
    has_bytes = "data" in payload
    if not has_path and not has_bytes:
        return "image widget requires 'path' (str) or 'data' (bytes)"
    if has_path:
        if not isinstance(payload["path"], str):
            return "image 'path' must be a string"
        # Guardrails check — resolve_safe_path raises PermissionError if unsafe
        try:
            from core.guardrails import resolve_safe_path
            safe = resolve_safe_path(payload["path"])
            if not safe.exists():
                return f"image file not found: {payload['path']}"
            payload["path"] = str(safe)   # normalise to absolute
        except PermissionError as e:
            return f"image path not allowed: {e}"
    if has_bytes:
        if not isinstance(payload["data"], bytes):
            return "image 'data' must be bytes"
        if len(payload["data"]) > _MAX_IMAGE_BYTES:
            return f"image data exceeds {_MAX_IMAGE_BYTES // 1024 // 1024} MB limit"
    return None


def _validate_table(payload: dict) -> Optional[str]:
    err = _require(payload, "headers", list, "table widget")
    if err:
        return err
    err = _require(payload, "rows", list, "table widget")
    if err:
        return err
    if len(payload["rows"]) > _MAX_TABLE_ROWS:
        payload["rows"] = payload["rows"][:_MAX_TABLE_ROWS]
    return None


def _validate_list(payload: dict) -> Optional[str]:
    err = _require(payload, "items", list, "list widget")
    if err:
        return err
    if len(payload["items"]) > _MAX_LIST_ITEMS:
        payload["items"] = payload["items"][:_MAX_LIST_ITEMS]
    return None


def _validate_toast(payload: dict) -> Optional[str]:
    err = _require(payload, "message", str, "toast widget")
    if err:
        return err
    allowed_kinds = {"info", "warning", "error", "success"}
    kind = payload.get("kind", "info")
    if kind not in allowed_kinds:
        return f"toast 'kind' must be one of {allowed_kinds}"
    payload.setdefault("kind", "info")
    return None


def _validate_chart(payload: dict) -> Optional[str]:
    err = _require(payload, "series", list, "chart widget")
    if err:
        return err
    chart_types = {"line", "bar", "pie"}
    ct = payload.get("chart_type", "line")
    if ct not in chart_types:
        return f"chart_type must be one of {chart_types}"
    return None


def _validate_gauge(payload: dict) -> Optional[str]:
    for field in ("value", "min_val", "max_val"):
        err = _require(payload, field, (int, float), "gauge widget")
        if err:
            return err
    v, lo, hi = payload["value"], payload["min_val"], payload["max_val"]
    if lo >= hi:
        return "gauge min_val must be less than max_val"
    if not (lo <= v <= hi):
        return f"gauge value {v} out of range [{lo}, {hi}]"
    return None


def _validate_toggle_list(payload: dict) -> Optional[str]:
    err = _require(payload, "items", list, "toggle_list widget")
    if err:
        return err
    for i, item in enumerate(payload["items"]):
        if not isinstance(item, dict) or "label" not in item or "state" not in item:
            return f"toggle_list item {i} must have 'label' (str) and 'state' (bool)"
    return None


def _validate_countdown(payload: dict) -> Optional[str]:
    err = _require(payload, "seconds", (int, float), "countdown widget")
    if err:
        return err
    return None


# ── Registry record ───────────────────────────────────────────────────────────
class _WidgetType:
    __slots__ = ("name", "validator", "renderer_cls")

    def __init__(self, name: str, validator: Callable, renderer_cls):
        self.name         = name
        self.validator    = validator
        self.renderer_cls = renderer_cls   # set after renderers module is loaded


class WidgetRegistry:
    """
    Central registry for widget types.

    Usage:
        registry.register("myplugin_type", my_validator, MyRendererClass)
        err = registry.validate(spec)
        cls = registry.get_renderer(spec["type"])
    """
    def __init__(self):
        self._types: dict[str, _WidgetType] = {}

    def register(self, type_name: str, validator: Callable,
                 renderer_cls=None) -> None:
        """Register a widget type. renderer_cls can be set later via set_renderer()."""
        self._types[type_name] = _WidgetType(type_name, validator, renderer_cls)

    def set_renderer(self, type_name: str, renderer_cls) -> None:
        """Attach a renderer class to an already-registered type."""
        if type_name in self._types:
            self._types[type_name].renderer_cls = renderer_cls

    def validate(self, spec: dict) -> Optional[str]:
        """
        Validate a widget spec dict.
        Returns None on success, or an error string on failure.
        Mutates spec payload in-place for auto-truncation (text, table rows, etc.).
        """
        if not isinstance(spec, dict):
            return "spec must be a dict"

        wid_id   = spec.get("id")
        wid_type = spec.get("type")
        payload  = spec.get("payload", {})

        if not wid_id or not isinstance(wid_id, str):
            return "spec 'id' must be a non-empty string"

        # Internal control messages bypass type validation
        if wid_type in ("__update__", "__remove__"):
            return None

        if wid_type not in self._types:
            return f"unknown widget type '{wid_type}'; registered: {list(self._types)}"

        if not isinstance(payload, dict):
            return "spec 'payload' must be a dict"

        # Throttle check (mutates _last_update state)
        if _is_throttled(wid_id):
            return f"throttled: widget '{wid_id}' updated too frequently (>{1000//_THROTTLE_MS}/s)"

        return self._types[wid_type].validator(payload)

    def get_renderer(self, type_name: str):
        """Return the renderer class for the given type, or None."""
        rec = self._types.get(type_name)
        return rec.renderer_cls if rec else None

    def registered_types(self) -> list[str]:
        return list(self._types.keys())


# ── Module-level singleton ────────────────────────────────────────────────────
registry = WidgetRegistry()

# Register all built-in Phase 1 types (renderers attached later by widget_renderers.py)
registry.register("text",        _validate_text)
registry.register("progress",    _validate_progress)
registry.register("image",       _validate_image)

# Phase 2
registry.register("table",       _validate_table)
registry.register("list",        _validate_list)
registry.register("toast",       _validate_toast)

# Phase 3
registry.register("chart",       _validate_chart)
registry.register("gauge",       _validate_gauge)
registry.register("toggle_list", _validate_toggle_list)
registry.register("countdown",   _validate_countdown)
