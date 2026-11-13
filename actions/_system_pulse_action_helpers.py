"""Shared implementation for the individual read-only system status actions."""
from __future__ import annotations

import json

from core.symbiosis_hub import get_symbiosis_hub


def read_metrics(keys: tuple[str, ...] | None = None) -> str:
    try:
        hub = get_symbiosis_hub(start=False)
        if hub is None:
            return json.dumps({"error": "SymbiosisHub non attivo o disabilitato."})
        pulse = hub.get_module("pulse")
        if pulse is None:
            return json.dumps({"error": "Modulo pulse non selezionato o non disponibile."})
        snapshot = pulse.snapshot()
        if not isinstance(snapshot, dict):
            return json.dumps({"error": "Modulo pulse non disponibile."})
        if "error" in snapshot:
            return json.dumps({"error": "Modulo pulse non disponibile."})
        result = snapshot if keys is None else {key: snapshot[key] for key in keys}
        return json.dumps(result, allow_nan=False)
    except Exception:
        return json.dumps({"error": "Metriche di sistema non disponibili."})
