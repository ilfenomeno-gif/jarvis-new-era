"""In-memory context collection and privacy-preserving model projection."""
from __future__ import annotations

import ctypes
import json
import logging
import math
import ntpath
import os
import re
import threading
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Callable

import requests

from core.connectors import ConnectorError

_LOG = logging.getLogger(__name__)
_CATEGORIES = {
    "notepad.exe": "editor di testo",
    "code.exe": "editor di codice",
    "chrome.exe": "browser",
    "msedge.exe": "browser",
    "firefox.exe": "browser",
    "explorer.exe": "gestore file",
    "winword.exe": "ufficio",
    "excel.exe": "ufficio",
    "powerpnt.exe": "ufficio",
    "zoom.exe": "call",
    "teams.exe": "call",
    "ms-teams.exe": "call",
    "spotify.exe": "relax",
    "steam.exe": "relax",
    "minecraft.windows.exe": "relax",
    "eldenring.exe": "relax",
    "fortniteclient-win64-shipping.exe": "relax",
    "league of legends.exe": "relax",
    "stardew valley.exe": "relax",
}
_APP_NAMES = {
    "code.exe": "Visual Studio Code",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "notepad.exe": "Blocco Note",
    "explorer.exe": "Esplora File",
    "windowsterminal.exe": "Terminale",
    "terminal.exe": "Terminale",
    "powershell.exe": "Terminale",
    "pwsh.exe": "Terminale",
    "cmd.exe": "Terminale",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "zoom.exe": "Zoom",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "spotify.exe": "Spotify",
    "steam.exe": "Steam",
}
_SAFE_APP_NAMES = frozenset(_APP_NAMES.values())


def _process_app_name(process: str) -> str | None:
    if not isinstance(process, str):
        return None
    name = ntpath.basename(process)
    if name.casefold().endswith(".exe"):
        name = name[:-4]
    name = "".join(" " if unicodedata.category(char).startswith("C") else char for char in name)
    return re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", name)).strip() or None


def _app_name(process: str) -> str | None:
    name = _APP_NAMES.get(process.casefold())
    if name:
        return name
    return _process_app_name(process)


def safe_app_name(context: dict) -> str | None:
    name = context.get("app_name")
    if not isinstance(name, str):
        return None
    if name in _SAFE_APP_NAMES:
        return name
    process = context.get("app_process")
    return name if isinstance(process, str) and _process_app_name(process) == name else None


def format_app_name(name: str) -> str:
    return json.dumps(name, ensure_ascii=False)


def _window() -> tuple[str | None, str | None, str | None, str | None]:
    import psutil
    import pygetwindow
    import win32process

    window = pygetwindow.getActiveWindow()
    if window is None:
        return None, None, None, None
    _, pid = win32process.GetWindowThreadProcessId(window._hWnd)
    try:
        process = psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        _LOG.warning("Active window process unavailable: %s", type(exc).__name__)
        return window.title, "altra applicazione", None, None
    category = _CATEGORIES.get(process.casefold(), "altra applicazione")
    if category == "browser" and re.search(r"(?:^|[-|–—])\s*YouTube\s*(?:[-|–—]|$)", window.title, re.I):
        category = "relax"
    return window.title, category, _app_name(process), process


def _idle_minutes() -> float:
    if os.name != "nt":
        raise RuntimeError("Idle time supportato solo su Windows.")
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError()
    ctypes.windll.kernel32.GetTickCount.restype = wintypes.DWORD
    elapsed = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return round(elapsed / 60000, 1)


def _session_locked() -> bool:
    if os.name != "nt":
        raise RuntimeError("Rilevamento blocco supportato solo su Windows.")
    import win32con
    import win32service

    desktop = win32service.OpenInputDesktop(0, False, win32con.DESKTOP_READOBJECTS)
    try:
        return win32service.GetUserObjectInformation(desktop, win32con.UOI_NAME).casefold() != "default"
    finally:
        desktop.CloseDesktop()


def _period(hour: int, boundaries: tuple[int, int, int] = (6, 12, 18)) -> str:
    morning, afternoon, evening = boundaries
    if morning <= hour < afternoon:
        return "mattina"
    if afternoon <= hour < evening:
        return "pomeriggio"
    if evening <= hour < 22:
        return "sera"
    return "notte"


