"""Measure basic connectivity latency, not bandwidth."""

from core.network_security import (
    NETWORK_MODULE_DISABLED,
    get_network_security_monitor,
    read_ping_summary,
)


def speed_test(parameters: dict) -> str:
    del parameters
    if get_network_security_monitor() is None:
        return NETWORK_MODULE_DISABLED
    result = read_ping_summary()
    if result["status"] != "available":
        return (
            "Test di connettività non disponibile. Il controllo usa al massimo "
            "5 ping verso un resolver pubblico; non misura la banda."
        )
    sent = result["packets_sent"]
    lost = result["packets_lost"]
    average = result["average_ms"]
    latency = f"{average} ms" if average >= 0 else "non disponibile"
    return (
        f"Connettività: {sent - lost}/{sent} pacchetti ricevuti; "
        f"perdita {round(lost * 100 / sent)}%; latenza media {latency}. "
        "È un test ping, non una misurazione di velocità di download/upload."
    )


TOOL = {
    "name": "speed_test",
    "description": (
        "Esegue un breve test di latenza e perdita con al massimo 5 ping. "
        "Non misura la banda e non mostra l'indirizzo del resolver."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": speed_test,
}
