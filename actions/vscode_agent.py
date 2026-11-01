"""Request a coding suggestion from the GitHub Copilot CLI."""

from __future__ import annotations

import shutil
import subprocess


PLUGIN = {
    "name": "vscode_agent",
    "description": (
        "Ask the GitHub Copilot CLI for a coding suggestion. Provide the prompt "
        "and optionally a working directory. This requests a suggestion; it does "
        "not apply changes to files."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "Coding question or task to send to Copilot.",
            },
            "working_dir": {
                "type": "STRING",
                "description": "Optional working directory for the Copilot CLI.",
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Optional timeout in seconds; defaults to 120.",
            },
        },
        "required": ["prompt"],
    },
}


def _output_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def run(parameters: dict, player=None) -> str:
    prompt = parameters.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return "Specificare un prompt non vuoto per GitHub Copilot."
    prompt = prompt.strip()

    timeout = parameters.get("timeout", 120)
    if type(timeout) is not int or timeout <= 0:
        return "Il timeout deve essere un numero intero positivo."

    working_dir = parameters.get("working_dir")
    if working_dir is not None and (
        not isinstance(working_dir, str) or not working_dir.strip()
    ):
        return "working_dir deve essere un percorso non vuoto."

    if shutil.which("gh") is None:
        return (
            "GitHub CLI ('gh') non trovato nel PATH. Installalo da "
            "https://cli.github.com/, quindi installa l'estensione Copilot "
            "con 'gh extension install github/gh-copilot'."
        )

    try:
        result = subprocess.run(
            ["gh", "copilot", "suggest", prompt],
            cwd=working_dir.strip() if working_dir else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return (
            "GitHub CLI ('gh') non trovato o non avviabile. Installalo da "
            "https://cli.github.com/ e verifica che sia nel PATH."
        )
    except PermissionError as exc:
        return (
            "L'esecuzione di GitHub CLI è stata rifiutata dalla policy di "
            f"sicurezza di JARVIS: {exc}"
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _output_text(exc.stdout)
        stderr = _output_text(exc.stderr)
        details = "\n".join(part for part in (stdout, stderr) if part)
        suffix = f"\n{details}" if details else ""
        return f"Richiesta a Copilot interrotta dopo {timeout} secondi.{suffix}"

    stdout = _output_text(result.stdout)
    stderr = _output_text(result.stderr)
    if result.returncode != 0:
        details = "\n".join(part for part in (stderr, stdout) if part)
        suffix = f"\n{details}" if details else ""
        return (
            f"GitHub Copilot CLI terminato con errore "
            f"(codice {result.returncode}).{suffix}"
        )
    return stdout or "GitHub Copilot CLI non ha restituito suggerimenti."


TOOL = {**PLUGIN, "handler": run}
