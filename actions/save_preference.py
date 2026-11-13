"""Save an explicitly stated communication preference."""
from core.bidirectional_learning import learn, save_explicit_preference


def save_preference(parameters: dict) -> str:
    text = parameters.get("preference")
    if not isinstance(text, str) or not text.strip():
        return "Specifica la preferenza che desideri salvare."
    result = learn(text)
    return result if result is not None else save_explicit_preference(text)


TOOL = {
    "name": "save_preference",
    "description": "Salva una preferenza esplicita espressa dall'utente.",
    "risk_class": "write",
    "parameters": {
        "type": "OBJECT",
        "properties": {"preference": {"type": "STRING", "description": "Preferenza espressa dall'utente."}},
        "required": ["preference"],
    },
    "handler": save_preference,
}
