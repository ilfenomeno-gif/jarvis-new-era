"""
Plugin: Kasa Smart Home — controlla dispositivi Kasa (lampade, prese) sulla rete locale.
"""
import asyncio

PLUGIN = {
    "name": "kasa_smart_home",
    "description": (
        "Controlla i dispositivi smart home Kasa sulla rete locale. "
        "Azioni disponibili: 'discover' per trovare dispositivi, 'on' per accendere, "
        "'off' per spegnere, 'status' per lo stato. Specificare device_ip per controllare un dispositivo specifico."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Azione da eseguire: 'discover', 'on', 'off', 'status'."
            },
            "device_ip": {
                "type": "STRING",
                "description": "Indirizzo IP del dispositivo Kasa da controllare."
            }
        },
        "required": ["action"]
    }
}


async def _discover():
    from kasa import Discover
    return await Discover.discover()


async def _control(ip: str, action: str):
    from kasa import SmartPlug
    dev = SmartPlug(ip)
    await dev.update()
    if action == "on":
        await dev.turn_on()
        return f"Dispositivo {dev.alias} acceso."
    elif action == "off":
        await dev.turn_off()
        return f"Dispositivo {dev.alias} spento."
    else:
        state = "acceso" if dev.is_on else "spento"
        return f"Il dispositivo {dev.alias} è attualmente {state}."


def run(parameters: dict, **kwargs) -> str:
    action = parameters.get("action", "discover").lower()
    device_ip = parameters.get("device_ip", "")

    try:
        if action == "discover" or not device_ip:
            devices = asyncio.run(_discover())
            if not devices:
                return "Nessun dispositivo Kasa trovato sulla rete locale."
            dev_list = ", ".join([f"{d.alias} ({ip})" for ip, d in devices.items()])
            return f"Dispositivi Kasa trovati: {dev_list}"
        else:
            return asyncio.run(_control(device_ip, action))
    except Exception as e:
        return f"Errore Kasa Smart Home: {e}"
