"""Launch a small set of Windows applications with a fixed start command."""
from __future__ import annotations

import os
import re
import subprocess

_COMMANDS = {
    "notepad": "start notepad",
    "calc": "start calc",
    "chrome": "start chrome",
    "mspaint": "start mspaint",
    "explorer": "start explorer",
}


def validated_command(command: object) -> str:
    if not isinstance(command, str) or not re.fullmatch(
        r"start[ \t]+(?:notepad|calc|chrome|mspaint|explorer)",
        command.strip(), flags=re.IGNORECASE,
    ):
        raise ValueError(
            "Comando non consentito. Sono ammessi solo start notepad, calc, chrome, mspaint o explorer, senza argomenti."
        )
    return _COMMANDS[command.strip().split()[1].casefold()]


def open_app_via_terminal(parameters: dict | None = None) -> str:
    values = parameters or {}
    command = validated_command(values.get("command"))
    if values.get("confirmed") is not True:
        return "Serve una conferma esplicita per avviare il comando."
    if os.name != "nt":
        raise RuntimeError("L'apertura tramite terminale è supportata solo su Windows.")
    subprocess.Popen(command, shell=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Ho richiesto l'avvio tramite terminale: {command}. L'apertura della finestra non è verificata."


TOOL = {
    "name": "open_app_via_terminal",
    "description": (
        "Usa solo quando l'utente chiede esplicitamente di aprire un'app tramite "
        "terminale. Richiede conferma separata; command deve essere esattamente "
        "start notepad, start calc, start chrome, start mspaint o start explorer. "
        "Non sono ammessi argomenti o operatori shell."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"command": {"type": "STRING"}},
        "required": ["command"],
    },
    "risk_class": "destructive",
    "handler": open_app_via_terminal,
}
