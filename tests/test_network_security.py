from __future__ import annotations

import builtins
import importlib.util
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.network_security as network_security_core
from actions import (
    check_firewall,
    check_public_ip,
    check_vpn,
    check_wifi,
    list_network_devices,
    list_open_ports,
    speed_test,
)
from actions import network_security as network_security_action
from core.action_loader import discover_actions
from core.network_security import (
    NetworkSecurityMonitor,
    NetworkSnapshot,
    parse_firewall,
    parse_ipconfig,
    parse_listening_ports,
    parse_neighbors,
    parse_wifi_interfaces,
    read_ping_summary,
    read_public_ip_metadata,
)


def _connection(status: str, ip: str, port: int = 443, pid: int | None = 17):
    return SimpleNamespace(
        status=status,
        laddr=(ip, port),
        raddr=("203.0.113.7", 443),
        pid=pid,
    )


def test_wifi_parser_returns_metadata_but_discards_ssid():
    output = """
    Name                   : Wi-Fi Personale
    State                  : connected
    SSID                   : Casa-Personale
    Signal                 : 87%
    Authentication         : WPA2-Personal
    """

    result = parse_wifi_interfaces(output)

    assert result == {
        "status": "available",
        "connected_interfaces": 1,
        "signal_percent": 87,
        "security": "secure",
    }
    assert "Casa-Personale" not in repr(result)
    assert "Wi-Fi Personale" not in repr(result)


def test_wifi_parser_detects_open_network_without_ssid():
    result = parse_wifi_interfaces(
        "Name: Wi-Fi\nState: connected\nSSID: private\nSignal: 40%\n"
        "Authentication: Open\n"
    )

    assert result["security"] == "open"
    assert "private" not in repr(result)


def test_wifi_parser_handles_disconnection_without_revealing_network():
    result = parse_wifi_interfaces(
        "Name: Wi-Fi privata\nState: disconnected\nSSID: rete-di-casa\n"
    )

    assert result == {
        "status": "available",
        "connected_interfaces": 0,
        "signal_percent": -1,
        "security": "unknown",
    }
    assert "rete-di-casa" not in repr(result)


def test_ipconfig_parser_counts_local_addresses_and_dns_without_returning_them():
    output = """
    Scheda Ethernet Ethernet:
       Indirizzo IPv4. . . . . . . . . . . : 192.168.10.22(Preferenziale)
       Server DNS . . . . . . . . . . . . : 192.168.10.1
                                           2001:db8::1
    """

    result = parse_ipconfig(output)

    assert result == {
        "status": "available",
        "local_ipv4_interfaces": 1,
        "dns_servers": 2,
    }
    assert "192.168" not in repr(result)
    assert "2001" not in repr(result)


def test_firewall_parser_summarizes_localized_profile_states():
    result = parse_firewall(
        "Domain Profile Settings:\n State ON\n"
        "Private Profile Settings:\n State ON\n"
        "Public Profile Settings:\n State OFF\n"
    )

    assert result == {
        "status": "mixed",
        "enabled_profiles": 2,
        "disabled_profiles": 1,
        "unknown_profiles": 0,
    }


def test_neighbor_parser_counts_entries_without_leaking_ip_or_mac():
    output = """
    Interface: 192.168.1.4 --- 0x7
      Internet Address      Physical Address      Type
      192.168.1.2           aa-bb-cc-dd-ee-ff     dynamic
      192.168.1.8           11-22-33-44-55-66     static
    """

    result = parse_neighbors(output)

    assert result == {
        "status": "available",
        "devices": 2,
        "dynamic": 1,
        "static": 1,
        "other": 0,
    }
    assert "192.168" not in repr(result)
    assert "aa-bb" not in repr(result)


def test_listening_port_parser_counts_pid_coverage_without_identifiers():
    result = parse_listening_ports(
        [
            _connection("LISTEN", "0.0.0.0", 22, 111),
            _connection("LISTEN", "127.0.0.1", 8000, None),
            _connection("ESTABLISHED", "192.0.2.2", 443, 222),
        ]
    )

    assert result == {
        "listening_sockets": 2,
        "network_bound_listeners": 1,
        "listeners_with_pid": 1,
    }
    assert "22" not in repr(result)
    assert "111" not in repr(result)
    assert "192.0.2.2" not in repr(result)


def test_monitor_scan_retains_only_safe_snapshot_metadata():
    monitor = NetworkSecurityMonitor(
        connection_source=lambda: [
            _connection("ESTABLISHED", "127.0.0.1"),
            _connection("LISTEN", "0.0.0.0", 22),
        ]
    )

    result = monitor.scan()

    assert result["status"] == "available"
    assert result["established_connections"] == 1
    assert result["listening_sockets"] == 1
    assert result["listeners_with_pid"] == 1
    assert "203.0.113.7" not in repr(result)
    assert "port" not in result
    assert "pid" not in result


def test_public_ip_request_uses_timeout_and_returns_family_only():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            del exc_info
            return None

        def read(self, limit):
            assert limit == 64
            return b"198.51.100.8"

    calls = []

    def opener(url, *, timeout):
        calls.append((url, timeout))
        return Response()

    result = read_public_ip_metadata(opener=opener)

    assert result == {"status": "available", "address_family": "IPv4"}
    assert calls == [("https://api.ipify.org", 3.0)]
    assert "198.51.100.8" not in repr(result)


