"""Lifecycle and MCP bridge for a local God's Eye View checkout."""

from __future__ import annotations

import atexit
from collections import deque
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

from plugins._gev_mcp_client import (
    McpClientError,
    McpStdioClient,
    to_gemini_schema,
    tool_result_text,
)

GEV_DIR = Path(__file__).resolve().parents[1] / "gods-eye-view-main" / "_gev-clone"
GEV_PORT = 4173
GEV_NODE_DIR = GEV_DIR / ".node"
GEV_HEALTH_URL = f"http://127.0.0.1:{GEV_PORT}/"
STARTUP_TIMEOUT_SEC = 60
INSTALL_TIMEOUT_SEC = 600
STOP_TIMEOUT_SEC = 5
GEV_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "gev.log"
_MAX_SAFE_JS_INTEGER = 2**53 - 1
_HISTORICAL_RESPONSE_TIMEOUT_SEC = 20
_historical_request_lock = threading.Lock()

_process: subprocess.Popen[str] | None = None
_process_lock = threading.Lock()
_started = False
_ui = None
_output_lines: deque[str] = deque(maxlen=200)
_output_lock = threading.Lock()
_output_reader: threading.Thread | None = None
_job_handle = None
_job_kernel = None
_mcp_client: McpStdioClient | None = None
_mcp_start_error: str | None = None
_startup_finished = threading.Event()


def _resolve_gev_dir(plugin_file: Path) -> Path:
    plugin_path = Path(plugin_file).resolve()
    roots = [
        plugin_path.parents[1],
        plugin_path.parents[2],
        plugin_path.parents[3],
    ]
    checkouts = [root / "gods-eye-view-main" / "_gev-clone" for root in roots]
    existing = [checkout for checkout in checkouts if checkout.is_dir()]
    if existing:
        return next(
            (checkout for checkout in existing if (checkout / "node_modules").is_dir()),
            existing[0],
        )
    return checkouts[0]


PLUGIN = {
    "name": "gev",
    "description": (
        "Controlla God's Eye View, il globo 3D con aerei, navi e satelliti. "
        "Azioni disponibili: open (apri il globo), open_tab (mostra la scheda GEV "
        "a schermo ampio con i pannelli Data Layers e Context aperti), "
        "hide_tab (chiudi la scheda visuale e torna a Jarvis), "
        "track (target_type e target_id), "
        "layer (layer ed enabled), reset (ripristina la vista), annotate (lat, lon e text), "
        "historical_map (mostra o anima confini storici disponibili). "
        "open_with_context (apre un luogo risolto dal tool GEV e applica "
        "eventuale anno e annotazione storico/geografica). "
        "historical_scenario, historical_factions, historical_events e "
        "historical_years per gli strumenti storici GEV. "
        "Per ricerche, rotte e altri strumenti usa le funzioni MCP gev_mcp_*."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "Azione GEV: open, open_tab (mostra il globo ampio con i pannelli "
                    "Data Layers e Context aperti), hide_tab (chiudi la scheda "
                    "visuale e torna a Jarvis), open_with_context, track, layer, reset, annotate, camera "
                    "incrementale (zoom, tilt, rotate, reset_camera) e comandi "
                    "historical_*. Per 'vai a X' usa show_in_gods_eye_view."
                ),
                "enum": [
                    "open", "open_tab", "hide_tab", "open_with_context",
                    "track", "layer", "reset",
                    "annotate", "historical_map",
                    "historical_scenario", "historical_factions",
                    "historical_events", "historical_years", "zoom", "tilt",
                    "rotate", "reset_camera",
                ],
            },
            "target_type": {
                "type": "STRING",
                "description": "Per track: tipo di oggetto tracciabile (flight o satellite).",
                "enum": ["flight", "satellite"],
            },
            "target_id": {
                "type": "STRING",
                "description": "Per track: identificativo dell'oggetto da tracciare (es. codice volo, MMSI, NORAD ID).",
            },
            "layer": {
                "type": "STRING",
                "description": "Per layer: nome del layer da attivare o disattivare (flights, vessels, satellites, earthquakes, fires, cctv, ...).",
            },
            "enabled": {
                "type": "BOOLEAN",
                "description": "Per layer: true per attivare, false per disattivare.",
            },
            "lat": {
                "type": "NUMBER",
                "description": "Latitudine da -90 a 90; per annotate.",
            },
            "lon": {
                "type": "NUMBER",
                "description": "Longitudine da -180 a 180; per annotate.",
            },
            "altitude_m": {
                "type": "NUMBER",
                "description": "Altitudine camera in metri (50..20000000).",
            },
            "heading_deg": {
                "type": "NUMBER",
                "description": "Rotazione orizzontale della camera (0..360).",
            },
            "pitch_deg": {
                "type": "NUMBER",
                "description": "Inclinazione della camera (-90..0).",
            },
            "level": {
                "type": "STRING",
                "description": "Per zoom: in dimezza l'altitudine, out la raddoppia.",
                "enum": ["in", "out"],
            },
            "text": {
                "type": "STRING",
                "description": "Per annotate: testo dell'annotazione.",
            },
            "location": {
                "type": "STRING",
                "description": "Per open_with_context: nome del luogo o dell'entità da mostrare.",
            },
            "intent": {
                "type": "STRING",
                "description": "Per open_with_context: geo oppure history.",
                "enum": ["geo", "history"],
            },
            "theme": {
                "type": "STRING",
                "description": "Per open_with_context: tema o query da annotare sulla mappa.",
            },
            "epoch": {
                "type": "STRING",
                "description": "Per open_with_context: epoca testuale da riportare nel contesto.",
            },
            "command": {
                "type": "STRING",
                "description": "Per historical_map: show, animate, stop oppure clear.",
                "enum": ["show", "animate", "stop", "clear"],
            },
            "year": {
                "type": "INTEGER",
                "description": (
                    "Anno richiesto per historical_map show e historical_scenario "
                    "(in historical_scenario è facoltativo), storico per "
                    "historical_factions (obbligatorio) o filtro per "
                    "historical_events (facoltativo). Per gli anni non presenti "
                    "viene selezionato lo snapshot disponibile più vicino."
                ),
            },
            "start_year": {
                "type": "INTEGER",
                "description": "Per historical_map animate: anno iniziale richiesto.",
            },
            "end_year": {
                "type": "INTEGER",
                "description": "Per historical_map animate: anno finale richiesto.",
            },
            "speed": {
                "type": "NUMBER",
                "description": "Per animate: secondi per snapshot (da 0.5 a 30).",
            },
            "name": {
                "type": "STRING",
                "description": "Per historical_scenario: identificativo (ww2, cold_war o ww1).",
            },
            "scenario": {
                "type": "STRING",
                "description": "Scenario per historical_factions e historical_events.",
            },
        },
        "required": ["action"],
    },
}


