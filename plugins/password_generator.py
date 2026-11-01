"""
JARVIS plugin: generatore di password sicure.

Usa il modulo `secrets` della standard library (crittograficamente sicuro,
NON `random`) per generare password casuali. La password generata viene
anche copiata negli appunti quando possibile, cosi l'utente non deve
ricordarla o farla ripetere ad alta voce da JARVIS.
"""

from __future__ import annotations

import secrets
import string

PLUGIN = {
    "name": "password_generator",
    "description": (
        "Genera una password casuale sicura di una lunghezza specificata e "
        "la copia automaticamente negli appunti. Usare quando l'utente chiede "
        "di generare, creare o suggerire una password nuova. NON restituisce "
        "password memorizzate in precedenza: ne crea sempre una nuova."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "length": {
                "type": "NUMBER",
                "description": "Lunghezza desiderata della password. Predefinito 16 se non specificato.",
            },
            "include_symbols": {
                "type": "BOOLEAN",
                "description": "Se includere simboli speciali (!@#$%...). Predefinito true.",
            },
        },
        "required": [],
    },
}

_MIN_LEN = 6
_MAX_LEN = 128
_DEFAULT_LEN = 16
_AMBIGUOUS = set("Il1O0")  # esclusi per evitare confusione quando la password viene letta/scritta a mano


def _charset(include_symbols: bool) -> str:
    letters = "".join(c for c in string.ascii_letters if c not in _AMBIGUOUS)
    digits = "".join(c for c in string.digits if c not in _AMBIGUOUS)
    charset = letters + digits
    if include_symbols:
        charset += "!@#$%^&*()-_=+"
    return charset


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        length = int(parameters.get("length", _DEFAULT_LEN) or _DEFAULT_LEN)
    except (TypeError, ValueError):
        length = _DEFAULT_LEN
    length = max(_MIN_LEN, min(length, _MAX_LEN))

    include_symbols = parameters.get("include_symbols", True)
    if isinstance(include_symbols, str):
        include_symbols = include_symbols.strip().lower() not in ("false", "no", "0", "")

    try:
        charset = _charset(bool(include_symbols))
        password = "".join(secrets.choice(charset) for _ in range(length))
    except Exception as e:
        return f"Sir, il generatore di password ha riscontrato un errore: {e}"

    copied = False
    try:
        import pyperclip
        pyperclip.copy(password)
        copied = True
    except Exception:
        copied = False

    if copied:
        result_text = (f"Ho generato una password di {length} caratteri e l'ho copiata "
                        f"negli appunti: {password}")
    else:
        result_text = (f"Ho generato una password di {length} caratteri (non sono riuscito "
                        f"a copiarla negli appunti): {password}")

    if player:
        try:
            player.write_log(f"JARVIS: password generata ({length} caratteri, copiata: {copied})")
        except Exception:
            pass
    return result_text