def test_public_ip_cache_last_60_seconds():
    now = [0.0]
    calls = []
    monitor = NetworkSecurityMonitor(
        clock=lambda: now[0],
        public_ip_reader=lambda: calls.append(1) or {
            "status": "available",
            "address_family": "IPv6",
        },
        snapshot_source=lambda: NetworkSnapshot(status="available"),
    )

    assert monitor.public_ip_metadata()["address_family"] == "IPv6"
    now[0] = 59.9
    monitor.public_ip_metadata()
    assert len(calls) == 1
    now[0] = 60.0
    monitor.public_ip_metadata()
    assert len(calls) == 2


def test_ping_parser_caps_packet_count_and_returns_only_metrics():
    output = (
        "Packets: Sent = 5, Received = 4, Lost = 1 (20% loss), "
        "Approximate round trip times: Minimum = 11ms, Maximum = 19ms, "
        "Average = 14ms"
    )

    def runner(arguments, **kwargs):
        assert arguments[arguments.index("-n") + 1] == "5"
        assert arguments[-1] == "8.8.8.8"
        assert kwargs["timeout"] == 7.0
        return SimpleNamespace(stdout=output, returncode=0)

    result = read_ping_summary(runner=runner)

    assert result == {
        "status": "available",
        "packets_sent": 5,
        "packets_lost": 1,
        "average_ms": 14,
    }
    assert "8.8.8.8" not in repr(result)


def test_actions_register_as_individual_tools_and_summarize_sensitive_data(monkeypatch):
    safe_snapshot = {
        "status": "available",
        "socket_status": "available",
        "established_connections": 3,
        "listening_sockets": 2,
        "network_bound_listeners": 1,
        "listeners_with_pid": 2,
        "wifi": {
            "status": "available",
            "connected_interfaces": 1,
            "signal_percent": 80,
            "security": "secure",
        },
        "interfaces": {
            "status": "available",
            "active_interfaces": 2,
            "local_ipv4_interfaces": 1,
            "dns_servers": 2,
        },
        "vpn": {"status": "available", "detected": True, "active_vpn_interfaces": 1},
        "firewall": {
            "status": "enabled",
            "enabled_profiles": 3,
            "disabled_profiles": 0,
            "unknown_profiles": 0,
        },
        "neighbors": {
            "status": "available",
            "devices": 4,
            "dynamic": 3,
            "static": 1,
            "other": 0,
        },
        "message": "",
    }

    class FakeMonitor:
        def snapshot(self):
            return safe_snapshot

        def public_ip_metadata(self):
            return {"status": "available", "address_family": "IPv4"}

    monkeypatch.setattr(
        "core.network_security.get_network_security_monitor",
        lambda: FakeMonitor(),
    )
    # Each action imported the getter directly.
    for action in (
        network_security_action,
        check_wifi,
        check_public_ip,
        check_vpn,
        check_firewall,
        list_open_ports,
        list_network_devices,
    ):
        monkeypatch.setattr(action, "get_network_security_monitor", lambda: FakeMonitor())
    monkeypatch.setattr(
        speed_test,
        "get_network_security_monitor",
        lambda: FakeMonitor(),
    )
    monkeypatch.setattr(
        speed_test,
        "read_ping_summary",
        lambda: {
            "status": "available",
            "packets_sent": 5,
            "packets_lost": 1,
            "average_ms": 12,
        },
    )

    action_modules = {
        "network_security": network_security_action,
        "check_wifi": check_wifi,
        "check_public_ip": check_public_ip,
        "check_vpn": check_vpn,
        "check_firewall": check_firewall,
        "list_open_ports": list_open_ports,
        "list_network_devices": list_network_devices,
        "speed_test": speed_test,
    }
    expected_names = set(action_modules)
    discovery_messages: list[str] = []
    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions",
        logger=discovery_messages.append,
    )
    assert expected_names <= registry.names()
    declarations = [
        item["name"]
        for item in registry.get_tool_declarations()
        if item["name"] in expected_names
    ]
    assert set(declarations) == expected_names
    assert len(declarations) == len(expected_names)

    responses = {
        name: module.TOOL["handler"]({})
        for name, module in action_modules.items()
    }
    for response in responses.values():
        assert "192.168" not in response
        assert "Casa-Personale" not in response
        assert "PID 17" not in response
        assert "porta 22" not in response
    assert "SSID" in responses["check_wifi"]
    assert "famiglia IPv4" in responses["check_public_ip"]
    assert "non una misurazione" in responses["speed_test"]


def test_stop_disconnects_worker_and_is_bounded():
    entered = threading.Event()
    release = threading.Event()

    def blocked_source():
        entered.set()
        release.wait()
        return NetworkSnapshot(status="available")

    monitor = NetworkSecurityMonitor(
        interval_seconds=0.01,
        snapshot_source=blocked_source,
    )
    monitor.start()
    assert entered.wait(1)

    started = time.monotonic()
    assert monitor.stop(timeout=0.02) is False
    assert time.monotonic() - started < 0.5

    release.set()
    assert monitor.stop(timeout=1) is True
    assert monitor._thread is None