def _log(message: str) -> None:
    print(message, flush=True)
    try:
        GEV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with GEV_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def _read_output(process: subprocess.Popen[str]) -> None:
    stream = process.stdout
    if stream is None:
        return
    try:
        for line in stream:
            text = line.rstrip()
            if not text:
                continue
            with _output_lock:
                _output_lines.append(text)
            _log(f"GEV subprocess: {text}")
    finally:
        stream.close()


def _process_output() -> str:
    with _output_lock:
        return "\n".join(_output_lines)


def _captured_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _port_is_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", GEV_PORT), timeout=0.25):
            return True
    except OSError:
        return False


def _gev_server_is_healthy() -> bool:
    try:
        with urlopen(GEV_HEALTH_URL, timeout=2) as response:
            if response.status != 200:
                return False
            html = response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError):
        return False
    return re.search(
        r"<title>\s*God's Eye View\s*</title>",
        html,
        re.IGNORECASE,
    ) is not None


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=STOP_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2.0)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
    except ProcessLookupError:
        pass


def _gev_runtime() -> tuple[dict[str, str], str, str]:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        part for part in (str(GEV_NODE_DIR), env.get("PATH", "")) if part
    )
    expected = GEV_NODE_DIR / "node.exe"
    node_exe = expected.resolve()
    if not node_exe.is_file():
        raise FileNotFoundError(f"GEV: runtime Node portatile non trovato: {node_exe}")

    # GEV security: invoca solo il node.exe del runtime portatile, mai un node arbitrario.
    if node_exe != expected.absolute():
        raise PermissionError(
            f"GEV: node.exe risolto in {node_exe}, atteso {expected.absolute()}"
        )

    npm_cli = GEV_NODE_DIR / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_cli.is_file():
        raise FileNotFoundError(f"GEV: npm-cli.js non trovato: {npm_cli}")
    return env, str(node_exe), str(npm_cli)


