"""Local network health collection with privacy-safe model-facing summaries."""

from __future__ import annotations

import ipaddress
import ctypes
import locale
import logging
import math
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace

_LOG = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 30.0
MAX_STOP_TIMEOUT_SECONDS = 2.0
PUBLIC_IP_CACHE_SECONDS = 60.0
PUBLIC_IP_TIMEOUT_SECONDS = 3.0
LOCAL_COMMAND_TIMEOUT_SECONDS = 0.5
_CONSOLE_ENCODING = "oem" if os.name == "nt" else locale.getpreferredencoding(False)
_LISTENING = "LISTEN"
_ESTABLISHED = "ESTABLISHED"
_IPIFY_URL = "https://api.ipify.org"
_admin_notice_lock = threading.Lock()
_admin_notice_sent = False
NETWORK_MODULE_DISABLED = (
    "Errore: modulo simbiosi 'network' non selezionato o non attivo. "
    "Attivare il modulo nella selezione JARVIS_SYMBIOSIS_MODULES; "
    "verificare anche JARVIS_SYMBIOSIS."
)
_VPN_HINTS = (
    "vpn", "wireguard", "tailscale", "zerotier", "openvpn", "proton",
    "nordlynx", "wintun", "tunnel",
)


@dataclass(frozen=True)
class NetworkSnapshot:
    """Only non-identifying summary values are retained between polls."""

    status: str
    sampled_at_monotonic: float | None = None
    socket_status: str = "not_checked"
    connected: bool | None = None
    wifi_signal_percent: int = -1
    wifi_weak_seconds: float = 0.0
    established_connections: int = 0
    listening_sockets: int = 0
    network_bound_listeners: int = 0
    listeners_with_pid: int = 0
    wifi: dict[str, int | str] = field(default_factory=dict)
    interfaces: dict[str, int | str] = field(default_factory=dict)
    vpn: dict[str, int | str | bool] = field(default_factory=dict)
    firewall: dict[str, int | str] = field(default_factory=dict)
    neighbors: dict[str, int | str] = field(default_factory=dict)
    message: str = ""

    def as_dict(self) -> dict:
        snapshot = asdict(self)
        if self.wifi_signal_percent < 0:
            signal = self.wifi.get("signal_percent")
            if isinstance(signal, int) and not isinstance(signal, bool):
                snapshot["wifi_signal_percent"] = signal
        if self.connected is None:
            connected = self.interfaces.get("connected")
            if isinstance(connected, bool):
                snapshot["connected"] = connected
        return snapshot