def test_monitor_worker_polls_after_interval_and_stops_cleanly():
    scanned = threading.Event()
    monitor = NetworkSecurityMonitor(
        interval_seconds=0.01,
        snapshot_source=lambda: scanned.set() or NetworkSnapshot(status="available"),
    )
    monitor.start()
    assert scanned.wait(1)
    assert monitor.stop(timeout=1) is True
    assert monitor._thread is None


def test_monitor_defaults_to_thirty_second_polling_interval():
    assert NetworkSecurityMonitor().interval_seconds == 30.0


def test_empty_and_malformed_parser_inputs_are_safe():
    assert parse_wifi_interfaces("") == {
        "status": "unavailable",
        "connected_interfaces": 0,
        "signal_percent": -1,
        "security": "unknown",
    }
    assert parse_wifi_interfaces(
        "Name: adapter\nState: connected\nSignal: 150%\nAuthentication: unknown\n"
    ) == {
        "status": "available",
        "connected_interfaces": 1,
        "signal_percent": -1,
        "security": "unknown",
    }
    assert parse_ipconfig("") == {
        "status": "unavailable",
        "local_ipv4_interfaces": 0,
        "dns_servers": 0,
    }
    assert parse_ipconfig("IPv4 Address: not-an-ip\nDNS Servers: invalid")[
        "local_ipv4_interfaces"
    ] == 0
    assert parse_firewall("") == {
        "status": "unknown",
        "enabled_profiles": 0,
        "disabled_profiles": 0,
        "unknown_profiles": 0,
    }
    assert parse_firewall("State: weird")["unknown_profiles"] == 0
    assert parse_firewall("State: OFF\nState: disabled")["status"] == "disabled"
    assert parse_neighbors("") == {
        "status": "unavailable",
        "devices": 0,
        "dynamic": 0,
        "static": 0,
        "other": 0,
    }
    assert parse_neighbors("header\nnot-an-ip aa-bb-cc-dd-ee-ff dynamic")["devices"] == 0
    assert parse_neighbors("192.0.2.2 aa-bb-cc-dd-ee-ff permanent")["static"] == 1
    assert parse_neighbors("192.0.2.3 aa-bb-cc-dd-ee-ff unusual")["other"] == 1


def test_address_helpers_handle_psutil_and_malformed_addresses():
    assert network_security_core._address_ip(None) is None
    assert network_security_core._address_ip(SimpleNamespace(ip="192.0.2.1")) == "192.0.2.1"
    assert network_security_core._address_ip(("192.0.2.2", 53)) == "192.0.2.2"
    assert network_security_core._address_ip("not-an-address") is None
    assert network_security_core._is_usable_local_ip("192.168.1.1")
    assert network_security_core._is_usable_local_ip("fe80::1%12")
    assert not network_security_core._is_usable_local_ip("127.0.0.1")
    assert not network_security_core._is_usable_local_ip("0.0.0.0")
    assert not network_security_core._is_usable_local_ip("invalid")
    assert parse_listening_ports(
        [
            SimpleNamespace(status="LISTEN", laddr=("bad", 0), pid=None),
            SimpleNamespace(status="LISTEN", laddr=None, pid=None),
            SimpleNamespace(status="LISTEN", laddr=("::", 0), pid=4),
        ]
    ) == {
        "listening_sockets": 3,
        "network_bound_listeners": 1,
        "listeners_with_pid": 1,
    }


def test_local_subprocess_helpers_cover_command_failure_paths(monkeypatch, caplog):
    def raise_oserror(*_args, **_kwargs):
        raise OSError("private command path")

    monkeypatch.setattr(network_security_core.subprocess, "run", raise_oserror)
    assert network_security_core._run_netsh("wlan", "show") == ""
    assert network_security_core._run_command(["ipconfig"], "query") == ""
    assert "OSError" in caplog.text
    assert "private command path" not in caplog.text

    monkeypatch.setattr(
        network_security_core.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="sensitive"),
    )
    assert network_security_core._run_netsh("wlan") == ""
    assert network_security_core._run_command(["ipconfig"], "query") == ""

    monkeypatch.setattr(
        network_security_core.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="safe output"),
    )
    assert network_security_core._run_netsh("wlan") == "safe output"
    assert network_security_core._run_command(["ipconfig"], "query") == "safe output"