def _creation_options() -> dict[str, int]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _attach_kill_on_close_job(process: subprocess.Popen[str]) -> None:
    """On Windows, terminate GEV and its descendants if Jarvis exits abruptly."""
    global _job_handle, _job_kernel
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())

    limits = ExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        raise ctypes.WinError(error)

    process_handle = wintypes.HANDLE(int(process._handle))
    if not kernel.AssignProcessToJobObject(job, process_handle):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        raise ctypes.WinError(error)

    _job_handle = job
    _job_kernel = kernel


def _attach_to_existing_job(process: subprocess.Popen[str]) -> None:
    """Keep the MCP Node child in the same kill-on-close job as Vite."""
    if os.name != "nt" or _job_handle is None or _job_kernel is None:
        return
    import ctypes
    from ctypes import wintypes

    _job_kernel.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
    ]
    _job_kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    process_handle = wintypes.HANDLE(int(process._handle))
    if not _job_kernel.AssignProcessToJobObject(_job_handle, process_handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _close_job_handle() -> None:
    global _job_handle, _job_kernel
    if _job_handle is not None and _job_kernel is not None:
        _job_kernel.CloseHandle(_job_handle)
    _job_handle = None
    _job_kernel = None


# GEV lifecycle hook
def start() -> None:
    _startup_finished.clear()
    try:
        _start_runtime()
    finally:
        _startup_finished.set()


def _install_gev_dependencies(env: dict[str, str], node_exe: str, npm_cli: str) -> None:
    lockfile = GEV_DIR / "package-lock.json"
    if not lockfile.is_file():
        raise FileNotFoundError(f"GEV: package-lock.json non trovato: {lockfile}")

    _log("GEV: primo avvio, installo le dipendenze bloccate da package-lock.json con npm ci...")
    try:
        result = subprocess.run(
            [node_exe, npm_cli, "ci"],
            cwd=GEV_DIR,
            env=env,
            timeout=INSTALL_TIMEOUT_SEC,
            capture_output=True,
            text=True,
            **_creation_options(),
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part for part in (
                _captured_text(exc.stdout),
                _captured_text(exc.stderr),
            ) if part
        )
        raise TimeoutError(
            f"GEV: npm ci superato il timeout di {INSTALL_TIMEOUT_SEC}s.\n{output}"
        ) from exc
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(f"GEV: npm ci fallito (exit {result.returncode}).\n{output}")


def _start_runtime() -> None:
    """Install locked GEV dependencies if needed and start its local Vite server."""
    global _output_reader, _process, _started, _mcp_client, _mcp_start_error

    with _process_lock:
        if _started:
            return
        if not GEV_DIR.is_dir():
            raise FileNotFoundError(f"GEV: checkout non trovata: {GEV_DIR}")

        server_is_external = _port_is_listening()
        if server_is_external and not _gev_server_is_healthy():
            message = (
                f"GEV: la porta {GEV_PORT} è occupata da un servizio che non "
                "ha superato l'health check di God's Eye View; il processo "
                "esistente non verrà terminato."
            )
            _log(message)
            raise RuntimeError(message)

        env, node_exe, npm_cli = _gev_runtime()
        creation_options = _creation_options()

        if not (GEV_DIR / "node_modules").is_dir():
            _install_gev_dependencies(env, node_exe, npm_cli)

        vite_cli = GEV_DIR / "node_modules" / "vite" / "bin" / "vite.js"
        if not vite_cli.is_file():
            raise FileNotFoundError(f"GEV: vite.js non trovato dopo install: {vite_cli}")

        if not server_is_external and _port_is_listening():
            server_is_external = _gev_server_is_healthy()
            if not server_is_external:
                message = (
                    f"GEV: la porta {GEV_PORT} è stata occupata durante "
                    "l'avvio da un servizio che non ha superato l'health "
                    "check di God's Eye View; il processo esistente non "
                    "verrà terminato."
                )
                _log(message)
                raise RuntimeError(message)

        if server_is_external:
            _log(
                f"GEV: riuso il server God's Eye View esistente su "
                f"{GEV_HEALTH_URL}; il processo non è gestito da JARVIS."
            )
        else:
            with _output_lock:
                _output_lines.clear()

            command = [
                node_exe,
                str(vite_cli),
                "--host", "127.0.0.1",
                "--port", str(GEV_PORT),
                "--strictPort",
            ]
            try:
                _process = subprocess.Popen(
                    command,
                    cwd=GEV_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    **creation_options,
                )
                _attach_kill_on_close_job(_process)
                _output_reader = threading.Thread(
                    target=_read_output,
                    args=(_process,),
                    name="gev-output",
                    daemon=True,
                )
                _output_reader.start()

                deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
                while True:
                    if _process.poll() is not None:
                        if _output_reader is not None:
                            _output_reader.join()
                        output = _process_output() or "(output vuoto)"
                        raise RuntimeError(
                            f"GEV: il server è terminato con exit code "
                            f"{_process.returncode}.\nstdout/stderr:\n{output}"
                        )
                    if _gev_server_is_healthy():
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"GEV: health check non riuscito entro "
                            f"{STARTUP_TIMEOUT_SEC}s.\nstdout/stderr:\n"
                            f"{_process_output() or '(output vuoto)'}"
                        )
                    time.sleep(1)
            except Exception:
                if _process is not None:
                    _terminate_process(_process)
                _close_job_handle()
                _process = None
                _started = False
                raise

        _started = True
        _mcp_start_error = None
        mcp_cli = GEV_DIR / "server" / "mcp" / "stdio.js"
        if not mcp_cli.is_file():
            _mcp_start_error = f"GEV MCP entrypoint not found: {mcp_cli}"
            _log(f"GEV MCP: avvio non riuscito: {_mcp_start_error}")
        else:
            try:
                mcp_client = McpStdioClient(
                    [node_exe, str(mcp_cli), "--api-base", GEV_HEALTH_URL],
                    GEV_DIR,
                    _log,
                    process_started=_attach_to_existing_job,
                )
                mcp_client.start()
                _mcp_client = mcp_client
            except Exception as exc:
                _mcp_start_error = str(exc)
                _log(f"GEV MCP: avvio non riuscito: {_mcp_start_error}")
        _log(f"GEV: pronto su {GEV_HEALTH_URL}")


