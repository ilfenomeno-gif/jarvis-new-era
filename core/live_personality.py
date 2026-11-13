"""Update a Live session using privacy-preserving personality instructions."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from core.personality_engine import PersonalityEngine

_LOG = logging.getLogger(__name__)


class LivePersonality:
    def __init__(self, context_engine, session, initial_prompt: str, *,
                 report: Callable[[str], None], interval: float = 300.0):
        self._context_engine = context_engine
        self._session = session
        self._applied = initial_prompt
        self._report = report
        self._interval = interval
        self._wake = asyncio.Event()
        self._pending_nudge: str | None = None

    def _instruction(self) -> tuple[str, str]:
        context = self._context_engine.get_context() if self._context_engine is not None else {}
        engine = PersonalityEngine()
        prompt = engine.get_personality_prompt(context)
        if not prompt:
            return "", "La personalità adattiva è disattivata o non disponibile; usa il tono predefinito."
        profile = engine.profile(context)
        return prompt, (
            f"Aggiornamento personalità: modalità {profile}. {prompt} "
            "Questa è una modifica interna: applicala alle prossime risposte, "
            "sostituisce le precedenti istruzioni di personalità e non va annunciata. "
            "Non è una nuova conversazione: conserva identità, memoria e continuità."
        )

    async def refresh(self) -> bool:
        prompt, instruction = self._instruction()
        if prompt == self._applied:
            self._pending_nudge = None
            return False
        try:
            await self._session.send_client_content(
                turns={"role": "user", "parts": [{"text": instruction}]},
                turn_complete=False,
            )
        except Exception as exc:
            _LOG.warning("Live personality update failed: %s", exc, exc_info=True)
            self._report(f"ERR: Aggiornamento personalità Live non riuscito: {type(exc).__name__}: {exc}")
            self._pending_nudge = (
                "Passiamo a un tono più adatto al momento."
                if prompt else "Torno al tono predefinito."
            )
            return False
        self._applied = prompt
        self._pending_nudge = None
        return True

    def take_nudge(self) -> str | None:
        nudge, self._pending_nudge = self._pending_nudge, None
        return nudge

    def notify_change(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        def window_changed() -> None:
            try:
                loop.call_soon_threadsafe(self._wake.set)
            except RuntimeError:
                _LOG.debug("Live personality loop already closed")

        if self._context_engine is not None:
            self._context_engine.add_window_listener(window_changed)
        try:
            while True:
                self._wake.clear()
                await self.refresh()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
        finally:
            if self._context_engine is not None:
                self._context_engine.remove_window_listener(window_changed)