def test_collect_network_snapshot_summarizes_psutil_and_netsh_without_data_leaks(
    monkeypatch,
):
    connections = [
        _connection("ESTABLISHED", "192.0.2.20", 443),
        _connection("LISTEN", "0.0.0.0", 22),
    ]
    interface_stats = {
        "Wi-Fi Casa": SimpleNamespace(isup=True),
        "WireGuard Tunnel": SimpleNamespace(isup=True),
        "Ethernet Spenta": SimpleNamespace(isup=False),
    }
    interface_addresses = {
        "Wi-Fi Casa": [
            SimpleNamespace(family=2, address="192.168.1.3"),
            SimpleNamespace(family=2, address="127.0.0.1"),
        ],
        "WireGuard Tunnel": [SimpleNamespace(family=2, address="10.0.0.2")],
        "Ethernet Spenta": [SimpleNamespace(family=2, address="10.0.0.3")],
    }
    fake_psutil = SimpleNamespace(
        net_connections=lambda **_kwargs: connections,
        net_if_stats=lambda: interface_stats,
        net_if_addrs=lambda: interface_addresses,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(network_security_core, "_run_netsh", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        network_security_core,
        "_run_command",
        lambda *_args, **_kwargs: "IPv4 Address: 10.1.1.9\nDNS Servers: 10.1.1.1",
    )

    result = network_security_core._collect_network_snapshot().as_dict()

    assert result["status"] == "available"
    assert result["socket_status"] == "available"
    assert result["established_connections"] == 1
    assert result["listening_sockets"] == 1
    assert result["listeners_with_pid"] == 1
    assert result["interfaces"] == {
        "status": "available",
        "active_interfaces": 2,
        "connected": True,
        "local_ipv4_interfaces": 2,
        "dns_servers": 1,
    }
    assert result["vpn"] == {
        "status": "available",
        "detected": True,
        "active_vpn_interfaces": 1,
    }
    assert "192.168.1.3" not in repr(result)
    assert "WireGuard Tunnel" not in repr(result)
    assert "10.1.1.1" not in repr(result)


def test_collect_network_snapshot_handles_socket_and_interface_errors(monkeypatch):
    fake_psutil = SimpleNamespace(
        net_connections=lambda **_kwargs: (_ for _ in ()).throw(PermissionError()),
        net_if_stats=lambda: (_ for _ in ()).throw(OSError()),
        net_if_addrs=lambda: {},
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(network_security_core, "_run_netsh", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        network_security_core,
        "_run_command",
        lambda *_args, **_kwargs: "",
    )

    result = network_security_core._collect_network_snapshot()

    assert result.status == "unavailable"
    assert result.socket_status == "unavailable"
    assert result.interfaces["status"] == "unavailable"
    assert result.vpn["detected"] is False
    assert result.listening_sockets == 0


def test_public_ip_invalid_response_and_transport_error_are_safe():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def read(self, _limit):
            return b"not-an-ip"

    assert read_public_ip_metadata(opener=lambda *_a, **_k: Response()) == {
        "status": "unavailable",
        "address_family": "unknown",
    }
    assert read_public_ip_metadata(
        opener=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError())
    ) == {"status": "unavailable", "address_family": "unknown"}


def test_ping_handles_command_error_and_incomplete_localized_output():
    assert read_ping_summary(
        runner=lambda *_a, **_k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("ping", 7)
        )
    ) == {
        "status": "unavailable",
        "packets_sent": 0,
        "packets_lost": 0,
        "average_ms": -1,
    }
    localized = read_ping_summary(
        runner=lambda *_a, **_k: SimpleNamespace(
            stdout=(
                "Pacchetti: Trasmessi = 8, Ricevuti = 9, Persi = 0\n"
                "Media = 7ms"
            ),
            returncode=1,
        )
    )
    assert localized == {
        "status": "available",
        "packets_sent": 5,
        "packets_lost": 0,
        "average_ms": 7,
    }
    assert read_ping_summary(
        runner=lambda *_a, **_k: SimpleNamespace(stdout="", returncode=1)
    )["status"] == "unavailable"


def test_monitor_validates_options_and_catches_poll_errors():
    with pytest.raises(ValueError):
        NetworkSecurityMonitor(interval_seconds=0)
    with pytest.raises(ValueError):
        NetworkSecurityMonitor(interval_seconds=float("nan"))
    with pytest.raises(ValueError):
        NetworkSecurityMonitor().stop(timeout=-1)

    monitor = NetworkSecurityMonitor(
        snapshot_source=lambda: (_ for _ in ()).throw(RuntimeError("private")),
    )
    result = monitor.scan()
    assert result["status"] == "unavailable"
    assert "private" not in repr(result)


def test_snapshot_does_not_start_a_worker_independently_of_the_hub():
    polls = []
    monitor = NetworkSecurityMonitor(
        interval_seconds=60,
        snapshot_source=lambda: polls.append(1) or NetworkSnapshot(status="available"),
    )

    result = monitor.snapshot()

    assert result["status"] == "not_checked"
    assert result["sampled_at_monotonic"] is None
    assert len(polls) == 0
    assert monitor._thread is None
    monitor.start()
    assert monitor._thread is not None and monitor._thread.is_alive()
    assert monitor.stop(timeout=1)


def test_snapshot_and_status_remain_fast_while_initial_worker_poll_is_blocked():
    entered = threading.Event()
    release = threading.Event()
    sampled = threading.Event()

    def blocked_source():
        entered.set()
        assert release.wait(5)
        sampled.set()
        return NetworkSnapshot(
            status="available",
            wifi={"status": "available", "signal_percent": 71},
            interfaces={"status": "available", "connected": True},
        )

    monitor = NetworkSecurityMonitor(interval_seconds=60, snapshot_source=blocked_source)
    assert monitor.snapshot()["sampled_at_monotonic"] is None
    try:
        before_start = time.monotonic()
        monitor.start()
        assert entered.wait(1), "first poll should start immediately, not after 60s"
        started = time.monotonic()
        snapshot = monitor.snapshot()
        status = monitor.status()
        assert time.monotonic() - started < 0.1
        assert snapshot["status"] == status["status"] == "not_checked"
        assert snapshot["sampled_at_monotonic"] is None
        assert status["sampled_at_monotonic"] is None

        before_release = time.monotonic()
        release.set()
        assert sampled.wait(1)
        deadline = time.monotonic() + 1
        while monitor.status()["sampled_at_monotonic"] is None and time.monotonic() < deadline:
            time.sleep(0.001)
        result = monitor.snapshot()
        assert result["status"] == "available"
        assert before_start <= before_release <= result["sampled_at_monotonic"] <= time.monotonic()
        assert result["wifi_signal_percent"] == 71
        assert result["connected"] is True
        assert "ssid" not in repr(result).lower()
        assert "address" not in repr(result).lower()
    finally:
        release.set()
        assert monitor.stop(timeout=1)


