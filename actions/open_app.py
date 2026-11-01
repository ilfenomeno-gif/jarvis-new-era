import time
import subprocess
import platform
import shutil
import os
from urllib.parse import quote, unquote

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    from actions.game_updater import _KNOWN_APPIDS
except ImportError:
    _KNOWN_APPIDS = {}

_SYSTEM = platform.system()


def _process_name(app_name: str) -> str:
    return app_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()


def _wait_for_process(app_name: str, timeout: float = 8.0) -> bool:
    """Confirm an executable launch without relying on a fixed startup delay."""
    if not _PSUTIL:
        return True
    expected = _process_name(app_name).replace(".exe", "")
    if expected in {"", "ms-settings:"} or app_name.startswith(("http://", "https://", "steam://")):
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for process in psutil.process_iter(["name", "exe"]):
                name = (process.info.get("name") or process.info.get("exe") or "").lower()
                if expected in name.replace(".exe", ""):
                    return True
        except (psutil.Error, OSError):
            pass
        time.sleep(0.25)
    return False


def _steam_library_launch(game_name: str) -> bool:
    """Open Steam, search its Library, and click the visible Play action."""
    try:
        import pyautogui
        from actions.screen_processor import get_element_coordinates, wait_for_text
        from actions.game_updater import _find_steam_path, _steam_exe, _is_steam_running

        if not _is_steam_running():
            steam_path = _find_steam_path()
            if not steam_path:
                print("[open_app] Steam installation not found")
                return False
            subprocess.Popen([str(_steam_exe(steam_path))])
            if not _wait_for_process("steam.exe", timeout=20.0):
                return False

        try:
            import pygetwindow as gw
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                steam_window = next(
                    (window for window in gw.getAllWindows()
                     if "steam" in window.title.lower() and window.visible),
                    None,
                )
                if steam_window:
                    steam_window.activate()
                    break
                time.sleep(0.25)
        except Exception as exc:
            print(f"[open_app] Could not focus Steam window: {exc}")

        pyautogui.PAUSE = 0.1
        pyautogui.hotkey("ctrl", "f")
        pyautogui.write(game_name, interval=0.04)
        pyautogui.press("enter")

        if wait_for_text:
            wait_for_text(game_name, timeout=10.0)

        for label in ("Play", "Gioca", "Launch", "Avvia"):
            coords = get_element_coordinates(label)
            if coords:
                pyautogui.click(*coords)
                return True
        print(f"[open_app] Steam game page opened, but Play button was not found for '{game_name}'")
    except Exception as exc:
        print(f"[open_app] Steam Library launch failed: {exc}")
    return False


def _steam_local_launch(game_name: str) -> bool:
    """Start Steam for license verification, then launch the local game exe."""
    try:
        from actions.game_updater import (
            _find_game_executable, _find_steam_path, _is_steam_running, _steam_exe,
        )
        steam_path = _find_steam_path()
        if not steam_path:
            print("[open_app] Steam installation not found")
            return False
        if not _is_steam_running():
            subprocess.Popen([str(_steam_exe(steam_path))])
            if not _wait_for_process("steam.exe", timeout=20.0):
                return False
        executable = _find_game_executable(game_name, steam_path)
        if not executable:
            print(f"[open_app] Local executable not found for '{game_name}'")
            return False
        subprocess.Popen([str(executable)], cwd=str(executable.parent))
        return _wait_for_process(executable.name, timeout=20.0)
    except Exception as exc:
        print(f"[open_app] Local Steam launch failed: {exc}")
        return False

