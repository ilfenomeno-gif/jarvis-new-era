"""hud_bridge.py - ponte tra Jarvis e l'HUD (jarvis_hud.html).

Solo libreria standard. Opzionali: psutil (CPU/RAM/disco/rete), nvidia-smi (GPU).
L'HUD viene servito su http://127.0.0.1:8765 e riceve dati runtime via SSE.
Metriche non disponibili sono trasmesse come null e mostrate come N/D.

Uso minimo:
    hud = HudBridge()
    hud.on_message = lambda testo: ...      # chiamata quando scrivi nella chat dell'HUD
    hud.set_plugins_from_dir("plugins")
    hud.start()
    hud.say("Ciao")                         # messaggio in chat + molecole che si separano
"""
from __future__ import annotations

import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterable

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None

HUD_HTML = Path(__file__).with_name("jarvis_hud.html")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class HudBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, html_path: Path = HUD_HTML):
        self.host, self.port, self.html_path = host, port, Path(html_path)
        self.on_message: Callable[[str], None] | None = None   # testo scritto nella chat dell'HUD
        self.on_plugin: Callable[[str], None] | None = None    # click su una molecola plugin
        self.on_system: Callable[[str], None] | None = None    # azione dal tab SISTEMA dell'HUD
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._stats: dict[str, float | int | str | None] = {
            "gpu": None,
            "cpu": None,
            "ram": None,
            "disk": None,
            "net": None,
            "temperature": None,
            "uptime": None,
            "processes": None,
            "os": platform.system(),
        }
        self._gpu_name = ""
        self._plugins: list[dict] = []
        self._runtime: dict = {
            "skills": {"active": 0, "total": 0},
            "task": {"status": "idle", "completed": 0, "total": 0, "progress": 0},
        }
        self._state = "starting"
        self._speaking = False
        self._speak_timer: threading.Timer | None = None
        self._server: ThreadingHTTPServer | None = None
        self._stop = threading.Event()
        self._gpu_ok = shutil.which("nvidia-smi") is not None

    # ------------------------------------------------------------------ API pubblica
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self, window: str = "app") -> str:
        """Avvia server e raccolta statistiche. window: 'app' | 'browser' | 'none'."""
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silenzia il log di default
                pass

            def _host_ok(self) -> bool:  # difesa da DNS rebinding
                return self.headers.get("Host", "") in (f"127.0.0.1:{bridge.port}", f"localhost:{bridge.port}")

            def do_GET(self):
                if not self._host_ok():
                    return self.send_error(403)
                if self.path in ("/", "/index.html"):
                    data = bridge.html_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path == "/events":
                    self._sse()
                else:
                    self.send_error(404)

            def _sse(self):
                q: queue.Queue = queue.Queue(maxsize=200)
                with bridge._lock:
                    bridge._clients.add(q)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    hello = {"type": "hello", "stats": bridge._stats, "gpu_name": bridge._gpu_name,
                             "plugins": bridge._plugins, "speaking": bridge._speaking,
                             "runtime": bridge._runtime, "state": bridge._state}
                    self.wfile.write(f"data: {json.dumps(hello)}\n\n".encode())
                    self.wfile.flush()
                    while not bridge._stop.is_set():
                        try:
                            msg = q.get(timeout=15)
                            self.wfile.write(f"data: {msg}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with bridge._lock:
                        bridge._clients.discard(q)

            def do_POST(self):
                # l'header custom blocca le richieste cross-site (richiederebbe un preflight CORS)
                if not self._host_ok() or self.headers.get("X-HUD") != "1":
                    return self.send_error(403)
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    return self.send_error(400)
                if self.path == "/api/chat" and isinstance(body.get("text"), str) and body["text"].strip():
                    bridge._fire(bridge.on_message, body["text"].strip()[:4000])
                elif self.path == "/api/plugin" and isinstance(body.get("name"), str):
                    bridge._fire(bridge.on_plugin, body["name"][:200])
                elif self.path == "/api/system" and isinstance(body.get("action"), str):
                    bridge._fire(bridge.on_system, body["action"][:200])
                else:
                    return self.send_error(400)
                self.send_response(204)
                self.end_headers()

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name="hud-http", daemon=True).start()
        threading.Thread(target=self._stats_loop, name="hud-stats", daemon=True).start()
        if window != "none":
            self.open_window(window)
        return self.url

    def stop(self) -> None:
        self._stop.set()
        self._broadcast({"type": "shutdown"})
        if self._speak_timer:
            self._speak_timer.cancel()
            self._speak_timer = None
        server, self._server = self._server, None
        if server:
            server.shutdown()
            server.server_close()

    def set_plugins(self, items: Iterable[str | dict]) -> None:
        """['gev_plugin', {'name': 'spotify', 'active': False}, ...]"""
        out = []
        for it in items:
            if isinstance(it, str):
                out.append({"name": it, "active": True})
            else:
                out.append({"name": str(it["name"]), "active": bool(it.get("active", True))})
        self._plugins = out
        self._broadcast({"type": "plugins", "items": out})

    def set_runtime(self, snapshot: dict) -> None:
        self._runtime = snapshot
        self._broadcast({"type": "runtime", "runtime": snapshot})

    def set_state(self, state: str) -> None:
        self._state = state.strip().lower()
        self._broadcast({"type": "state", "state": self._state})

    def set_plugins_from_dir(self, folder: str | os.PathLike) -> None:
        names = sorted(p.stem for p in Path(folder).glob("*.py") if not p.name.startswith("_"))
        self.set_plugins(names)

    def push_chat(self, role: str, text: str) -> None:
        self._broadcast({"type": "chat", "role": role, "text": text})

    def command(self, action: str, **kwargs) -> None:
        """Send a command to the HUD so Jarvis can drive the 3D map UI.

        The HUD (jarvis_hud.html) handles these in its `handleEvent` "command"
        case. Actions: open_system(id), pick(id), tour(), run(scenario),
        say(text), set_task(progress, status). Unknown actions are ignored by
        the HUD (fail-safe).
        """
        self._broadcast({"type": "command", "action": str(action), **kwargs})

    def say(self, text: str, speak: bool = True, role: str = "assistant") -> None:
        """Mostra il messaggio in chat; se speak=True le molecole si separano per una durata stimata.
        Se hai il vero inizio/fine dell'audio usa set_speaking() e passa speak=False."""
        self.push_chat(role, text)
        if speak:
            self.set_speaking(True)
            if self._speak_timer:
                self._speak_timer.cancel()
            self._speak_timer = threading.Timer(max(1.2, len(text) / 14), self.set_speaking, args=(False,))
            self._speak_timer.daemon = True
            self._speak_timer.start()

    def set_speaking(self, on: bool, level: float | None = None) -> None:
        """level 0..1 (opzionale): ampiezza audio reale per pilotare la separazione."""
        self._speaking = on
        self._broadcast({"type": "speak", "on": on, "level": level})

    def open_window(self, mode: str = "app") -> None:
        url = self.url
        if mode == "app" and sys.platform == "win32":
            for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                         os.environ.get("LOCALAPPDATA", "")):
                for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                    exe = Path(base) / rel
                    if base and exe.exists():
                        subprocess.Popen([str(exe), f"--app={url}", "--window-size=1320,820"])
                        return
        webbrowser.open(url)

    # ------------------------------------------------------------------ interni
    def _fire(self, cb: Callable | None, arg: str) -> None:
        if cb:
            threading.Thread(target=cb, args=(arg,), daemon=True).start()

    def _broadcast(self, payload: dict) -> None:
        msg = json.dumps(payload)
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def _read_gpu(self) -> float | None:
        if not self._gpu_ok:
            return None
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,name", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, creationflags=_NO_WINDOW,
            ).stdout.strip().splitlines()[0]
            util, name = [x.strip() for x in out.split(",", 1)]
            self._gpu_name = name
            return float(util)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    def _stats_loop(self) -> None:
        last_net, last_t = None, time.time()
        anchor = Path.home().anchor or "/"
        while not self._stop.is_set():
            s = dict(self._stats)
            for key in ("gpu", "cpu", "ram", "disk", "net", "temperature", "uptime", "processes"):
                s[key] = None
            if psutil is not None:
                try:
                    s["cpu"] = psutil.cpu_percent(interval=None)
                    s["ram"] = psutil.virtual_memory().percent
                    s["uptime"] = max(0.0, time.time() - psutil.boot_time())
                    s["processes"] = len(psutil.pids())
                except (OSError, psutil.Error):
                    pass
                try:
                    s["disk"] = psutil.disk_usage(anchor).percent
                except (OSError, psutil.Error):
                    pass
                try:
                    io = psutil.net_io_counters()
                except (OSError, psutil.Error):
                    io = None
                if io is not None:
                    now, total = time.time(), io.bytes_sent + io.bytes_recv
                    if last_net is not None and now > last_t:
                        s["net"] = max(0.0, (total - last_net) / (now - last_t))
                    last_net, last_t = total, now
                temperatures = getattr(psutil, "sensors_temperatures", None)
                if temperatures is not None:
                    try:
                        readings = temperatures()
                        values = [
                            entry.current
                            for entries in readings.values()
                            for entry in entries
                            if entry.current is not None
                        ]
                        if values:
                            s["temperature"] = max(values)
                    except (OSError, psutil.Error):
                        pass
            g = self._read_gpu()
            if g is not None:
                s["gpu"] = g
            else:
                self._gpu_name = ""
            self._stats = s
            self._broadcast({"type": "stats", "stats": s, "gpu_name": self._gpu_name})
            self._stop.wait(1.0)


if __name__ == "__main__":  # prova rapida: python hud_bridge.py
    hud = HudBridge()
    hud.on_message = lambda text: hud.say(f"Ho ricevuto: {text}")
    plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
    hud.set_plugins_from_dir(plugins_dir) if plugins_dir.is_dir() else hud.set_plugins(["gev_plugin", "demo"])
    print("HUD su", hud.start())
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        hud.stop()
