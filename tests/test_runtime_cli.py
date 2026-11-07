from __future__ import annotations

import os
from types import SimpleNamespace

import main


def test_hud_port_cli_overrides_environment(monkeypatch, capsys):
    observed = {}

    class FakeUI:
        def __init__(self, _face):
            self._app = SimpleNamespace(quit=lambda: None)
            self.root = SimpleNamespace(mainloop=lambda: None)

        def show_hud_browser(self, url):
            observed["url"] = url

    class FakeHud:
        def __init__(self):
            self.port = int(os.environ["JARVIS_HUD_PORT"])

        def start(self, window):
            observed["window"] = window
            observed["configured_port"] = self.port
            self.port = 43210
            return self.url

        @property
        def url(self):
            return f"http://127.0.0.1:{self.port}/"

        def stop(self):
            observed["stopped"] = True

    monkeypatch.setenv("JARVIS_HUD_PORT", "8765")
    monkeypatch.setattr("core.logging_config.configure_logging", lambda: None)
    monkeypatch.setattr(main, "JarvisUI", FakeUI)
    monkeypatch.setattr(main, "HudBridge", FakeHud)
    monkeypatch.setattr("PyQt6.QtCore.QTimer.singleShot", lambda *_args: None)

    main.main(["--startup-smoke", "--hud-port", "0"])

    assert observed == {
        "url": "http://127.0.0.1:43210/",
        "configured_port": 0,
        "window": "none",
        "stopped": True,
    }
    assert "JARVIS_STARTUP_READY http://127.0.0.1:43210/" in capsys.readouterr().out


def test_invalid_hud_port_is_rejected(monkeypatch):
    monkeypatch.setattr("core.logging_config.configure_logging", lambda: None)

    try:
        main.main(["--hud-port", "65536"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("Out-of-range HUD ports must be rejected.")
