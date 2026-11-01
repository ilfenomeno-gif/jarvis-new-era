"""
JARVIS plugin: timer Pomodoro.

Gestisce cicli di lavoro/pausa in un thread in background (lo stato vive nel
modulo, che rimane in memoria per tutta la sessione perché plugin_loader lo
importa una sola volta). Ad ogni cambio di fase il plugin annuncia il
cambiamento sia nel log della UI (`player.write_log`, thread-safe: usa un
segnale Qt) sia vocalmente tramite `pyttsx3`, un motore TTS locale
indipendente dalla pipeline audio di Gemini Live — cosi l'annuncio funziona
anche se in quel momento JARVIS non e "in conversazione".
"""

from __future__ import annotations

import threading
import time

PLUGIN = {
    "name": "pomodoro_timer",
    "description": (
        "Avvia, interrompe o mostra lo stato di un timer Pomodoro (cicli di "
        "lavoro e pausa con annuncio vocale ad ogni cambio di fase). Usare "
        "action='start' con work_minutes/break_minutes/long_break_minutes/"
        "cycles opzionali per iniziare; action='stop' per fermare il timer "
        "attivo; action='status' per sapere in che fase si trova e quanto "
        "tempo resta. NON usare 'reminder' per questo: e uno strumento "
        "diverso pensato per promemoria singoli, non per cicli ricorrenti."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Una tra: 'start', 'stop', 'status'."},
            "work_minutes": {"type": "NUMBER", "description": "Durata della fase di lavoro in minuti. Predefinito 25."},
            "break_minutes": {"type": "NUMBER", "description": "Durata della pausa breve in minuti. Predefinito 5."},
            "long_break_minutes": {"type": "NUMBER", "description": "Durata della pausa lunga (dopo 'cycles' cicli) in minuti. Predefinito 15."},
            "cycles": {"type": "NUMBER", "description": "Numero di cicli lavoro+pausa prima della pausa lunga. Predefinito 4."},
        },
        "required": ["action"],
    },
}

_lock = threading.Lock()
_state = {
    "active": False,
    "phase": None,            # 'work' | 'break' | 'long_break'
    "phase_ends_at": 0.0,
    "cycles_completed": 0,
    "cycles_target": 4,
    "work_minutes": 25,
    "break_minutes": 5,
    "long_break_minutes": 15,
    "stop_event": None,
    "thread": None,
}


def _speak(text: str) -> None:
    """Annuncio vocale locale best-effort: non deve mai far crashare il thread del timer."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception:
        pass  # TTS non disponibile su questa macchina: l'annuncio resta solo nel log


def _log(player, text: str) -> None:
    if player:
        try:
            player.write_log(f"JARVIS: {text}")
        except Exception:
            pass


def _run_loop(player, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        with _lock:
            remaining = _state["phase_ends_at"] - time.monotonic()
        if remaining <= 0:
            _advance_phase(player)
        stop_event.wait(timeout=min(1.0, max(0.1, remaining if remaining > 0 else 1.0)))
    with _lock:
        _state["active"] = False


def _phase_minutes(phase: str) -> float:
    if phase == "work":
        return _state["work_minutes"]
    if phase == "break":
        return _state["break_minutes"]
    return _state["long_break_minutes"]


def _advance_phase(player) -> None:
    with _lock:
        prev_phase = _state["phase"]
        if prev_phase == "work":
            _state["cycles_completed"] += 1
            if _state["cycles_completed"] % _state["cycles_target"] == 0:
                next_phase = "long_break"
            else:
                next_phase = "break"
        else:
            next_phase = "work"
        _state["phase"] = next_phase
        _state["phase_ends_at"] = time.monotonic() + _phase_minutes(next_phase) * 60
        cycles_completed = _state["cycles_completed"]

    messages = {
        "work": "Pausa finita. Si torna al lavoro.",
        "break": f"Ciclo {cycles_completed} completato. Inizia una pausa breve.",
        "long_break": f"Ottimo lavoro, {cycles_completed} cicli completati. Inizia una pausa lunga.",
    }
    text = messages[next_phase]
    _log(player, f"Pomodoro: {text}")
    _speak(text)


def _start(params: dict, player) -> str:
    with _lock:
        if _state["active"]:
            return "Sir, c'e già un timer Pomodoro attivo. Lo interrompa prima con action='stop' se vuole cambiarne i parametri."

        try:
            work = float(params.get("work_minutes") or 25)
            brk = float(params.get("break_minutes") or 5)
            long_brk = float(params.get("long_break_minutes") or 15)
            cycles = int(params.get("cycles") or 4)
        except (TypeError, ValueError):
            return "Sir, i parametri del timer devono essere numerici."
        if work <= 0 or brk <= 0 or long_brk <= 0 or cycles <= 0:
            return "Sir, i valori del timer devono essere maggiori di zero."

        _state.update({
            "active": True, "phase": "work",
            "phase_ends_at": time.monotonic() + work * 60,
            "cycles_completed": 0, "cycles_target": cycles,
            "work_minutes": work, "break_minutes": brk, "long_break_minutes": long_brk,
        })
        stop_event = threading.Event()
        _state["stop_event"] = stop_event
        thread = threading.Thread(target=_run_loop, args=(player, stop_event), daemon=True)
        _state["thread"] = thread
        thread.start()

    return (f"Timer Pomodoro avviato: {work:g} minuti di lavoro, {brk:g} di pausa breve, "
            f"pausa lunga di {long_brk:g} minuti ogni {cycles} cicli.")


def _stop() -> str:
    with _lock:
        if not _state["active"]:
            return "Sir, non c'e nessun timer Pomodoro attivo."
        stop_event = _state["stop_event"]
        completed = _state["cycles_completed"]
        _state["active"] = False
    if stop_event:
        stop_event.set()
    return f"Timer Pomodoro interrotto. Cicli completati in questa sessione: {completed}."


def _status() -> str:
    with _lock:
        if not _state["active"]:
            return "Sir, non c'e nessun timer Pomodoro attivo al momento."
        remaining = max(0, _state["phase_ends_at"] - time.monotonic())
        minutes, seconds = divmod(int(remaining), 60)
        phase_label = {"work": "lavoro", "break": "pausa breve", "long_break": "pausa lunga"}[_state["phase"]]
        completed = _state["cycles_completed"]
    return f"Fase attuale: {phase_label}, restano {minutes} minuti e {seconds} secondi. Cicli completati: {completed}."


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    try:
        if action == "start":
            result_text = _start(parameters, player)
        elif action == "stop":
            result_text = _stop()
        elif action == "status":
            result_text = _status()
        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare start, stop o status."
    except Exception as e:
        return f"Sir, il plugin pomodoro_timer ha riscontrato un errore: {e}"

    _log(player, result_text)
    return result_text
