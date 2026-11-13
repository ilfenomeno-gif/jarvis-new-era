"""Report listener counts and PID coverage, not endpoint identifiers."""

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor


def list_open_ports(parameters: dict) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    result = monitor.snapshot()
    if result.get("socket_status") != "available":
        return "Socket locali non disponibili; potrebbe essere necessario elevare i permessi."
    return (
        f"Socket in ascolto: {result['listening_sockets']}; "
        f"associati a indirizzi di rete: {result['network_bound_listeners']}; "
        f"con PID disponibile: {result['listeners_with_pid']}. "
        "Numeri di porta, indirizzi e PID sono omessi per privacy."
    )


TOOL = {
    "name": "list_open_ports",
    "description": (
        "Riassume i socket locali in ascolto e la copertura PID senza restituire "
        "numeri di porta, indirizzi o PID."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": list_open_ports,
}
