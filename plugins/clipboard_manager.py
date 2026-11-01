"""
JARVIS plugin: gestione appunti di sistema (clipboard).

Permette di leggere, scrivere o svuotare la clipboard del sistema operativo
tramite `pyperclip` (dipendenza già elencata in requirements.txt). Se il
backend della clipboard non e disponibile sulla macchina (mancano xclip/xsel
su Linux, ecc.), l'errore viene intercettato e restituito come frase parlata
invece di far crashare il plugin.
"""

PLUGIN = {
    "name": "clipboard_manager",
    "description": (
        "Legge, scrive o svuota gli appunti (clipboard) del sistema operativo. "
        "Usare action='read' per leggere cosa e attualmente copiato, "
        "action='write' con 'text' per copiare un testo negli appunti, "
        "oppure action='clear' per svuotarli. NON usare per la cronologia "
        "appunti (non viene mantenuta) o per file/immagini, solo testo."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Una tra: 'read', 'write', 'clear'.",
            },
            "text": {
                "type": "STRING",
                "description": "Il testo da copiare negli appunti. Richiesto solo se action='write'.",
            },
        },
        "required": ["action"],
    },
}

_MAX_SPOKEN_CHARS = 400


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    text = parameters.get("text", "")

    try:
        import pyperclip
    except ImportError:
        return ("Sir, il modulo pyperclip non e installato. Eseguire "
                "'pip install pyperclip' per abilitare questo plugin.")

    try:
        if action == "read":
            content = pyperclip.paste()
            if not content:
                result_text = "Gli appunti sono attualmente vuoti."
            elif len(content) > _MAX_SPOKEN_CHARS:
                result_text = (f"Gli appunti contengono {len(content)} caratteri, "
                                f"inizio: {content[:_MAX_SPOKEN_CHARS]}...")
            else:
                result_text = f"Gli appunti contengono: {content}"

        elif action == "write":
            if not isinstance(text, str) or not text.strip():
                return "Sir, deve specificare il testo da copiare negli appunti."
            pyperclip.copy(text)
            result_text = "Testo copiato negli appunti."

        elif action == "clear":
            pyperclip.copy("")
            result_text = "Appunti svuotati."

        else:
            return f"Sir, azione '{action}' non riconosciuta. Usare read, write o clear."

    except pyperclip.PyperclipException as e:
        return (f"Sir, non riesco ad accedere agli appunti di sistema: {e}. "
                "Su Linux potrebbe essere necessario installare xclip o xsel.")
    except Exception as e:
        return f"Sir, il plugin clipboard_manager ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
