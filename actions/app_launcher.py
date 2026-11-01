"""Restricted application discovery and launch for Windows."""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

APP_LAUNCHER_ENV = "JARVIS_APP_LAUNCHER"
ALLOWED_EXTENSIONS = frozenset({".exe", ".lnk", ".bat", ".msi"})
SEARCH_TIMEOUT_SECONDS = 5.0
PROCESS_TIMEOUT_SECONDS = 5.0
_BLOCKED_PARTS = frozenset({"downloads", "temp", "tmp"})
_BLOCKED_EXECUTABLES = frozenset({
    "cmd",
    "powershell",
    "powershell_ise",
    "pwsh",
    "wscript",
    "cscript",
    "mshta",
    "rundll32",
    "regsvr32",
    "bash",
    "sh",
})
_SAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_APP_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = _APP_ROOT / "logs" / "app_launcher.log"
CACHE_PATH = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
) / "Jarvis" / "app_launcher_cache.json"
_HELP_APPS = frozenset({"code", "git", "node", "npm", "python", "python3"})
_APP_NAME_ALIASES = {"blocconote": "notepad"}


def enabled() -> bool:
    return os.environ.get(APP_LAUNCHER_ENV, "1").strip() != "0"


def _validated_name(name: str) -> str | None:
    value = str(name or "").strip()
    if (
        not value
        or len(value) > 128
        or value in {".", ".."}
        or _SAFE_NAME_CHARS.search(value)
        or PureWindowsPath(value).name != value
    ):
        return None
    return value


def _app_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def _canonical_app_name(name: str) -> str | None:
    requested = _validated_name(name)
    if requested is None:
        return None
    return _APP_NAME_ALIASES.get(_app_key(requested), requested)


def _name_variants(name: str) -> tuple[str, ...]:
    suffix = PureWindowsPath(name).suffix.casefold()
    if suffix in ALLOWED_EXTENSIONS:
        return (name,)
    if suffix:
        return ()
    return tuple(name + extension for extension in (".exe", ".lnk", ".bat", ".msi"))


def _candidate_path(value: str | Path) -> Path | None:
    candidate = Path(value)
    if candidate.suffix.casefold() not in ALLOWED_EXTENSIONS or not candidate.is_file():
        return None
    try:
        return candidate.resolve(strict=True)
    except OSError:
        return None


def _known_directories() -> tuple[Path, ...]:
    local_appdata = os.environ.get("LOCALAPPDATA")
    values = (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        str(Path(local_appdata) / "Programs") if local_appdata else None,
        os.environ.get("WINDIR"),
    )
    roots: list[Path] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        root = Path(value)
        key = os.path.normcase(os.path.abspath(root))
        if key not in seen and root.is_dir():
            roots.append(root)
            seen.add(key)
    return tuple(roots)


def _start_menu_directories() -> tuple[Path, ...]:
    roots = (
        Path(os.environ.get("APPDATA", "")),
        Path(os.environ.get("PROGRAMDATA", "")),
    )
    return tuple(
        root / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        for root in roots
        if str(root) not in {"", "."}
        and (root / "Microsoft" / "Windows" / "Start Menu" / "Programs").is_dir()
    )


def _is_blocked(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    if any(part.casefold() in _BLOCKED_PARTS for part in resolved.parts):
        return True
    for variable in ("TEMP", "TMP"):
        root = os.environ.get(variable)
        if root:
            try:
                resolved.relative_to(Path(root).resolve(strict=False))
                return True
            except ValueError:
                pass
    return False


def _whitelist_roots() -> tuple[Path, ...]:
    local_appdata = os.environ.get("LOCALAPPDATA")
    roots: list[Path] = []
    for value in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        str(Path(local_appdata) / "Programs") if local_appdata else None,
        os.environ.get("WINDIR"),
    ):
        if value and Path(value).is_dir():
            roots.append(Path(value).resolve(strict=False))
    return tuple(roots)


