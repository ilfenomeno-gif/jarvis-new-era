"""Report aggregate Windows firewall status."""

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor


def check_firewall(parameters: dict) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    firewall = monitor.snapshot()["firewall"]
    return (
        f"Firewall Windows: {firewall.get('status', 'unknown')}; "
        f"profili attivi {firewall.get('enabled_profiles', 0)}, "
        f"disattivi {firewall.get('disabled_profiles', 0)}, "
        f"non determinati {firewall.get('unknown_profiles', 0)}. "
        "Non vengono esposti i nomi dei profili."
    )


TOOL = {
    "name": "check_firewall",
    "description": "Riassume lo stato dei profili Windows Firewall senza esporre dettagli personali.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_firewall,
}