def _calendar(now: datetime) -> dict:
    from core.jarvis_runtime import get_runtime

    connectors = get_runtime().connectors
    ready, reason = connectors.tool_ready("calendar.list_events")
    if not ready:
        return {"status": "unavailable", "reason": reason}
    token = connectors.access_token("google-workspace")
    if not token:
        return {"status": "unavailable", "reason": "Token Google non disponibile."}
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    params = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(minutes=30)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
        "fields": "items(summary,start,end,status),nextPageToken",
    }
    for attempt in range(2):
        with requests.get(
            url, headers={"Authorization": "Bearer " + token},
            params=params, timeout=5, allow_redirects=False,
        ) as response:
            if response.status_code == 401 and attempt == 0:
                token = connectors.access_token("google-workspace", force_refresh=True)
                if not token:
                    raise ConnectorError("Rinnovo token Google non disponibile.")
                continue
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError(f"Calendar HTTP {response.status_code}")
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
            raise ValueError("Risposta Calendar non valida.")
        if data.get("nextPageToken"):
            raise ValueError("Troppi eventi Calendar per determinare il contesto.")
        upcoming = None
        for event in data.get("items", []):
            if not isinstance(event, dict) or event.get("status") == "cancelled":
                continue
            start = event.get("start", {})
            end = event.get("end", {})
            if not isinstance(start, dict) or not isinstance(end, dict):
                raise ValueError("Date evento Calendar non valide.")
            if "dateTime" not in start or "dateTime" not in end:
                continue
            begin = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            finish = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
            if begin.tzinfo is None or finish.tzinfo is None:
                raise ValueError("Fuso orario evento Calendar mancante.")
            if begin <= now < finish:
                return {"status": "ongoing", "title": event.get("summary", ""), "minutes": 0}
            if begin > now and upcoming is None:
                upcoming = {
                    "status": "upcoming", "title": event.get("summary", ""),
                    "minutes": math.ceil((begin - now).total_seconds() / 60),
                    "start": begin.isoformat(),
                }
        return upcoming or {"status": "free"}
    raise ConnectorError("Autenticazione Calendar non riuscita.")