def _is_whitelisted(path: Path) -> bool:
    candidate = path.resolve(strict=False)
    return any(
        not _is_blocked(candidate)
        and _is_relative_to(candidate, root)
        for root in _whitelist_roots()
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _read_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in data.items()
    ):
        raise ValueError(f"Invalid application cache format: {CACHE_PATH}")
    return data


def _write_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".app-launcher-", suffix=".tmp", dir=CACHE_PATH.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(cache, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, CACHE_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def _remember(name: str, path: Path) -> None:
    cache = _read_cache()
    cache[_app_key(name)] = str(path)
    if len(cache) > 250:
        cache = dict(sorted(cache.items())[-250:])
    _write_cache(cache)


def _find_on_path(name: str) -> Path | None:
    for variant in _name_variants(name):
        found = shutil.which(variant)
        if found:
            candidate = _candidate_path(found)
            if candidate is not None:
                return candidate
    return None


def _walk_for_name(
    roots: tuple[Path, ...], name: str, deadline: float
) -> Path | None:
    requested = _app_key(PureWindowsPath(name).stem)
    exact: dict[str, Path] = {}
    partial: dict[str, Path] = {}
    for root in roots:
        for current, directories, filenames in os.walk(root, followlinks=False):
            directories[:] = [
                directory for directory in directories
                if directory.casefold() not in _BLOCKED_PARTS
            ]
            if time.monotonic() >= deadline:
                return None
            for filename in filenames:
                candidate_name = Path(filename)
                if candidate_name.suffix.casefold() not in ALLOWED_EXTENSIONS:
                    continue
                candidate = _candidate_path(Path(current) / filename)
                if candidate is None:
                    continue
                key = _app_key(candidate_name.stem)
                identity = os.path.normcase(str(candidate))
                if key == requested:
                    exact[identity] = candidate
                elif len(requested) >= 4 and requested in key:
                    partial[identity] = candidate
    matches = exact or partial
    return next(iter(matches.values())) if len(matches) == 1 else None


def _find_in_registry(name: str) -> Path | None:
    try:
        import winreg
    except ImportError:
        return None
    app_name = PureWindowsPath(name).stem
    if not app_name:
        return None
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_name}.exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        candidate = _candidate_path(os.path.expandvars(str(value).strip().strip('"')))
        if candidate is not None:
            return candidate
    return None


def _resolve_shortcut(path: Path) -> tuple[Path | None, str]:
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required to validate Windows shortcut targets") from exc

    initialized = False
    shell = None
    shortcut = None
    try:
        pythoncom.CoInitialize()
        initialized = True
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(path))
        target = str(shortcut.TargetPath or "").strip()
        arguments = str(shortcut.Arguments or "").strip()
    except pywintypes.com_error as exc:
        raise OSError(f"Could not inspect shortcut '{path}': {exc}") from exc
    finally:
        shortcut = None
        shell = None
        if initialized:
            pythoncom.CoUninitialize()

    if not target:
        return None, arguments
    resolved_target = _candidate_path(os.path.expandvars(target))
    if resolved_target is not None and resolved_target.suffix.casefold() == ".lnk":
        return None, arguments
    return resolved_target, arguments


def find_executable(name: str) -> Path | None:
    """Find an application in PATH, install directories, Start Menu, registry, then cache."""
    if not enabled() or os.name != "nt":
        return None
    requested = _canonical_app_name(name)
    if requested is None:
        return None

    candidate = _find_on_path(requested)
    if candidate is not None:
        _remember(requested, candidate)
        return candidate

    started = time.monotonic()
    deadline = started + SEARCH_TIMEOUT_SECONDS
    known_deadline = min(deadline, started + SEARCH_TIMEOUT_SECONDS * 0.6)
    candidate = _walk_for_name(_known_directories(), requested, known_deadline)
    if candidate is not None:
        _remember(requested, candidate)
        return candidate

    candidate = _walk_for_name(
        _start_menu_directories(), requested, min(deadline, started + SEARCH_TIMEOUT_SECONDS * 0.9)
    )
    if candidate is not None:
        _remember(requested, candidate)
        return candidate

    candidate = _find_in_registry(requested)
    if candidate is not None:
        _remember(requested, candidate)
        return candidate

    cached = _read_cache().get(_app_key(requested))
    candidate = _candidate_path(cached) if cached else None
    if candidate is not None:
        return candidate
    return None


