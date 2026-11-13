"""Read a privacy-preserving summary of the current Wi-Fi connection."""

import subprocess

import sounddevice

from core.network_security import NETWORK_MODULE_DISABLED, get_network_security_monitor, local_wifi_details


def check_wifi(parameters: dict, player=None) -> str:
    del parameters
    monitor = get_network_security_monitor()
    if monitor is None:
        return NETWORK_MODULE_DISABLED
    snapshot = monitor.snapshot()
    if snapshot.get("status") == "not_checked":
        snapshot = monitor.scan()
    wifi = snapshot.get("wifi", {})
    if wifi.get("status") != "available":
        return "Stato Wi-Fi non disponibile; i dettagli di rete non sono stati esposti."
    signal = wifi.get("signal_percent", -1)
    signal_text = f"{signal}%" if isinstance(signal, int) and signal >= 0 else "non disponibile"
    response = (
        f"Wi-Fi connesso su {wifi.get('connected_interfaces', 0)} interfacce; "
        f"segnale {signal_text}; sicurezza {wifi.get('security', 'unknown')}. "
    )
    jarvis = getattr(player, "_jarvis", None)
    local_voice = getattr(jarvis, "speak_private_local", None)
    local_display = getattr(jarvis, "show_private_local", None)
    if not callable(local_voice) and not callable(local_display):
        return response + "SSID non disponibile tramite voce locale."
    try:
        details = local_wifi_details()
        entries = [entry for entry in details.get("interfaces", [])
                   if isinstance(entry.get("ssid"), str) and entry["ssid"].strip()]
        if not entries:
            return response + "Nome della rete non disponibile."
        lines = []
        for entry in entries:
            local_signal = entry.get("signal_percent")
            suffix = (f" con segnale al {local_signal}%"
                      if isinstance(local_signal, int) and not isinstance(local_signal, bool)
                      and 0 <= local_signal <= 100 else "")
            lines.append(f"Sei connesso a {entry['ssid']}{suffix}.")
        text = " ".join(lines)
        if callable(local_display):
            local_display(text)
        ambient = getattr(jarvis, "_ambient", None)
        if ambient is not None and ambient.is_silent():
            return response + ("SSID mostrato localmente nella UI." if callable(local_display)
                               else "SSID non disponibile tramite UI locale.")
        if not callable(local_voice):
            return response + "SSID non disponibile tramite voce locale."
        local_voice(text)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError,
            sounddevice.PortAudioError):
        return response + "Impossibile leggere o pronunciare localmente il nome della rete."
    return response + "Il nome della rete è stato pronunciato localmente, senza inviarlo al modello."


TOOL = {
    "name": "check_wifi",
    "description": (
        "Usa per richieste sul Wi-Fi o nome della rete: verifica connessione, "
        "segnale e sicurezza; mostra e pronuncia l'SSID localmente senza inviarlo al modello."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_wifi,
}
