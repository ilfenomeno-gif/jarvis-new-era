"""Starts and advances the approval-gated presentation pipeline."""
from __future__ import annotations

import json
import re
from typing import Any

from core.deck_pipeline import run_pipeline

_YES = re.compile(r"\b(?:si|sì|ok|okay|approvo|approva|confermo|conferma|accetto|procedi|vai)\b", re.I)
_BRIEF = re.compile(r"\bbrief\b|\bbozza\b|\bobiettivo\b|\bstruttura\b", re.I)
_EXPORT = re.compile(r"\b(?:pptx|pdf|export|esport(?:a|azione)|consegna)\b", re.I)


def _approval_matches(operation: str, user_text: str) -> bool:
    text = str(user_text or "").strip()
    if not _YES.search(text):
        return False
    target = _BRIEF if operation == "approve_brief" else _EXPORT
    return bool(target.search(text) or len(text.split()) <= 2)


def deck_pipeline(
    parameters: dict[str, Any] | None = None,
    user_text: str = "",
    user_turn_id: int | None = None,
    **_context: Any,
) -> str:
    params = parameters or {}
    operation = params.get("operation", "start")
    if not isinstance(operation, str):
        return json.dumps(
            {"status": "failed", "error": "operation must be a string."},
            ensure_ascii=False,
        )
    if operation in {"approve_brief", "approve_export"} and not _approval_matches(
        operation, user_text
    ):
        target = "brief" if operation == "approve_brief" else "export PPTX/PDF"
        return json.dumps(
            {
                "status": "approval_required",
                "message": f"Chiedi conferma esplicita per il {target}; non ho avanzato la pipeline.",
            },
            ensure_ascii=False,
        )
    if user_turn_id is not None:
        params = {**params, "_approval_turn_id": user_turn_id}
    try:
        result = run_pipeline(params)
    except ValueError as exc:
        return json.dumps(
            {"status": "failed", "error": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result, ensure_ascii=False)


TOOL = {
    "name": "deck_pipeline",
    "description": (
        "Avvia AUTOMATICAMENTE questo workflow quando l'utente chiede una presentazione, "
        "slide o deck, senza richiedere /deck o un comando tecnico. Crea il brief, poi "
        "attendi l'approvazione umana del brief prima di avviare ricerca parallela, "
        "outline, agenti slide, QA visuale e critica. Dopo i gate, richiedi approvazione "
        "umana separata prima di esportare PPTX editabile e PDF (se LibreOffice è presente). "
        "Usa operation=start con request che contiene la richiesta utente, audience opzionale "
        "e slide_budget opzionale; operation=approve_brief, approve_export, cancel o status "
        "avanzano o controllano un progetto. Le approvazioni sono verificate sul testo "
        "effettivo dell'ultimo turno utente e non possono essere concesse da un parametro del modello."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING",
                "enum": ["start", "approve_brief", "approve_export", "cancel", "status"],
            },
            "request": {"type": "STRING"},
            "audience": {"type": "STRING"},
            "slide_budget": {"type": "INTEGER"},
            "project_id": {"type": "STRING"},
        },
        "required": ["operation"],
    },
    "risk_class": "write",
    "handler": deck_pipeline,
}
