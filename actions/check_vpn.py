"""Report a summary of likely active VPN network adapters."""

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor


def check_vpn(parameters: dict) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    vpn = monitor.snapshot()["vpn"]
    if vpn.get("status") != "available":
        return "Stato VPN non disponibile; i nomi delle interfacce non sono stati esposti."
    if vpn.get("detected"):
        return (
            f"Rilevate {vpn.get('active_vpn_interfaces', 0)} interfacce attive "
            "compatibili con VPN. È un'indicazione euristica, non verifica il tunnel."
        )
    return (
        "Nessuna interfaccia attiva riconosciuta come VPN. "
        "Il rilevamento è euristico e può non riconoscere client o tunnel personalizzati."
    )


TOOL = {
    "name": "check_vpn",
    "description": "Riassume la possibile presenza di una VPN senza rivelare nomi di interfaccia.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_vpn,
}
