"""
JARVIS plugin: controllo dispositivi smart home.

Supporta tre backend, scelti automaticamente in base a cosa e configurato in
config/api_keys.json (lo stesso file, escluso da git, già usato dai tool
core per le altre chiavi API), oppure forzati con il parametro 'backend':

  home_assistant  - REST API di Home Assistant (funziona anche per luci Hue
                     e prese Tasmota se sono già integrate in HA: e il modo
                     piu semplice se si ha già un hub Home Assistant).
      Chiavi richieste: HOME_ASSISTANT_URL (es. "http://homeassistant.local:8123")
                        HOME_ASSISTANT_TOKEN (Long-Lived Access Token)

  hue             - API locale del Bridge Philips Hue, senza passare da Home
                     Assistant (utile se si ha solo l'ecosistema Hue).
      Chiavi richieste: HUE_BRIDGE_IP, HUE_API_KEY

  mqtt            - Publish MQTT in stile Tasmota (cmnd/<device>/POWER ecc.),
                     per dispositivi Tasmota collegati a un broker MQTT senza
                     Home Assistant nel mezzo.
      Chiavi richieste: MQTT_BROKER_HOST (MQTT_BROKER_PORT opzionale, default 1883;
                        MQTT_USERNAME / MQTT_PASSWORD opzionali)

Ogni backend viene importato pigramente (requests / paho-mqtt) cosi il
plugin resta valido anche se una dipendenza opzionale non e installata:
fallisce solo l'azione che la richiede, con un messaggio d'errore chiaro.
"""

from __future__ import annotations

from config import get_config

PLUGIN = {
    "name": "smart_device_control",
    "description": (
        "Controlla dispositivi smart home (luci, prese, termostati) via "
        "Home Assistant, Philips Hue o MQTT/Tasmota. Usare 'device' per "
        "identificare il dispositivo (entity_id per Home Assistant, es. "
        "'light.soggiorno'; nome della luce per Hue; nome del topic per "
        "MQTT/Tasmota) e 'action' per l'operazione: 'on', 'off', 'toggle', "
        "oppure 'brightness' con 'value' 0-100. Il backend viene scelto "
        "automaticamente in base a cosa e configurato, salvo che l'utente "
        "non specifichi 'backend' esplicitamente. Se nessun backend e "
        "configurato, spiega all'utente come configurarlo invece di "
        "inventare un risultato."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "device": {"type": "STRING", "description": "Identificatore del dispositivo (dipende dal backend, vedi descrizione)."},
            "action": {"type": "STRING", "description": "Una tra: 'on', 'off', 'toggle', 'brightness'."},
            "value": {"type": "NUMBER", "description": "Valore 0-100 per action='brightness'."},
            "backend": {"type": "STRING", "description": "Forza un backend specifico: 'home_assistant', 'hue' o 'mqtt'. Opzionale."},
        },
        "required": ["device", "action"],
    },
}


def _pick_backend(cfg: dict, forced: str) -> str | None:
    if forced:
        return forced.strip().lower()
    if cfg.get("HOME_ASSISTANT_URL") and cfg.get("HOME_ASSISTANT_TOKEN"):
        return "home_assistant"
    if cfg.get("HUE_BRIDGE_IP") and cfg.get("HUE_API_KEY"):
        return "hue"
    if cfg.get("MQTT_BROKER_HOST"):
        return "mqtt"
    return None


# ── Home Assistant ───────────────────────────────────────────────────────

