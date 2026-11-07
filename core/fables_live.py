"""Read-only, explicitly authorized Fables browser preflight."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime

from core.internal_workflow import InternalWorkflowStore


BrowserAction = Callable[[dict], str]
_REQUEST_TERMS = re.compile(
    r"\b(?:request|invitation|invite|pending|accepted|accept|richiesta|invito|"
    r"in attesa|accettat[oa]|accetta)\b",
    re.IGNORECASE,
)


def run_read_only_preflight(
    store: InternalWorkflowStore,
    world_url: str,
    browser_action: BrowserAction,
) -> dict:
    """Navigate and record visible-page evidence without clicking or invoking agents."""
    workflow = store.create_fables_plan(
        "Preflight live in sola lettura della pagina Fables.",
        world_url,
    )
    if workflow["status"] != "planned":
        raise ValueError("This Fables workflow has already been used; refusing to repeat preflight.")

    before_url = browser_action({"action": "get_url"})
    navigation = browser_action({"action": "go_to", "url": world_url})
    after_url = browser_action({"action": "get_url"})
    visible_text = browser_action({"action": "get_text"})

    if not all(isinstance(value, str) for value in (before_url, navigation, after_url, visible_text)):
        raise TypeError("Browser preflight returned an unexpected result type.")

    terms = sorted({match.group(0).casefold() for match in _REQUEST_TERMS.finditer(visible_text)})
    evidence = {
        "observed_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "operation": "read_only_preflight",
        "before_url": before_url[:2048],
        "navigation_result": navigation[:1000],
        "after_url": after_url[:2048],
        "visible_text_sha256": hashlib.sha256(visible_text.encode("utf-8")).hexdigest(),
        "visible_text_chars": len(visible_text),
        "request_related_terms_visible": terms[:30],
        "request_state": "not established; visible text alone is insufficient",
        "network_or_console_evidence": "unavailable from the existing browser action interface",
        "mutations_performed": False,
        "agents_invoked": [],
    }
    return store.record_live_observation(workflow["id"], evidence)