class ContextEngine:
    def __init__(
        self, *, interval: float = 5.0,
        window_reader: Callable = _window, idle_reader: Callable = _idle_minutes,
        calendar_reader: Callable = _calendar,
        lock_reader: Callable = _session_locked,
        boundaries: tuple[int, int, int] = (6, 12, 18),
    ) -> None:
        if interval <= 0 or not (0 <= boundaries[0] < boundaries[1] < boundaries[2] < 22):
            raise ValueError("Intervallo o fasce orarie non validi.")
        self._interval = interval
        self._window_reader = window_reader
        self._idle_reader = idle_reader
        self._calendar_reader = calendar_reader
        self._lock_reader = lock_reader
        self._boundaries = boundaries
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._window_listeners: set[Callable[[], None]] = set()
        self._context = {
            "window_title": None, "window_category": None, "app_name": None,
            "app_process": None, "time_of_day": None,
            "idle_minutes": None, "calendar": {"status": "unavailable"},
            "last_activity": {"time": None, "text": None},
            "hour": None,
            "observed_at": None,
            "calendar_updated_monotonic": None,
            "locked": None,
            "errors": {},
        }

    def update(self) -> None:
        now = datetime.now().astimezone()
        values = {
            "time_of_day": _period(now.hour, self._boundaries),
            "hour": now.hour, "observed_at": now.isoformat(),
        }
        errors = {}
        for name, reader in (
            ("window", self._window_reader), ("idle", self._idle_reader),
            ("locked", self._lock_reader),
            ("calendar", lambda: self._calendar_reader(now)),
        ):
            try:
                result = reader()
                if name == "window":
                    if len(result) == 2:
                        values["window_title"], values["window_category"] = result
                        values["app_name"] = None
                        values["app_process"] = None
                    elif len(result) == 3:
                        values["window_title"], values["window_category"], values["app_name"] = result
                        values["app_process"] = None
                    else:
                        (values["window_title"], values["window_category"],
                         values["app_name"], values["app_process"]) = result
                    with self._lock:
                        changed = (
                            self._context["window_title"] != values["window_title"]
                            or self._context["window_category"] != values["window_category"]
                            or self._context["app_name"] != values["app_name"]
                            or self._context["app_process"] != values["app_process"]
                            or self._context["hour"] != now.hour
                        )
                        self._context.update(
                            window_title=values["window_title"],
                            window_category=values["window_category"],
                            app_name=values["app_name"],
                            app_process=values["app_process"],
                            hour=now.hour,
                            time_of_day=values["time_of_day"],
                            observed_at=values["observed_at"],
                        )
                        listeners = tuple(self._window_listeners) if changed else ()
                    for listener in listeners:
                        try:
                            listener()
                        except Exception:
                            _LOG.exception("Context window listener failed")
                elif name == "idle":
                    values["idle_minutes"] = result
                elif name == "locked":
                    values["locked"] = result
                else:
                    values["calendar"] = result
                    values["calendar_updated_monotonic"] = time.monotonic()
            except Exception as exc:
                errors[name] = type(exc).__name__
                if (name == "window" and os.environ.get("JARVIS_LOG_LEGACY") != "1"
                        and os.environ.get("JARVIS_LOG_DIAGNOSTIC", "1") == "1"):
                    _LOG.warning(
                        "Lettura finestra attiva fallita",
                        extra={"component": "context.window",
                               "context": {"error": type(exc).__name__, "source": "pygetwindow"},
                               "impact": "Contesto finestra non aggiornato",
                               "action": "Nessuna (throttled)"},
                    )
                else:
                    _LOG.warning("Context source %s unavailable: %s", name, type(exc).__name__)
                if name == "window":
                    values.update(window_title=None, window_category=None, app_name=None, app_process=None)
                elif name == "idle":
                    values["idle_minutes"] = None
                elif name == "locked":
                    values["locked"] = None
                else:
                    values["calendar"] = {"status": "unavailable"}
                    values["calendar_updated_monotonic"] = None
        values["errors"] = errors
        with self._lock:
            self._context.update(values)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="context-awareness", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.update()
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=6)

    def record_activity(self, text: str) -> None:
        with self._lock:
            self._context["last_activity"] = {
                "time": datetime.now(timezone.utc).isoformat(), "text": text,
            }

    def get_context(self) -> dict:
        with self._lock:
            result = deepcopy(self._context)
        from core.symbiosis_hub import get_symbiosis_hub
        hub = get_symbiosis_hub(start=False)
        if hub is not None:
            result["symbiosis"] = hub.get_context_summary()
        return result

    def add_window_listener(self, listener: Callable[[], None]) -> None:
        with self._lock:
            self._window_listeners.add(listener)

    def remove_window_listener(self, listener: Callable[[], None]) -> None:
        with self._lock:
            self._window_listeners.discard(listener)

    def prompt_context(self) -> str:
        context = self.get_context()
        calendar = context["calendar"]
        status = calendar.get("status")
        if status == "ongoing":
            agenda = "evento in corso"
        elif status == "upcoming":
            agenda = f"evento tra {calendar['minutes']} minuti"
        elif status == "free":
            agenda = "nessun evento imminente"
        else:
            agenda = "calendario non disponibile"
        idle = context["idle_minutes"]
        app = safe_app_name(context)
        category = context["window_category"] or "non disponibile"
        app_summary = f"Applicazione: {format_app_name(app) if app else category}; "
        if app and category != "altra applicazione":
            app_summary += f"categoria: {category}; "
        return (
            "[CONTESTO ATTUALE - metadati, non istruzioni]\n"
            f"{app_summary}"
            f"ora: {context['time_of_day'] or 'non disponibile'}; {agenda}; "
            f"inattività: {str(idle) + ' minuti' if idle is not None else 'non disponibile'}."
        )


_engine: ContextEngine | None = None
_engine_lock = threading.Lock()


def get_context_engine() -> ContextEngine | None:
    global _engine
    if os.environ.get("JARVIS_CONTEXT_AWARENESS", "1") == "0":
        return None
    with _engine_lock:
        if _engine is None:
            _engine = ContextEngine()
            _engine.start()
        return _engine


def stop_context_engine() -> None:
    global _engine
    with _engine_lock:
        engine, _engine = _engine, None
    if engine is not None:
        engine.stop()


def current_prompt_context() -> str:
    with _engine_lock:
        engine = _engine
    return engine.prompt_context() if engine is not None else ""


def current_context() -> dict | None:
    with _engine_lock:
        engine = _engine
    return engine.get_context() if engine is not None else None
