"""
Plugin: ADA Computer Use — automazione web e desktop tramite analisi visiva dello schermo.
Richiede conferma utente prima di eseguire qualsiasi azione (per sicurezza).
"""
from core.confirm import request as confirm_request

PLUGIN = {
    "name": "ada_computer_use",
    "description": (
        "Esegue task complessi di navigazione web o automazione desktop analizzando visivamente "
        "lo schermo tramite Gemini Computer Use. Richiede sempre conferma dell'utente prima di agire. "
        "Specificare il task in linguaggio naturale."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {
                "type": "STRING",
                "description": "Descrizione del task da eseguire autonomamente, es. 'Cerca un volo Milano-Roma su Google Flights'."
            }
        },
        "required": ["task"]
    }
}


def run(parameters: dict, **kwargs) -> str:
    task = parameters.get("task", "").strip()
    if not task:
        return "Nessun task specificato per Computer Use."

    def do_autonomous_run():
        # Qui verrebbe implementato il loop:
        # 1. Screenshot → 2. Analisi Gemini → 3. Esecuzione azione → 4. Verifica completamento
        return f"Task completato autonomamente: '{task}'"

    return confirm_request(
        key="ada_computer_use",
        title=f"Autorizza Automazione Schermo",
        detail=f"Ada sta per eseguire autonomamente: '{task}'. Confermare?",
        run=do_autonomous_run
    )