# GEV lifecycle hook
def stop() -> None:
    """Stop the local GEV subprocess; repeated calls are harmless."""
    global _process, _started, _output_reader, _mcp_client

    with _process_lock:
        mcp_client = _mcp_client
        _mcp_client = None
        if mcp_client is not None:
            try:
                mcp_client.stop()
            except Exception as exc:
                _log(f"GEV MCP: arresto non riuscito: {exc}")
        if not _started and _process is None:
            return
        process = _process
        if process is None or process.poll() is not None:
            _started = False
            _process = None
            _close_job_handle()
            return

        try:
            _terminate_process(process)
        finally:
            _close_job_handle()
            _started = False
            _process = None
            _output_reader = None
        _log("GEV: fermato")


def get_extra_tool_declarations() -> list[dict]:
    """Expose the local GEV MCP catalog as separate Gemini function tools."""
    if not _startup_finished.wait(INSTALL_TIMEOUT_SEC + STARTUP_TIMEOUT_SEC + 30):
        raise TimeoutError("GEV MCP startup did not finish before the declaration deadline")
    if _mcp_client is None:
        if _mcp_start_error:
            raise RuntimeError(f"GEV MCP unavailable: {_mcp_start_error}")
        return []

    declarations = []
    for tool in _mcp_client.tools:
        try:
            parameters = to_gemini_schema(tool["inputSchema"])
            declarations.append({
                "name": f"gev_mcp_{tool['name']}",
                "description": tool["description"],
                "parameters": parameters,
            })
        except (KeyError, TypeError, ValueError) as exc:
            _log(f"GEV MCP: schema non esposto per '{tool.get('name')}': {exc}")
    return declarations


def run_extra_tool(tool_name: str, parameters: dict, player=None) -> str:
    """Call one namespaced GEV MCP tool and return its summary and data."""
    prefix = "gev_mcp_"
    if not isinstance(tool_name, str) or not tool_name.startswith(prefix):
        raise ValueError(f"Invalid GEV MCP tool name: {tool_name!r}")
    if not isinstance(parameters, dict):
        raise TypeError("GEV MCP arguments must be an object")
    mcp_tool_name = tool_name[len(prefix):]
    client = _mcp_client
    if client is None:
        detail = _mcp_start_error or "MCP client is not running"
        raise McpClientError(f"GEV MCP unavailable: {detail}")
    if not any(tool["name"] == mcp_tool_name for tool in client.tools):
        raise McpClientError(f"Unknown GEV MCP tool: {mcp_tool_name}")
    try:
        result = _call_mcp_tool(mcp_tool_name, parameters)
    except (McpClientError, TimeoutError) as exc:
        _log(f"GEV MCP: chiamata '{mcp_tool_name}' fallita: {exc}")
        return f"GEV non è riuscito a eseguire '{mcp_tool_name}': {exc}"
    return tool_result_text(mcp_tool_name, result)


