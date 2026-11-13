"""Context-based proactive triggers, with a global cooldown and pause."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

_LOG = logging.getLogger(__name__)
_CATEGORIES = frozenset({"browser", "editor di testo", "editor di codice", "gestore file", "altra applicazione", "ufficio", "relax", "call"})


@dataclass(frozen=True)
class ProactiveEvent:
    kind: str
    key: str
    detail: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("La confidenza deve essere compresa fra 0 e 1.")

    def prompt(self) -> str:
        return (
            "[PROACTIVE_CHECK] Avvisa l'utente con una sola breve frase naturale, "
            "rispettosa, nello stile della personalità corrente e nella lingua della conversazione. Non usare strumenti e "
            "non inventare dettagli. Dato verificato: " + self.detail
        )


class ProactiveEngine:
    def __init__(
        self, context, dispatch: Callable[[ProactiveEvent], bool], *,
        interval: float = 30, cooldown: float = 900,
        ambient=None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        if interval <= 0 or cooldown < 0:
            raise ValueError("Intervallo o cooldown non validi.")
        self._context = context
        self._ambient = ambient
        self._dispatch = dispatch
        self._interval = interval
        self._cooldown = cooldown
        self._clock = clock
        self._wall_clock = wall_clock
        self._now = now
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sent: float | None = None
        self._paused_until = 0.0
        self._pending: ProactiveEvent | None = None
        self._seen: set[str] = set()
        self._category: str | None = None
        self._category_since = 0.0
        self._session_number = 0
        self._idle_number = 0
        self._idle_active = False
        self._hardware_since: dict[str, float] = {}
        self._hardware_epoch: dict[str, int] = {}
        self._network_connected: bool | None = None
        self._monitor_version: int | None = None
        self._monitor_pending_version: int | None = None
        self._hog_identity: str | None = None

    def start(self) -> bool:
        if os.environ.get("JARVIS_PROACTIVE_ENGINE", "1") == "0" or self._context is None:
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="proactive-engine")
            self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def pause(self, seconds: float | None = None) -> None:
        if seconds is not None and seconds <= 0:
            raise ValueError("La durata della pausa deve essere positiva.")
        with self._lock:
            self._paused_until = float("inf") if seconds is None else self._clock() + seconds

    def resume(self) -> None:
        with self._lock:
            self._paused_until = 0.0

    def is_paused(self) -> bool:
        with self._lock:
            return self._clock() < self._paused_until

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                _LOG.exception("Valutazione dei trigger proattivi non riuscita.")

    def _hardware_candidates(self, context: dict, now: float) -> list[ProactiveEvent]:
        state = context.get("symbiosis")
        if not isinstance(state, dict):
            return []
        pulse = state.get("pulse") or {}
        process = state.get("process") or {}
        network = state.get("network") or {}
        monitor = state.get("monitor") or {}
        candidates: list[ProactiveEvent] = []

        def held(kind: str, condition: bool, seconds: float, detail: str, confidence: float = 0.95):
            if not condition:
                if kind in self._hardware_since:
                    self._hardware_since.pop(kind)
                    self._hardware_epoch[kind] = self._hardware_epoch.get(kind, 0) + 1
                return
            start = self._hardware_since.setdefault(kind, now)
            if now - start >= seconds:
                candidates.append(ProactiveEvent(kind, f"{kind}:{self._hardware_epoch.get(kind, 0)}", detail, confidence))

        def number(value):
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value))

        def fresh(observed, max_age, current):
            return (number(observed) and number(max_age) and max_age > 0
                    and 0 <= current - observed <= max_age)

        pulse_fresh = fresh(pulse.get("sampled_at_monotonic"), pulse.get("fresh_for_seconds"), now)
        cpu = pulse.get("cpu_percent") if pulse_fresh else None
        ram = pulse.get("ram_percent") if pulse_fresh else None
        battery = pulse.get("battery_percent") if pulse_fresh else None
        disk = pulse.get("disk_free_gb") if pulse_fresh else None
        temperature = pulse.get("temperature_c") if pulse_fresh else None
        sustained = pulse.get("cpu_sustained_seconds")
        held("high_cpu", number(cpu) and cpu > 90 and number(sustained) and sustained >= 120,
             0, "La CPU supera il 90% da due minuti.")
        held("high_ram", number(ram) and ram > 85, 0, "La RAM supera l'85%.")
        try:
            from memory.memory_manager import load_user_profile
            battery_enabled = load_user_profile()["preferences"].get("low_battery_alert") != "disabled"
        except (OSError, ValueError):
            _LOG.exception("[SYMBIOSIS][PROACTIVE] Profilo non disponibile: avviso batteria sospeso")
            battery_enabled = False
        held("low_battery", battery_enabled and number(battery) and battery < 15 and pulse.get("battery_plugged") is False,
             0, "La batteria è sotto il 15% e non è in carica.")
        held("low_disk", number(disk) and disk < 5, 0, "Il disco C: ha meno di 5 GB liberi.")
        held("high_temp", number(temperature) and temperature > 85, 0, "La temperatura hardware supera 85 gradi.")
        hog = process.get("hog")
        hog_name = hog.get("name") if isinstance(hog, dict) else None
        hog_cpu = hog.get("cpu_percent") if isinstance(hog, dict) else None
        hog_duration = hog.get("cpu_high_for_seconds") if isinstance(hog, dict) else None
        hog_fresh = (isinstance(hog, dict)
                     and fresh(hog.get("observed_at"), hog.get("fresh_for_seconds"), self._wall_clock()))
        safe_name = hog_name if isinstance(hog_name, str) and re.fullmatch(r"[A-Za-z0-9_.+\-]{1,80}", hog_name) else None
        identity = hog.get("identity", safe_name) if isinstance(hog, dict) else None
        identity = identity if isinstance(identity, str) else safe_name
        if identity != self._hog_identity:
            if "hog_alert" in self._hardware_since:
                self._hardware_since.pop("hog_alert")
                self._hardware_epoch["hog_alert"] = self._hardware_epoch.get("hog_alert", 0) + 1
            self._hog_identity = identity
        held("hog_alert", hog_fresh and safe_name is not None and number(hog_cpu) and hog_cpu > 80
             and number(hog_duration) and hog_duration >= 180, 0,
             "Un processo supera l'80% di CPU da tre minuti"
             + (f": {json.dumps(safe_name)}. Chiedi se chiuderlo; non chiuderlo senza conferma." if safe_name else "."))
        held("zombie_alert", bool(process.get("zombies")), 0, "Rilevati processi zombie.", 0.8)
        network_fresh = fresh(network.get("sampled_at_monotonic"), network.get("fresh_for_seconds"), now)
        connected = network.get("connected") if network_fresh else None
        if isinstance(connected, bool):
            if self._network_connected is True and not connected:
                self._hardware_epoch["network_drop"] = self._hardware_epoch.get("network_drop", 0) + 1
            self._network_connected = connected
        held("network_drop", connected is False and self._hardware_epoch.get("network_drop", 0) > 0,
             0, "La connessione di rete è caduta.")
        signal = network.get("wifi_signal_percent") if network_fresh else None
        weak_duration = network.get("wifi_weak_seconds")
        held("wifi_weak", number(signal) and 0 <= signal < 30
             and number(weak_duration) and weak_duration >= 120,
             0, "Il segnale Wi-Fi è debole da due minuti.", 0.8)
        version = monitor.get("change_counter")
        if isinstance(version, int) and not isinstance(version, bool):
            if self._monitor_version is not None and version != self._monitor_version:
                self._monitor_pending_version = version
            self._monitor_version = version
        if self._monitor_pending_version is not None:
            candidates.append(ProactiveEvent("monitor_change", f"monitor:{self._monitor_pending_version}",
                                             "La configurazione dei monitor è cambiata.", 0.8))
        return candidates

    def tick(self) -> ProactiveEvent | None:
        context = self._context.get_context()
        now_mono = self._clock()
        now = self._now()
        with self._lock:
            category = context.get("window_category")
            if category not in _CATEGORIES:
                category = None
            idle = context.get("idle_minutes")
            active = isinstance(idle, (float, int)) and not isinstance(idle, bool) and 0 <= idle < 5
            if category != self._category or not active:
                self._category = category
                self._category_since = now_mono
                self._session_number += 1
            period = context.get("time_of_day")
            threshold = 30 if period in {"sera", "notte"} else 20
            idle_trigger = isinstance(idle, (int, float)) and not isinstance(idle, bool) and idle > threshold
            if not idle_trigger and self._idle_active:
                self._idle_number += 1
            self._idle_active = idle_trigger
            if self._ambient is not None:
                from core.ambient_presence import AWAY
                state = self._ambient.get_presence_state(context)
                if state == AWAY or self._ambient.is_away(context):
                    print(f"[AMBIENT] Stato: {state} | Trigger: nessuno | Canale: SKIP")
                    return None
            if self._stop.is_set() or self.is_paused() or self._pending is not None:
                return None
            if self._last_sent is not None and now_mono - self._last_sent < self._cooldown:
                return None

            calendar = context.get("calendar")
            candidates = self._hardware_candidates(context, now_mono)
            if isinstance(calendar, dict) and calendar.get("status") == "upcoming":
                minutes = calendar.get("minutes")
                start = calendar.get("start")
                if isinstance(minutes, int) and not isinstance(minutes, bool) and 0 < minutes <= 5 and isinstance(start, str):
                    candidates.append(ProactiveEvent("calendar", "calendar:" + start, f"Un evento inizia tra {minutes} minuti.", 0.95))
            if now.hour == 2 and active:
                candidates.append(ProactiveEvent("late_night", f"night:{now.date()}", "Sono circa le 02:00 e l'utente è attivo al PC.", 0.95))
            if idle_trigger:
                candidates.append(ProactiveEvent("idle", f"idle:{self._idle_number}", f"L'utente è inattivo da oltre {threshold} minuti.", 0.95))
            if category and active and now_mono - self._category_since > 7200:
                candidates.append(ProactiveEvent("long_work", f"work:{self._session_number}", f"L'utente usa la categoria {category} da oltre due ore.", 0.8))
            event = next((candidate for candidate in candidates if candidate.key not in self._seen), None)
            if event is None:
                return None
            self._pending = event
        try:
            accepted = self._dispatch(event)
        except Exception:
            _LOG.exception("Invio del trigger proattivo non riuscito.")
            accepted = False
        if not accepted:
            self.complete(event, delivered=False)
            return None
        return event

    def complete(self, event: ProactiveEvent, *, delivered: bool) -> None:
        with self._lock:
            if self._pending != event:
                return
            self._pending = None
            if delivered:
                self._last_sent = self._clock()
                self._seen.add(event.key)
                if len(self._seen) > 256:
                    self._seen = {event.key}


def parse_pause_command(text: str) -> tuple[str, float | None] | None:
    value = re.sub(r"[^\w\sàèéìòù']", " ", text.casefold())
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(?:jarvis|iris)\s+", "", value)
    if re.fullmatch(r"(?:riprendi|riattiva)(?:\s+(?:gli interventi|la proattività|la proattivita))?", value):
        return "resume", None
    if re.fullmatch(r"(?:stai zitto|stai zitta|non disturbarmi|mettiti in pausa)", value):
        return "pause", None
    match = re.fullmatch(
        r"(?:non disturbarmi|mettiti in pausa|stai zitt[oa]) per (?:(\d+)\s+|(un|una)\s+|(un|mezz)'|(mezza)\s+)?(ora|ore|minuto|minuti)",
        value,
    )
    if match is None:
        return None
    amount = 0.5 if match.group(3) == "mezz" or match.group(4) else int(match.group(1)) if match.group(1) else 1
    seconds = amount * (3600 if match.group(5) in {"ora", "ore"} else 60)
    return ("pause", seconds) if seconds > 0 else None
