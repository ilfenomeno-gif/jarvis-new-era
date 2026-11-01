from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from actions import app_launcher
from actions import open_app as open_app_module
from core import computer_use, pattern_learner, registry_cli
from core.action_loader import discover_actions
from core.intent_router import route_tool


def _write_pe_executable(path: Path, subsystem: int) -> None:
    data = bytearray(0x200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84 + 16, 0xE0)
    struct.pack_into("<H", data, 0x98 + 68, subsystem)
    path.write_bytes(data)


def _configure_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(app_launcher, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(app_launcher, "LOG_PATH", tmp_path / "logs" / "app_launcher.log")
    monkeypatch.setattr(app_launcher, "_known_directories", lambda: ())
    monkeypatch.setattr(app_launcher, "_start_menu_directories", lambda: ())
    monkeypatch.setattr(app_launcher, "_find_in_registry", lambda _name: None)
    monkeypatch.setattr(app_launcher, "_BLOCKED_PARTS", frozenset({"downloads"}))
    monkeypatch.setenv("TEMP", str(tmp_path.parent / "other-temp"))
    monkeypatch.setenv("TMP", str(tmp_path.parent / "other-temp"))
    monkeypatch.setattr(computer_use, "wait_for_foreground", lambda *_args, **_kwargs: True)


def test_find_executable_uses_path_and_remembers_result(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Code.exe"
    executable.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "_find_on_path", lambda _name: executable)

    assert app_launcher.find_executable("code") == executable.resolve()
    assert json.loads(app_launcher.CACHE_PATH.read_text(encoding="utf-8")) == {
        "code": str(executable.resolve())
    }


def test_find_executable_uses_shutil_which_for_named_exe(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Code.exe"
    executable.write_bytes(b"")
    monkeypatch.setattr(
        app_launcher.shutil,
        "which",
        lambda value: str(executable) if value == "code.exe" else None,
    )

    assert app_launcher.find_executable("code") == executable.resolve()


def test_find_executable_normalizes_localized_notepad_name(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Notepad.exe"
    executable.write_bytes(b"")
    searched = []
    monkeypatch.setattr(
        app_launcher,
        "_find_on_path",
        lambda name: searched.append(name) or executable,
    )

    assert app_launcher.find_executable("blocco note") == executable.resolve()
    assert searched == ["notepad"]


def test_launch_localized_notepad_alias_uses_canonical_audit_name(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Program Files" / "Notepad.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    searched = []
    opened = []
    monkeypatch.setattr(
        app_launcher,
        "find_executable",
        lambda name: searched.append(name) or executable,
    )
    monkeypatch.setattr(app_launcher, "_is_whitelisted", lambda _path: True)
    monkeypatch.setattr(app_launcher.os, "startfile", opened.append, raising=False)

    assert "Launch requested for notepad" in app_launcher.launch_app(
        "blocco note", confirmed=True
    )
    assert searched == ["notepad"]
    assert opened == [str(executable)]
    entry = json.loads(app_launcher.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["app"] == "notepad"


def test_app_launcher_waits_for_launched_process_to_become_foreground(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Program Files" / "Notepad.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    monkeypatch.setattr(app_launcher, "_is_whitelisted", lambda _path: True)
    monkeypatch.setattr(app_launcher.os, "startfile", lambda _path: None, raising=False)
    waits = []

    def wait(process_name, timeout):
        waits.append((process_name, timeout))
        return False

    monkeypatch.setattr(computer_use, "wait_for_foreground", wait)

    result = app_launcher.launch_app("notepad", confirmed=True)

    assert waits == [("Notepad.exe", 3)]
    assert "did not become foreground" in result
    assert json.loads(app_launcher.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])[
        "event"
    ] == "launch_failed"


def test_find_executable_returns_none_for_unknown_app(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)

    assert app_launcher.find_executable("nonexistent_xyz") is None


def test_recursive_search_refuses_ambiguous_partial_matches(tmp_path, monkeypatch):
    first = tmp_path / "Visual Studio Code.exe"
    second = tmp_path / "Code Editor.exe"
    first.write_bytes(b"")
    second.write_bytes(b"")

    assert app_launcher._walk_for_name(
        (tmp_path,), "code", app_launcher.time.monotonic() + 2
    ) is None


def test_find_executable_checks_each_search_stage_in_order(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    requested = tmp_path / "cached.exe"
    requested.write_bytes(b"")
    (tmp_path / "cache.json").write_text(
        json.dumps({"cached": str(requested)}), encoding="utf-8"
    )
    stages = []

    def walk(_roots, _name, _deadline):
        stages.append("known" if stages.count("known") == 0 else "start_menu")
        return None

    monkeypatch.setattr(app_launcher, "_walk_for_name", walk)
    monkeypatch.setattr(
        app_launcher,
        "_find_in_registry",
        lambda _name: stages.append("registry") or None,
    )
    monkeypatch.setattr(
        app_launcher,
        "_find_on_path",
        lambda _name: stages.append("path") or None,
    )

    assert app_launcher.find_executable("cached") == requested.resolve()
    assert stages == ["path", "known", "start_menu", "registry"]


def test_launch_refuses_downloads_and_temp_even_after_confirmation(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    for folder in ("Downloads", "Temp"):
        monkeypatch.setattr(
            app_launcher,
            "_BLOCKED_PARTS",
            frozenset({"downloads", "temp", "tmp"}),
        )
        blocked = tmp_path / folder / "unsafe.exe"
        blocked.parent.mkdir()
        blocked.write_bytes(b"")
        monkeypatch.setattr(app_launcher, "find_executable", lambda _name, p=blocked: p)

        assert "Refused" in app_launcher.launch_app("unsafe", confirmed=True)


def test_non_whitelisted_app_requires_confirmation_then_launches(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Portable" / "example.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    monkeypatch.setattr(app_launcher, "_is_whitelisted", lambda _path: False)
    opened = []
    monkeypatch.setattr(app_launcher.os, "startfile", opened.append, raising=False)

    assert "confirmation" in app_launcher.launch_app("example")
    assert "Launch requested" in app_launcher.launch_app("example", confirmed=True)
    assert opened == [str(executable)]


def test_whitelisted_executable_is_started_with_startfile_and_audit_log(
    tmp_path, monkeypatch
):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Program Files" / "Example" / "example.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    opened = []
    monkeypatch.setattr(app_launcher.os, "startfile", opened.append, raising=False)

    assert "Launch requested" in app_launcher.launch_app("example", confirmed=True)
    assert opened == [str(executable)]
    entry = json.loads(app_launcher.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["event"] == "launch_started"
    assert entry["path"] == str(executable)


def test_arbitrary_arguments_are_rejected(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Program Files" / "git.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(executable.parent))
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    popen_calls = []
    monkeypatch.setattr(
        app_launcher.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    assert "Only --help is allowed" in app_launcher.launch_app(
        "git", args="--exec-path", confirmed=True
    )
    assert not popen_calls


def test_opt_out_disables_search_and_launch(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    monkeypatch.setenv(app_launcher.APP_LAUNCHER_ENV, "0")

    assert app_launcher.find_executable("code") is None
    assert "disabled" in app_launcher.launch_app("code", confirmed=True)


def test_list_known_apps_returns_cached_paths_without_launching(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "known.exe"
    executable.write_bytes(b"")
    app_launcher.CACHE_PATH.write_text(
        json.dumps({"known": str(executable)}), encoding="utf-8"
    )

    assert app_launcher.list_known_apps() == {"known": str(executable.resolve())}


def test_action_is_auto_registered_as_destructive():
    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions",
        logger=lambda _message: None,
    )

    assert registry.has("app_launcher")
    assert registry.risk_class("app_launcher") == "destructive"
    assert "confirmed" in registry.get_tool_declarations()[
        next(
            index
            for index, declaration in enumerate(registry.get_tool_declarations())
            if declaration["name"] == "app_launcher"
        )
    ]["parameters"]["properties"]


def test_game_names_are_not_routed_to_app_launcher():
    decision = route_tool(
        "app_launcher", {"name": "GeoGuessr"}, "apri il gioco GeoGuessr"
    )

    assert decision is not None
    assert decision.blocked
    assert "Steam/Epic" in decision.clarification


def test_legacy_open_app_does_not_launch_windows_desktop_apps(monkeypatch):
    monkeypatch.setattr(open_app_module, "_SYSTEM", "Windows")
    monkeypatch.setattr(
        open_app_module,
        "_OS_LAUNCHERS",
        {"Windows": lambda _name: pytest.fail("legacy app launch must be blocked")},
    )

    result = open_app_module.open_app({"app_name": "notepad"})

    assert "use app_launcher" in result
    assert "confirmation" in result


def test_shortcut_target_in_downloads_is_refused(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    shortcut = tmp_path / "Programs" / "Example.lnk"
    shortcut.parent.mkdir()
    shortcut.write_bytes(b"")
    target = tmp_path / "Downloads" / "unsafe.exe"
    target.parent.mkdir()
    target.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: shortcut)
    monkeypatch.setattr(
        app_launcher, "_resolve_shortcut", lambda _path: (target.resolve(), "")
    )

    assert "shortcut target is in Downloads or Temp" in app_launcher.launch_app(
        "Example", confirmed=True
    )


def test_shortcut_resolution_reads_target_and_embedded_arguments(tmp_path):
    win32com = pytest.importorskip("win32com.client")
    target = tmp_path / "Target.exe"
    target.write_bytes(b"")
    shortcut_path = tmp_path / "Target.lnk"
    shortcut = win32com.Dispatch("WScript.Shell").CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = str(target)
    shortcut.Arguments = ""
    shortcut.Save()
    shortcut = None

    assert app_launcher._resolve_shortcut(shortcut_path) == (target.resolve(), "")


def test_shortcut_with_embedded_arguments_is_refused(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    shortcut = tmp_path / "Programs" / "Example.lnk"
    shortcut.parent.mkdir()
    shortcut.write_bytes(b"")
    target = tmp_path / "Program Files" / "example.exe"
    target.parent.mkdir()
    target.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(target.parent))
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: shortcut)
    monkeypatch.setattr(
        app_launcher, "_resolve_shortcut", lambda _path: (target.resolve(), "--unsafe")
    )

    assert "shortcut arguments are not allowed" in app_launcher.launch_app(
        "Example", confirmed=True
    )


def test_command_interpreters_are_never_launched(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Program Files" / "cmd.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    opened = []
    monkeypatch.setattr(app_launcher.os, "startfile", opened.append, raising=False)

    assert "command interpreters" in app_launcher.launch_app("cmd", confirmed=True)
    assert opened == []


def test_app_search_cli_only_resolves_and_never_launches(tmp_path, monkeypatch):
    executable = tmp_path / "Code.exe"
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)

    assert registry_cli.run(["app-search", "code"], runtime=None) == str(executable)


def test_pattern_learner_records_app_launch_frequency_and_context(tmp_path, monkeypatch):
    monkeypatch.setattr(pattern_learner, "PATTERNS_PATH", tmp_path / "patterns.json")
    monkeypatch.delenv(pattern_learner.ENABLED_ENV, raising=False)
    for _ in range(3):
        pattern_learner.observe_app_launch("auto", "Visual Studio Code")

    patterns = pattern_learner.list_patterns()

    assert len(patterns) == 1
    assert patterns[0]["type"] == "app_launch"
    assert patterns[0]["context"] == "auto"
    assert patterns[0]["observation"] == "visualstudiocode"
    assert patterns[0]["occurrences"] == 3


def test_pattern_observer_learns_only_successful_app_launches(tmp_path, monkeypatch):
    from main import JarvisLive

    monkeypatch.setattr(pattern_learner, "PATTERNS_PATH", tmp_path / "patterns.json")
    monkeypatch.delenv(pattern_learner.ENABLED_ENV, raising=False)
    jarvis = object.__new__(JarvisLive)
    jarvis._last_user_text = "apri l'app mentre guardiamo un'auto"

    jarvis._observe_pattern_tool_result("app_launcher", {"name": "code"}, "Application not found.")
    assert pattern_learner.list_patterns() == []

    jarvis._observe_pattern_tool_result(
        "app_launcher", {"name": "code"}, "Launch requested for code."
    )
    pattern = pattern_learner.list_patterns()[0]
    assert pattern["context"] == "auto"
    assert pattern["observation"] == "code"


def test_console_script_uses_popen_without_a_shell_and_times_out_cleanly(
    tmp_path, monkeypatch
):
    _configure_paths(tmp_path, monkeypatch)
    script = tmp_path / "Program Files" / "example.bat"
    script.parent.mkdir()
    script.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: script)
    monkeypatch.setattr(app_launcher, "_is_whitelisted", lambda _path: True)
    calls = []

    class Process:
        pid = 123

        def wait(self, timeout):
            calls.append(("wait", timeout))
            raise app_launcher.subprocess.TimeoutExpired("example.bat", timeout)

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr(app_launcher.subprocess, "Popen", popen)

    result = app_launcher.launch_app("example", confirmed=True)

    assert "PID 123" in result
    assert calls[0][0] == [str(script)]
    assert calls[0][1]["shell"] is False
    assert calls[1] == ("wait", 5.0)


def test_console_executable_is_detected_from_pe_subsystem(tmp_path):
    executable = tmp_path / "console.exe"
    _write_pe_executable(executable, 3)

    assert app_launcher._is_console_executable(executable)


def test_help_argument_is_allowed_only_for_supported_console_apps(tmp_path, monkeypatch):
    _configure_paths(tmp_path, monkeypatch)
    executable = tmp_path / "Program Files" / "git.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    monkeypatch.setattr(app_launcher, "_is_whitelisted", lambda _path: True)
    calls = []

    class Process:
        pid = 456

        @staticmethod
        def wait(timeout):
            return 0

    monkeypatch.setattr(
        app_launcher.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or Process(),
    )

    assert "completed" in app_launcher.launch_app("git", args="--help", confirmed=True)
    assert calls[0][0] == [str(executable), "--help"]
    assert calls[0][1]["shell"] is False