def _call_mcp_tool(tool_name: str, parameters: dict) -> dict:
    client = _mcp_client
    if client is None:
        detail = _mcp_start_error or "MCP client is not running"
        raise McpClientError(f"GEV MCP unavailable: {detail}")
    if not any(tool["name"] == tool_name for tool in client.tools):
        raise McpClientError(f"Unknown GEV MCP tool: {tool_name}")
    return client.call_tool(tool_name, parameters)


def _run_open_with_context(parameters: dict, player, log_message) -> str:
    location = parameters.get("location")
    intent = parameters.get("intent")
    if not isinstance(location, str) or not location.strip():
        return "Per aprire la GEV con contesto mi serve un luogo, signore."
    location = location.strip()[:120]
    if intent not in {"geo", "history"}:
        return "Per aprire la GEV con contesto mi serve l'intento geo o history, signore."

    year = parameters.get("year")
    if year is not None and (
        not isinstance(year, int)
        or isinstance(year, bool)
        or abs(year) > _MAX_SAFE_JS_INTEGER
    ):
        return "Per il contesto storico mi serve un anno intero valido, signore."

    try:
        result = _call_mcp_tool(
            "show_in_gods_eye_view",
            {"area": {"place": location}},
        )
    except (McpClientError, TimeoutError) as exc:
        log_message(f"GEV: impossibile risolvere '{location}' tramite MCP: {exc}")
        return f"Signore, la GEV non ha risolto '{location}': {exc}"

    structured = result.get("structuredContent")
    data = structured.get("data") if isinstance(structured, dict) else None
    view = data.get("view") if isinstance(data, dict) else None
    camera = view.get("camera") if isinstance(view, dict) else None
    if not isinstance(camera, dict):
        return f"Signore, la GEV non ha restituito una vista valida per '{location}'."
    lat, lon = camera.get("lat"), camera.get("lon")
    if (
        not isinstance(lat, (int, float))
        or isinstance(lat, bool)
        or not math.isfinite(lat)
        or not -90 <= lat <= 90
        or not isinstance(lon, (int, float))
        or isinstance(lon, bool)
        or not math.isfinite(lon)
        or not -180 <= lon <= 180
    ):
        return f"Signore, la GEV ha restituito coordinate non valide per '{location}'."

    send_to_gev = getattr(player, "send_to_gev", None)
    wait_for_gev = getattr(player, "wait_for_gev", None)
    if not callable(send_to_gev) or not callable(wait_for_gev):
        return "Signore, l'interfaccia GEV non supporta l'apertura con contesto."
    try:
        send_to_gev({"action": "open_tab", "params": {}})
        if not wait_for_gev(30):
            return "Signore, la GEV non è diventata pronta entro il timeout."
        camera_params = {"lat": lat, "lon": lon}
        altitude = camera.get("altitude_m")
        if (
            isinstance(altitude, (int, float))
            and not isinstance(altitude, bool)
            and math.isfinite(altitude)
            and altitude > 0
        ):
            camera_params["altitude_m"] = altitude
        send_to_gev({"action": "camera_fly", "params": camera_params})
        if intent == "history" and year is not None:
            send_to_gev({
                "action": "historical_map",
                "params": {"command": "show", "year": year},
            })
        theme = parameters.get("theme", "")
        epoch = parameters.get("epoch", "")
        context = " — ".join(
            value.strip()
            for value in (epoch, theme)
            if isinstance(value, str) and value.strip()
        )
        if not context:
            context = f"{intent}: {location}"
        send_to_gev({
            "action": "annotate",
            "params": {"lat": lat, "lon": lon, "text": context[:200]},
        })
    except (RuntimeError, TypeError, ValueError) as exc:
        log_message(f"GEV: apertura contestuale di '{location}' fallita: {exc}")
        return f"Signore, non è stato possibile applicare il contesto alla GEV: {exc}"

    log_message(
        f"GEV: aperta su '{location}' ({intent})"
        + (f", anno {year}" if intent == "history" and year is not None else "")
    )
    return f"Apro God's Eye View su {location} con contesto {intent}, signore."


