"""
Plugin discovery, validation, collision detection, and dispatch.

Discovery runs once (JarvisLive.__init__ calls discover_plugins()); the resulting
PluginRegistry is cached for the process lifetime. Enable/disable state is re-read
from config on every call to get_tool_declarations() / run() / list_for_ui(), so
toggling a plugin does not require restarting the app or re-importing anything.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from memory.config_manager import get_plugin_enabled
from core.guardrails import resolve_safe_path

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "OBJECT", "properties": {}}


@dataclass
class PluginRecord:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    run: Optional[Callable] = None
    file: str = ""
    valid: bool = False
    error: str = ""
    start: Optional[Callable] = None
    stop: Optional[Callable] = None
    extra_tool_declarations: Optional[Callable] = None
    run_extra_tool: Optional[Callable] = None


class PluginRegistry:
    def __init__(
        self,
        plugins: dict[str, PluginRecord],
        logger: Callable[[str], None],
        reserved_tool_names: set[str] | None = None,
    ):
        self._plugins = plugins          # name -> PluginRecord, VALID entries only
        self._all_records: list[PluginRecord] = []   # valid + invalid, for UI listing
        self._logger = logger
        self._reserved_tool_names = set(reserved_tool_names or ()) | set(plugins)
        self._extra_tool_routes: dict[str, PluginRecord] = {}
        self._extra_tools_loaded: set[str] = set()
        self._extra_declarations_cache: dict[str, list[dict]] = {}

    # GEV lifecycle hook
    def start_all(self) -> None:
        """Start plugin lifecycle hooks in discovery order."""
        for name, rec in self._plugins.items():
            if not callable(rec.start):
                continue
            try:
                rec.start()
            except Exception as exc:
                self._logger(f"Plugin '{name}' failed during start(): {exc}")

    # GEV lifecycle hook
    def stop_all(self, timeout: float = 5.0) -> None:
        """Stop plugin lifecycle hooks in reverse order within a time limit."""
        hooks = [
            (name, rec.stop)
            for name, rec in reversed(self._plugins.items())
            if callable(rec.stop)
        ]
        if not hooks:
            return

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plugin-stop")
        futures = [(name, executor.submit(stop)) for name, stop in hooks]
        try:
            done, _ = wait(
                [future for _, future in futures],
                timeout=max(0.0, timeout),
            )
            for name, future in futures:
                if future not in done:
                    future.cancel()
                    self._logger(
                        f"Plugin '{name}' stop timed out after {timeout:.1f} seconds."
                    )
                    continue
                try:
                    future.result()
                except Exception as exc:
                    self._logger(f"Plugin '{name}' failed during stop(): {exc}")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    # -- called by main.py at LiveConnectConfig build time --
    def get_tool_declarations(self) -> list[dict]:
        decls = []
        for name, rec in self._plugins.items():
            if get_plugin_enabled(name):
                decls.append({
                    "name": rec.name,
                    "description": rec.description,
                    "parameters": rec.parameters,
                })
                decls.extend(self._load_extra_tool_declarations(rec))
        return decls

    def has(self, name: str) -> bool:
        if name in self._plugins:
            return True
        self._load_all_extra_tool_declarations()
        return name in self._extra_tool_routes

    # -- called by main.py from _execute_tool's else branch --
    def run(self, name: str, parameters: dict, player=None, session_memory=None) -> str:
        rec = self._plugins.get(name)
        extra_tool_name = None
        if rec is None:
            self._load_all_extra_tool_declarations()
            rec = self._extra_tool_routes.get(name)
            if rec is not None:
                extra_tool_name = name
        if rec is None or not rec.valid:
            return f"Plugin '{name}' is not available."
        if not get_plugin_enabled(rec.name):
            plugin_name = rec.name
            return f"The '{plugin_name}' plugin is currently disabled."
        try:
            if extra_tool_name is not None and callable(rec.run_extra_tool):
                return rec.run_extra_tool(
                    extra_tool_name,
                    parameters,
                    player=player,
                ) or "Done."
            return _call_run(rec.run, parameters, player, session_memory) or "Done."
        except Exception as e:
            self._logger(f"Plugin '{rec.name}' crashed during run(): {e}")
            traceback.print_exc()
            return f"Sir, the '{rec.name}' plugin failed: {e}"

    def _load_all_extra_tool_declarations(self) -> None:
        for rec in self._plugins.values():
            if get_plugin_enabled(rec.name):
                self._load_extra_tool_declarations(rec)

    def _load_extra_tool_declarations(self, rec: PluginRecord) -> list[dict]:
        if rec.name in self._extra_tools_loaded:
            return [
                declaration
                for declaration in self._extra_declarations_cache.get(rec.name, [])
            ]
        provider = rec.extra_tool_declarations
        if not callable(provider):
            self._extra_tools_loaded.add(rec.name)
            self._cache_extra_declarations(rec.name, [])
            return []

        try:
            declarations = provider()
        except Exception as exc:
            self._logger(
                f"Plugin '{rec.name}' could not provide extra tools: {exc}"
            )
            return []
        if not isinstance(declarations, list):
            self._logger(
                f"Plugin '{rec.name}' returned invalid extra tool declarations."
            )
            return []

        accepted = []
        for declaration in declarations:
            if (
                not isinstance(declaration, dict)
                or not isinstance(declaration.get("name"), str)
                or not _NAME_RE.match(declaration["name"])
                or not isinstance(declaration.get("description"), str)
                or not declaration["description"].strip()
                or not isinstance(declaration.get("parameters"), dict)
                or declaration["parameters"].get("type") != "OBJECT"
            ):
                self._logger(
                    f"Plugin '{rec.name}' returned a malformed extra tool declaration."
                )
                continue
            tool_name = declaration["name"]
            if tool_name in self._reserved_tool_names or tool_name in self._extra_tool_routes:
                self._logger(
                    f"Plugin '{rec.name}' extra tool '{tool_name}' collides with another tool."
                )
                continue
            self._extra_tool_routes[tool_name] = rec
            accepted.append({
                "name": tool_name,
                "description": declaration["description"].strip(),
                "parameters": declaration["parameters"],
            })

        self._extra_tools_loaded.add(rec.name)
        self._cache_extra_declarations(rec.name, accepted)
        return accepted

    def _cache_extra_declarations(self, name: str, declarations: list[dict]) -> None:
        self._extra_declarations_cache[name] = declarations

    # -- called by ui.py's Plugin Manager overlay --
    def list_for_ui(self) -> list[dict]:
        out = []
        for rec in self._all_records:
            out.append({
                "name": rec.name,
                "description": rec.description,
                "file": rec.file,
                "valid": rec.valid,
                "error": rec.error,
                "enabled": get_plugin_enabled(rec.name) if rec.valid else False,
            })
        return out


def _call_run(run_fn, parameters, player, session_memory):
    """Invoke run() passing only the kwargs it actually declares (or all of them
    if it has **kwargs), so a minimal `def run(parameters):` plugin still works."""
    sig = inspect.signature(run_fn)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    kwargs = {}
    if has_var_kw or "player" in sig.parameters:
        kwargs["player"] = player
    if has_var_kw or "session_memory" in sig.parameters:
        kwargs["session_memory"] = session_memory
    return run_fn(parameters, **kwargs)


def _validate(module, filename: str) -> PluginRecord:
    """Returns a PluginRecord; .valid=False + .error set on any problem. Never raises."""
    plugin_meta = getattr(module, "PLUGIN", None)
    if not isinstance(plugin_meta, dict):
        return PluginRecord(name=Path(filename).stem, file=filename,
                             error="Missing PLUGIN dict constant.")

    name = plugin_meta.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return PluginRecord(name=str(name or Path(filename).stem), file=filename,
                             error="PLUGIN['name'] missing or not a valid identifier "
                                   "(letters/digits/underscore, must start with letter/underscore).")

    description = plugin_meta.get("description")
    if not isinstance(description, str) or not description.strip():
        return PluginRecord(name=name, file=filename,
                             error="PLUGIN['description'] missing or empty.")

    parameters = plugin_meta.get("parameters", _DEFAULT_PARAMS)
    if not isinstance(parameters, dict) or parameters.get("type") != "OBJECT":
        return PluginRecord(name=name, file=filename,
                             error="PLUGIN['parameters'] must be a dict with \"type\": \"OBJECT\".")

    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        return PluginRecord(name=name, file=filename,
                             error="Missing callable run(parameters, ...) function.")

    start_fn = getattr(module, "start", None)
    stop_fn = getattr(module, "stop", None)
    extra_tools_fn = getattr(module, "get_extra_tool_declarations", None)
    run_extra_fn = getattr(module, "run_extra_tool", None)

    return PluginRecord(name=name, description=description.strip(), parameters=parameters,
                         run=run_fn, file=filename, valid=True, error="",
                         start=start_fn if callable(start_fn) else None,
                         stop=stop_fn if callable(stop_fn) else None,
                         extra_tool_declarations=(
                             extra_tools_fn if callable(extra_tools_fn) else None
                         ),
                         run_extra_tool=(
                             run_extra_fn if callable(run_extra_fn) else None
                         ))


def discover_plugins(plugins_dir: Path, core_tool_names: set[str],
                      logger: Callable[[str], None] = print) -> PluginRegistry:
    """
    Scans plugins_dir for *.py files (skips files starting with '_', e.g. __init__.py,
    _template.py, and any shared-helper modules an author prefixes with '_').
    Import errors, validation errors, and name collisions are logged and the offending
    file is skipped — they NEVER raise out of this function and never abort the scan
    of remaining files.
    """
    try:
        resolve_safe_path(plugins_dir, allow_plugin_dir=True)
    except PermissionError as exc:
        logger(f"Plugin discovery blocked: {exc}")
        return PluginRegistry({}, logger)
    plugins_dir.mkdir(parents=True, exist_ok=True)
    valid: dict[str, PluginRecord] = {}
    all_records: list[PluginRecord] = []

    files = sorted(plugins_dir.glob("*.py"), key=lambda p: p.name)  # deterministic order
    for path in files:
        if path.name.startswith("_"):
            continue
        try:
            if path.suffix.lower() != ".py":
                continue
            module_name = f"plugins.{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError("could not build import spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise

            rec = _validate(module, path.name)

            if rec.valid and rec.name in core_tool_names:
                rec = PluginRecord(name=rec.name, file=path.name,
                                    error=f"Name '{rec.name}' collides with a core tool — rejected.")
            elif rec.valid and rec.name in valid:
                other = valid[rec.name].file
                rec = PluginRecord(name=rec.name, file=path.name,
                                    error=f"Name '{rec.name}' already used by plugin '{other}' — rejected.")

        except Exception as e:
            rec = PluginRecord(name=path.stem, file=path.name,
                                error=f"Failed to load: {e}")
            traceback.print_exc()

        all_records.append(rec)
        if rec.valid:
            valid[rec.name] = rec
            logger(f"Plugin loaded: {rec.name} ({path.name})")
        else:
            logger(f"Plugin rejected: {path.name} — {rec.error}")

    registry = PluginRegistry(valid, logger, reserved_tool_names=core_tool_names)
    registry._all_records = all_records
    logger(f"Plugin discovery complete: {len(valid)} active, "
           f"{len(all_records) - len(valid)} rejected, {len(all_records)} total.")
    return registry
