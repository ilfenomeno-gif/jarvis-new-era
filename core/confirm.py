"""
core/confirm.py — a confirmation the model cannot forge.

THE PROBLEM WITH THE OLD GATE
    computer_settings guarded shutdown and restart like this:

        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return "Please confirm by calling again with confirmed=yes."

    `confirmed` is a tool parameter, which means the *model* writes it. Nothing
    stops it from sending confirmed=yes on the first call, and nothing checks
    that a human was ever involved. It is a convention, not a gate — and its
    coverage was two actions, so deleting files and switching off the WiFi the
    assistant is talking over went through with no gate at all.

THE DESIGN HERE
    The confirmation token is issued by the *interface*, never by the model:

      1. An action calls `request(...)` with a callable that does the real work.
      2. This module hands the UI a banner with CONFIRM / CANCEL and returns
         IMMEDIATELY with a sentence for the model to say out loud.
      3. If — and only if — the user presses CONFIRM, the UI calls `resolve()`,
         which runs the stored callable off the Qt thread.

    Nothing blocks. The model keeps talking while the banner is up, so this
    costs no latency at all; in fact it is cheaper than the old gate, which
    burned two tool round trips (reject, then re-call) on every shutdown.

WHAT BELONGS HERE AND WHAT DOES NOT
    Only genuinely irreversible things. Anything that can be reversed should be
    done at once and pushed onto core/undo.py instead — undo is faster than a
    question, and an assistant that asks before every action is one nobody uses.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

# A pending confirmation is abandoned after this long. Chosen to outlast a
# normal "hang on, let me look at the screen" pause without leaving a live
# shutdown button sitting on the HUD for the rest of the day.
TIMEOUT_SECONDS = 90.0


@dataclass
class _Pending:
    key:     str
    title:   str
    detail:  str
    run:     Callable[[], str]
    at:      float
    on_cancel: Callable[[], None] | None = None
    process_voice: bool = False
    ready: bool = False
    token: str = ""


_pending: Optional[_Pending] = None
_lock = threading.Lock()

# Legacy callbacks accept (title, detail) and (); keyed callbacks receive the
# confirmation token first. The UI marshals both onto the Qt thread.
_show_cb: Optional[Callable[..., None]] = None
_hide_cb: Optional[Callable[..., None]] = None
_log_cb:  Optional[Callable[[str], None]] = None
_keyed_bind = False


def bind(show, hide, log=None, *, keyed: bool = False) -> None:
    """Wire this module to the HUD. Called once from main.py at startup."""
    global _show_cb, _hide_cb, _log_cb, _keyed_bind
    with _lock:
        if _pending is not None:
            raise RuntimeError("Cannot rebind while a confirmation is pending")
        _show_cb, _hide_cb, _log_cb = show, hide, log
        _keyed_bind = keyed is True and callable(show) and callable(hide)


def keyed_interface_active() -> bool:
    with _lock:
        return _keyed_bind and _show_cb is not None and _hide_cb is not None


def is_current(token: str) -> bool:
    with _lock:
        return _keyed_bind and _pending is not None and _pending.token == token


def _log(msg: str) -> None:
    if _log_cb:
        try:
            _log_cb(msg)
        except Exception:
            pass


def request(
    key: str,
    title: str,
    detail: str,
    run: Callable[[], str],
    *,
    on_cancel: Callable[[], None] | None = None,
    process_voice: bool = False,
) -> str:
    """Park an irreversible action behind the on-screen gate.

    Returns the sentence the tool should hand back to the model — phrased as an
    instruction so the assistant asks the user out loud in their own language,
    rather than reading an English string verbatim."""
    global _pending

    if _show_cb is None:
        # No interface bound (headless, or a very early call). Refuse rather
        # than silently performing something irreversible.
        return (f"I cannot confirm '{title}' right now because the interface is "
                f"not available, so I have not done it.")

    with _lock:
        if _pending is not None:
            return "Another confirmation is already pending; nothing was done."
        _pending = _Pending(key=key, title=title, detail=detail,
                            run=run, at=time.monotonic(), on_cancel=on_cancel,
                            process_voice=process_voice, token=uuid.uuid4().hex)
        p = _pending

    try:
        if _keyed_bind:
            _show_cb(p.token, title, detail)
        else:
            _show_cb(title, detail)
    except Exception as e:
        with _lock:
            if _pending is p:
                _pending = None
        return f"Could not ask for confirmation: {e}. Nothing was done."

    with _lock:
        if _pending is p:
            p.ready = True
    _log(f"SYS: Awaiting confirmation — {title}")
    if process_voice and _keyed_bind:
        return (
            f"[CONFIRMATION_PENDING] Confirmation is on screen for: {title}. "
            "Ask the user to confirm or cancel on the HUD or, if available, "
            "speak a brief confirmation or cancellation after a pause. "
            "Do not claim it is done."
        )
    return (
        f"[CONFIRMATION_PENDING] I have put a confirmation on screen for: {title}. "
        f"Say ONE short sentence in the user's own language telling them you need "
        f"them to confirm it on the HUD before you do it. Do not claim it is done."
    )


def process_voice_candidate() -> tuple[str, float] | None:
    """Return the identity of a currently pending process-only confirmation."""
    with _lock:
        p = _pending
        if (
            p is None
            or not _keyed_bind
            or not p.process_voice
            or not p.ready
            or time.monotonic() - p.at > TIMEOUT_SECONDS
        ):
            return None
        return p.token, p.at


def resolve_process_voice(key: str, accepted: bool, captured_at: float) -> bool:
    """Consume only the process request bound to this post-request audio capture."""
    global _pending

    if (
        not isinstance(key, str)
        or not isinstance(captured_at, (int, float))
        or isinstance(captured_at, bool)
        or not isinstance(accepted, bool)
    ):
        return False
    import math
    if not math.isfinite(captured_at):
        return False
    with _lock:
        p = _pending
        if (
            p is None or not _keyed_bind or not p.process_voice or not p.ready
            or not p.key.startswith("process-master-") or p.token != key
            or captured_at <= p.at
            or captured_at > time.monotonic()
            or time.monotonic() - p.at > TIMEOUT_SECONDS
        ):
            return False
        _hide_locked(p)
        _pending = None
    _finish_resolution(p, accepted)
    return True


def resolve(accepted: bool, key: str | None = None) -> None:
    """Called by the UI when the user presses CONFIRM or CANCEL.

    Runs the stored callable on a worker thread — this is invoked from the Qt
    thread, and shutting the machine down from inside a button handler would
    freeze the interface on its way out."""
    global _pending

    with _lock:
        p = _pending
        if p is None or not p.ready or (
            _keyed_bind and (not isinstance(key, str) or key != p.token)
        ):
            return
        _hide_locked(p)
        _pending = None

    _finish_resolution(p, accepted)


def _hide_locked(p: _Pending) -> None:
    if _hide_cb:
        try:
            if _keyed_bind:
                _hide_cb(p.token)
            else:
                _hide_cb()
        except Exception:
            pass


def _finish_resolution(p: Optional[_Pending], accepted: bool) -> None:
    if p is None:
        return

    if time.monotonic() - p.at > TIMEOUT_SECONDS:
        _log(f"SYS: Confirmation expired — {p.title}")
        _notify_cancel(p)
        return

    if not accepted:
        _log(f"SYS: Cancelled — {p.title}")
        _notify_cancel(p)
        return

    def _worker():
        try:
            result = p.run() or "Done."
            _log(f"SYS: Confirmed — {p.title}. {result}")
        except Exception as e:
            _log(f"ERR: {p.title} failed — {e}")

    threading.Thread(target=_worker, daemon=True,
                     name=f"confirm-{p.key}").start()


def _notify_cancel(pending: _Pending) -> None:
    if pending.on_cancel is None:
        return
    try:
        pending.on_cancel()
    except Exception as exc:
        _log(f"ERR: Confirmation cancellation callback failed — {exc}")


def pending_title() -> str:
    """'' when nothing is waiting. Lets an action avoid stacking two banners."""
    with _lock:
        if _pending is None:
            return ""
        if time.monotonic() - _pending.at > TIMEOUT_SECONDS:
            return ""
        return _pending.title
