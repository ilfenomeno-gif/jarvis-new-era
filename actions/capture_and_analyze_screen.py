"""Capture the visible desktop and return a concise Gemini vision analysis."""

from __future__ import annotations

import faulthandler
import logging
import multiprocessing
import re
import threading
import time
from contextlib import contextmanager

VISION_START_MESSAGE = "Sto analizzando lo schermo, Signore..."
VISION_PROGRESS_MESSAGE = "L'analisi dello schermo sta impiegando più del previsto..."
VISION_PROGRESS_SECONDS = 20.0
VISION_PROCESS_TIMEOUT_SECONDS = 150.0
VISION_REQUEST_TIMEOUT_MS = 20_000
VISION_FALLBACK_TIMEOUT_MS = 45_000
VISION_COOLDOWN_SECONDS = 10.0
VISION_REDUCED_WIDTH = 800
GEMMA_VISION_MODEL = "gemma-4-26b-a4b-it"
VISION_EMPTY_MESSAGE = "Gemini ha analizzato ma non ha prodotto testo. Riprova."
VISION_QUOTA_MESSAGE = (
    "Signore, ho esaurito le mie richieste per l'analisi visiva. "
    "Riprovo tra qualche minuto."
)
VISION_OVERLOAD_MESSAGE = "Il server di visione è sovraccarico, Signore. Riprovo più tardi."
VISION_INTERNAL_MESSAGE = (
    "Signore, il server di visione ha avuto un problema interno. Riprovo tra poco."
)
VISION_COOLDOWN_MESSAGE = (
    "Signore, ho appena analizzato lo schermo. Aspetti qualche secondo prima di chiedermelo di nuovo."
)
_vision_state_lock = threading.Lock()
_vision_in_progress = False
_vision_finished_at: float | None = None
_vision_internal_errors = 0

VISION_SLOW_MESSAGE = (
    "Non riesco ad analizzare lo schermo in questo momento, Signore. "
    "Il server di visione è lento. Riprovo tra poco?"
)