def list_known_apps() -> dict[str, str]:
    """Return the validated name-to-path cache without launching anything."""
    if not enabled() or os.name != "nt":
        return {}
    cache = _read_cache()
    return {
        name: str(candidate)
        for name, value in cache.items()
        if (candidate := _candidate_path(value)) is not None
    }


def _audit(event: str, name: str, path: Path | None = None, detail: str = "") -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "app": name,
        "path": str(path) if path is not None else None,
        "detail": detail,
    }
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _validated_args(args: Any, path: Path) -> list[str] | None:
    if args in (None, "", []):
        return []
    values = [args] if isinstance(args, str) else args
    if (
        not isinstance(values, (list, tuple))
        or len(values) != 1
        or values[0] != "--help"
        or path.stem.casefold() not in _HELP_APPS
    ):
        return None
    return ["--help"]


def _is_console_executable(path: Path) -> bool:
    try:
        with path.open("rb") as executable:
            if executable.read(2) != b"MZ":
                return False
            executable.seek(0x3C)
            raw_offset = executable.read(4)
            if len(raw_offset) != 4:
                return False
            pe_offset = struct.unpack("<I", raw_offset)[0]
            executable.seek(pe_offset)
            if executable.read(4) != b"PE\0\0":
                return False
            coff_header = executable.read(20)
            if len(coff_header) != 20:
                return False
            optional_header_size = struct.unpack_from("<H", coff_header, 16)[0]
            if optional_header_size < 70:
                return False
            optional_header = executable.read(optional_header_size)
            return (
                len(optional_header) >= 70
                and struct.unpack_from("<H", optional_header, 68)[0] == 3
            )
    except (OSError, struct.error):
        return False


def _wait_for_launched_app(
    requested: str, path: Path, launch_target: Path
) -> str | None:
    from core.computer_use import wait_for_foreground

    try:
        focused = wait_for_foreground(launch_target.name, timeout=3)
    except RuntimeError as exc:
        focused = False
        detail = str(exc)
    else:
        detail = f"{launch_target.name} did not become the foreground process"
    if focused:
        return None
    _audit("launch_failed", requested, path, detail)
    return (
        f"Could not continue with {requested}: its window did not become "
        "foreground within 3 seconds."
    )


