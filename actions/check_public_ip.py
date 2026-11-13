"""Check public-IP availability without disclosing the address to the model."""

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor


def check_public_ip(parameters: dict) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    result = monitor.public_ip_metadata()
    if result["status"] != "available":
        return "Verifica dell'IP pubblico non disponibile; nessun indirizzo è stato esposto."
    return (
        "IP pubblico rilevato tramite ipify; famiglia "
        f"{result['address_family']}. L'indirizzo, dato identificativo, non viene "
        "restituito al modello. La verifica esterna usa timeout di 3 secondi e cache di 60."
    )


TOOL = {
    "name": "check_public_ip",
    "description": (
        "Verifica tramite ipify la presenza e la famiglia dell'IP pubblico; "
        "non restituisce né registra l'indirizzo effettivo."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_public_ip,
}