def _run_netsh(
    *arguments: str,
    stop_event: threading.Event | None = None,
) -> str:
    if stop_event is not None and stop_event.is_set():
        return ""
    try:
        result = subprocess.run(
            ["netsh", *arguments],
            capture_output=True,
            text=True,
            encoding=_CONSOLE_ENCODING,
            errors="replace",
            timeout=LOCAL_COMMAND_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        global _admin_notice_sent
        if (isinstance(exc, PermissionError) and os.name == "nt"
                and os.environ.get("JARVIS_LOG_LEGACY") != "1"
                and os.environ.get("JARVIS_LOG_DIAGNOSTIC", "1") == "1"):
            with _admin_notice_lock:
                if not _admin_notice_sent:
                    try:
                        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
                    except (AttributeError, OSError) as admin_error:
                        _LOG.warning("Verifica privilegi amministratore non disponibile: %s", admin_error)
                        is_admin = None
                    _LOG.log(25, "Comando rete non autorizzato; privilegi amministratore: %s",
                             "sconosciuti" if is_admin is None else "sì" if is_admin else "no",
                             extra={"component": "symbiosis.network"})
                    _admin_notice_sent = True
        _LOG.warning("[SYMBIOSIS][NETWORK] Local network command failed (%s).", type(exc).__name__)
        return ""
    if result.returncode:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local network command returned status %d.", result.returncode)
        return ""
    return result.stdout or ""


def parse_wifi_interfaces(output: str) -> dict[str, int | str]:
    """Parse netsh WLAN output, discarding SSIDs and interface identifiers."""
    sections: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                sections.append(current)
                current = {}
            continue
        match = re.match(r"([^:]+?)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1).strip().casefold(), match.group(2).strip()
        if key in {"name", "nome"} and current:
            sections.append(current)
            current = {}
        if key in {
            "state", "stato", "signal", "segnale", "authentication",
            "autenticazione", "ssid",
        }:
            current[key] = value
    if current:
        sections.append(current)

    connected = 0
    signals: list[int] = []
    security: list[str] = []
    for section in sections:
        state = section.get("state", section.get("stato", "")).casefold()
        is_connected = state in {"connected", "connesso", "connessa", "collegato"}
        if not is_connected:
            continue
        connected += 1
        signal = section.get("signal", section.get("segnale", ""))
        match = re.search(r"\d{1,3}", signal)
        if match and 0 <= int(match.group()) <= 100:
            signals.append(int(match.group()))
        authentication = section.get(
            "authentication", section.get("autenticazione", "")
        ).casefold()
        if any(term in authentication for term in ("open", "aperta", "nessuna")):
            security.append("open")
        elif any(
            term in authentication
            for term in ("wpa", "802.1x", "enterprise", "protetta")
        ):
            security.append("secure")
        else:
            security.append("unknown")
    security_status = (
        "open" if "open" in security
        else "secure" if security and all(item == "secure" for item in security)
        else "unknown"
    )
    return {
        "status": "available" if sections else "unavailable",
        "connected_interfaces": connected,
        "signal_percent": max(signals) if signals else -1,
        "security": security_status,
    }


def parse_ipconfig(output: str) -> dict[str, int | str]:
    """Count local IPv4 and DNS entries without retaining any address values."""
    ipv4_count = 0
    dns_count = 0
    in_dns_list = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            in_dns_list = False
            continue
        lower = line.casefold()
        if "dns servers" in lower or "server dns" in lower:
            value = line.split(":", 1)[-1].strip()
            in_dns_list = True
            if value and _contains_ip(value):
                dns_count += 1
            continue
        if in_dns_list and _contains_ip(line):
            dns_count += 1
        elif "ipv4 address" in lower or "indirizzo ipv4" in lower:
            value = line.split(":", 1)[-1].strip()
            if _contains_ip(value):
                ipv4_count += 1
    return {
        "status": "available" if output.strip() else "unavailable",
        "local_ipv4_interfaces": ipv4_count,
        "dns_servers": dns_count,
    }


def _contains_ip(value: str) -> bool:
    candidate = value.split("(")[0].strip().split()[0] if value.strip() else ""
    try:
        ipaddress.ip_address(candidate.split("%", 1)[0])
    except ValueError:
        return False
    return True


def parse_firewall(output: str) -> dict[str, int | str]:
    """Summarize firewall profile states without including profile labels."""
    states: list[bool | None] = []
    for line in output.splitlines():
        match = re.search(
            r"\b(?:state|stato)\b\s*(?:[.:]+\s*)?(on|off|enabled|disabled|"
            r"attivo|attiva|attivato|attivata|disattivo|disattiva|"
            r"disattivato|disattivata)\b",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue
        value = match.group(1).casefold()
        states.append(value in {"on", "enabled", "attivo", "attiva", "attivato", "attivata"})
    enabled = sum(state is True for state in states)
    disabled = sum(state is False for state in states)
    status = (
        "unknown" if not states
        else "enabled" if enabled == len(states)
        else "disabled" if disabled == len(states)
        else "mixed"
    )
    return {
        "status": status,
        "enabled_profiles": enabled,
        "disabled_profiles": disabled,
        "unknown_profiles": len(states) - enabled - disabled,
    }


def parse_neighbors(output: str) -> dict[str, int | str]:
    """Count netsh neighbor entries; never retain IP or hardware addresses."""
    total = dynamic = static = 0
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            ipaddress.ip_address(parts[0])
        except ValueError:
            continue
        total += 1
        kind = parts[-1].casefold()
        if kind in {"dynamic", "dinamico", "dinamica", "reachable", "stale"}:
            dynamic += 1
        elif kind in {"static", "statico", "statica", "permanent"}:
            static += 1
    return {
        "status": "available" if output.strip() else "unavailable",
        "devices": total,
        "dynamic": dynamic,
        "static": static,
        "other": total - dynamic - static,
    }


def _address_ip(address: object) -> str | None:
    if address is None:
        return None
    if hasattr(address, "ip"):
        candidate = getattr(address, "ip", None)
    elif isinstance(address, (tuple, list)) and address:
        candidate = address[0]
    else:
        candidate = None
    return candidate if isinstance(candidate, str) else None


def parse_listening_ports(connections: Iterable[object]) -> dict[str, int]:
    """Summarize listening sockets and PID coverage without returning IDs."""
    listeners = bound = with_pid = 0
    for connection in connections:
        if str(getattr(connection, "status", "")).upper() != _LISTENING:
            continue
        listeners += 1
        address = _address_ip(getattr(connection, "laddr", None))
        try:
            parsed = ipaddress.ip_address(address) if address else None
        except ValueError:
            parsed = None
        if parsed is not None and not parsed.is_loopback:
            bound += 1
        if getattr(connection, "pid", None) is not None:
            with_pid += 1
    return {
        "listening_sockets": listeners,
        "network_bound_listeners": bound,
        "listeners_with_pid": with_pid,
    }


def parse_local_wifi_details(output: str) -> list[dict]:
    """Parse sensitive Wi-Fi details for local callers; never use in tools."""
    interfaces: list[dict] = []
    current: dict | None = None
    fields = {
        "name": "interface", "nome": "interface",
        "state": "state", "stato": "state",
        "ssid": "ssid",
        "signal": "signal_percent", "segnale": "signal_percent",
        "authentication": "security", "autenticazione": "security",
        "cipher": "cipher", "crittografia": "cipher",
    }
    for line in output.splitlines():
        match = re.match(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.group(1).strip().casefold(), match.group(2).strip()
        field_name = fields.get(key)
        if not field_name:
            continue
        if field_name == "interface":
            current = {
                "interface": value, "state": None, "ssid": None,
                "signal_percent": None, "security": None, "cipher": None,
            }
            interfaces.append(current)
        elif current is not None:
            if field_name == "signal_percent":
                signal = re.fullmatch(r"(\d{1,3})\s*%", value)
                current[field_name] = (
                    int(signal.group(1))
                    if signal and int(signal.group(1)) <= 100 else None
                )
            else:
                current[field_name] = value or None
    for entry in interfaces:
        state = (entry["state"] or "").casefold()
        if state not in {"connected", "connesso", "connessa", "collegato"}:
            entry["ssid"] = None
            entry["signal_percent"] = None
            entry["security"] = None
            entry["cipher"] = None
    return interfaces


def parse_local_dns_details(output: str) -> dict[str, list[str]]:
    """Extract DNS entries by adapter from English or Italian ipconfig output."""
    adapters: dict[str, list[str]] = {}
    current: str | None = None
    dns_continuation = False
    for raw_line in output.splitlines():
        if raw_line and not raw_line[0].isspace() and raw_line.strip().endswith(":"):
            heading = raw_line.strip()[:-1]
            match = re.match(
                r"^(?:.+?\s+adapter|scheda\s+(?:lan\s+wireless|ethernet|"
                r"lan|tunnel|wireless))\s+(.+)$",
                heading, re.IGNORECASE,
            )
            current = match.group(1).strip() if match else None
            dns_continuation = False
            if current is not None:
                adapters.setdefault(current, [])
            continue
        line = raw_line.strip()
        if not line:
            dns_continuation = False
            continue
        if "dns servers" in line.casefold() or "server dns" in line.casefold():
            candidate = line.split(":", 1)[-1].strip()
            dns_continuation = True
        elif dns_continuation and _contains_ip(line):
            candidate = line
        else:
            dns_continuation = False
            continue
        if current is not None and _contains_ip(candidate):
            address = candidate.split()[0].split("(")[0]
            if address not in adapters[current]:
                adapters[current].append(address)
    return adapters


def parse_local_neighbor_details(output: str) -> list[dict[str, str]]:
    """Extract sensitive ARP neighbor entries for local callers."""
    neighbors = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            address = str(ipaddress.ip_address(parts[0]))
        except ValueError:
            continue
        mac_index = next(
            (i for i, part in enumerate(parts[1:], 1)
             if re.fullmatch(r"(?:[0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}", part)),
            None,
        )
        if mac_index is None:
            continue
        neighbors.append({
            "ip": address, "mac": parts[mac_index], "state": parts[-1],
        })
    return neighbors


def local_wifi_details() -> dict:
    """Query SSID, authentication and signal locally, without logging details."""
    output = _run_netsh("wlan", "show", "interfaces")
    return {
        "status": "available" if output.strip() else "unavailable",
        "interfaces": parse_local_wifi_details(output),
    }


def local_interface_details() -> dict:
    """Query local interface names, addresses and DNS; no persistence or logging."""
    try:
        import psutil

        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local interface enumeration failed (%s).", type(exc).__name__)
        return {"status": "unavailable", "dns_status": "unavailable", "interfaces": []}
    output = _run_command(["ipconfig", "/all"], "IP configuration")
    dns_by_adapter = parse_local_dns_details(output)
    entries = []
    for name in sorted(set(addresses) | set(stats)):
        info = stats.get(name)
        entries.append({
            "name": name,
            "is_up": bool(info.isup) if info is not None else None,
            "addresses": [
                {"family": "IPv4" if record.family == socket.AF_INET else "IPv6",
                 "address": record.address}
                for record in addresses.get(name, [])
                if record.family in (socket.AF_INET, socket.AF_INET6)
            ],
            "dns_servers": list(dns_by_adapter.get(name, [])),
        })
    return {
        "status": "available",
        "dns_status": "available" if output.strip() else "unavailable",
        "interfaces": entries,
    }


def local_listening_ports() -> dict:
    """Return local listener addresses, ports and PIDs, without process lookup."""
    try:
        import psutil

        connections = psutil.net_connections(kind="inet")
        listeners = []
        for connection in connections:
            if str(getattr(connection, "status", "")).upper() != _LISTENING:
                continue
            address = getattr(connection, "laddr", None)
            if not address:
                continue
            port = getattr(address, "port", None)
            if port is None and isinstance(address, (tuple, list)) and len(address) > 1:
                port = address[1]
            listeners.append({
                "address": _address_ip(address),
                "port": port,
                "pid": getattr(connection, "pid", None),
                "family": (
                    "IPv4" if getattr(connection, "family", None) == socket.AF_INET
                    else "IPv6" if getattr(connection, "family", None) == socket.AF_INET6
                    else "unknown"
                ),
            })
    except Exception as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local socket enumeration failed (%s).", type(exc).__name__)
        return {"status": "unavailable", "listeners": []}
    return {"status": "available", "listeners": listeners}


def local_network_neighbors() -> dict:
    """Read the local IPv4 neighbor cache; does not discover or probe devices."""
    output = _run_netsh("interface", "ipv4", "show", "neighbors")
    return {
        "status": "available" if output.strip() else "unavailable",
        "neighbors": parse_local_neighbor_details(output),
    }


def _read_local_public_ip(
    *, opener: Callable[..., object] | None = None,
) -> dict[str, str | None]:
    """Read an IP from ipify exclusively for local callers."""
    try:
        with (opener or urllib.request.urlopen)(
            _IPIFY_URL, timeout=PUBLIC_IP_TIMEOUT_SECONDS
        ) as response:
            address = str(ipaddress.ip_address(response.read(64).decode("ascii").strip()))
    except Exception as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Public IP query failed (%s).", type(exc).__name__)
        return {"status": "unavailable", "address": None}
    return {"status": "available", "address": address}


def _collect_network_snapshot(
    *, stop_event: threading.Event | None = None
) -> NetworkSnapshot:
    import psutil

    if stop_event is not None and stop_event.is_set():
        return NetworkSnapshot(status="stopping", message="Rilevamento interrotto.")
    try:
        connections = list(psutil.net_connections(kind="inet"))
    except Exception as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local socket enumeration failed (%s).", type(exc).__name__)
        connections = []
        socket_status = "unavailable"
    else:
        socket_status = "available"
    ports = parse_listening_ports(connections)
    established = sum(
        str(getattr(connection, "status", "")).upper() == _ESTABLISHED
        for connection in connections
    )

    if stop_event is not None and stop_event.is_set():
        return NetworkSnapshot(status="stopping", message="Rilevamento interrotto.")
    try:
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
    except Exception as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local interface enumeration failed (%s).", type(exc).__name__)
        stats, addresses = {}, {}
        interface_status = "unavailable"
    else:
        interface_status = "available"
    active = [
        name for name, info in stats.items()
        if info.isup and "loopback" not in name.casefold()
    ]
    local_ipv4_count = sum(
        1
        for name, records in addresses.items()
        if name in active
        for record in records
        if getattr(record, "family", None) in (socket.AF_INET, socket.AF_INET6)
        and _is_usable_local_ip(getattr(record, "address", ""))
    )
    connected_interfaces = {
        name
        for name, records in addresses.items()
        if name in active
        and any(
            getattr(record, "family", None) in (socket.AF_INET, socket.AF_INET6)
            and _is_usable_local_ip(getattr(record, "address", ""))
            for record in records
        )
    }
    vpn_names = [
        name for name in active
        if any(hint in name.casefold() for hint in _VPN_HINTS)
    ]

    wifi_output = _run_netsh(
        "wlan", "show", "interfaces", stop_event=stop_event
    )
    if stop_event is not None and stop_event.is_set():
        return NetworkSnapshot(status="stopping", message="Rilevamento interrotto.")
    ipconfig_output = _run_command(
        ["ipconfig", "/all"], "IP configuration", stop_event=stop_event
    )
    if stop_event is not None and stop_event.is_set():
        return NetworkSnapshot(status="stopping", message="Rilevamento interrotto.")
    firewall_output = _run_netsh(
        "advfirewall", "show", "allprofiles", stop_event=stop_event
    )
    if stop_event is not None and stop_event.is_set():
        return NetworkSnapshot(status="stopping", message="Rilevamento interrotto.")
    neighbors_output = _run_netsh(
        "interface", "ipv4", "show", "neighbors", stop_event=stop_event
    )
    if stop_event is not None and stop_event.is_set():
        return NetworkSnapshot(status="stopping", message="Rilevamento interrotto.")
    wifi = parse_wifi_interfaces(wifi_output)
    ip_details = parse_ipconfig(ipconfig_output)
    firewall = parse_firewall(firewall_output)
    neighbors = parse_neighbors(neighbors_output)
    return NetworkSnapshot(
        status="available" if socket_status == "available" or interface_status == "available" else "unavailable",
        socket_status=socket_status,
        connected=(
            bool(connected_interfaces) if interface_status == "available" else None
        ),
        wifi_signal_percent=wifi["signal_percent"],
        established_connections=established,
        listening_sockets=ports["listening_sockets"],
        network_bound_listeners=ports["network_bound_listeners"],
        listeners_with_pid=ports["listeners_with_pid"],
        wifi=wifi,
        interfaces={
            "status": interface_status,
            "active_interfaces": len(active),
            "connected": (
                bool(connected_interfaces) if interface_status == "available" else None
            ),
            "local_ipv4_interfaces": max(
                ip_details["local_ipv4_interfaces"], local_ipv4_count
            ),
            "dns_servers": ip_details["dns_servers"],
        },
        vpn={
            "status": "available" if interface_status == "available" else "unavailable",
            "detected": bool(vpn_names),
            "active_vpn_interfaces": len(vpn_names),
        },
        firewall=firewall,
        neighbors=neighbors,
        message="",
    )


def _run_command(
    arguments: list[str],
    label: str,
    timeout: float = LOCAL_COMMAND_TIMEOUT_SECONDS,
    *,
    stop_event: threading.Event | None = None,
) -> str:
    del label
    if stop_event is not None and stop_event.is_set():
        return ""
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding=_CONSOLE_ENCODING,
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local command failed (%s).", type(exc).__name__)
        return ""
    if result.returncode:
        _LOG.warning("[SYMBIOSIS][NETWORK] Local command returned status %d.", result.returncode)
        return ""
    return result.stdout or ""


def _is_usable_local_ip(value: str) -> bool:
    try:
        parsed = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return not parsed.is_loopback and not parsed.is_unspecified


def read_public_ip_metadata(
    *,
    opener: Callable[..., object] | None = None,
) -> dict[str, str | bool]:
    """Query ipify but expose/cache only address-family metadata, never the IP."""
    return _public_ip_metadata_from_local(_read_local_public_ip(opener=opener))


def _public_ip_metadata_from_local(result: dict[str, str | None]) -> dict[str, str | bool]:
    address = result.get("address")
    if result.get("status") != "available" or not address:
        return {"status": "unavailable", "address_family": "unknown"}
    try:
        version = ipaddress.ip_address(address).version
    except ValueError:
        return {"status": "unavailable", "address_family": "unknown"}
    return {
        "status": "available",
        "address_family": "IPv4" if version == 4 else "IPv6",
    }


def read_ping_summary(
    *,
    runner: Callable[..., object] | None = None,
    timeout: float = 7.0,
) -> dict[str, int | str]:
    """Ping one fixed public resolver, at most five packets, and return statistics."""
    run = runner or subprocess.run
    try:
        result = run(
            ["ping", "-n", "5", "-w", "1000", "8.8.8.8"],
            capture_output=True,
            text=True,
            encoding=_CONSOLE_ENCODING,
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("[SYMBIOSIS][NETWORK] Connectivity check failed (%s).", type(exc).__name__)
        return {"status": "unavailable", "packets_sent": 0, "packets_lost": 0, "average_ms": -1}
    output = result.stdout or ""
    sent_match = re.search(r"Sent\s*=\s*(\d+)", output, re.IGNORECASE)
    received_match = re.search(r"Received\s*=\s*(\d+)", output, re.IGNORECASE)
    if not sent_match:
        sent_match = re.search(
            r"(?:Inviati|Trasmessi)\s*=\s*(\d+)", output, re.IGNORECASE
        )
    if not received_match:
        received_match = re.search(r"Ricevuti\s*=\s*(\d+)", output, re.IGNORECASE)
    sent = min(5, int(sent_match.group(1))) if sent_match else 0
    received = min(sent, int(received_match.group(1))) if received_match else 0
    average_match = re.search(
        r"(?:Average|Media)\s*=\s*(\d+)\s*ms", output, re.IGNORECASE
    )
    return {
        "status": "available" if sent else "unavailable",
        "packets_sent": sent,
        "packets_lost": sent - received,
        "average_ms": int(average_match.group(1)) if average_match else -1,
    }


class NetworkSecurityMonitor:
    """Poll aggregate metadata; cache requested public IP in memory for local use."""

    def __init__(
        self,
        *,
        interval_seconds: float = POLL_INTERVAL_SECONDS,
        connection_source: Callable[[], Iterable[object]] | None = None,
        snapshot_source: Callable[[], NetworkSnapshot] | None = None,
        clock: Callable[[], float] = time.monotonic,
        public_ip_reader: Callable[[], dict[str, str | bool]] | None = None,
    ) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Network monitor interval must be finite and positive.")
        self._interval = interval_seconds
        self._connection_source = connection_source
        self._snapshot_source = snapshot_source or (
            self._collect_from_connections if connection_source else _collect_network_snapshot
        )
        self._clock = clock
        self._public_ip_reader = public_ip_reader
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._wifi_weak_since: float | None = None
        self._wifi_last_sample: float | None = None
        self._snapshot = NetworkSnapshot(
            status="not_checked",
            message="Il controllo non è ancora stato eseguito.",
        )
        self._public_ip_lock = threading.Lock()
        self._public_ip_cache: tuple[float, dict] | None = None

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def _collect_from_connections(self) -> NetworkSnapshot:
        try:
            connections = list(self._connection_source()) if self._connection_source else []
            ports = parse_listening_ports(connections)
            established = sum(
                str(getattr(connection, "status", "")).upper() == _ESTABLISHED
                for connection in connections
            )
        except Exception as exc:
            _LOG.warning("[SYMBIOSIS][NETWORK] Local socket enumeration failed (%s).", type(exc).__name__)
            return NetworkSnapshot(
                status="unavailable",
                socket_status="unavailable",
                message="Socket locali non disponibili.",
            )
        return NetworkSnapshot(
            status="available",
            socket_status="available",
            established_connections=established,
            listening_sockets=ports["listening_sockets"],
            network_bound_listeners=ports["network_bound_listeners"],
            listeners_with_pid=ports["listeners_with_pid"],
        )

    def scan(self, *, stop_event: threading.Event | None = None) -> dict:
        """Perform one local poll. Raw interface/address data is never retained."""
        with self._scan_lock:
            if stop_event is not None and stop_event.is_set():
                return self.status()
            try:
                if self._snapshot_source is _collect_network_snapshot:
                    snapshot = self._snapshot_source(stop_event=stop_event)
                else:
                    snapshot = self._snapshot_source()
            except Exception as exc:
                _LOG.warning("[SYMBIOSIS][NETWORK] Local network poll failed (%s).", type(exc).__name__)
                snapshot = NetworkSnapshot(
                    status="unavailable",
                    message="Riepilogo della rete locale non disponibile.",
                )
            if stop_event is not None and stop_event.is_set():
                return self.status()
            completed = time.monotonic()
            signal = snapshot.as_dict()["wifi_signal_percent"]
            with self._lock:
                weak = (
                    snapshot.status == "available"
                    and snapshot.wifi.get("status") == "available"
                    and isinstance(snapshot.wifi.get("connected_interfaces"), int)
                    and snapshot.wifi["connected_interfaces"] > 0
                    and isinstance(signal, int)
                    and not isinstance(signal, bool)
                    and 0 <= signal < 30
                )
                previous = self._wifi_last_sample
                gap = previous is None or not 0 <= completed - previous <= 2 * self._interval
                if not weak:
                    self._wifi_weak_since = None
                elif self._wifi_weak_since is None or gap:
                    self._wifi_weak_since = completed
                self._wifi_last_sample = completed
                duration = (
                    completed - self._wifi_weak_since
                    if self._wifi_weak_since is not None else 0.0
                )
                snapshot = replace(
                    snapshot,
                    sampled_at_monotonic=completed,
                    wifi_weak_seconds=duration,
                )
                self._snapshot = snapshot
                return snapshot.as_dict()

    def status(self) -> dict:
        with self._lock:
            return self._snapshot.as_dict()

    def start(self) -> None:
        """Start the single periodic worker; safe to call more than once."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="jarvis-network-security",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.scan(stop_event=self._stop_event)
            if self._stop_event.wait(self._interval):
                return

    def stop(self, timeout: float = 1.0) -> bool:
        """Request worker shutdown and wait for at most two seconds."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Network monitor stop timeout must be finite and non-negative.")
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        if thread.is_alive():
            thread.join(min(timeout, MAX_STOP_TIMEOUT_SECONDS))
        stopped = not thread.is_alive()
        if stopped:
            with self._lock:
                if self._thread is thread:
                    self._thread = None
        return stopped

    def snapshot(self) -> dict:
        """Return cached local metadata without polling or starting a worker."""
        return self.status()

    def public_ip_metadata(self) -> dict[str, str | bool]:
        """Return cached public-IP availability/family without disclosing the IP."""
        result = self._cached_public_ip()
        if self._public_ip_reader is not None:
            status = result.get("status")
            family = result.get("address_family")
            if status == "available" and family in {"IPv4", "IPv6"}:
                return {"status": "available", "address_family": family}
        return _public_ip_metadata_from_local(result)

    def local_public_ip(self) -> dict[str, str | None]:
        """Read/cache a public IP locally only; never expose via actions/snapshot."""
        result = self._cached_public_ip()
        address = result.get("address")
        try:
            parsed = str(ipaddress.ip_address(address)) if isinstance(address, str) else None
        except ValueError:
            parsed = None
        if result.get("status") != "available" or parsed is None:
            return {"status": "unavailable", "address": None}
        return {"status": "available", "address": parsed}

    def _cached_public_ip(self) -> dict:
        """One locked acquisition per cache period, including failed lookups.

        A custom reader may return an address or legacy metadata alone. In the
        latter case, local_public_ip reports unavailable without a second query.
        """
        with self._public_ip_lock:
            now = self._clock()
            cached = self._public_ip_cache
            if cached and 0 <= now - cached[0] < PUBLIC_IP_CACHE_SECONDS:
                return dict(cached[1])
            result = (
                self._public_ip_reader()
                if self._public_ip_reader is not None else _read_local_public_ip()
            )
            self._public_ip_cache = (self._clock(), dict(result))
            return dict(result)


def get_network_security_monitor() -> NetworkSecurityMonitor | None:
    """Return only the active network module owned by the selected symbiosis hub."""
    from core.symbiosis_hub import get_symbiosis_hub

    hub = get_symbiosis_hub(start=False)
    if hub is None:
        return None
    monitor = hub.get_module("network")
    return monitor if isinstance(monitor, NetworkSecurityMonitor) else None