def launch_app(
    name: str, args: Any = None, *, confirmed: bool = False
) -> str:
    """Launch a discovered app, refusing unsafe paths and arbitrary arguments."""
    if not enabled():
        return "app_launcher is disabled by JARVIS_APP_LAUNCHER=0."
    if os.name != "nt":
        return "app_launcher is supported only on Windows."
    requested = _canonical_app_name(name)
    if requested is None:
        return "Invalid application name. Supply a name only, without a path or command."
    path = find_executable(requested)
    if path is None:
        return f"Application '{requested}' was not found."
    if _is_blocked(path):
        _audit("blocked", requested, path, "Downloads/Temp paths are never allowed")
        return f"Refused to launch '{requested}': its location is Downloads or Temp."

    launch_target = path
    if path.suffix.casefold() == ".lnk":
        try:
            launch_target, shortcut_args = _resolve_shortcut(path)
        except (OSError, RuntimeError) as exc:
            _audit("launch_failed", requested, path, str(exc))
            return f"Could not safely validate shortcut '{requested}': {exc}"
        if launch_target is None:
            _audit("blocked", requested, path, "shortcut target is missing or unsupported")
            return f"Refused to launch '{requested}': its shortcut target is missing or unsupported."
        if shortcut_args:
            _audit("blocked", requested, path, "shortcut contains arguments")
            return f"Refused to launch '{requested}': shortcut arguments are not allowed."
        if _is_blocked(launch_target):
            _audit("blocked", requested, path, f"shortcut target is blocked: {launch_target}")
            return f"Refused to launch '{requested}': its shortcut target is in Downloads or Temp."
        if (
            path.suffix.casefold() == ".lnk"
            and launch_target.suffix.casefold() == ".exe"
            and _is_console_executable(launch_target)
        ):
            path = launch_target

    if launch_target.stem.casefold() in _BLOCKED_EXECUTABLES:
        _audit("blocked", requested, path, "command interpreter or script host")
        return f"Refused to launch '{requested}': command interpreters and script hosts are blocked."

    if not confirmed:
        _audit("confirmation_required", requested, path, f"target={launch_target}")
        return f"Explicit user confirmation is required before launching '{requested}'."
    arguments = _validated_args(args, launch_target)
    if arguments is None:
        _audit("rejected_arguments", requested, path)
        return "Only --help is allowed, and only for supported command-line applications."

    _audit("launch_requested", requested, path, f"target={launch_target}")
    if not _is_whitelisted(launch_target):
        _audit("non_whitelisted_confirmed", requested, path, f"target={launch_target}")
    try:
        if (
            (
                path.suffix.casefold() == ".lnk"
                and launch_target.suffix.casefold() == ".exe"
                and not _is_console_executable(launch_target)
            )
            or (
                path.suffix.casefold() == ".exe"
                and not _is_console_executable(path)
            )
        ) and not arguments:
            os.startfile(str(path))
            _audit("launch_started", requested, path, f"target={launch_target}")
            if not arguments and not _is_console_executable(launch_target):
                focus_error = _wait_for_launched_app(requested, path, launch_target)
                if focus_error:
                    return focus_error
            return f"Launch requested for {requested}."

        if launch_target.suffix.casefold() == ".msi":
            windows_dir = os.environ.get("WINDIR")
            fallback = Path(windows_dir) / "System32" / "msiexec.exe" if windows_dir else None
            installer = (
                str(fallback)
                if fallback and fallback.is_file() and _is_whitelisted(fallback)
                else None
            )
            if installer is None:
                _audit("launch_failed", requested, path, "msiexec.exe not found")
                return "Could not launch the installer: msiexec.exe was not found."
            command = [installer, "/i", str(launch_target)]
        else:
            command = [str(launch_target), *arguments]

        process = subprocess.Popen(
            command,
            cwd=str(launch_target.parent),
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return_code = process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _audit(
                "launch_started",
                requested,
                path,
                f"target={launch_target}; pid={process.pid}; still running after 5s",
            )
            if not arguments and not _is_console_executable(launch_target):
                focus_error = _wait_for_launched_app(requested, path, launch_target)
                if focus_error:
                    return focus_error
            return f"Launch started for {requested} (PID {process.pid})."
        if return_code != 0:
            _audit("launch_failed", requested, path, f"target={launch_target}; exit_code={return_code}")
            return f"'{requested}' exited with code {return_code}."
        _audit("launch_started", requested, path, f"target={launch_target}; pid={process.pid}")
        if not arguments and not _is_console_executable(launch_target):
            focus_error = _wait_for_launched_app(requested, path, launch_target)
            if focus_error:
                return focus_error
        return f"Launch completed for {requested} (PID {process.pid})."
    except (OSError, subprocess.SubprocessError) as exc:
        _audit("launch_failed", requested, path, str(exc))
        return f"Failed to launch '{requested}': {exc}"


def app_launcher(parameters: dict | None = None, **_context: Any) -> str:
    values = parameters or {}
    return launch_app(
        values.get("name", ""),
        values.get("args"),
        confirmed=values.get("confirmed") is True,
    )


TOOL = {
    "name": "app_launcher",
    "description": (
        "Finds and launches an installed Windows application by name using a restricted "
        "search. Never accepts a path or arbitrary command. Every launch requires explicit "
        "user confirmation; apps outside trusted directories require confirmation for that "
        "specific app. Do not use for games; use their Steam/Epic launcher. Optional args "
        "are limited to --help for supported command-line apps."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": "Application name only, not a path or command.",
            },
            "args": {
                "type": "STRING",
                "enum": ["--help"],
                "description": "Optional: --help, only for supported command-line apps.",
            },
        },
        "required": ["name"],
    },
    "risk_class": "destructive",
    "handler": app_launcher,
} if enabled() else None