def test_cancelled_worker_poll_never_publishes_timestamp_or_partial_data():
    entered = threading.Event()
    release = threading.Event()

    def blocked_source():
        entered.set()
        assert release.wait(5)
        return NetworkSnapshot(status="available", established_connections=123)

    monitor = NetworkSecurityMonitor(interval_seconds=60, snapshot_source=blocked_source)
    try:
        monitor.start()
        assert entered.wait(1)
        assert monitor.stop(timeout=0) is False
        release.set()
        assert monitor.stop(timeout=1) is True
        snapshot = monitor.status()
        assert snapshot["status"] == "not_checked"
        assert snapshot["sampled_at_monotonic"] is None
        assert snapshot["established_connections"] == 0
    finally:
        release.set()
        monitor.stop(timeout=1)


def test_completed_failed_scan_records_monotonic_time_without_private_error():
    def fail():
        raise OSError("private network data")

    monitor = NetworkSecurityMonitor(snapshot_source=fail)
    before = time.monotonic()
    result = monitor.scan()
    assert result["status"] == "unavailable"
    assert before <= result["sampled_at_monotonic"] <= time.monotonic()
    assert "private network data" not in repr(result)


def test_weak_wifi_duration_uses_consecutive_actual_samples_and_resets_on_gap(monkeypatch):
    class FakeTime:
        now = 100.0

        def monotonic(self):
            return self.now

    clock = FakeTime()
    monkeypatch.setattr(network_security_core, "time", clock)
    sample = {"signal": 29, "status": "available", "connected": 1}

    def source():
        return NetworkSnapshot(
            status="available",
            wifi={
                "status": sample["status"],
                "signal_percent": sample["signal"],
                "connected_interfaces": sample["connected"],
            },
        )

    monitor = NetworkSecurityMonitor(interval_seconds=30, snapshot_source=source)
    assert monitor.snapshot()["wifi_weak_seconds"] == 0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    clock.now = 130.0
    assert monitor.scan()["wifi_weak_seconds"] == 30
    clock.now = 190.0
    assert monitor.scan()["wifi_weak_seconds"] == 90
    clock.now = 251.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    clock.now = 281.0
    assert monitor.scan()["wifi_weak_seconds"] == 30
    sample["signal"] = 30
    clock.now = 311.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    sample["signal"] = 10
    clock.now = 341.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    sample["status"] = "unavailable"
    clock.now = 371.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    sample["status"] = "available"
    sample["connected"] = 0
    clock.now = 401.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    sample["connected"] = 1
    sample["signal"] = -1
    clock.now = 431.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    sample["signal"] = 0
    clock.now = 461.0
    assert monitor.scan()["wifi_weak_seconds"] == 0
    clock.now = 491.0
    assert monitor.scan()["wifi_weak_seconds"] == 30
    clock.now = 5000.0
    assert monitor.snapshot()["wifi_weak_seconds"] == 30


def test_public_ip_reader_failure_is_reported_without_caching_address():
    calls = []

    def fail():
        calls.append(True)
        raise OSError("private address data")

    monitor = NetworkSecurityMonitor(public_ip_reader=fail)
    with pytest.raises(OSError):
        monitor.public_ip_metadata()
    with pytest.raises(OSError):
        monitor.public_ip_metadata()
    assert len(calls) == 2


def test_facade_getter_returns_only_network_module_from_existing_hub(monkeypatch):
    monitor = NetworkSecurityMonitor(snapshot_source=lambda: NetworkSnapshot(status="available"))

    class Hub:
        def get_module(self, name):
            assert name == "network"
            return monitor

    seen = []
    monkeypatch.setattr(
        "core.symbiosis_hub.get_symbiosis_hub",
        lambda *, start: seen.append(start) or Hub(),
    )

    assert network_security_core.get_network_security_monitor() is monitor
    assert seen == [False]

    monkeypatch.setattr(
        "core.symbiosis_hub.get_symbiosis_hub",
        lambda *, start: None,
    )
    assert network_security_core.get_network_security_monitor() is None


def test_actions_return_explicit_disabled_error_without_starting_independent_work(
    monkeypatch,
):
    modules = (
        network_security_action,
        check_wifi,
        check_public_ip,
        check_vpn,
        check_firewall,
        list_open_ports,
        list_network_devices,
    )
    for module in modules:
        monkeypatch.setattr(module, "get_network_security_monitor", lambda: None)
    monkeypatch.setattr(network_security_core, "get_network_security_monitor", lambda: None)
    monkeypatch.setattr(
        speed_test,
        "get_network_security_monitor",
        lambda: None,
    )
    monkeypatch.setattr(
        speed_test,
        "read_ping_summary",
        lambda: pytest.fail("ping must not run when the hub module is disabled"),
    )

    for module in modules:
        response = module.TOOL["handler"]({})
        assert "Errore" in response
        assert "network" in response
        assert "non selezionato o non attivo" in response
    assert "Errore" in speed_test.TOOL["handler"]({})


