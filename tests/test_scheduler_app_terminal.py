from pathlib import Path

from actions import app_launcher
from core.terminal_guard import TerminalGuard


def test_local_appdata_discovery_outside_programs(monkeypatch, tmp_path):
    root = tmp_path / "Local"
    executable = root / "Vendor" / "Example" / "example.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test")
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("WINDIR", raising=False)
    import time
    result = app_launcher._walk_for_name(app_launcher._known_directories(), "example", time.monotonic() + 5)
    assert result == executable.resolve()
    assert not app_launcher._is_whitelisted(result)


def test_program_files_discovery_with_spaces(monkeypatch, tmp_path):
    root = tmp_path / "Program Files"
    executable = root / "A Vendor" / "Example App" / "example.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test")
    monkeypatch.setenv("ProgramFiles", str(root))
    for variable in ("ProgramFiles(x86)", "ProgramW6432", "WINDIR"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing"))
    import time
    result = app_launcher._walk_for_name(app_launcher._known_directories(), "example", time.monotonic() + 5)
    assert result == executable.resolve()


def test_launch_app_discovers_local_appdata_outside_path(monkeypatch, tmp_path):
    root = tmp_path / "Local"
    executable = root / "Vendor Name" / "Example App" / "example.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test")
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "WINDIR"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(app_launcher, "_find_on_path", lambda _name: None)
    monkeypatch.setattr(app_launcher, "_remember", lambda *_args: None)
    monkeypatch.setattr(app_launcher, "_is_blocked", lambda _path: False)
    monkeypatch.setattr(app_launcher, "_audit", lambda *_args: None)
    monkeypatch.setattr(app_launcher, "_wait_for_launched_app", lambda *_args: None)
    started = []
    monkeypatch.setattr(app_launcher.os, "startfile", started.append, raising=False)
    assert "confirmation" in app_launcher.launch_app("example").lower()
    assert started == []
    assert "Launch requested" in app_launcher.launch_app("example", confirmed=True)
    assert started == [str(executable.resolve())]


def test_ipconfig_read_only_arguments():
    guard = TerminalGuard()
    assert guard.inspect("ipconfig").allowed
    assert guard.inspect("ipconfig /all").allowed
    assert guard.inspect("ipconfig /release").blocked
    assert guard.inspect("ipconfig /renew").blocked
    assert guard.inspect("ipconfig && format C:").blocked


def test_ping_allows_only_a_single_target():
    guard = TerminalGuard()
    assert guard.inspect("ping example.com").allowed
    assert guard.inspect("ping -t example.com").blocked
    assert guard.inspect("ping example.com && echo hello").blocked
    assert guard.inspect("ping").blocked