def _run_historical_request(
    player, request_type: str, response_type: str, params: dict
) -> tuple[dict | list | None, str | None]:
    send_to_gev = getattr(player, "send_to_gev", None)
    on_gev_message = getattr(player, "on_gev_message", None)
    if not callable(send_to_gev) or not callable(on_gev_message):
        return None, "L'interfaccia GEV non supporta le risposte ai comandi storici."

    request_id = f"jarvis-historical-{time.time_ns()}"
    response_ready = threading.Event()
    response: dict | None = None

    def receive(message: dict) -> None:
        nonlocal response
        if (
            isinstance(message, dict)
            and message.get("type") == response_type
            and message.get("id") == request_id
        ):
            response = message
            response_ready.set()

    with _historical_request_lock:
        try:
            on_gev_message(receive)
            send_to_gev({
                "action": "historical_map",
                # The UI accepts this legacy command; GEV dispatches by `type`.
                "params": {
                    "command": "stop",
                    "type": request_type,
                    "id": request_id,
                    **params,
                },
            })
        except Exception as exc:
            return None, f"Invio comando storico non riuscito: {exc}"
        if not response_ready.wait(_HISTORICAL_RESPONSE_TIMEOUT_SEC):
            return None, "GEV non ha risposto entro il timeout del comando storico."
    if response is None:
        return None, "GEV ha restituito una risposta storica vuota."
    if response.get("ok") is not True:
        return None, str(response.get("error", "GEV ha rifiutato il comando storico."))
    result = response.get("result")
    if not isinstance(result, (dict, list)):
        return None, "GEV ha restituito un risultato storico non valido."
    return result, None


