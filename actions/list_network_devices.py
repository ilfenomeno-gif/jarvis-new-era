"""Report ARP/neighbor counts without disclosing device identifiers."""

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor


def list_network_devices(parameters: dict) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    neighbors = monitor.snapshot()["neighbors"]
    if neighbors.get("status") != "available":
        return "Tabella dei dispositivi vicini non disponibile."
    return (
        f"Dispositivi vicini rilevati: {neighbors.get('devices', 0)} "
        f"({neighbors.get('dynamic', 0)} dinamici, "
        f"{neighbors.get('static', 0)} statici, "
        f"{neighbors.get('other', 0)} altro). "
        "Indirizzi IP e hardware non vengono mostrati."
    )


TOOL = {
    "name": "list_network_devices",
    "description": (
        "Riassume le voci ARP/vicini di rete senza esporre indirizzi IP o "
        "indirizzi hardware dei dispositivi."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": list_network_devices,
}
