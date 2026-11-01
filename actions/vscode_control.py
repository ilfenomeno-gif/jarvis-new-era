"""Open Visual Studio Code or a file/folder in it."""

from __future__ import annotations

import os
import subprocess

from core.guardrails import validate_command


PLUGIN = {
    "name": "vscode_control",
    "description": (
        "Open Visual Studio Code or a folder/file in it, open a PowerShell "
        "terminal in a working directory, or run an allowed command and return "
        "its output. Commands are subject to JARVIS's security policy."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "VS Code operation to perform.",
                "enum": [
                    "open_app",
                    "open_folder",
                    "open_file",
                    "open_terminal",
                    "run_task",
                ],
            },
            "path": {
                "type": "STRING",
                "description": "Path to the folder or file to open.",
            },
            "working_dir": {
                "type": "STRING",
                "description": "Working directory for open_terminal or run_task.",
            },
            "command": {
                "type": "ARRAY",
                "description": (
                    "Executable and arguments as separate strings, for example "
                    "['python', '-m', 'pytest', 'tests', '-q']. Shell syntax is not supported."
                ),
                "items": {"type": "STRING"},
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Optional run_task timeout in seconds; defaults to 60.",
            },
        },
        "required": ["action"],
    },
}


def _output_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _run_task(parameters: dict) -> str:
    raw_command = parameters.get("command")
    if (
        not isinstance(raw_command, list)
        or not raw_command
        or not all(isinstance(part, str) for part in raw_command)
        or not raw_command[0].strip()
    ):
        return "Specificare command come lista non vuota di argomenti stringa."

    timeout = parameters.get("timeout", 60)
    if type(timeout) is not int or timeout <= 0:
        return "Il timeout deve essere un numero intero positivo."

    working_dir = parameters.get("working_dir")
    if working_dir is not None and (
        not isinstance(working_dir, str) or not working_dir.strip()
    ):
        return "working_dir deve essere un percorso non vuoto."

    command = [raw_command[0].strip(), *raw_command[1:]]
    try:
        validate_command(command)
        result = subprocess.run(
            command,
            cwd=working_dir or None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except PermissionError as exc:
        return f"Comando rifiutato dalla policy di sicurezza: {exc}"
    except FileNotFoundError:
        return f"Comando o directory di lavoro non trovati: {command[0]}"
    except subprocess.TimeoutExpired as exc:
        stdout = _output_text(exc.stdout)
        stderr = _output_text(exc.stderr)
        details = "\n".join(part for part in (stdout, stderr) if part)
        suffix = f"\n{details}" if details else ""
        return f"Comando interrotto: timeout dopo {timeout} secondi.{suffix}"

    stdout = _output_text(result.stdout)
    stderr = _output_text(result.stderr)
    status = "completato" if result.returncode == 0 else "terminato con errore"
    output = "\n".join(part for part in (stdout, stderr) if part)
    suffix = f"\n{output}" if output else "\nNessun output."
    return f"Comando {status} (codice {result.returncode}).{suffix}"


def run(parameters: dict, player=None) -> str:
    action = str(parameters.get("action", "")).strip().casefold()
    if action == "run_task":
        return _run_task(parameters)

    if action == "open_terminal":
        if os.name != "nt":
            return "L'apertura del terminale PowerShell è supportata solo su Windows."
        working_dir = parameters.get("working_dir")
        if working_dir is not None and (
            not isinstance(working_dir, str) or not working_dir.strip()
        ):
            return "working_dir deve essere un percorso non vuoto."
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit"],
                cwd=working_dir or None,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except FileNotFoundError:
            return "PowerShell o la directory di lavoro non sono stati trovati."
        return "Nuova finestra PowerShell aperta."

    if action not in {"open_app", "open_folder", "open_file"}:
        return (
            "Azione VS Code non valida. Usare open_app, open_folder, open_file, "
            "open_terminal o run_task."
        )

    command = ["code"]
    if action != "open_app":
        path = str(parameters.get("path", "")).strip()
        if not path:
            return f"Specificare il percorso da aprire con {action}."
        command.append(path)

    try:
        subprocess.Popen(command, shell=(os.name == "nt"))
    except FileNotFoundError:
        return (
            "Visual Studio Code non trovato: verificare che sia installato "
            "e che il comando 'code' sia disponibile nel PATH."
        )

    if action == "open_app":
        return "Visual Studio Code avviato."
    return f"Richiesta apertura in Visual Studio Code: {command[1]}"


# Built-in actions are discovered through TOOL by core.action_loader.
TOOL = {**PLUGIN, "handler": run}