def test_snapshot_schema_has_facade_connection_and_wifi_signal_keys():
    snapshot = NetworkSnapshot(
        status="available",
        interfaces={"connected": True},
        wifi={"signal_percent": 73},
    ).as_dict()

    assert snapshot["connected"] is True
    assert snapshot["wifi_signal_percent"] == 73
    assert snapshot["interfaces"]["connected"] is True


def test_local_poll_uses_short_command_timeouts_and_honors_stop_between_queries(
    monkeypatch,
):
    spec = importlib.util.spec_from_file_location(
        "_isolated_network_security_timeout_test",
        Path(network_security_core.__file__),
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    fake_psutil = SimpleNamespace(
        net_connections=lambda **_kwargs: [],
        net_if_stats=lambda: {},
        net_if_addrs=lambda: {},
    )
    real_import = builtins.__import__

    def local_import(name, *args, **kwargs):
        if name == "psutil":
            return fake_psutil
        return real_import(name, *args, **kwargs)

    module.__dict__["__builtins__"] = {**vars(builtins), "__import__": local_import}
    spec.loader.exec_module(module)
    stop_event = threading.Event()
    calls = []
    original_netsh = module._run_netsh
    original_command = module._run_command

    def netsh(*arguments, stop_event=None):
        calls.append(("netsh", arguments))
        if len(calls) == 1:
            stop_event.set()
        return "output"

    monkeypatch.setattr(module, "_run_netsh", netsh)
    monkeypatch.setattr(
        module,
        "_run_command",
        lambda *_args, **_kwargs: pytest.fail("must stop before ipconfig"),
    )
    result = module._collect_network_snapshot(stop_event=stop_event)

    assert result.status == "stopping"
    assert calls == [("netsh", ("wlan", "show", "interfaces"))]

    monkeypatch.setattr(module, "_run_netsh", original_netsh)
    monkeypatch.setattr(module, "_run_command", original_command)
    run_calls = []

    def runner(arguments, **kwargs):
        run_calls.append(kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="")

    module.subprocess = SimpleNamespace(
        run=runner,
        SubprocessError=subprocess.SubprocessError,
        CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    module._run_netsh("wlan", "show")
    module._run_command(["ipconfig"], "query")
    assert run_calls == [0.5, 0.5]


@pytest.mark.parametrize("operation", ["netsh", "ipconfig", "ping"])
def test_console_output_decoding_replaces_invalid_bytes_without_logging(
    monkeypatch, caplog, operation,
):
    child = (
        "import sys; sys.stdout.buffer.write("
        "b'Sent = 5, Received = 4, Average = 8ms\\nprivate-\\x8d'); "
        "sys.stderr.buffer.write(b'private-\\x8d')"
    )
    calls = []

    def runner(_arguments, **kwargs):
        calls.append(kwargs)
        return subprocess.run([sys.executable, "-c", child], **kwargs)

    fake_subprocess = SimpleNamespace(
        run=runner,
        SubprocessError=subprocess.SubprocessError,
        CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    monkeypatch.setattr(network_security_core, "subprocess", fake_subprocess)
    monkeypatch.setattr(network_security_core, "_CONSOLE_ENCODING", "cp1252")

    if operation == "netsh":
        result = network_security_core._run_netsh("wlan", "show")
        assert "private-\ufffd" in result
    elif operation == "ipconfig":
        result = network_security_core._run_command(["ipconfig"], "query", timeout=3)
        assert "private-\ufffd" in result
    else:
        result = network_security_core.read_ping_summary()
        assert result["packets_sent"] == 5
        assert result["packets_lost"] == 1
        assert result["average_ms"] == 8
        assert "private" not in repr(result)

    assert calls[0]["encoding"] == "cp1252"
    assert calls[0]["errors"] == "replace"
    assert "private" not in caplog.text


def test_local_wifi_details_preserve_wpa_and_disconnected_interface(monkeypatch, caplog):
    output = (
        "Name : Wi-Fi personale\nState : connected\nSSID : ReteCasa\n"
        "BSSID : aa-bb-cc-dd-ee-ff\nSignal : 78%\n"
        "Authentication : WPA2-Personal\nCipher : CCMP\n"
        "Name : Wi-Fi 2\nState : connected\nSSID : ReteOspiti\n"
        "Signal : 50%\nAuthentication : WPA3-Personal\nCipher : GCMP\n"
        "Nome : Wi-Fi 3\nStato : disconnesso\nSSID : dato-obsoleto\n"
    )
    monkeypatch.setattr(network_security_core, "_run_netsh", lambda *_a: output)

    result = network_security_core.local_wifi_details()

    assert result["status"] == "available"
    assert result["interfaces"] == [
        {
            "interface": "Wi-Fi personale", "state": "connected", "ssid": "ReteCasa",
            "signal_percent": 78, "security": "WPA2-Personal", "cipher": "CCMP",
        },
        {
            "interface": "Wi-Fi 2", "state": "connected", "ssid": "ReteOspiti",
            "signal_percent": 50, "security": "WPA3-Personal", "cipher": "GCMP",
        },
        {
            "interface": "Wi-Fi 3", "state": "disconnesso", "ssid": None,
            "signal_percent": None, "security": None, "cipher": None,
        },
    ]
    assert "ReteCasa" not in caplog.text
    assert "aa-bb-cc" not in repr(result)


def test_local_interface_details_pairs_ipv4_ipv6_and_dns_by_adapter(monkeypatch):
    fake_psutil = SimpleNamespace(
        net_if_addrs=lambda: {
            "Wi-Fi": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.10.22"),
                SimpleNamespace(family=socket.AF_INET6, address="fe80::123%7"),
            ],
            "Ethernet": [SimpleNamespace(family=socket.AF_INET, address="10.0.0.2")],
        },
        net_if_stats=lambda: {
            "Wi-Fi": SimpleNamespace(isup=True),
            "Ethernet": SimpleNamespace(isup=False),
        },
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(
        network_security_core, "_run_command",
        lambda *_a: (
            "Scheda LAN wireless Wi-Fi:\n"
            "   Server DNS . . . . . . . : 192.168.10.1\n"
            "                               2001:db8::1\n"
            "   Nome DHCP . . . . . . . : ignored\n\n"
            "Ethernet adapter Ethernet:\n"
            "   DNS Servers . . . . . : 10.0.0.1\n"
        ),
    )
    result = network_security_core.local_interface_details()
    assert result["status"] == "available"
    assert result["dns_status"] == "available"
    entries = {item["name"]: item for item in result["interfaces"]}
    assert entries["Wi-Fi"]["addresses"] == [
        {"family": "IPv4", "address": "192.168.10.22"},
        {"family": "IPv6", "address": "fe80::123%7"},
    ]
    assert entries["Wi-Fi"]["dns_servers"] == ["192.168.10.1", "2001:db8::1"]
    assert entries["Ethernet"]["dns_servers"] == ["10.0.0.1"]
    assert entries["Ethernet"]["is_up"] is False


def test_local_listening_ports_and_neighbors_only_return_local_data(monkeypatch):
    fake_psutil = SimpleNamespace(net_connections=lambda **_kwargs: [
        SimpleNamespace(
            status="LISTEN", laddr=SimpleNamespace(ip="127.0.0.1", port=1234),
            family=socket.AF_INET, pid=456,
        ),
        SimpleNamespace(
            status="LISTEN", laddr=("::", 443),
            family=socket.AF_INET6, pid=None,
        ),
        _connection("ESTABLISHED", "192.0.2.1"),
    ])
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(
        network_security_core, "_run_netsh",
        lambda *_a: (
            "192.168.1.1  00-11-22-33-44-55  Reachable\n"
            "192.168.1.255  ff-ff-ff-ff-ff-ff  Permanent\n"
            "192.168.1.9 incomplete Unreachable\n"
        ),
    )
    assert network_security_core.local_listening_ports() == {
        "status": "available",
        "listeners": [
            {"address": "127.0.0.1", "port": 1234, "pid": 456, "family": "IPv4"},
            {"address": "::", "port": 443, "pid": None, "family": "IPv6"},
        ],
    }
    assert network_security_core.local_network_neighbors() == {
        "status": "available",
        "neighbors": [
            {"ip": "192.168.1.1", "mac": "00-11-22-33-44-55", "state": "Reachable"},
            {"ip": "192.168.1.255", "mac": "ff-ff-ff-ff-ff-ff", "state": "Permanent"},
        ],
    }


def test_local_public_ip_cache_timeout_and_private_snapshot(monkeypatch, caplog):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            del exc_info

        def read(self, size):
            assert size == 64
            return b"198.51.100.8"

    clock = [0.0]
    calls = []

    def opener(url, *, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(network_security_core.urllib.request, "urlopen", opener)
    monitor = NetworkSecurityMonitor(clock=lambda: clock[0])
    assert monitor.local_public_ip() == {"status": "available", "address": "198.51.100.8"}
    clock[0] = 59.9
    copy = monitor.local_public_ip()
    copy["address"] = "modified"
    assert monitor.local_public_ip()["address"] == "198.51.100.8"
    assert len(calls) == 1
    clock[0] = 60.0
    assert monitor.local_public_ip()["address"] == "198.51.100.8"
    assert calls == [("https://api.ipify.org", 3.0)] * 2
    assert "198.51.100.8" not in repr(monitor.status())
    assert "198.51.100.8" not in caplog.text


def test_local_public_ip_failure_is_cached_and_does_not_log_address(monkeypatch, caplog):
    calls = []

    def opener(_url, *, timeout):
        calls.append(timeout)
        raise TimeoutError("198.51.100.8 private information")

    monkeypatch.setattr(network_security_core.urllib.request, "urlopen", opener)
    monitor = NetworkSecurityMonitor(clock=lambda: 0.0)
    assert monitor.local_public_ip() == {"status": "unavailable", "address": None}
    assert monitor.local_public_ip() == {"status": "unavailable", "address": None}
    assert monitor.public_ip_metadata() == {
        "status": "unavailable", "address_family": "unknown",
    }
    assert calls == [3.0]
    assert "TimeoutError" in caplog.text
    assert "198.51.100.8" not in caplog.text
    assert all(
        record.message.startswith("[SYMBIOSIS][NETWORK]")
        for record in caplog.records
        if record.name == network_security_core.__name__
    )


def test_local_details_fail_closed_without_exposing_errors(monkeypatch, caplog):
    def denied(*_args, **_kwargs):
        raise PermissionError("192.0.2.10 private process")

    fake_psutil = SimpleNamespace(
        net_connections=denied, net_if_addrs=denied, net_if_stats=denied,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(network_security_core, "_run_netsh", lambda *_args: "")

    assert network_security_core.local_interface_details() == {
        "status": "unavailable", "dns_status": "unavailable", "interfaces": [],
    }
    assert network_security_core.local_listening_ports() == {
        "status": "unavailable", "listeners": [],
    }
    assert network_security_core.local_wifi_details() == {
        "status": "unavailable", "interfaces": [],
    }
    assert network_security_core.local_network_neighbors() == {
        "status": "unavailable", "neighbors": [],
    }
    assert "192.0.2.10" not in caplog.text
    assert all(
        record.message.startswith("[SYMBIOSIS][NETWORK]")
        for record in caplog.records
        if record.name == network_security_core.__name__
    )


@pytest.mark.parametrize("first", ["metadata", "local"])
def test_public_metadata_and_local_ip_share_cache(monkeypatch, first):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            del exc_info

        def read(self, size):
            assert size == 64
            return b"203.0.113.42"

    def opener(url, *, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(network_security_core.urllib.request, "urlopen", opener)
    now = [0.0]
    monitor = NetworkSecurityMonitor(clock=lambda: now[0])
    if first == "metadata":
        public = monitor.public_ip_metadata()
        local = monitor.local_public_ip()
    else:
        local = monitor.local_public_ip()
        public = monitor.public_ip_metadata()
    assert local["address"] == "203.0.113.42"
    assert public == {"status": "available", "address_family": "IPv4"}
    assert "203.0.113.42" not in repr(public)
    assert "203.0.113.42" not in repr(monitor.status())
    assert calls == [("https://api.ipify.org", 3.0)]
    now[0] = 60.0
    assert monitor.public_ip_metadata() == public
    assert monitor.local_public_ip() == local
    assert len(calls) == 2


def test_injected_metadata_reader_is_shared_without_inventing_address():
    calls = []
    monitor = NetworkSecurityMonitor(
        clock=lambda: 0.0,
        public_ip_reader=lambda: calls.append(1) or {
            "status": "available", "address_family": "IPv6",
        },
    )
    assert monitor.public_ip_metadata() == {
        "status": "available", "address_family": "IPv6",
    }
    assert monitor.local_public_ip() == {"status": "unavailable", "address": None}
    assert calls == [1]


def test_public_ip_concurrent_local_and_metadata_requests_share_one_acquisition(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def reader():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return {"status": "available", "address": "203.0.113.99"}

    monkeypatch.setattr(network_security_core, "_read_local_public_ip", reader)
    monitor = NetworkSecurityMonitor(clock=lambda: 0.0)
    results = {}
    first = threading.Thread(target=lambda: results.update(local=monitor.local_public_ip()))
    second = threading.Thread(target=lambda: results.update(metadata=monitor.public_ip_metadata()))
    first.start()
    assert entered.wait(1)
    second.start()
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == [1]
    assert results == {
        "local": {"status": "available", "address": "203.0.113.99"},
        "metadata": {"status": "available", "address_family": "IPv4"},
    }


def test_local_details_never_flow_into_snapshot_or_model_actions(monkeypatch, caplog):
    fake_psutil = SimpleNamespace(
        net_connections=lambda **_kwargs: [
            SimpleNamespace(
                status="LISTEN", laddr=("192.168.11.20", 8877),
                pid=9988, family=socket.AF_INET,
            ),
        ],
        net_if_stats=lambda: {"PrivateAdapter": SimpleNamespace(isup=True)},
        net_if_addrs=lambda: {
            "PrivateAdapter": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.11.20"),
            ],
        },
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    def netsh(*args, **_kwargs):
        if args[:2] == ("wlan", "show"):
            return (
                "Name: PrivateAdapter\nState: connected\nSSID: SecretSSID\n"
                "Signal: 91%\nAuthentication: WPA3-Personal\n"
            )
        if args[0] == "interface":
            return "192.168.11.30 aa-bb-cc-dd-ee-ff Reachable\n"
        return "State ON"

    monkeypatch.setattr(network_security_core, "_run_netsh", netsh)
    monkeypatch.setattr(
        network_security_core,
        "_run_command",
        lambda *_args, **_kwargs: (
            "Ethernet adapter PrivateAdapter:\n"
            "DNS Servers: 192.168.11.1\n"
        ),
    )
    monitor = NetworkSecurityMonitor()
    monkeypatch.setattr(check_wifi, "get_network_security_monitor", lambda: monitor)
    monkeypatch.setattr(list_open_ports, "get_network_security_monitor", lambda: monitor)
    monkeypatch.setattr(list_network_devices, "get_network_security_monitor", lambda: monitor)

    assert network_security_core.local_wifi_details()["interfaces"][0]["ssid"] == "SecretSSID"
    assert network_security_core.local_listening_ports()["listeners"][0]["pid"] == 9988
    snapshot = monitor.scan()
    exposed = repr(snapshot) + " ".join(
        module.TOOL["handler"]({})
        for module in (check_wifi, list_open_ports, list_network_devices)
    )
    for private_value in (
        "SecretSSID", "PrivateAdapter", "192.168.11.20", "192.168.11.30",
        "192.168.11.1", "aa-bb-cc-dd-ee-ff", "8877", "9988",
    ):
        assert private_value not in exposed
        assert private_value not in caplog.text
