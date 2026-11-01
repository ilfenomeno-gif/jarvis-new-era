"""
JARVIS plugin: generatore di codici QR.

Genera un'immagine PNG con il codice QR corrispondente al testo/URL fornito,
usando il pacchetto `qrcode[pil]` già presente in requirements.txt. Il
percorso di destinazione viene sempre validato con lo stesso guardrail dei
tool core (`resolve_safe_path`) prima di scrivere su disco.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.guardrails import resolve_safe_path

PLUGIN = {
    "name": "qr_code_generator",
    "description": (
        "Genera un'immagine PNG con un codice QR a partire da un testo o un "
        "URL e la salva su disco. Usare quando l'utente chiede di creare o "
        "generare un codice QR. Il percorso di output e opzionale: se omesso "
        "viene salvato in una cartella 'JARVIS_Output' nella home dell'utente."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "content": {
                "type": "STRING",
                "description": "Il testo o URL da codificare nel codice QR.",
            },
            "output_path": {
                "type": "STRING",
                "description": "Percorso file .png di destinazione, opzionale.",
            },
        },
        "required": ["content"],
    },
}

_DEFAULT_DIR = Path.home() / "JARVIS_Output"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _default_filename(content: str) -> str:
    slug = _SAFE_NAME_RE.sub("_", content.strip())[:40].strip("_") or "qrcode"
    return f"qr_{slug}.png"


def run(parameters: dict, player=None, session_memory=None) -> str:
    content = str(parameters.get("content", "")).strip()
    if not content:
        return "Sir, deve specificare il testo o l'URL da codificare nel QR."

    raw_output = parameters.get("output_path")

    try:
        import qrcode
    except ImportError:
        return ("Sir, il modulo qrcode non e installato. Eseguire "
                "'pip install qrcode[pil]' per abilitare questo plugin.")

    try:
        if raw_output:
            dest = resolve_safe_path(raw_output)
            if dest.is_dir() or not dest.suffix:
                dest = dest / _default_filename(content)
        else:
            dest = resolve_safe_path(_DEFAULT_DIR / _default_filename(content))

        dest.parent.mkdir(parents=True, exist_ok=True)

        img = qrcode.make(content)
        img.save(dest)
    except PermissionError as e:
        return f"Sir, non posso scrivere in quel percorso: {e}"
    except Exception as e:
        return f"Sir, il generatore di codici QR ha riscontrato un errore: {e}"

    result_text = f"Codice QR generato e salvato in {dest}"
    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