_APP_ALIASES: dict[str, dict[str, str]] = {

    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "safari":             {"Windows": "msedge",                  "Darwin": "Safari",               "Linux": "firefox"},
    "opera":              {"Windows": "opera",                   "Darwin": "Opera",                "Linux": "opera"},
    "whatsapp":           {"Windows": "WhatsApp",                "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "teams":              {"Windows": "msteams",                 "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "skype":              {"Windows": "skype",                   "Darwin": "Skype",                "Linux": "skype"},
    "signal":             {"Windows": "signal",                  "Darwin": "Signal",               "Linux": "signal"},
    "spotify":            {"Windows": "Spotify",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "netflix":            {"Windows": "Netflix",                 "Darwin": "Netflix",              "Linux": "firefox"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "code":               {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "terminal":           {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "x-terminal-emulator"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": "Terminal",             "Linux": "bash"},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "git":                {"Windows": "git-bash",                "Darwin": "Terminal",             "Linux": "bash"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "libreoffice":        {"Windows": "soffice",                 "Darwin": "LibreOffice",          "Linux": "libreoffice"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "textedit":           {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "finder":             {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",            "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "instagram":          {"Windows": "Instagram",               "Darwin": "Instagram",            "Linux": "firefox"},
    "tiktok":             {"Windows": "TikTok",                  "Darwin": "TikTok",               "Linux": "firefox"},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "steam":              {"Windows": "steam",                   "Darwin": "Steam",                "Linux": "steam"},
    "epic":               {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "epic games":         {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "geoguessr":          {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    # Common speech-to-text spellings of GeoGuessr.
    "gio gasser":         {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    "jao gasser":         {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    "jailgassar":         {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    "geogasser":          {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    "geo guesser":        {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    "geogas":             {"Windows": "steam://local/GeoGuessr", "Darwin": "steam://local/GeoGuessr", "Linux": "steam://local/GeoGuessr"},
    "youtube":            {"Windows": "https://www.youtube.com", "Darwin": "https://www.youtube.com", "Linux": "https://www.youtube.com"},
    "chatgpt":            {"Windows": "https://chatgpt.com",     "Darwin": "https://chatgpt.com",  "Linux": "https://chatgpt.com"},
}


def _normalize(raw: str) -> str:
    key = raw.lower().strip()

    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(_SYSTEM, raw)

    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(_SYSTEM, raw)

    for game_key, (app_id, _) in _KNOWN_APPIDS.items():
        if game_key in key or key in game_key:
            return f"steam://local/{quote(game_key)}"

    return raw  

def _launch_windows(app_name: str) -> bool:

    if app_name.startswith("steam://library/"):
        return _steam_library_launch(unquote(app_name.removeprefix("steam://library/")))

    if app_name.startswith("steam://local/"):
        return _steam_local_launch(unquote(app_name.removeprefix("steam://local/")))

    if app_name.startswith(("http://", "https://", "steam://")):
        try:
            os.startfile(app_name)
            return True
        except Exception as e:
            print(f"[open_app] URL launch failed: {e}")

    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return _wait_for_process(app_name)
        except Exception as e:
            print(f"[open_app] subprocess failed: {e}")

    if ":" in app_name:
        try:
            os.startfile(app_name)
            return True
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.7)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.9)
        pyautogui.press("enter")
        time.sleep(2.5)
        return True
    except Exception as e:
        print(f"[open_app] Start Menu search failed: {e}")

    return False


def _launch_macos(app_name: str) -> bool:

    try:
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["open", "-a", f"{app_name}.app"],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] Spotlight failed: {e}")

    return False


_LINUX_TERMINAL_FALLBACKS = [
    "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
    "xterm", "lxterminal", "mate-terminal", "tilix", "alacritty", "kitty",
]

def _launch_linux(app_name: str) -> bool:

    # terminal emulators: try common ones in order
    if app_name in ("x-terminal-emulator", "gnome-terminal", "terminal"):
        for term in _LINUX_TERMINAL_FALLBACKS:
            if shutil.which(term):
                try:
                    subprocess.Popen([term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.0)
                    return True
                except Exception:
                    continue

    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdg-open", app_name],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        pass

    for desktop_name in [
        app_name.lower(),
        app_name.lower().replace(" ", "-"),
        app_name.lower().replace(" ", ""),
    ]:
        try:
            result = subprocess.run(
                ["gtk-launch", desktop_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}

def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}' → '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    if _SYSTEM == "Windows":
        media_suffixes = {
            ".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".wma", ".opus",
            ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".3gp",
        }
        is_legacy_target = (
            normalized.startswith(("http://", "https://", "steam://", "ms-settings:"))
            or os.path.splitext(normalized)[1].casefold() in media_suffixes
        )
        if not is_legacy_target:
            return (
                "For Windows desktop applications, use app_launcher with the app name "
                "and obtain explicit user confirmation before launching."
            )

    try:
        if launcher(normalized):
            return f"Opened {app_name}."
        if normalized.lower() != app_name.lower():
            if launcher(app_name):
                return f"Opened {app_name}."
        return (
            f"Could not confirm that {app_name} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        return f"Failed to open {app_name}: {e}"