def run(parameters: dict, player=None) -> str:
    """Validate an action and forward its abstract message to the UI bridge."""
    if not isinstance(parameters, dict):
        parameters = {}

    action = parameters.get("action", "")
    if not isinstance(action, str):
        action = ""
    action = action.strip()

    write_log = getattr(player, "write_log", None) if player is not None else None

    def log_message(message: str) -> None:
        if callable(write_log):
            try:
                write_log(message)
                return
            except Exception:
                pass
        _log(message)

    allowed_actions = {
        "open", "open_tab", "hide_tab", "open_with_context", "track", "layer",
        "reset", "annotate",
        "historical_map",
        "historical_scenario", "historical_factions",
        "historical_events", "historical_years", "zoom", "tilt", "rotate",
        "reset_camera",
    }
    if action not in allowed_actions:
        log_message(f"GEV: azione sconosciuta '{action}'")
        return f"Non riconosco l'azione GEV '{action}', signore."

    if action == "open_with_context":
        return _run_open_with_context(parameters, player, log_message)

    params: dict[str, object]
    camera_response: str | None = None
    if action in {"open", "open_tab", "hide_tab", "reset", "historical_years"}:
        params = {}
    elif action == "historical_scenario":
        name = parameters.get("name")
        if not isinstance(name, str) or not name.strip():
            return "Per caricare uno scenario storico mi serve il nome, signore."
        params = {"name": name.strip()}
        year = parameters.get("year")
        if year is not None:
            if (
                not isinstance(year, int)
                or isinstance(year, bool)
                or abs(year) > _MAX_SAFE_JS_INTEGER
            ):
                return "Per selezionare l'anno dello scenario mi serve un intero valido, signore."
            params["year"] = year
    elif action == "historical_factions":
        scenario = parameters.get("scenario")
        year = parameters.get("year")
        if not isinstance(scenario, str) or not scenario.strip():
            return "Per applicare le fazioni mi serve lo scenario, signore."
        if (
            not isinstance(year, int)
            or isinstance(year, bool)
            or abs(year) > _MAX_SAFE_JS_INTEGER
        ):
            return "Per applicare le fazioni mi serve un anno intero valido, signore."
        params = {"scenario": scenario.strip(), "year": year}
    elif action == "historical_events":
        scenario = parameters.get("scenario")
        if not isinstance(scenario, str) or not scenario.strip():
            return "Per caricare gli eventi mi serve lo scenario, signore."
        params = {"scenario": scenario.strip()}
        year = parameters.get("year")
        if year is not None:
            if (
                not isinstance(year, int)
                or isinstance(year, bool)
                or abs(year) > _MAX_SAFE_JS_INTEGER
            ):
                return "Per filtrare gli eventi mi serve un anno intero valido, signore."
            params["year"] = year
    elif action == "track":
        target_type = parameters.get("target_type")
        if not isinstance(target_type, str) or target_type not in {"flight", "satellite"}:
            return "Per tracciare un oggetto mi serve il tipo (flight o satellite), signore."
        target_id = parameters.get("target_id")
        if not isinstance(target_id, str) or not target_id.strip():
            target_description, missing = {
                "flight": ("un volo", "il codice"),
                "satellite": ("un satellite", "il NORAD ID"),
            }[target_type]
            return f"Per tracciare {target_description} mi serve {missing}, signore."
        target_id = target_id.strip()
        params = {"target_type": target_type, "target_id": target_id}
    elif action == "layer":
        layer = parameters.get("layer")
        if not isinstance(layer, str) or not layer.strip():
            return "Per modificare un layer mi serve il nome del layer, signore."
        enabled = parameters.get("enabled")
        if not isinstance(enabled, bool):
            return "Per il layer mi dica se devo attivarlo o disattivarlo, signore."
        params = {"layer": layer.strip(), "enabled": enabled}
    elif action == "zoom":
        level = parameters.get("level")
        if isinstance(level, str) and level in {"in", "out"}:
            params = {"level": level}
            camera_response = (
                "Zoom avanti, signore." if level == "in" else "Zoom indietro, signore."
            )
        elif "altitude_m" in parameters:
            altitude = parameters["altitude_m"]
            if (
                not isinstance(altitude, (int, float))
                or isinstance(altitude, bool)
                or not math.isfinite(altitude)
                or not 50 <= altitude <= 20_000_000
            ):
                return "L'altitudine camera deve essere compresa tra 50 e 20000000 metri, signore."
            params = {"altitude_m": altitude}
            camera_response = f"Imposto altitudine a {altitude} m, signore."
        else:
            return "Specifica 'in', 'out' o un'altitudine, signore."
    elif action == "tilt":
        pitch = parameters.get("pitch_deg")
        if (
            not isinstance(pitch, (int, float))
            or isinstance(pitch, bool)
            or not math.isfinite(pitch)
            or not -90 <= pitch <= 0
        ):
            return "L'inclinazione deve essere compresa tra -90 e 0 gradi, signore."
        params = {"pitch_deg": pitch}
        camera_response = f"Inclino la vista a {pitch}°, signore."
    elif action == "rotate":
        heading = parameters.get("heading_deg")
        if (
            not isinstance(heading, (int, float))
            or isinstance(heading, bool)
            or not math.isfinite(heading)
            or not 0 <= heading <= 360
        ):
            return "La rotazione deve essere compresa tra 0 e 360 gradi, signore."
        params = {"heading_deg": heading}
        camera_response = f"Ruoto la vista a {heading}°, signore."
    elif action == "reset_camera":
        params = {}
        camera_response = "Torno alla vista globale, signore."
    elif action == "historical_map":
        command = parameters.get("command")
        if command == "show":
            year = parameters.get("year")
            if (
                not isinstance(year, int)
                or isinstance(year, bool)
                or abs(year) > _MAX_SAFE_JS_INTEGER
            ):
                return "Per mostrare una mappa storica mi serve un anno intero, signore."
            params = {"command": "show", "year": year}
        elif command == "animate":
            start_year = parameters.get("start_year")
            end_year = parameters.get("end_year")
            if any(
                not isinstance(value, int) or isinstance(value, bool)
                or abs(value) > _MAX_SAFE_JS_INTEGER
                for value in (start_year, end_year)
            ):
                return "Per avviare l'animazione mi servono anno iniziale e finale, signore."
            speed = parameters.get("speed", 3)
            if (
                not isinstance(speed, (int, float))
                or isinstance(speed, bool)
                or not 0.5 <= speed <= 30
                or not math.isfinite(speed)
            ):
                return "La velocità deve essere compresa tra 0.5 e 30 secondi per snapshot, signore."
            if start_year > end_year:
                return "L'anno iniziale non può essere successivo a quello finale, signore."
            params = {
                "command": "animate",
                "start_year": start_year,
                "end_year": end_year,
                "speed": speed,
            }
        elif command in {"stop", "clear"}:
            params = {"command": command}
        else:
            return "Per la mappa storica scelga show, animate, stop oppure clear, signore."
    else:
        lat = parameters.get("lat")
        lon = parameters.get("lon")
        if not isinstance(lat, (int, float)) or isinstance(lat, bool) or not -90 <= lat <= 90:
            return "Per annotare mi serve una latitudine valida, signore."
        if not isinstance(lon, (int, float)) or isinstance(lon, bool) or not -180 <= lon <= 180:
            return "Per annotare mi serve una longitudine valida, signore."
        text = parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return "Per annotare mi serve il testo dell'annotazione, signore."
        params = {"lat": lat, "lon": lon, "text": text.strip()}

    send_to_gev = getattr(player, "send_to_gev", None) if player is not None else None
    if not callable(send_to_gev):
        log_message(f"GEV: UI non pronta, azione '{action}' non inviata")
        return (
            f"Signore, non posso eseguire l'azione GEV '{action}': "
            "l'interfaccia non è ancora pronta."
        )

    historical_actions = {
        "historical_scenario": {
            "request_type": "gev:historical-scenario",
            "response_type": "gev:historical-scenario-applied",
        },
        "historical_factions": {
            "request_type": "gev:historical-factions",
            "response_type": "gev:historical-factions-applied",
        },
        "historical_events": {
            "request_type": "gev:historical-events",
            "response_type": "gev:historical-events-applied",
        },
        "historical_years": {
            "request_type": "gev:historical-years",
            "response_type": "gev:historical-years-applied",
        },
    }
    if action in historical_actions:
        historical_action = historical_actions[action]
        result, error = _run_historical_request(
            player,
            historical_action["request_type"],
            historical_action["response_type"],
            params,
        )
        if error:
            log_message(f"GEV: comando '{action}' non riuscito: {error}")
            return f"Signore, il comando storico '{action}' non è riuscito: {error}"
        if action == "historical_years":
            if not isinstance(result, list) or any(
                not isinstance(year, int)
                or isinstance(year, bool)
                or abs(year) > _MAX_SAFE_JS_INTEGER
                for year in result
            ):
                return "GEV ha restituito una lista degli anni non valida, signore."
            return "Anni storici disponibili: " + ", ".join(map(str, result))
        assert isinstance(result, dict)
        if action == "historical_scenario":
            map_result = result.get("map")
            snapshot_year = (
                map_result.get("year")
                if isinstance(map_result, dict)
                else result.get("year", "non disponibile")
            )
            return (
                f"Scenario storico '{params['name']}' caricato: "
                f"snapshot {snapshot_year}, signore."
            )
        if action == "historical_factions":
            return (
                f"Fazioni di '{params['scenario']}' applicate per "
                f"{result.get('selectedFactionYear', params['year'])}, signore."
            )
        return (
            f"Eventi storici di '{params['scenario']}' caricati: "
            f"{result.get('count', 0)}, signore."
        )

    camera_actions = {
        "zoom": "camera_zoom",
        "tilt": "camera_tilt",
        "rotate": "camera_rotate",
        "reset_camera": "camera_reset",
    }
    message = {"action": camera_actions.get(action, action), "params": params}
    try:
        send_to_gev(message)
    except Exception as exc:
        log_message(f"GEV: invio fallito per '{action}': {exc}")
        return f"Signore, l'invio dell'azione GEV '{action}' è fallito: {exc}"

    details = ""
    if action == "track":
        details = f" (target_type={params['target_type']}, target_id={params['target_id']})"
    elif action == "layer":
        details = f" (layer={params['layer']}, enabled={params['enabled']})"
    elif action == "annotate":
        details = f" (lat={params['lat']}, lon={params['lon']})"
    elif action == "historical_map":
        details = f" (command={params['command']})"
    elif action in camera_actions:
        details = f" (bridge={message['action']}, params={params})"
    log_message(f"GEV: invio azione '{action}'{details}")

    if camera_response is not None:
        return camera_response
    if action == "open":
        return "Apro God's Eye View, signore."
    if action == "open_tab":
        return "Apro la scheda God's Eye View con i pannelli visibili, signore."
    if action == "hide_tab":
        return "Torno alla schermata Jarvis; God's Eye View resta aperto, signore."
    if action == "track":
        target_name = {
            "flight": "il volo",
            "satellite": "il satellite",
        }[params["target_type"]]
        return f"Traccio {target_name} {params['target_id']}, signore."
    if action == "layer":
        verb = "Attivo" if params["enabled"] else "Disattivo"
        return f"{verb} il layer {params['layer']}, signore."
    if action == "reset":
        return "Resetto la vista di God's Eye View, signore."
    if action == "historical_map":
        return f"Richiesta mappa storica '{params['command']}' inviata, signore."
    return f"Aggiungo un'annotazione a ({params['lat']}, {params['lon']}), signore."


# GEV lifecycle hook
atexit.register(stop)
