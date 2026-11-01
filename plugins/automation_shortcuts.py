"""
JARVIS plugin: shortcut/automazioni personalizzate multi-step.

Non duplica 'open_app' (apertura di una singola applicazione: usare quello
per casi semplici): questo plugin salva SEQUENZE di passi con un nome, per
lanciarle con un solo comando vocale (es. "esegui la routine lavoro" ->
apre due URL e un'app in un colpo).

Ogni passo e uno di:
  {"type": "url",     "value": "https://..."}      -> apre nel browser predefinito
  {"type": "app",     "value": "nome applicazione"} -> riusa actions.open_app
  {"type": "command", "value": ["eseguibile", "arg1", ...]}
        -> eseguito con subprocess, filtrato dalla stessa whitelist di
           sicurezza (core/guardrails.py) usata da tutti i comandi shell di
           JARVIS: un eseguibile non in whitelist viene rifiutato con un
           messaggio chiaro, non eseguito silenziosamente.

Per aprire una singola app generica preferire sempre 'open_app' (core tool):
questo plugin ha senso quando servono PIU passi salvati insieme.
"""

from __future__ import annotations

import webbrowser

from core.guardrails import validate_command
from plugins._plugin_utils import MEMORY_DIR, load_json, atomic_write_json

PLUGIN = {
    "name": "automation_shortcuts",
    "description": (
        "Salva ed esegue sequenze personalizzate di passi (apertura URL, "
        "apertura app, comandi di sistema in whitelist) sotto un nome, per "
        "lanciare intere routine con un solo comando vocale. Usare "
        "action='save' con 'name' e 'steps' (lista di passi tipo url/app/"
        "command) per creare o aggiornare uno shortcut; action='run' con "
        "'name' per eseguirlo; action='list' per vedere gli shortcut "
        "salvati; action='delete' con 'name' per eliminarne uno. Per "
        "aprire una singola applicazione generica usare invece 'open_app'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Una tra: 'save', 'run', 'list', 'delete'."},
            "name": {"type": "STRING", "description": "Nome dello shortcut. Richiesto per save/run/delete."},
            "steps": {
                "type": "ARRAY",
                "description": (
                    "Lista di passi per action='save'. Ogni passo e un oggetto con "
                    "'type' ('url'|'app'|'command') e 'value' (stringa per url/app, "
                    "lista di stringhe per command)."
                ),
                "items": {"type": "OBJECT"},
            },
        },
        "required": ["action"],
    },
}

_STORE_PATH = MEMORY_DIR / "shortcuts.json"
_VALID_TYPES = {"url", "app", "command"}


def _load_all() -> dict:
    data = load_json(_STORE_PATH, {})
    return data if isinstance(data, dict) else {}


def _validate_steps(steps) -> list[dict]:
    if not isinstance(steps, list) or not steps:
        raise ValueError("'steps' deve essere una lista non vuota di passi.")
    cleaned = []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or "type" not in step or "value" not in step:
            raise ValueError(f"passo {i} malformato: deve avere 'type' e 'value'.")
        step_type = str(step["type"]).strip().lower()
        if step_type not in _VALID_TYPES:
            raise ValueError(f"passo {i}: type '{step_type}' non valido (usare url, app o command).")
        value = step["value"]
        if step_type == "command" and not (isinstance(value, list) and all(isinstance(p, str) for p in value) and value):
            raise ValueError(f"passo {i}: per 'command', 'value' deve essere una lista non vuota di stringhe.")
        if step_type in ("url", "app") and not (isinstance(value, str) and value.strip()):
            raise ValueError(f"passo {i}: per '{step_type}', 'value' deve essere una stringa non vuota.")
        cleaned.append({"type": step_type, "value": value})
    return cleaned


def _run_step(step: dict, player) -> str:
    step_type, value = step["type"], step["value"]

    if step_type == "url":
        opened = webbrowser.open(value)
        return f"URL aperto: {value}" if opened else f"Non sono riuscito ad aprire l'URL: {value}"

    if step_type == "app":
        from actions.open_app import open_app
        return open_app({"app_name": value}, player=player)

    if step_type == "command":
        import subprocess
        validate_command(value)  # solleva PermissionError se l'eseguibile non e in whitelist
        subprocess.run(value, timeout=30, check=False)
        return f"Comando eseguito: {' '.join(value)}"

    return f"Tipo di passo non gestito: {step_type}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()

    try:
        shortcuts = _load_all()

        if action == "save":
            name = str(parameters.get("name", "")).strip()
            if not name:
                return "Sir, deve specificare il nome dello shortcut."
            steps = _validate_steps(parameters.get("steps"))
            shortcuts[name] = steps
            atomic_write_json(_STORE_PATH, shortcuts)
            result_text = f"Shortcut '{name}' salvato con {len(steps)} passi."

        elif action == "run":
            name = str(parameters.get("name", "")).strip()
            if not name:
                return "Sir, deve specificare quale shortcut eseguire."
            steps = shortcuts.get(name)
            if steps is None:
                return f"Sir, non esiste nessuno shortcut chiamato '{name}'."
            outcomes = []
            for i, step in enumerate(steps, start=1):
                try:
                    outcomes.append(_run_step(step, player))
                except PermissionError as e:
                    outcomes.append(f"Passo {i} bloccato dalla policy di sicurezza: {e}")
                except Exception as e:
                    outcomes.append(f"Passo {i} fallito: {e}")
            result_text = f"Shortcut '{name}' eseguito. " + " | ".join(outcomes)

        elif action == "list":
            if not shortcuts:
                result_text = "Non ha nessuno shortcut salvato al momento."
            else:
                lines = [f"{n} ({len(s)} passi)" for n, s in shortcuts.items()]
                result_text = "Shortcut salvati: " + "; ".join(lines)

        elif action == "delete":
            name = str(parameters.get("name", "")).strip()
            if name not in shortcuts:
                return f"Sir, non esiste nessuno shortcut chiamato '{name}'."
            del shortcuts[name]
            atomic_write_json(_STORE_PATH, shortcuts)
            result_text = f"Shortcut '{name}' eliminato."

        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare save, run, list o delete."

    except ValueError as e:
        return f"Sir, {e}"
    except Exception as e:
        return f"Sir, il plugin automation_shortcuts ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