def plain_speech_text(text: object) -> str:
    """Strip markdown so the analysis reads naturally in chat and TTS."""
    cleaned = str(text or "")
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]*[-*+•][ \t]+", "", cleaned)
    cleaned = re.sub(r"(?<!\w)_{1,2}(.+?)_{1,2}(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"[*`]+", "", cleaned)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in cleaned.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    result = lines[0]
    for line in lines[1:]:
        if result[-1] not in ".,;:!?…":
            result += "."
        result += " " + line
    return result


def extract_vision_text(response) -> str:
    """Prefer final text; use the last nonempty thought if no final text exists."""
    try:
        candidates = getattr(response, "candidates", None)
        if candidates is None:
            # Lightweight response adapters may expose only the text property.
            text = getattr(response, "text", None)
            if text is not None and not isinstance(text, str):
                raise TypeError("Il testo della risposta non è una stringa.")
            result = plain_speech_text(text)
        else:
            parts = None
            if candidates:
                content = candidates[0].content
                parts = content.parts if content is not None else None
            text_parts = []
            last_thought = ""
            for part in parts or ():
                text = getattr(part, "text", None)
                if text is None:
                    continue
                if not isinstance(text, str):
                    raise TypeError("Una parte testuale non è una stringa.")
                if getattr(part, "thought", False):
                    if plain_speech_text(text):
                        last_thought = text
                else:
                    text_parts.append(text)
            result = plain_speech_text("".join(text_parts))
            if not result and last_thought:
                logging.getLogger(__name__).warning(
                    "Vision returned only thought text; using it as an unverified fallback."
                )
                return plain_speech_text(last_thought)
        print(f"[Vision] Risposta: {result}")
        return result
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        logging.getLogger(__name__).exception("Invalid Gemini Vision response format")
        raise RuntimeError("Formato della risposta Gemini Vision non riconosciuto.") from exc


@contextmanager
def _vision_progress(player):
    if player is None:
        yield
        return

    player.write_log(VISION_START_MESSAGE)
    lock = threading.Lock()
    finished = False

    def report_slow():
        with lock:
            if not finished:
                player.write_log(VISION_PROGRESS_MESSAGE)

    timer = threading.Timer(VISION_PROGRESS_SECONDS, report_slow)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        with lock:
            finished = True
            timer.cancel()


def capture_and_analyze_screen(
    parameters: dict | None = None,
    player=None,
) -> str:
    """Capture the primary display or active window and analyze it with Vision."""
    global _vision_in_progress, _vision_finished_at, _vision_internal_errors
    with _vision_state_lock:
        if _vision_in_progress or (
            _vision_finished_at is not None
            and time.monotonic() - _vision_finished_at < VISION_COOLDOWN_SECONDS
        ):
            return VISION_COOLDOWN_MESSAGE
        _vision_in_progress = True
        reduced = _vision_internal_errors >= 2
    result = None
    try:
        values = dict(parameters or {})
        values["_vision_max_width"] = VISION_REDUCED_WIDTH if reduced else 1024
        with _vision_progress(player):
            try:
                result = _run_isolated(values, player)
            except TimeoutError as exc:
                logging.getLogger(__name__).warning("Vision process timed out: %s", exc)
                result = VISION_SLOW_MESSAGE
            return result
    finally:
        with _vision_state_lock:
            _vision_internal_errors = (
                _vision_internal_errors + 1 if result == VISION_INTERNAL_MESSAGE else 0
            )
            _vision_finished_at = time.monotonic()
            _vision_in_progress = False


def _vision_worker(connection, parameters):
    class ProcessPlayer:
        def write_log(self, message):
            connection.send(("progress", message))

    diagnostic_armed = False
    try:
        try:
            faulthandler.dump_traceback_later(55, repeat=False)
            diagnostic_armed = True
        except (OSError, RuntimeError, ValueError) as exc:
            connection.send(("progress", f"[Vision] Traceback watchdog non disponibile: {exc}"))
        result = _capture_and_analyze_screen(parameters, ProcessPlayer())
        connection.send(("result", result))
    except Exception as exc:
        connection.send(("error", str(exc) or type(exc).__name__))
    finally:
        if diagnostic_armed:
            faulthandler.cancel_dump_traceback_later()
        connection.close()


def _run_isolated(parameters, player, *, worker=None, timeout=None):
    ctx = multiprocessing.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=worker or _vision_worker, args=(send, parameters),
                          name="jarvis-vision-process", daemon=True)
    started = False
    try:
        process.start()
        started = True
        send.close()
        deadline = time.monotonic() + (
            VISION_PROCESS_TIMEOUT_SECONDS if timeout is None else timeout
        )
        while True:
            is_cancelled = getattr(player, "vision_cancelled", None)
            if callable(is_cancelled) and is_cancelled():
                raise RuntimeError("Analisi dello schermo annullata.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timeout del processo di analisi dello schermo.")
            if receive.poll(min(0.05, remaining)):
                try:
                    kind, message = receive.recv()
                except EOFError as exc:
                    raise RuntimeError("Il processo Vision si è chiuso senza risposta.") from exc
                if kind == "progress":
                    if player is not None:
                        player.write_log(message)
                elif kind == "result":
                    return message
                elif kind == "error":
                    raise RuntimeError(message)
                else:
                    raise RuntimeError(f"Risposta Vision inattesa: {kind!r}")
            elif not process.is_alive():
                raise RuntimeError(
                    f"Il processo Vision è terminato senza risposta (exit code {process.exitcode})."
                )
    finally:
        send.close()
        receive.close()
        if started:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
            else:
                process.join(timeout=2)
            if process.is_alive():
                logging.getLogger(__name__).error("Could not terminate Vision process %s", process.pid)
            else:
                process.close()


def _capture_and_analyze_screen(parameters: dict | None, player) -> str:
    from google import genai
    from google.genai import types
    import httpx

    from actions.screen_processor import (
        GEMINI_VISION_MODEL,
        _capture_vision_screen,
        _get_api_key,
        _resize_vision_image,
    )

    values = parameters or {}
    capture_mode = values.get("capture_mode", "screen")
    if capture_mode not in ("screen", "active_window"):
        raise ValueError("capture_mode deve essere 'screen' o 'active_window'.")
    question = str(values.get("question") or "").strip()
    if not question:
        question = (
            "Descrivi cosa è visibile sullo schermo. Leggi il testo importante "
            "se presente e riassumi la pagina o l'immagine in modo conciso, "
            "adatto a una risposta vocale: massimo quattro frasi in prosa, senza elenchi né markdown. Non inventare dettagli illeggibili. "
            "Rispondi in italiano."
        )
    else:
        question = (
            "Analizza lo schermo e rispondi in modo conciso e adatto alla voce, "
            "in prosa (massimo quattro frasi, senza elenchi né markdown), "
            "nella stessa lingua della richiesta. Non inventare dettagli "
            "illeggibili. Richiesta: "
            + question
        )
    question = (
        "Descrivi con precisione la posizione degli elementi (sinistra, destra, centro). "
        "Identifica correttamente le finestre del terminale, del browser e "
        "dell'interfaccia utente. "
        + question[:1200]
    )

    image_bytes, mime_type = _capture_vision_screen(capture_mode)
    if not image_bytes:
        raise RuntimeError("La cattura dello schermo non ha prodotto un'immagine.")
    if mime_type not in {"image/jpeg", "image/png"}:
        raise RuntimeError(
            f"Formato immagine non supportato per Gemini Vision: {mime_type!r}."
        )
    image_bytes, mime_type = _resize_vision_image(
        image_bytes, max_width=values.get("_vision_max_width", 1024)
    )
    if player is not None:
        player.write_log(
            f"[vision] Schermata catturata ({len(image_bytes):,} byte); "
            "invio a Gemini Vision."
        )

    api_key = _get_api_key()
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=VISION_REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    fallback_client = None
    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        question,
    ]
    primary_config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=2000,
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    )
    fallback_config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=2000)
    attempt = 0
    is_fallback = False
    while True:
        model = GEMMA_VISION_MODEL if is_fallback else GEMINI_VISION_MODEL
        try:
            if is_fallback and fallback_client is None:
                fallback_client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(
                        timeout=VISION_FALLBACK_TIMEOUT_MS,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
            active_client = fallback_client if is_fallback else client
            response = active_client.models.generate_content(
                model=model,
                contents=contents,
                config=fallback_config if is_fallback else primary_config,
            )
            break
        except Exception as exc:
            error_response = getattr(exc, "response", None)
            status = (
                getattr(exc, "status_code", None)
                or getattr(error_response, "status_code", None)
                or getattr(exc, "code", None)
            )
            details = str(exc).replace(api_key, "[redacted]").strip()
            if status and str(status) not in details:
                details = f"HTTP {status}: {details}"
            if not details:
                details = type(exc).__name__
            message = (
                f"Errore API Visione ({model}): {details[:400]}"
                if is_fallback else f"Errore API Visione: {details[:400]}"
            )
            logging.getLogger(__name__).error(
                "Gemini Vision model %s attempt %d failed (%s): %s",
                model,
                1 if is_fallback else attempt + 1,
                type(exc).__name__,
                message,
            )
            print(f"[Vision] {message}")
            error_details = getattr(exc, "details", None)
            internal_error = (
                str(status) in {"500", "INTERNAL"}
                or getattr(exc, "status", None) == "INTERNAL"
                or (isinstance(error_details, dict)
                    and error_details.get("status") == "INTERNAL")
                or (status is None and (
                    bool(re.search(r"\bINTERNAL\b", details.upper()))
                    or bool(re.search(r"\b500\b", details))
                ))
            )
            if internal_error:
                return VISION_INTERNAL_MESSAGE
            quota_exhausted = (
                str(status) in {"429", "RESOURCE_EXHAUSTED"}
                or getattr(exc, "status", None) == "RESOURCE_EXHAUSTED"
                or (isinstance(error_details, dict)
                    and error_details.get("status") == "RESOURCE_EXHAUSTED")
                or (status is None and (
                    "RESOURCE_EXHAUSTED" in details.upper()
                    or bool(re.search(r"\b429\b", details))
                ))
            )
            if quota_exhausted:
                if is_fallback:
                    return VISION_QUOTA_MESSAGE
                print(f"[Vision] Quota modello principale esaurita; provo {GEMMA_VISION_MODEL}.")
                is_fallback = True
                continue
            unavailable = (str(status) in {"503", "UNAVAILABLE"}
                           or getattr(exc, "status", None) == "UNAVAILABLE"
                           or (isinstance(error_details, dict)
                               and error_details.get("status") == "UNAVAILABLE")
                           or (status is None and (
                               bool(re.search(r"\bUNAVAILABLE\b", details))
                               or bool(re.search(r"\b503\b", details)))))
            timed_out = (
                str(status) in {"504", "DEADLINE_EXCEEDED"}
                or getattr(exc, "status", None) == "DEADLINE_EXCEEDED"
                or (isinstance(error_details, dict)
                    and error_details.get("status") == "DEADLINE_EXCEEDED")
                or (status is None and (
                    "DEADLINE_EXCEEDED" in details.upper()
                    or bool(re.search(r"\b504\b", details))
                ))
                or isinstance(exc, (TimeoutError, httpx.TimeoutException))
            )
            if is_fallback:
                if unavailable:
                    return VISION_OVERLOAD_MESSAGE
                if timed_out:
                    return VISION_SLOW_MESSAGE
                raise RuntimeError(message) from exc
            transient = unavailable or timed_out
            if transient and attempt < 2:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            if unavailable:
                print(f"[Vision] Modello principale non disponibile; provo {GEMMA_VISION_MODEL}.")
                time.sleep(4)
                is_fallback = True
                continue
            if transient:
                return VISION_SLOW_MESSAGE
            raise RuntimeError(message) from exc
    result = extract_vision_text(response)
    if not result:
        logging.getLogger(__name__).warning("Vision model %s returned no visible text", model)
        return VISION_EMPTY_MESSAGE
    return result


TOOL = {
    "name": "capture_and_analyze_screen",
    "description": (
        "Captures the user's primary screen or, when explicitly requested, the active "
        "window, and sends the image to Gemini Vision "
        "for analysis. Use when asked what is visible, to read or describe a page, "
        "or when asked to use Google Lens. This is a read-only action and must "
        "run immediately without asking for confirmation. The response is concise "
        "and suitable for speaking aloud."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {
                "type": "STRING",
                "description": (
                    "What to inspect, read, or describe in the captured screen."
                ),
            },
            "capture_mode": {
                "type": "STRING",
                "enum": ["screen", "active_window"],
                "description": (
                    "Use active_window only when the user explicitly requests the "
                    "active or foreground window; otherwise use screen."
                ),
            },
        },
        "required": [],
    },
    "risk_class": "read",
    "handler": capture_and_analyze_screen,
}
