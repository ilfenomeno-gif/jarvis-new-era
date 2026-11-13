"""One-tool summary action for the local network monitor."""

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor


def network_security(parameters: dict) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    result = monitor.snapshot()
    if result["status"] != "available":
        return (
            "Riepilogo della rete locale non disponibile. "
            "Potrebbero mancare permessi o strumenti di sistema."
        )
    return (
        "Riepilogo rete: "
        f"rete {'connessa' if result.get('connected') is True else 'disconnessa' if result.get('connected') is False else 'non disponibile'}; "
        f"{result['established_connections']} connessioni stabilite, "
        f"{result['listening_sockets']} socket in ascolto "
        f"({result['network_bound_listeners']} associati a indirizzi di rete); "
        f"{result['wifi'].get('connected_interfaces', 0)} interfacce Wi-Fi connesse; "
        f"{result['interfaces'].get('active_interfaces', 0)} interfacce attive, "
        f"{result['interfaces'].get('local_ipv4_interfaces', 0)} con IPv4 locale, "
        f"{result['interfaces'].get('dns_servers', 0)} server DNS; "
        f"VPN rilevata: {'sì' if result['vpn'].get('detected') else 'no'}; "
        f"firewall: {result['firewall'].get('status', 'unknown')}. "
        "Nessun IP, SSID, nome interfaccia, porta o PID è incluso."
    )


TOOL = {
    "name": "network_security",
    "description": (
        "Riassume lo stato locale della rete, Wi-Fi, firewall, VPN e socket "
        "senza esporre IP, SSID, nomi di interfaccia, porte o PID."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": network_security,
}
