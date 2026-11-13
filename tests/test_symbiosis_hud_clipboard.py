import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from core.hud_bridge import HudBridge


def test_clipboard_hud_requires_header_and_only_reveals_on_request():
    hud = HudBridge(port=0)
    calls = []
    hud.clipboard_history_provider = lambda: calls.append(True) or [
        {"content": "<private>", "type": "text", "timestamp": "now"}
    ]
    hud.start(window="none")
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(hud.url + "api/symbiosis/clipboard", timeout=3)
        assert exc.value.code == 403
        assert not calls
        request = Request(hud.url + "api/symbiosis/clipboard", headers={"X-HUD": "1"})
        with urlopen(request, timeout=3) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert json.load(response)["items"][0]["content"] == "<private>"
        assert calls == [True]
    finally:
        hud.stop()


def test_clipboard_hud_marks_disabled():
    hud = HudBridge(port=0)
    hud.start(window="none")
    try:
        request = Request(hud.url + "api/symbiosis/clipboard", headers={"X-HUD": "1"})
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=3)
        assert exc.value.code == 503
    finally:
        hud.stop()


def test_network_details_require_explicit_local_request():
    hud = HudBridge(port=0)
    calls = []
    hud.network_details_provider = lambda category: calls.append(category) or {
        "status": "available", "address": "private-network-data"
    }
    hud.start(window="none")
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(hud.url + "api/symbiosis/network/public_ip", timeout=3)
        assert exc.value.code == 403
        assert not calls
        request = Request(hud.url + "api/symbiosis/network/public_ip", headers={"X-HUD": "1"})
        with urlopen(request, timeout=3) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert json.load(response)["address"] == "private-network-data"
        assert calls == ["public_ip"]
        request = Request(hud.url + "api/symbiosis/network/unknown", headers={"X-HUD": "1"})
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=3)
        assert exc.value.code == 404
    finally:
        hud.stop()


def test_local_network_details_never_in_public_hud_or_context(monkeypatch):
    from core import network_security
    from core.symbiosis_hub import SymbiosisHub

    class Network:
        def start(self):
            pass

        def stop(self, timeout=3):
            return True

        def snapshot(self):
            return {"connected": True}

        def local_public_ip(self):
            return {"address": "private-ip"}

    network = Network()
    hub = SymbiosisHub(modules={"network"}, factories={"network": lambda: network})
    hub.start()
    try:
        assert hub.get_local_network_details("public_ip")["address"] == "private-ip"
        assert "private-ip" not in repr(hub.get_hud_state())
        assert "private-ip" not in repr(hub.get_context_summary())
        monkeypatch.setattr(network_security, "local_wifi_details", lambda: {"ssid": "private-ssid"})
        assert hub.get_local_network_details("wifi")["ssid"] == "private-ssid"
        assert "private-ssid" not in repr(hub.get_full_symbiosis_state())
        with pytest.raises(ValueError):
            hub.get_local_network_details("invalid")
    finally:
        hub.shutdown()