def _home_assistant(cfg: dict, device: str, action: str, value) -> str:
    import requests

    base_url = cfg["HOME_ASSISTANT_URL"].rstrip("/")
    token = cfg["HOME_ASSISTANT_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    domain = device.split(".", 1)[0] if "." in device else "homeassistant"
    if action == "on":
        service, payload = "turn_on", {"entity_id": device}
    elif action == "off":
        service, payload = "turn_off", {"entity_id": device}
    elif action == "toggle":
        service, payload = "toggle", {"entity_id": device}
    elif action == "brightness":
        if value is None:
            raise ValueError("specificare 'value' (0-100) per action='brightness'.")
        service, payload = "turn_on", {"entity_id": device, "brightness_pct": int(max(0, min(100, value)))}
    else:
        raise ValueError(f"azione '{action}' non supportata da Home Assistant.")

    url = f"{base_url}/api/services/{domain}/{service}"
    resp = requests.post(url, headers=headers, json=payload, timeout=8)
    resp.raise_for_status()
    return f"Comando '{action}' inviato a '{device}' via Home Assistant."


# ── Philips Hue (Bridge locale) ─────────────────────────────────────────

def _hue_find_light_id(base_url: str, api_key: str, name: str) -> str:
    import requests

    resp = requests.get(f"{base_url}/api/{api_key}/lights", timeout=8)
    resp.raise_for_status()
    lights = resp.json()
    name_lower = name.strip().lower()
    for light_id, info in lights.items():
        if info.get("name", "").strip().lower() == name_lower:
            return light_id
    for light_id, info in lights.items():
        if name_lower in info.get("name", "").strip().lower():
            return light_id
    raise ValueError(f"nessuna luce Hue trovata con nome simile a '{name}'.")


def _hue(cfg: dict, device: str, action: str, value) -> str:
    import requests

    base_url = f"http://{cfg['HUE_BRIDGE_IP']}"
    api_key = cfg["HUE_API_KEY"]
    light_id = _hue_find_light_id(base_url, api_key, device)

    if action == "on":
        state = {"on": True}
    elif action == "off":
        state = {"on": False}
    elif action == "toggle":
        current = requests.get(f"{base_url}/api/{api_key}/lights/{light_id}", timeout=8).json()
        state = {"on": not current.get("state", {}).get("on", False)}
    elif action == "brightness":
        if value is None:
            raise ValueError("specificare 'value' (0-100) per action='brightness'.")
        state = {"on": True, "bri": int(max(1, min(254, round(float(value) / 100 * 254))))}
    else:
        raise ValueError(f"azione '{action}' non supportata da Hue.")

    resp = requests.put(f"{base_url}/api/{api_key}/lights/{light_id}/state", json=state, timeout=8)
    resp.raise_for_status()
    return f"Comando '{action}' inviato alla luce Hue '{device}'."


# ── MQTT / Tasmota ───────────────────────────────────────────────────────

def _mqtt(cfg: dict, device: str, action: str, value) -> str:
    import paho.mqtt.publish as mqtt_publish

    host = cfg["MQTT_BROKER_HOST"]
    port = int(cfg.get("MQTT_BROKER_PORT", 1883))
    auth = None
    if cfg.get("MQTT_USERNAME"):
        auth = {"username": cfg["MQTT_USERNAME"], "password": cfg.get("MQTT_PASSWORD", "")}

    if action == "on":
        topic, payload = f"cmnd/{device}/POWER", "ON"
    elif action == "off":
        topic, payload = f"cmnd/{device}/POWER", "OFF"
    elif action == "toggle":
        topic, payload = f"cmnd/{device}/POWER", "TOGGLE"
    elif action == "brightness":
        if value is None:
            raise ValueError("specificare 'value' (0-100) per action='brightness'.")
        topic, payload = f"cmnd/{device}/Dimmer", str(int(max(0, min(100, value))))
    else:
        raise ValueError(f"azione '{action}' non supportata da MQTT/Tasmota.")

    mqtt_publish.single(topic, payload=payload, hostname=host, port=port, auth=auth, client_id="jarvis-smarthome")
    return f"Comando '{action}' pubblicato su '{topic}' (MQTT/Tasmota)."


_BACKENDS = {"home_assistant": _home_assistant, "hue": _hue, "mqtt": _mqtt}
_MISSING_CONFIG_HINT = (
    "Sir, nessun ecosistema smart home e configurato. Aggiunga in "
    "config/api_keys.json una delle seguenti combinazioni: "
    "HOME_ASSISTANT_URL + HOME_ASSISTANT_TOKEN (Home Assistant), "
    "HUE_BRIDGE_IP + HUE_API_KEY (Philips Hue), oppure "
    "MQTT_BROKER_HOST (MQTT/Tasmota)."
)


def run(parameters: dict, player=None, session_memory=None) -> str:
    device = str(parameters.get("device", "")).strip()
    action = str(parameters.get("action", "")).strip().lower()
    value = parameters.get("value")
    forced_backend = str(parameters.get("backend", "")).strip().lower()

    if not device:
        return "Sir, deve specificare quale dispositivo controllare."
    if not action:
        return "Sir, deve specificare l'azione da eseguire (on, off, toggle, brightness)."

    try:
        cfg = get_config()
        backend = _pick_backend(cfg, forced_backend)
        if backend is None:
            return _MISSING_CONFIG_HINT
        if backend not in _BACKENDS:
            return f"Sir, backend '{backend}' non riconosciuto. Usare home_assistant, hue o mqtt."

        result_text = _BACKENDS[backend](cfg, device, action, value)

    except ModuleNotFoundError as e:
        return f"Sir, manca una dipendenza per questo backend: {e}. Installarla con pip."
    except ValueError as e:
        return f"Sir, {e}"
    except Exception as e:
        return f"Sir, il controllo smart home ha riscontrato un errore: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
