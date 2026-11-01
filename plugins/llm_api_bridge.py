"""
JARVIS plugin: ponte verso un modello linguistico esterno.

Effettua una chiamata HTTP al formato "chat completions" compatibile
OpenAI (funziona quindi con OpenAI stesso, ma anche Groq, OpenRouter,
Together AI, o un proxy locale Ollama/vLLM che esponga la stessa API),
per delegare un compito specifico (scrittura, revisione codice,
ragionamento) a un modello diverso da quello che guida la conversazione
di JARVIS (Gemini Live).

Chiavi richieste in config/api_keys.json:
    LLM_API_KEY    - chiave API del provider scelto
Chiavi opzionali:
    LLM_API_URL    - endpoint chat completions (default: OpenAI)
    LLM_API_MODEL  - nome modello (default: "gpt-4o-mini")
"""

from __future__ import annotations

from config import get_config

PLUGIN = {
    "name": "llm_api_bridge",
    "description": (
        "Invia un prompt testuale a un modello linguistico esterno "
        "(configurabile: OpenAI, Groq, OpenRouter, un proxy locale, ecc.) "
        "e restituisce la risposta generata. Usare quando l'utente chiede "
        "esplicitamente di 'chiedere a un altro modello/IA', per compiti di "
        "scrittura o revisione di codice complessi da delegare, oppure "
        "quando vuole confrontare una risposta con un modello diverso. NON "
        "usare per la normale conversazione: quella la gestisce già JARVIS "
        "stesso senza bisogno di questo strumento."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "Il testo/istruzione da inviare al modello esterno."},
            "system": {"type": "STRING", "description": "Istruzione di sistema opzionale per orientare il modello."},
            "max_tokens": {"type": "NUMBER", "description": "Limite opzionale di token nella risposta."},
            "temperature": {"type": "NUMBER", "description": "Temperatura opzionale (0-2), creatività della risposta."},
        },
        "required": ["prompt"],
    },
}

_DEFAULT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o-mini"
_MAX_SPOKEN_CHARS = 4000


def run(parameters: dict, player=None, session_memory=None) -> str:
    prompt = str(parameters.get("prompt", "")).strip()
    if not prompt:
        return "Sir, deve specificare il prompt da inviare al modello esterno."

    try:
        cfg = get_config()
        api_key = cfg.get("LLM_API_KEY")
        if not api_key:
            return ("Sir, nessuna API LLM esterna e configurata. Aggiunga LLM_API_KEY "
                    "(e opzionalmente LLM_API_URL, LLM_API_MODEL) in config/api_keys.json.")

        url = cfg.get("LLM_API_URL", _DEFAULT_URL)
        model = cfg.get("LLM_API_MODEL", _DEFAULT_MODEL)

        messages = []
        system = str(parameters.get("system", "")).strip()
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages}
        if parameters.get("max_tokens") is not None:
            try:
                payload["max_tokens"] = int(parameters["max_tokens"])
            except (TypeError, ValueError):
                pass
        if parameters.get("temperature") is not None:
            try:
                payload["temperature"] = float(parameters["temperature"])
            except (TypeError, ValueError):
                pass

        import requests
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        if len(content) > _MAX_SPOKEN_CHARS:
            content = content[:_MAX_SPOKEN_CHARS] + "... (risposta troncata)"
        result_text = content

    except KeyError:
        return "Sir, la risposta del modello esterno non ha il formato atteso."
    except Exception as e:
        return f"Sir, la chiamata al modello esterno ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: (llm_api_bridge) {result_text[:200]}")
        except Exception:
            pass
    return result_text
