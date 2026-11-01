from __future__ import annotations

import atexit
import json
import logging
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QPropertyAnimation,
    QThread, QTimer, QUrl, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QKeySequence, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar,
)
from PyQt6.QtTest import QTest
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineSettings
from core.browser_interaction import (
    build_click_link_script, build_keyboard_event_script,
    normalize_link_text, normalize_web_key,
)
from core.animations import ScanlineOverlay, start_pulsing_glow
from core.ui_panels import (
    DOCKS, LAYOUT_VERSION, PanelState, layout_anomalies, layout_path, load_layout, resolve,
    save_layout, wants_chat,
)
from core.page_reader import PageSpeechWorker, build_page_read_script
from core.browser_url import is_allowed_http_scheme, normalize_http_url
from core.hud_animator import HudAnimator, STATE_NAMES
from gemini_chat_window import GeminiChatPanel, GeminiChatWindow

_GEV_URL = "http://127.0.0.1:4173/?ui=panels"


def _gev_url() -> str:
    """GEV page URL; the plugin publishes the port it actually bound (4173 unless it was busy)."""
    port = os.environ.get("JARVIS_GEV_PORT", "")
    if port.isdigit() and 1024 <= int(port) <= 65535:
        return f"http://127.0.0.1:{port}/?ui=panels"
    return _GEV_URL

_GEV_LAYERS = {
    "flights": "flights",
    "vessels": "ais-live-vessels",
    "satellites": "satellites",
    "earthquakes": "earthquakes",
    "fires": "fire-perimeters",
    "cctv": "cctv",
}
_GEV_FOLLOW_KINDS = {
    "flight": "aircraft",
    "satellite": "satellite",
}
_GEV_MAX_SAFE_JS_INTEGER = 2**53 - 1
_JARVIS_VISUAL_STATES = STATE_NAMES


class _GEVWebEnginePage(QWebEnginePage):
    def __init__(self, parent, message_handler):
        super().__init__(parent)
        self._message_handler = message_handler

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        prefix = "GEV_MSG:"
        if message and message.startswith(prefix):
            try:
                payload = json.loads(message[len(prefix):])
            except json.JSONDecodeError as exc:
                print(f"[GEV] Messaggio JavaScript non valido: {exc}", flush=True)
                return
            if isinstance(payload, dict):
                self._message_handler(payload)
            return
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class _ViewerPage(QWebEnginePage):
    """Viewer page: navigation is limited to the local assets/viewer3d folder."""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        from core.viewer3d import is_viewer_url_allowed
        if not is_viewer_url_allowed(url.toString(), BASE_DIR / "assets" / "viewer3d"):
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class ViewerBridge(QObject):
    """QWebChannel object exposed to viewer.js as `bridge` (hover and 3D events)."""

    hoverChanged = pyqtSignal(str, str)
    viewerEvent = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)

    @pyqtSlot(str, str)
    def onEvent(self, name: str, payload_json: str) -> None:
        from core.viewer3d import parse_event
        event = parse_event(name, payload_json)
        if event is not None:
            self.viewerEvent.emit(*event)

    @pyqtSlot(str, str)
    def onHover(self, name: str, text: str) -> None:
        from core.viewer3d import sanitize_hover
        hover = sanitize_hover(name, text)
        if hover is not None:
            self.hoverChanged.emit(hover["name"], hover["text"])


class _SafeBrowserPage(QWebEnginePage):
    def __init__(self, parent, blocked_callback):
        super().__init__(parent)
        self._blocked_callback = blocked_callback

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if not is_allowed_http_scheme(url.scheme()):
            self._blocked_callback()
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class _HudBrowserPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.scheme() != "http" or url.host() not in ("127.0.0.1", "localhost"):
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"


def _read_full_config() -> dict:
    """Read api_keys.json config dict. Returns {} on any error."""
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#00d4ff"
    PRI_DIM   = "#007a99"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#8ffcff"
    TEXT_DIM  = "#3a8a9a"
    TEXT_MED  = "#5ab8cc"
    WHITE     = "#d8f8ff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


# Ana renge (accent) bağlı anahtarlar — durum renkleri (ACC, GREEN, RED…) sabit kalır
_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG",
)
_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}

DEFAULT_UI_COLOR = _PALETTE_DEFAULTS["PRI"]


def apply_ui_accent(accent_hex: str) -> bool:
    """
    Seçilen accent rengine göre tüm turkuaz-ailesi paleti yeniden türetir
    (hue kaydırma — parlaklık/doygunluk oranları korunur, tasarım bozulmaz).
    Boyanan öğeler (HUD, dalga formu, metrikler) bir sonraki karede yeni
    rengi alır; stylesheet tabanlı paneller yeniden kurulduklarında alır.
    """
    import colorsys

    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _hsv(h: str) -> tuple[float, float, float]:
        r = int(h[1:3], 16) / 255
        g = int(h[3:5], 16) / 255
        b = int(h[5:7], 16) / 255
        return colorsys.rgb_to_hsv(r, g, b)

    base_h            = _hsv(_PALETTE_DEFAULTS["PRI"])[0]
    acc_h, acc_s, _av = _hsv(accent_hex)
    dh   = acc_h - base_h
    grey = acc_s < 0.08   # griye yakın accent → tüm tema desaturize edilir

    for key, hex0 in _PALETTE_DEFAULTS.items():
        h, s, v = _hsv(hex0)
        if grey:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        setattr(C, key, "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)))
    return True


def current_palette() -> dict[str, str]:
    """C sınıfındaki accent'e bağlı renklerin anlık kopyası."""
    return {k: getattr(C, k) for k in _HUE_LINKED}


def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    """
    CANLI tam tema değişimi. Uygulamadaki HER widget'ın stylesheet'inde eski
    palet renklerini yenileriyle değiştirir ve yeniden çizdirir. Böylece renk
    değişimi yalnızca boyanan öğelerde değil, panel/buton/kenarlık dahil tüm
    arayüzde ANINDA uygulanır — yeniden başlatma gerekmez.
    """
    mapping = {old[k].lower(): new[k].lower()
               for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                s2 = ss
                for o, n in mapping.items():
                    if o in s2:
                        s2 = s2.replace(o, n)
                if s2 != ss:
                    w.setStyleSheet(s2)
            w.update()
        except Exception:
            pass


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        self._pynvml = None
        self._nv_handle = None
        self._nv_lib = None
        self._nv_lib_failed = False
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            self._nv_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._pynvml = pynvml
        except Exception:
            self._pynvml = None
            self._nv_handle = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def close(self):
        """Stop the sampling thread and release NVML (idempotent)."""
        self._running = False
        thread = getattr(self, "_thread", None)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if self._pynvml is not None:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:
                pass
            self._pynvml = None
            self._nv_handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free, works on all platforms if installed
        if self._pynvml is not None and self._nv_handle is not None:
            try:
                return float(self._pynvml.nvmlDeviceGetUtilizationRates(self._nv_handle).gpu)
            except Exception:
                pass

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        if self._nv_lib_failed:
            return -1.0

        # Linux / macOS: libnvidia-ml shared lib via ctypes (initialised once)
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            if self._nv_lib is None:
                self._nv_lib = ctypes.CDLL(_lib)
                self._nv_lib.nvmlInit_v2()
            nv = self._nv_lib
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            self._nv_lib_failed = True

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess)
        if _OS == "Windows":
            try:
                import wmi  # type: ignore
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()
atexit.register(_metrics.close)

class HudCanvas(QWidget):
    animationChanged = pyqtSignal(object)

    def __init__(self, face_path: str, assistant_name: str = "J.A.R.V.I.S", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self.motion_state = "idle"
        self._hud_animator = HudAnimator()
        self._animation_values = self._hud_animator.update(_allow_reload=False)
        self.reduced_motion = os.environ.get("JARVIS_REDUCED_MOTION") == "1"
        self._error_started: float | None = None
        self._error_flash = 0.0
        self._assistant_name = assistant_name

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.monotonic()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._static_px: QPixmap | None = None
        self._static_key: tuple | None = None
        self._load_face(face_path)
        self._last_step_t = time.monotonic()

        # Live audio reactivity: _live_amp is written from the audio threads
        # (0.0–1.0), _amp_disp is the smoothed value the paint code reads.
        self._live_amp  = 0.0
        self._amp_disp  = 0.0
        self._base_scale = 1.0    # slow "breathing" target; amp is added per-frame
        self._base_halo  = 55.0
        self._cpu_percent = 0.0
        self._gpu_percent = -1.0
        self._projection_status = "WAITING FOR 3D MODEL"

        self._frame = 0
        try:
            fps = float(os.environ.get("JARVIS_UI_FPS", "30"))
        except ValueError:
            fps = 30.0
        self._paint_every = 1 if self.reduced_motion else max(1, round(60 / max(1.0, fps)))
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(33 if self.reduced_motion else 17)

    def set_jarvis_state(self, state: str) -> None:
        normalized = state.strip().lower()
        if normalized not in _JARVIS_VISUAL_STATES:
            raise ValueError(f"Unsupported JARVIS visual state: {state}")
        target = self._hud_animator.set_state(normalized)
        if normalized == "error" or normalized != self.motion_state:
            self._error_started = (
                time.monotonic() if normalized == "error" else None
            )
            self._error_flash = 0.0
        self.motion_state = normalized
        self.animationChanged.emit(target)

    def animation_snapshot(self) -> dict:
        return self._hud_animator.target_snapshot()

    def poll_hud_reload(self) -> bool:
        try:
            reloaded = self._hud_animator.poll_reload()
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).error("HUD configuration reload failed: %s", exc)
            return False
        if reloaded:
            self._animation_values = self._hud_animator.update(_allow_reload=False)
            self.animationChanged.emit(self.animation_snapshot())
            self.update()
        return reloaded

    def stop_animations(self) -> None:
        self._tmr.stop()

    def closeEvent(self, event) -> None:
        self.stop_animations()
        super().closeEvent(event)

    def set_audio_level(self, level: float) -> None:
        """Thread-safe entry point for the audio threads. Stores the louder of
        the incoming level and the current value so brief gaps between chunks
        don't make the waveform stutter; _step() decays it back down."""
        try:
            lv = float(level)
        except (TypeError, ValueError):
            return
        if lv < 0.0:
            lv = 0.0
        elif lv > 1.0:
            lv = 1.0
        if lv > self._live_amp:
            self._live_amp = lv

    def set_system_metrics(self, cpu: float, gpu: float) -> None:
        self._cpu_percent = max(0.0, min(100.0, float(cpu)))
        self._gpu_percent = float(gpu)
        self.update()

    def set_projection_status(self, status: str) -> None:
        self._projection_status = str(status or "WAITING FOR 3D MODEL")[:36].upper()
        self.update()

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        if not self.reduced_motion:
            self._tick += 1
        now = time.monotonic()
        self._animation_values = self._hud_animator.update(now, _allow_reload=False)
        ring_speed = self._animation_values["ring_speed"]
        glow_intensity = self._animation_values["glow_intensity"]

        # ── Live audio reactivity ────────────────────────────────────────────
        # Audio threads push peaks into _live_amp; decay it toward silence so
        # gaps between chunks fade out instead of freezing, then smooth it.
        self._live_amp *= 0.86
        self._amp_disp += (self._live_amp - self._amp_disp) * 0.45
        amp = self._amp_disp
        
        dt = now - getattr(self, '_last_step_t', now)
        self._last_step_t = now

        # Slow "breathing" base target (random shimmer), refreshed on a timer.
        if not self.reduced_motion and now - self._last_t > (
            0.12 if self.speaking else 0.5
        ):
            if self.speaking:
                self._base_scale = 1.03
                self._base_halo  = 122.0
            elif self.muted:
                self._base_scale = random.uniform(0.998, 1.002)
                self._base_halo  = random.uniform(15, 28)
            else:
                self._base_scale = random.uniform(1.001, 1.008)
                self._base_halo  = random.uniform(48, 68)
            self._last_t = now

        # Every frame, the live audio level lifts the target on top of the base
        # — this is what makes the core visibly pulse to the actual voice.
        if self.muted:
            self._tgt_scale, self._tgt_halo = self._base_scale, self._base_halo
        elif self.speaking:
            self._tgt_scale = self._base_scale + amp * 0.13
            self._tgt_halo  = (self._base_halo + amp * 95.0) * glow_intensity
        else:
            self._tgt_scale = self._base_scale + amp * 0.06
            self._tgt_halo  = (self._base_halo + amp * 75.0) * glow_intensity
        if self.motion_state == "error":
            elapsed = now - (self._error_started or now)
            self._error_flash = (
                0.5 + 0.5 * math.sin(elapsed * math.tau * 2.5)
                if elapsed < 0.8 and not self.reduced_motion
                else 0.0
            )
            self._tgt_halo = (
                self._base_halo + 45.0 * self._error_flash
            ) * glow_intensity

        sp = 0.38 if self.speaking else (0.30 if amp > 0.02 else 0.15)
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        if not self.reduced_motion:
            boost = 1.0 + amp * 1.6
            if self.motion_state == "thinking":
                speeds = [1.5, -1.1, 2.1]
            elif self.speaking:
                speeds = [1.3, -0.9, 2.0]
            else:
                speeds = [0.55, -0.35, 0.9]
            for i, speed in enumerate(speeds):
                self._rings[i] = (self._rings[i] + speed * ring_speed * boost) % 360

            self._scan = (
                self._scan + (3.0 if self.speaking else 1.3) * ring_speed * boost
            ) % 360
            self._scan2 = (
                self._scan2 + (-2.0 if self.speaking else -0.75) * ring_speed * boost
            ) % 360

            fw = min(self.width(), self.height())
            lim = fw * 0.74
            pulse_speed = (4.2 if self.speaking else 2.0) * ring_speed
            self._pulses = [
                radius + pulse_speed
                for radius in self._pulses
                if radius + pulse_speed < lim
            ]
            if len(self._pulses) < 3 and random.random() < (
                0.07 if self.speaking else 0.025
            ):
                self._pulses.append(0.0)

            max_particles = int(self._animation_values["particle_count"])
            spawn_chance = min(0.9, max_particles / 24)
            spawn_count = max(1, math.ceil(max_particles / 24))
            if max_particles and random.random() < spawn_chance:
                cx, cy = self.width() / 2, self.height() / 2
                for _ in range(spawn_count):
                    if len(self._particles) >= max_particles:
                        break
                    angle = random.uniform(0, 2 * math.pi)
                    start_radius = fw * 0.28
                    self._particles.append([
                        cx + math.cos(angle) * start_radius,
                        cy + math.sin(angle) * start_radius,
                        math.cos(angle) * random.uniform(0.9, 2.4),
                        math.sin(angle) * random.uniform(0.9, 2.4) - 0.4,
                        1.0,
                    ])
            self._particles = [
                [
                    particle[0] + particle[2],
                    particle[1] + particle[3],
                    particle[2] * 0.97,
                    particle[3] * 0.97,
                    particle[4] - 0.028,
                ]
                for particle in self._particles
                if particle[4] > 0
            ]
            self._particles = self._particles[:max_particles]

            self._blink_tick += 1
            if self._blink_tick >= 38:
                self._blink = not self._blink
                self._blink_tick = 0
        else:
            self._pulses.clear()
            self._particles.clear()
        # Logic stays at 60 Hz so motion speed is unchanged; only repaints are capped (default 30 fps).
        self._frame += 1
        if self._frame % self._paint_every == 0:
            self.update()

    def _rebuild_static_cache(self, W: int, H: int, fw: int, state_color: str, dpr: float) -> None:
        cx, cy = W / 2, H / 2
        px = QPixmap(max(1, int(W * dpr)), max(1, int(H * dpr)))
        px.setDevicePixelRatio(dpr)
        c = QPainter(px)
        c.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QLinearGradient(0, 0, W, H)
        background.setColorAt(0.0, qcol(C.BG))
        background.setColorAt(0.52, qcol(C.DARK))
        background.setColorAt(1.0, qcol(C.BG))
        c.fillRect(QRectF(0, 0, W, H), QBrush(background))

        c.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                c.drawPoint(x, y)

        t_out, t_in = fw * 0.497, fw * 0.474
        c.setPen(QPen(qcol(state_color, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            c.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        ch_r, gap_h = fw * 0.51, fw * 0.16
        c.setPen(QPen(qcol(state_color, 40), 1))
        c.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        c.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        c.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        c.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        bl = 24
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        c.setPen(QPen(qcol(state_color, 210), 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            c.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            c.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))
        c.end()
        self._static_px = px
        self._static_key = (W, H, state_color, dpr, C.BG, C.DARK, C.PRI_GHO)

    def hideEvent(self, e):
        self._tmr.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        if not self._tmr.isActive():
            self._last_step_t = time.monotonic()
            self._tmr.start(33 if self.reduced_motion else 17)
        super().showEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():      # device not ready (e.g. 0-size during layout) — skip cleanly
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        state_color = self._animation_values["core_color"]
        static_state_color = self._animation_values["target_core_color"]
        accent_color = C.MUTED_C if self.muted else state_color

        dpr = self.devicePixelRatioF()
        key = (W, H, static_state_color, dpr, C.BG, C.DARK, C.PRI_GHO)
        if self._static_px is None or self._static_key != key:
            self._rebuild_static_cache(W, H, fw, static_state_color, dpr)
        p.drawPixmap(0, 0, self._static_px)

        r_face = fw * 0.31

        # halo glow: single radial gradient instead of stacked ellipses
        halo_r = r_face * 1.8
        halo_a = max(0, min(255, int(self._halo * 0.85)))
        glow = QRadialGradient(QPointF(cx, cy), halo_r)
        glow.setColorAt(0.0, qcol(accent_color, 0))
        glow.setColorAt(0.55, qcol(accent_color, 0))
        glow.setColorAt(0.8, qcol(accent_color, halo_a // 3))
        glow.setColorAt(1.0, qcol(accent_color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, halo_r * 2, halo_r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(accent_color, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(accent_color, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(accent_color, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(accent_color, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        self._draw_quantum_blueprint(p, W, H, cx, cy, fw, state_color)

        # tick marks, crosshair and corner brackets live in the static cache

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(accent_color, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(state_color)
        elif self.motion_state == "error":
            txt, col = "⚠  ERROR", qcol(state_color)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(state_color)
        elif self.motion_state == "generating_3d":
            sym = "◌" if self._blink else "◍"
            txt, col = f"{sym}  GENERATING 3D", qcol(state_color)
        elif self.motion_state == "thinking":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(state_color)
        elif self.motion_state == "listening":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(state_color)
        elif self.motion_state == "speaking":
            txt, col = "●  SPEAKING", qcol(state_color)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(state_color)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform — reacts to the real audio level (mic while listening,
        # JARVIS's own voice while speaking). Falls back to a gentle idle
        # ripple when there's no sound. _amp_disp is the smoothed 0–1 level.
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        amp = self._amp_disp
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(0, wy - 13, W, 11),
            Qt.AlignmentFlag.AlignCenter,
            "STIMULUS / VOICE INPUT",
        )
        mid = (N - 1) / 2.0
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            else:
                env     = (1.0 - abs(i - mid) / mid) ** 0.7      # center-weighted hump
                shimmer = 0.55 + 0.45 * math.sin(self._tick * 0.18 + i * 0.7)
                idle    = 3.0 + 2.0 * math.sin(self._tick * 0.09 + i * 0.6)
                hgt     = int(max(
                    2,
                    min(
                        24,
                        idle
                        + amp * 22.0 * env * shimmer
                        * self._animation_values["waveform_amplitude"],
                    ),
                ))
                if amp > 0.05:
                    cl = qcol(state_color) if hgt > 12 else qcol(C.PRI_DIM)
                else:
                    cl = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

        p.end()   # end deterministically so the backing store never flushes an active painter

    def _draw_quantum_blueprint(
        self, p: QPainter, W: int, H: int, cx: float, cy: float,
        fw: int, state_color: str,
    ) -> None:
        radius = fw * 0.16
        core_y = cy + fw * 0.015
        top_y = core_y - fw * 0.36
        cylinder_w = fw * 0.27
        cylinder_h = fw * 0.15
        p.save()

        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(
            QRectF(cx - fw * 0.29, top_y - 18, fw * 0.58, 10),
            Qt.AlignmentFlag.AlignCenter,
            "PROJECTION AREA",
        )
        p.setFont(QFont("Courier New", 5))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(cx - fw * 0.34, top_y - 8, fw * 0.68, 10),
            Qt.AlignmentFlag.AlignCenter,
            self._projection_status,
        )

        p.setPen(QPen(qcol(state_color, 130), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx - cylinder_w / 2, top_y), QPointF(cx - cylinder_w / 2, top_y + cylinder_h))
        p.drawLine(QPointF(cx + cylinder_w / 2, top_y), QPointF(cx + cylinder_w / 2, top_y + cylinder_h))
        p.drawEllipse(QRectF(cx - cylinder_w / 2, top_y - cylinder_h * 0.18, cylinder_w, cylinder_h * 0.36))
        p.drawArc(
            QRectF(cx - cylinder_w / 2, top_y + cylinder_h - cylinder_h * 0.18,
                   cylinder_w, cylinder_h * 0.36),
            0, 180 * 16,
        )
        p.drawArc(
            QRectF(cx - cylinder_w / 2, top_y + cylinder_h - cylinder_h * 0.18,
                   cylinder_w, cylinder_h * 0.36),
            180 * 16, 180 * 16,
        )

        glow = QRadialGradient(QPointF(cx, core_y), radius * 1.2)
        glow.setColorAt(0, qcol(state_color, 38))
        glow.setColorAt(0.72, qcol(state_color, 16))
        glow.setColorAt(1, qcol(state_color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - radius * 1.2, core_y - radius * 1.2,
                             radius * 2.4, radius * 2.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(state_color, 210), 1.2))
        p.drawEllipse(QRectF(cx - radius, core_y - radius, radius * 2, radius * 2))
        for latitude in (-0.62, -0.32, 0, 0.32, 0.62):
            half_width = radius * math.sqrt(1 - latitude * latitude)
            ellipse_h = max(2.0, radius * (0.19 if latitude else 0.28))
            p.setPen(QPen(qcol(state_color, 185 if latitude == 0 else 110), 1))
            p.drawEllipse(QRectF(
                cx - half_width, core_y + radius * latitude - ellipse_h / 2,
                half_width * 2, ellipse_h,
            ))
        for longitude in (0.42, 0.72, 1.0):
            p.setPen(QPen(qcol(state_color, 120), 1))
            p.drawEllipse(QRectF(
                cx - radius * longitude, core_y - radius,
                radius * 2 * longitude, radius * 2,
            ))

        pad_y = core_y + radius * 1.55
        pad_w = fw * 0.29
        p.setPen(QPen(qcol(state_color, 180), 1))
        p.drawEllipse(QRectF(cx - pad_w / 2, pad_y - fw * 0.025, pad_w, fw * 0.05))
        p.setPen(QPen(qcol(state_color, 145), 1))
        p.drawEllipse(QRectF(cx - pad_w * 0.34, pad_y - fw * 0.014,
                             pad_w * 0.68, fw * 0.028))
        p.drawLine(
            QPointF(cx - pad_w / 2, pad_y),
            QPointF(cx - pad_w / 2, pad_y + fw * 0.025),
        )
        p.drawLine(
            QPointF(cx + pad_w / 2, pad_y),
            QPointF(cx + pad_w / 2, pad_y + fw * 0.025),
        )
        p.drawArc(
            QRectF(cx - pad_w / 2, pad_y, pad_w, fw * 0.05), 180 * 16, 180 * 16
        )
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(
            QRectF(cx - pad_w / 2, pad_y + fw * 0.025, pad_w, 10),
            Qt.AlignmentFlag.AlignCenter,
            "QUANTUM CORE / PROJECTION PAD",
        )

        side_y = 20
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(12, side_y, fw * 0.31, 10),
                   Qt.AlignmentFlag.AlignLeft, "STIMULUS / VOICE")
        p.setPen(QPen(qcol(C.PRI, 110), 1))
        p.drawLine(QPointF(12, side_y + 13), QPointF(cx - radius, core_y - radius * 0.45))
        wave_x = 12.0
        wave_y = side_y + 22
        wave_color = self._animation_values["core_color"]
        for index in range(12):
            envelope = 0.4 + 0.6 * math.sin(index * 0.58 + self._tick * 0.12)
            bar_h = 2 + int(
                envelope
                * (3 + self._amp_disp * 9 * self._animation_values["waveform_amplitude"])
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(wave_color, 185 if self._amp_disp > 0.02 else 90)))
            p.drawRect(QRectF(wave_x + index * 5, wave_y - bar_h / 2, 3, bar_h))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        gpu_text = f"GPU {self._gpu_percent:.0f}%" if self._gpu_percent >= 0 else "GPU N/A"
        p.drawText(
            QRectF(W - fw * 0.33, side_y, fw * 0.31, 10),
            Qt.AlignmentFlag.AlignRight,
            f"REACTION / {gpu_text}",
        )
        p.setFont(QFont("Courier New", 5))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(W - fw * 0.33, side_y + 10, fw * 0.31, 10),
            Qt.AlignmentFlag.AlignRight,
            f"CPU {self._cpu_percent:.0f}%  VRAM N/A",
        )
        p.setPen(QPen(qcol(C.ACC, 110), 1))
        p.drawLine(QPointF(W - 12, side_y + 24),
                   QPointF(cx + radius, core_y - radius * 0.45))
        p.restore()

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        # HUD Circular Gauge
        cx, cy = 24, H / 2
        r = 14
        
        # Sfondo anello
        p.setPen(QPen(qcol(C.BAR_BG), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Valore anello
        if self._value > 0:
            p.setPen(QPen(bar_col, 3))
            span_angle = int(-self._value * 3.6 * 16)
            # In Qt, 0 è ore 3, 90 è ore 12.
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, span_angle)

        # Centro glow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(bar_col.name(), 150)))
        p.drawEllipse(QPointF(cx, cy), 3, 3)

        # Etichetta (Label)
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(48, 4, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        # Valore (Text)
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(48, 18, W - 54, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)

        p.end()


class HudGauge(QWidget):
    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0
        self._text = "N/A"
        self.setFixedSize(82, 70)

    def set_value(self, pct: float, text: str) -> None:
        self._value = max(0.0, min(100.0, float(pct)))
        self._text = str(text)[:8]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, radius = self.width() / 2, 22.0, 15.0
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(C.BORDER_A), 3))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        if self._value:
            p.setPen(QPen(qcol(self._color), 3))
            p.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                90 * 16, -int(self._value * 3.6 * 16),
            )
        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT), 1))
        p.drawText(QRectF(1, 16, self.width() - 2, 12),
                   Qt.AlignmentFlag.AlignCenter, self._text)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(0, 45, self.width(), 15),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._ai_name_lc = "jarvis"   # updated when assistant name changes
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        _ai_pfx = f"{self._ai_name_lc}:"
        
        icon = "⚡"
        if   tl.startswith("you:"):                              self._tag = "you"; icon = "👤"
        elif tl.startswith(_ai_pfx) or tl.startswith("jarvis:"): self._tag = "ai"; icon = "🤖"
        elif tl.startswith("file:"):                             self._tag = "file"; icon = "📄"
        elif "err" in tl:                                        self._tag = "err"; icon = "❌"
        else:                                                    self._tag = "sys"; icon = "⚙️"
        
        self._text = f"{icon} {self._text}"
        self._tmr.start(33)   # 30 Hz: finer ticks only add layout work

    def _step(self):
        if self._pos < len(self._text):
            # ~60 chars/s for a lone line, more as lines queue up so bursts never lag behind
            ch  = self._text[self._pos:self._pos + min(200, 2 + 8 * len(self._queue))]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += len(ch)
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

        p.end()

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class HueWheel(QWidget):
    """
    Dairesel renk seçici. Kullanıcı tutamacı (küçük beyaz daire) çarkın
    çevresinde sürükleyerek TÜM renk tonları arasından seçim yapar.
    Merkezdeki dolu daire seçilen rengin canlı önizlemesidir.
    """

    hue_picked    = pyqtSignal(str)   # sürükleme sırasında (canlı)
    hue_committed = pyqtSignal(str)   # tutamaç bırakıldığında

    _RING = 16   # halka kalınlığı (px)

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.53
        self._drag = False
        self.set_color(initial_hex)

    # ── API ──────────────────────────────────────────────────────────────────
    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    # ── geometri yardımcıları ────────────────────────────────────────────────
    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()          # ekran y'si aşağı — matematiksel eksene çevir
        ang = math.atan2(dy, dx)      # [-π, π], saat yönünün tersi
        return (ang / (2 * math.pi)) % 1.0

    # ── çizim ────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # merkez önizleme dairesi
        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        # sürüklenen tutamaç
        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#00060a"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)
        p.end()

    # ── fare ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())


class CustomizeOverlay(QWidget):
    """Floating overlay — change identity, voice, reader backend and UI colour."""

    saved = pyqtSignal(str, str, str, str, str, bool, bool, float)
    install_wake_word_requested = pyqtSignal()
    _OW, _OH = 420, 740

    def __init__(self, assistant_name="JARVIS", user_name="",
                 ui_color=DEFAULT_UI_COLOR, voice="", page_reader_engine="system",
                 wake_word_enabled=False, full_duplex_enabled=False,
                 page_reader_speed=1.0,
                 parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        _fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
               f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
               f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        lay.addWidget(_lbl("⚙  CUSTOMISE ASSISTANT", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_lbl("ASSISTANT NAME", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(QFont("Courier New", 10))
        self._name_input.setFixedHeight(32)
        self._name_input.setStyleSheet(_fs)
        lay.addWidget(self._name_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("YOUR NAME  (leave blank for default sir / efendim)", 8,
                            color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._user_input = QLineEdit(user_name)
        self._user_input.setPlaceholderText("e.g.  Tony   (leave blank for auto)")
        self._user_input.setFont(QFont("Courier New", 10))
        self._user_input.setFixedHeight(32)
        self._user_input.setStyleSheet(_fs)
        lay.addWidget(self._user_input)

        # ── Assistant voice — Gemini prebuilt voices ─────────────────────────
        # Names are language-neutral proper nouns, so the row reads the same in
        # every locale. Selecting one and applying rebuilds the Live session.
        from memory.config_manager import AVAILABLE_VOICES, DEFAULT_VOICE
        lay.addSpacing(4)
        lay.addWidget(_lbl("ASSISTANT VOICE", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._sel_voice   = (voice or DEFAULT_VOICE)
        if self._sel_voice not in AVAILABLE_VOICES:
            self._sel_voice = DEFAULT_VOICE
        self._voice_btns: dict[str, QPushButton] = {}
        voice_row = QHBoxLayout(); voice_row.setSpacing(4)
        for _v in AVAILABLE_VOICES:
            b = QPushButton(_v)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
            self._voice_btns[_v] = b
            voice_row.addWidget(b)
        lay.addLayout(voice_row)
        self._refresh_voice_btns()

        lay.addSpacing(4)
        lay.addWidget(_lbl("PAGE READER VOICE", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._page_reader_engine = QComboBox()
        self._page_reader_engine.addItem("SYSTEM VOICE (offline)", "system")
        self._page_reader_engine.addItem(
            "KOKORO NEURAL (offline; model download on first use)",
            "kokoro",
        )
        engine_index = self._page_reader_engine.findData(page_reader_engine)
        self._page_reader_engine.setCurrentIndex(engine_index if engine_index >= 0 else 0)
        self._page_reader_engine.setToolTip(
            "Kokoro may download its voice model on the first read (about 330 MB)."
        )
        self._page_reader_engine.setFixedHeight(28)
        self._page_reader_engine.setStyleSheet(f"""
            QComboBox {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 8px;
            }}
            QComboBox QAbstractItemView {{
                background: #000d12; color: {C.TEXT};
                selection-background-color: {C.PRI_DIM};
            }}
        """)
        lay.addWidget(self._page_reader_engine)

        self._page_reader_speed = QComboBox()
        for speed, label in (
            (0.75, "SLOW"),
            (1.0, "NORMAL"),
            (1.25, "FAST"),
            (1.5, "VERY FAST"),
        ):
            self._page_reader_speed.addItem(label, speed)
        speed_index = self._page_reader_speed.findData(float(page_reader_speed))
        self._page_reader_speed.setCurrentIndex(speed_index if speed_index >= 0 else 1)
        self._page_reader_speed.setToolTip(
            "Adjust Kokoro page-reader speed; SYSTEM VOICE ignores this setting."
        )
        self._page_reader_speed.setFixedHeight(26)
        self._page_reader_speed.setStyleSheet(self._page_reader_engine.styleSheet())
        lay.addWidget(self._page_reader_speed)

        lay.addSpacing(4)
        self._wake_word_checkbox = QCheckBox(
            "Enable local wake phrase (Hey Jarvis)"
        )
        self._wake_word_checkbox.setChecked(bool(wake_word_enabled))
        self._wake_word_checkbox.setToolTip(
            "When enabled, mic audio stays on this device until the phrase is detected."
        )
        self._wake_word_checkbox.setStyleSheet(f"""
            QCheckBox {{ color: {C.TEXT}; background: transparent; spacing: 8px; }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {C.BORDER_B}; background: #000d12;
            }}
            QCheckBox::indicator:checked {{
                background: {C.PRI}; border: 1px solid {C.PRI};
            }}
        """)
        lay.addWidget(self._wake_word_checkbox)

        self._full_duplex_checkbox = QCheckBox(
            "Voice interruption (experimental)"
        )
        self._full_duplex_checkbox.setChecked(
            bool(full_duplex_enabled) and not bool(wake_word_enabled)
        )
        self._full_duplex_checkbox.setToolTip(
            "Experimental: while JARVIS speaks, a local echo classifier may "
            "interrupt on detected speech. Test with your own microphone and speakers."
        )
        self._full_duplex_checkbox.setStyleSheet(self._wake_word_checkbox.styleSheet())
        self._wake_word_checkbox.toggled.connect(
            lambda enabled: self._full_duplex_checkbox.setChecked(False)
            if enabled else None
        )
        self._full_duplex_checkbox.toggled.connect(
            lambda enabled: self._wake_word_checkbox.setChecked(False)
            if enabled else None
        )
        lay.addWidget(self._full_duplex_checkbox)

        self._wake_word_install_btn = QPushButton("DOWNLOAD WAKE WORD MODEL")
        self._wake_word_install_btn.setFixedHeight(28)
        self._wake_word_install_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._wake_word_install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wake_word_install_btn.setToolTip(
            "Explicitly installs openwakeword and downloads its local model files."
        )
        self._wake_word_install_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; }}
        """)
        self._wake_word_install_btn.clicked.connect(
            self.install_wake_word_requested.emit
        )
        lay.addWidget(self._wake_word_install_btn)

        # ── UI colour — renk çarkı ───────────────────────────────────────────
        lay.addSpacing(4)
        clr_hdr = QHBoxLayout()
        clr_hdr.addWidget(_lbl("UI COLOUR  —  drag the handle", 8,
                               color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        clr_hdr.addStretch()
        df_btn = QPushButton("DEFAULT")
        df_btn.setFixedSize(64, 20)
        df_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        clr_hdr.addWidget(df_btn)
        lay.addLayout(clr_hdr)

        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self.on_preview     = None   # callable(hex) — canlı önizleme; MainWindow bağlar

        self._wheel = HueWheel(self._sel_color)
        wheel_row = QHBoxLayout()
        wheel_row.addStretch(); wheel_row.addWidget(self._wheel); wheel_row.addStretch()
        lay.addLayout(wheel_row)
        self._wheel.hue_picked.connect(self._on_wheel_pick)
        self._wheel.hue_committed.connect(self._on_wheel_commit)

        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#00d4ff   (custom hex colour)")
        self._hex_input.setFont(QFont("Courier New", 10))
        self._hex_input.setFixedHeight(28)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        lay.addWidget(self._hex_input)

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("▸  APPLY CHANGES")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(QFont("Courier New", 9))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    # ── ses seçimi ───────────────────────────────────────────────────────────
    def _on_voice_pick(self, name: str):
        self._sel_voice = name
        self._refresh_voice_btns()

    def _refresh_voice_btns(self):
        """Highlight the selected voice pill; dim the rest."""
        for name, b in self._voice_btns.items():
            on = (name == self._sel_voice)
            b.setChecked(on)
            if on:
                b.setStyleSheet(f"""
                    QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                        border: 1px solid {C.PRI}; border-radius: 3px; }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_MED};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
                """)

    # ── renk akışı ───────────────────────────────────────────────────────────
    def _set_color(self, hx: str, update_wheel: bool = True, preview: bool = True):
        """Seçili rengi günceller; hex kutusu + çark senkron kalır, tema canlı önizlenir."""
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if update_wheel:
            self._wheel.set_color(self._sel_color)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)

    def _on_wheel_pick(self, hx: str):
        # Sürükleme sırasında: hex kutusunu güncelle, temayı henüz uygulama
        self._sel_color = hx
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hx)
        self._hex_input.blockSignals(False)

    def _on_wheel_commit(self, hx: str):
        # Tutamaç bırakıldı → tüm arayüzü canlı önizle
        self._set_color(hx, update_wheel=False)

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
            except ValueError:
                return
            self._set_color(t, update_wheel=True, preview=True)

    def _cancel(self):
        # Önizleme uygulandıysa açılıştaki renge geri dön
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "JARVIS"
        user = self._user_input.text().strip()
        self.saved.emit(
            name,
            user,
            self._sel_color or DEFAULT_UI_COLOR,
            self._sel_voice,
            self._page_reader_engine.currentData(),
            self._wake_word_checkbox.isChecked(),
            self._full_duplex_checkbox.isChecked(),
            float(self._page_reader_speed.currentData()),
        )
        self.hide()


class PluginManagerOverlay(QWidget):
    """Floating overlay — lists discovered plugins with per-plugin ON/OFF toggles."""

    _OW = 420

    def __init__(self, plugins: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginManagerOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🧩  PLUGIN MANAGER")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        if not plugins:
            empty = QLabel("No plugins found in /plugins.")
            empty.setFont(QFont("Courier New", 8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(empty)

        for p in plugins:
            lay.addLayout(self._build_row(p))

        lay.addSpacing(4)
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(30)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        self.adjustSize()

    def _build_row(self, p: dict) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(6)

        label_text = p["name"] if p["valid"] else f"{p['name']}  (⚠ {p['file']})"
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT if p['valid'] else C.TEXT_DIM}; background: transparent;")
        lbl.setToolTip(p["description"] if p["valid"] else p["error"])
        lbl.setWordWrap(False)
        row.addWidget(lbl, stretch=1)

        btn = QPushButton()
        btn.setFixedSize(72, 24)
        btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        if not p["valid"]:
            btn.setText("BROKEN")
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
        else:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_toggle(btn, p["enabled"])
            btn.clicked.connect(lambda _, name=p["name"], b=btn: self._toggle(name, b))
        row.addWidget(btn)
        return row

    def _style_toggle(self, btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle(self, name: str, btn: QPushButton):
        from memory.config_manager import get_plugin_enabled, save_plugin_enabled
        new_val = not get_plugin_enabled(name)
        save_plugin_enabled(name, new_val)
        self._style_toggle(btn, new_val)


class _HudOverlay(QWidget):
    """Base for the floating panels placed by hand over the HUD.

    They are children of the central widget but sit in no layout, so Qt never
    invalidates the region they occupy when they hide or shrink: the HUD keeps
    painting around them and their last frame stays on screen as a ghost. Any
    overlay positioned with _centre_overlay needs this."""

    def hideEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            # Repaint exactly what we were covering, before we stop covering it.
            p.update(self.geometry())
        super().hideEvent(e)

    def closeEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            p.update(self.geometry())
        super().closeEvent(e)


class ConfirmBanner(_HudOverlay):
    """The gate in front of an action that cannot be taken back.

    The old confirmation was a tool parameter the model filled in itself, which
    means it confirmed its own shutdown requests. This is the interface asking,
    and the answer travels from a human finger to core/confirm.py without the
    model in the loop. Nothing blocks while it is up: the assistant keeps
    talking, so this costs no latency — unlike the old gate, which spent two
    tool round trips on every power command."""

    answered = pyqtSignal(bool)
    _OW = 430

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ConfirmBanner {{
                background: rgba(14, 3, 0, 250);
                border: 1px solid {C.ACC};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        hdr = QLabel("⚠  CONFIRM")
        hdr.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.ACC}; background: transparent;")
        lay.addWidget(hdr)

        ttl = QLabel(title)
        ttl.setWordWrap(True)
        ttl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        ttl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(ttl)

        if detail:
            dtl = QLabel(detail)
            dtl.setWordWrap(True)
            dtl.setFont(QFont("Courier New", 8))
            dtl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            lay.addWidget(dtl)

        row = QHBoxLayout(); row.setSpacing(8)

        yes = QPushButton("▸  CONFIRM")
        yes.setFixedHeight(32)
        yes.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        yes.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.ACC};
                border: 1px solid {C.ACC}; border-radius: 3px; }}
            QPushButton:hover {{ background: rgba(255,107,0,40); }}
        """)
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(yes)

        no = QPushButton("CANCEL")
        no.setFixedHeight(32)
        no.setFont(QFont("Courier New", 9))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        no.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(no)
        lay.addLayout(row)

        # Default focus on CANCEL: if someone hits Enter without reading, the
        # safe answer wins.
        no.setDefault(True)
        no.setFocus()


class AudioDeviceOverlay(_HudOverlay):
    """Choose which microphone JARVIS listens to and which speakers it uses.

    Both audio streams used to open with no `device=` at all, so they always
    took the OS default — which on Windows moves by itself the moment a headset
    is plugged in. 'JARVIS can't hear me' is usually 'JARVIS is listening to the
    webcam'."""

    picked = pyqtSignal()      # emitted after Apply, when something changed
    _OW = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.audio_devices import list_devices, DEFAULT_LABEL
        from memory.config_manager import get_input_device, get_output_device

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AudioDeviceOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🎧  AUDIO DEVICES")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        _combo_css = (
            f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )

        def _row(label: str, kind: str, current: str) -> QComboBox:
            cap = QLabel(label)
            cap.setFont(QFont("Courier New", 8))
            cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(cap)

            box = QComboBox()
            box.setFont(QFont("Courier New", 9))
            box.setFixedHeight(30)
            box.setStyleSheet(_combo_css)
            # The list is served from a cache warmed on a background thread at
            # startup, so opening this panel never blocks the Qt thread on the
            # host audio API.
            box.addItem(DEFAULT_LABEL, "")
            for name in list_devices(kind):
                box.addItem(name, name)
            idx = box.findData(current) if current else 0
            box.setCurrentIndex(idx if idx >= 0 else 0)
            if current and idx < 0:
                # Saved device is not plugged in right now. Show it rather than
                # silently resetting the user's choice to default.
                box.addItem(f"{current}  (not connected)", current)
                box.setCurrentIndex(box.count() - 1)
            lay.addWidget(box)
            return box

        self._in_box  = _row("MICROPHONE — what JARVIS hears you with",
                             "input", get_input_device())
        lay.addSpacing(4)
        self._out_box = _row("SPEAKERS — what JARVIS talks through",
                             "output", get_output_device())

        note = QLabel("Applying reconnects the session. Your conversation is kept.")
        note.setWordWrap(True)
        note.setFont(QFont("Courier New", 7))
        note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(6)
        lay.addWidget(note)

        row = QHBoxLayout(); row.setSpacing(8)
        ok = QPushButton("▸  APPLY")
        ok.setFixedHeight(32)
        ok.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        ok.clicked.connect(self._apply)
        row.addWidget(ok)

        cancel = QPushButton("CLOSE")
        cancel.setFixedHeight(32)
        cancel.setFont(QFont("Courier New", 9))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel.clicked.connect(self.hide)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _apply(self):
        from memory.config_manager import (
            get_input_device, get_output_device,
            save_input_device, save_output_device,
        )
        new_in  = self._in_box.currentData()  or ""
        new_out = self._out_box.currentData() or ""
        changed = (new_in != get_input_device()) or (new_out != get_output_device())
        save_input_device(new_in)
        save_output_device(new_out)
        self.hide()
        # Only rebuild the session if something actually moved — a no-op Apply
        # should not cost a reconnect.
        if changed:
            self.picked.emit()


class MemoryOverlay(_HudOverlay):
    """Everything JARVIS has stored about you, and when it learned it.

    Memory used to be a 2200-character store that deleted its oldest entries
    when full and mentioned it only on stdout. The cap is gone; this panel is
    the other half of that change — a memory you cannot inspect is a memory you
    cannot trust, and 'delete' has to be something the person can do."""

    _OW = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MemoryOverlay {{
                background: rgba(0, 6, 10, 246);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(5)
        self._rebuild()

    def _clear_layout(self):
        """Take every item out of the layout and detach it from the widget tree
        in this call.

        deleteLater() on its own is not enough: it queues destruction for the
        next event-loop pass, and until then the old rows are still children of
        this widget and still paint — which is what drew half of the previous
        panel over the new one. setParent(None) removes them from the tree now;
        deleteLater() then frees them safely."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() stops it painting in this frame; deleteLater() frees it
                # safely afterwards. setParent(None) would also stop the paint,
                # but it turns the widget into a top-level window for the moment
                # between the two calls, which is not something to leave lying
                # around inside a click handler.
                w.hide()
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw is not None:
                        sw.hide()
                        sw.deleteLater()
                sub.deleteLater()

    def _settle(self, before):
        """Size the panel to its content, re-centre it, and repaint what the old
        size covered.

        The re-size has to happen here rather than at the end of _rebuild
        because Qt has not polished the freshly-created children at that point,
        so the size hint it would read is the empty-layout one. Measured: a
        first adjustSize() returned 32 px for a panel whose content needed 155,
        and a second call — after the same widgets had been through the event
        loop — returned 155. So this runs twice: once now, once on the next
        turn, from _rebuild.

        The re-centre and the repaint are needed because the overlay is placed
        by hand and is in no layout: shrinking it leaves it off-centre and
        leaves its former pixels on screen, since nothing tells the parent that
        region changed. The repaint has to cover the union of the old and new
        rectangles."""
        self._lay.invalidate()
        self._lay.activate()
        self.updateGeometry()
        self.adjustSize()

        p = self.parentWidget()
        if p is None:
            self.update()
            return
        self.move(max(0, (p.width()  - self.width())  // 2),
                  max(0, (p.height() - self.height()) // 2))
        p.update(before.united(self.geometry()))
        self.update()

    def _rebuild(self):
        before = self.geometry()
        self._clear_layout()

        from memory.memory_manager import all_entries_for_ui

        hdr = QLabel("🧠  WHAT JARVIS REMEMBERS")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        self._lay.addWidget(sep)

        rows = all_entries_for_ui()

        cap = QLabel(f"{len(rows)} stored facts — newest first. "
                     f"Nothing here is sent anywhere; it lives in "
                     f"memory/long_term.json on this machine.")
        cap.setWordWrap(True)
        cap.setFont(QFont("Courier New", 7))
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(cap)

        if not rows:
            empty = QLabel("Nothing stored yet.")
            empty.setFont(QFont("Courier New", 9))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            self._lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(min(420, 34 * len(rows) + 10))
            scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {C.BORDER}; border-radius: 3px; "
                f"background: transparent; }}"
            )
            inner = QWidget()
            ilay  = QVBoxLayout(inner)
            ilay.setContentsMargins(6, 6, 6, 6)
            ilay.setSpacing(3)

            for r in rows:
                line = QHBoxLayout(); line.setSpacing(6)
                txt = QLabel(f"<b>{r['key'].replace('_', ' ')}</b> "
                             f"<span style='color:{C.TEXT_MED}'>— {r['value']}</span>")
                txt.setWordWrap(True)
                txt.setFont(QFont("Courier New", 8))
                txt.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
                line.addWidget(txt, 1)

                meta = QLabel(f"{r['category'][:4]} · {r['updated'] or '—'}")
                meta.setFont(QFont("Courier New", 7))
                meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                line.addWidget(meta)

                rm = QPushButton("✕")
                rm.setFixedSize(20, 20)
                rm.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip("Forget this")
                rm.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
                """)
                rm.clicked.connect(
                    lambda _=False, c=r["category"], k=r["key"]: self._forget(c, k))
                line.addWidget(rm)

                holder = QWidget()
                holder.setLayout(line)
                ilay.addWidget(holder)

            ilay.addStretch()
            scroll.setWidget(inner)
            self._lay.addWidget(scroll)

        close = QPushButton("CLOSE")
        close.setFixedHeight(30)
        close.setFont(QFont("Courier New", 9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        self._lay.addWidget(close)

        self._settle(before)
        # …and again once Qt has polished the new children, because the size
        # hint is not final until then. Harmless when the first pass already
        # got it right: _settle is idempotent.
        QTimer.singleShot(0, lambda g=before: self._settle(g))

    def _forget(self, category: str, key: str):
        from memory.memory_manager import forget
        forget(key, category)
        # Rebuild on the NEXT event-loop turn, not inside this click handler.
        # The rebuild destroys the very ✕ button that emitted this signal, and
        # Qt is entitled to touch the sender after a slot returns; tearing it
        # down mid-emission is how a widget ends up half-alive on screen.
        QTimer.singleShot(0, self._rebuild)


class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — offers quick Jarvis actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(0, 8, 14, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setFont(QFont("Courier New", 8))
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(QFont("Courier New", 8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Courier New", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class HudDock(QDockWidget):
    """Movable, closable, floatable side panel. ``closed_by_user`` fires only on the X button."""

    closed_by_user = pyqtSignal(str)

    def __init__(self, name: str, title: str, widget: QWidget, parent: QWidget):
        super().__init__(title, parent)
        self.panel_name = name
        self.setObjectName(f"dock_{name}")
        self.setWidget(widget)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setStyleSheet(
            f"QDockWidget {{ color: {C.PRI}; font: bold 7pt 'Courier New'; }}"
            f"QDockWidget::title {{ background: {C.PANEL2}; text-align: left; "
            f"padding: 4px 8px; border-bottom: 1px solid {C.BORDER}; }}"
        )

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self.closed_by_user.emit(self.panel_name)


class MainWindow(QMainWindow):
    _log_sig          = pyqtSignal(str)
    _state_sig        = pyqtSignal(str)
    _generation_status_sig = pyqtSignal(str)
    _generation_elapsed_sig = pyqtSignal(int)
    _generation_fallback_sig = pyqtSignal(object)
    _content_hide_sig = pyqtSignal(str)      # title prefix of the content panel to close
    _content_sig      = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _hud_browser_sig  = pyqtSignal(str)
    _reconfig_sig     = pyqtSignal()           # trigger setup overlay from any thread
    _camera_sig       = pyqtSignal(bytes)      # show camera frame preview (small overlay)
    _cam_stream_sig   = pyqtSignal(bool)       # True=start live stream, False=stop
    _cam_frame_sig    = pyqtSignal(bytes)      # live camera frame → HUD area
    _clipboard_sig    = pyqtSignal(str)        # clipboard text changed (thread-safe)
    _confirm_sig      = pyqtSignal(str, str)   # (title, detail) — irreversible-action gate
    _confirm_hide_sig = pyqtSignal()
    _widget_sig       = pyqtSignal(dict)       # (spec) — generic widget bus, thread-safe
    _gev_send_sig     = pyqtSignal(str)
    _gemini_chat_sig  = pyqtSignal()
    _streaming_play_confirm_sig = pyqtSignal(str, object)
    _browser_open_sig = pyqtSignal(str)
    _browser_close_sig = pyqtSignal()
    _browser_key_sig = pyqtSignal(str)
    _browser_click_sig = pyqtSignal(str)
    _browser_read_page_sig = pyqtSignal(str)
    _browser_stop_reading_sig = pyqtSignal()
    _page_reader_audio_sig = pyqtSignal(bool)
    _wake_word_setup_result_sig = pyqtSignal(bool, str)
    _dictation_result_sig = pyqtSignal(bool, str)
    _dictation_busy_sig = pyqtSignal(bool)
    _focus_mode_sig = pyqtSignal(bool)
    _workspace_sig = pyqtSignal(str)
    _panel_sig = pyqtSignal(str, bool)
    _float_sig = pyqtSignal(str, int)        # (panel, -1 toggle / 0 dock / 1 float)
    _restore_layout_sig = pyqtSignal()
    _viewer_show_sig = pyqtSignal(bool)
    _viewer_call_sig = pyqtSignal(str, str)

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path
        self._gev_ready_evt = threading.Event()
        self._gev_load_started = False
        self._gev_tab_open = False
        self._gev_previous_content_visible = False
        self._gev_previous_split_sizes: list[int] = []
        self._gev_message_dispatch = None
        self._gemini_chat_window: GeminiChatWindow | None = None
        self._gemini_chat_panel: GeminiChatPanel | None = None
        self._gemini_previous_widget: QWidget | None = None
        self._gev_view_state = {
            "camera": {
                "lat": 0,
                "lon": 0,
                "altitude_m": 800_000,
                "heading_deg": 0,
                "pitch_deg": -90,
            },
            "layers": [],
            "style": None,
            "map": None,
            "follow": None,
            "annotations": [],
        }

        # Load customization from config
        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "JARVIS").strip()
        _display = self._assistant_name.upper()

        # Kayıtlı UI rengini panel/stylesheet'ler kurulmadan ÖNCE uygula
        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        self.setWindowTitle(f"{_display} — MARK LII")
        self.setObjectName("jarvisMainWindow")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)
        self._reduced_motion = os.environ.get("JARVIS_REDUCED_MOTION") == "1"
        self._title_glow: QPropertyAnimation | None = None
        self._scanline: ScanlineOverlay | None = None

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_voice_change   = None   # callable: () -> None — rebuild session with new voice
        self.on_audio_input_mode_change = None
        self.on_audio_device_change = None  # callable: () -> None — reopen audio streams
        self._confirm_overlay  = None   # live ConfirmBanner, if one is on screen
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self.get_hud_runtime  = None   # callable: () -> runtime telemetry, set by JarvisLive
        self._muted            = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None
        self._wake_word_setup_active = False
        self._generation_backend = ""
        self._generation_started_at = 0.0
        self._generation_elapsed = 0

        central = QWidget()
        central.setObjectName("jarvisCentralWidget")
        self.setCentralWidget(central)
        self._apply_theme()

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._panel_state = PanelState()
        self._header_panel = self._build_header()
        root.addWidget(self._header_panel)
        self._title_glow = start_pulsing_glow(
            self._title_lbl, C.PRI, reduced_motion=self._reduced_motion
        )

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Center column: HUD + resizable content panel via QSplitter
        self.hud = HudCanvas(face_path, _display)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._scanline = ScanlineOverlay(
            self.hud, C.PRI, reduced_motion=self._reduced_motion
        )
        self._content_panel = self._build_content_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #000308;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # Stack: animated HUD fallback, camera, GEV, embedded browser HUD
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.addWidget(_cam_cont)

        self._gev_stack = QStackedWidget()
        self._gev_placeholder = QLabel("GEV NON CARICATO")
        self._gev_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gev_placeholder.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: #000308; font-family: 'Courier New';"
        )
        self._gev_view = QWebEngineView()
        self._gev_page = _GEVWebEnginePage(self._gev_view, self._on_gev_message)
        self._gev_view.setPage(self._gev_page)
        self._gev_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._gev_view.loadFinished.connect(self._on_gev_load_finished)
        self._gev_stack.addWidget(self._gev_placeholder)
        self._gev_stack.addWidget(self._gev_view)
        self._gev_stack.setCurrentWidget(self._gev_placeholder)
        self._hud_cam_stack.addWidget(self._gev_stack)

        self._hud_browser_view = QWebEngineView()
        self._hud_browser_view.setPage(_HudBrowserPage(self._hud_browser_view))
        self._hud_browser_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._hud_browser_view.loadFinished.connect(
            self._on_hud_browser_load_finished
        )
        self._hud_browser_loaded = False
        self._hud_cam_stack.addWidget(self._hud_browser_view)

        self._browser_panel = self._build_browser_panel()
        self._browser_return_widget: QWidget | None = None
        self._main_content_stack = QStackedWidget()
        self._main_content_stack.addWidget(self._hud_cam_stack)
        self._main_content_stack.addWidget(self._browser_panel)
        try:
            self._gemini_chat_panel = GeminiChatPanel()
            self._gemini_chat_panel.closeRequested.connect(
                self._close_gemini_chat
            )
            self._main_content_stack.addWidget(self._gemini_chat_panel)
        except Exception as exc:
            self._gemini_chat_panel = None
            print(
                f"[JARVIS] Gemini chat panel unavailable; fallback enabled: {exc}",
                flush=True,
            )
        self._main_content_stack.setCurrentWidget(self._hud_cam_stack)

        # GEV checks this flag with strict boolean equality during module startup.
        embed_script = QWebEngineScript()
        embed_script.setName("jarvis-gev-inline-bridge")
        embed_script.setInjectionPoint(
            QWebEngineScript.InjectionPoint.DocumentCreation
        )
        embed_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        embed_script.setSourceCode(
            "window.GEV_EMBED_INLINE = true;"
            "window.addEventListener('message', event => {"
            " const data = event.data;"
            " if (data && typeof data.type === 'string' && data.type.startsWith('gev:'))"
            "  console.log('GEV_MSG:' + JSON.stringify(data));"
            "});"
        )
        self._gev_page.scripts().insert(embed_script)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER};
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._main_content_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        root.addLayout(body, stretch=1)
        self._footer_panel = self._build_footer()
        root.addWidget(self._footer_panel)
        self._build_docks()

        # Quick-access drawer (floating overlay, built after central widget layout is done)
        self._quick_drawer = self._build_quick_drawer()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()
        self._generation_tmr = QTimer(self)
        self._generation_tmr.timeout.connect(self._tick_generation_status)

        self._log_sig.connect(self._on_log_message)
        self._state_sig.connect(self._apply_state)
        self._generation_status_sig.connect(self._set_generation_status)
        self._generation_elapsed_sig.connect(self._set_generation_elapsed)
        self._generation_fallback_sig.connect(self._handle_generation_fallback)
        self.hud.animationChanged.connect(self._viewer3d_set_hud_state)
        self._hud_reload_timer = QTimer(self)
        self._hud_reload_timer.setInterval(250)
        self._hud_reload_timer.timeout.connect(self.hud.poll_hud_reload)
        self._hud_reload_timer.start()
        self._content_sig.connect(self._show_content)
        self._hud_browser_sig.connect(self._load_hud_browser)
        self._content_hide_sig.connect(self._hide_content_if)
        self._widget_sig.connect(self._on_widget)
        self._gev_send_sig.connect(self._on_gev_send)
        self._gemini_chat_sig.connect(self._show_gemini_chat)
        self._streaming_play_confirm_sig.connect(
            self._confirm_streaming_play_on_ui_thread
        )
        self._browser_open_sig.connect(self._open_url_in_webview)
        self._browser_close_sig.connect(self.close_browser)
        self._focus_mode_sig.connect(self.set_focus_mode)
        self._workspace_sig.connect(self.apply_workspace)
        self._panel_sig.connect(self.set_panel_visible)
        self._float_sig.connect(self._on_float_sig)
        self._restore_layout_sig.connect(self.restore_layout)
        self._viewer_show_sig.connect(self.show_viewer3d)
        self._viewer_call_sig.connect(self.viewer3d_call)
        self._browser_key_sig.connect(self._press_key_in_webview)
        self._browser_click_sig.connect(self._click_link_in_webview)
        self._browser_read_page_sig.connect(self._read_page_aloud)
        self._browser_stop_reading_sig.connect(self._stop_page_reading)
        self._wake_word_setup_result_sig.connect(self._on_wake_word_setup_result)
        self._dictation_result_sig.connect(self._on_dictation_result)
        self._dictation_busy_sig.connect(self._set_dictation_busy)
        self._page_read_pending = False
        self._page_reader = PageSpeechWorker(
            on_error=self._log_sig.emit,
            on_started=self._page_reader_started,
            on_finished=self._page_reader_finished,
        )
        # Widget system state
        self._active_widgets: dict[str, QWidget] = {}
        self._toast_timers:   dict[str, QTimer]  = {}
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._confirm_sig.connect(self._show_confirm_banner)
        self._confirm_hide_sig.connect(self._hide_confirm_banner)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._cam_stop = threading.Event()

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # Clipboard panel (child of central widget, bottom-center)
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)
        sc_focus = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        sc_focus.activated.connect(lambda: self.set_focus_mode(not self._focus_mode))
        self._load_saved_layout()
        self._layout_timer = QTimer(self)
        self._layout_timer.timeout.connect(self._persist_layout)
        self._layout_timer.start(5000)

    # --- Dock layout ---------------------------------------------------------
    _DOCK_TITLES = {
        "controls": "◈ SYS MONITOR",
        "activity_log": "▸ ACTIVITY LOG",
        "input": "▸ INPUT",
    }
    _pre_focus = None
    _last_saved_layout = b""

    def _build_docks(self) -> None:
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
        )
        panels = {
            "controls": (self._build_left_panel(), Qt.DockWidgetArea.LeftDockWidgetArea),
            "activity_log": (self._build_log_panel(), Qt.DockWidgetArea.RightDockWidgetArea),
            "input": (self._build_input_panel(), Qt.DockWidgetArea.RightDockWidgetArea),
        }
        self._docks: dict[str, HudDock] = {}
        self._dock_floating = {name: False for name in DOCKS}
        for name, (widget, area) in panels.items():
            dock = HudDock(name, self._DOCK_TITLES[name], widget, self)
            dock.closed_by_user.connect(self._on_dock_closed)
            dock.topLevelChanged.connect(
                lambda floating, n=name: self._dock_floating.__setitem__(n, bool(floating))
            )
            self.addDockWidget(area, dock)
            self._docks[name] = dock
        self.resizeDocks([self._docks["controls"]], [_LEFT_W], Qt.Orientation.Horizontal)
        self.resizeDocks(
            [self._docks["activity_log"], self._docks["input"]], [_RIGHT_W, _RIGHT_W],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks(
            [self._docks["activity_log"], self._docks["input"]], [520, 300],
            Qt.Orientation.Vertical,
        )
        self._default_state = self.saveState(LAYOUT_VERSION)
        self._header_panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._header_panel.customContextMenuRequested.connect(
            lambda pos: self._layout_menu().exec(self._header_panel.mapToGlobal(pos))
        )

    def _layout_menu(self) -> QMenu:
        menu = QMenu(self)
        for name in DOCKS:
            action = menu.addAction(self._DOCK_TITLES[name].lstrip("◈▸ ").title())
            action.setCheckable(True)
            action.setChecked(self._panel_state.visible(name))
            action.toggled.connect(lambda checked, n=name: self.set_panel_visible(n, checked))
        menu.addSeparator()
        menu.addAction("Ripristina layout", self.restore_layout)
        return menu

    def createPopupMenu(self) -> QMenu:
        return self._layout_menu()

    def _on_dock_closed(self, name: str) -> None:
        self._pre_focus = None
        self._panel_state.set_visible(name, False)

    def _on_float_sig(self, panel: str, mode: int) -> None:
        self.float_panel(panel, None if mode < 0 else bool(mode))

    def float_panel(self, panel: str, floating: bool | None = None) -> None:
        """Tear a dock off into its own window (or put it back). A hidden dock is shown first."""
        for name in resolve(panel):
            dock = self._docks.get(name)
            if dock is None:
                raise ValueError(f"'{name}' is not a dock; docks are: {', '.join(DOCKS)}.")
            target = (not dock.isFloating()) if floating is None else bool(floating)
            if target and not self._panel_state.visible(name):
                self._pre_focus = None
                self._panel_state.set_visible(name, True)
                dock.setVisible(True)
            dock.setFloating(target)

    def restore_layout(self) -> None:
        """Back to the original arrangement: all docks shown, docked, in their default place."""
        self._pre_focus = None
        for dock in self._docks.values():
            dock.setFloating(False)
        self.restoreState(self._default_state, LAYOUT_VERSION)
        self._panel_state.apply_workspace("full")
        self._render_panels()

    def _layout_snapshot(self) -> dict:
        return {
            "qt_state": bytes(self.saveState(LAYOUT_VERSION)),
            "geometry": bytes(self.saveGeometry()),
            "panels": self._panel_state.snapshot(),
            "workspace": self._panel_state.workspace,
            "floating": dict(self._dock_floating),
        }

    def _persist_layout(self, force: bool = False) -> None:
        """Save only when something changed; skipped while focus mode has the docks hidden."""
        if self._pre_focus is not None or self._panel_state.workspace == "focus":
            return
        snap = self._layout_snapshot()
        fingerprint = repr(sorted(snap.items(), key=lambda kv: kv[0])).encode()
        if not force and fingerprint == self._last_saved_layout:
            return
        try:
            save_layout(layout_path(), **snap)
            self._last_saved_layout = fingerprint
        except OSError as exc:
            self._log_sig.emit(f"UI: salvataggio layout non riuscito: {exc}")

    def _load_saved_layout(self) -> None:
        data = load_layout(layout_path())
        if data is None:
            return
        problems = layout_anomalies(data)
        if problems:
            self._log_sig.emit(f"UI: layout salvato anomalo ({', '.join(problems)}): uso il default")
            self.restore_layout()
            return
            self.restoreGeometry(data["geometry"])
        if not self.restoreState(data["qt_state"], LAYOUT_VERSION):
            self.restoreState(self._default_state, LAYOUT_VERSION)
        workspace = data["workspace"]
        self._panel_state.restore(data["panels"], "custom" if workspace == "focus" else workspace)
        # Without the input dock the user cannot type, so a saved "closed" state is never restored.
        if not self._panel_state.visible("input"):
            self._panel_state.set_visible("input", True)
            self._docks["input"].setVisible(True)
        self._render_panels()
        # Input must never end up floating, whatever the restored Qt state says.
        if self._docks["input"].isFloating():
            self._docks["input"].setFloating(False)
        self._last_saved_layout = repr(
            sorted(self._layout_snapshot().items(), key=lambda kv: kv[0])
        ).encode()

    @property
    def _focus_mode(self) -> bool:
        return self._panel_state.workspace == "focus"

    def set_focus_mode(self, active: bool) -> None:
        """Hide the docks so only the central HUD stays visible; leaving brings them back as they were."""
        if active:
            self.apply_workspace("focus")
        elif self._pre_focus is not None and self._panel_state.workspace == "focus":
            visible, workspace, content_shown = self._pre_focus
            self._pre_focus = None
            self._panel_state.restore(visible, workspace)
            self._render_panels()
            # The content panel opens on demand, so give back exactly what was on screen
            self._content_panel.setVisible(content_shown and visible["content"])
        else:
            self.apply_workspace("full")

    def apply_workspace(self, name: str) -> None:
        was_focus = self._panel_state.workspace == "focus"
        before = (
            self._panel_state.snapshot(), self._panel_state.workspace,
            self._content_panel.isVisible(),
        )
        self._panel_state.apply_workspace(name)
        if self._panel_state.workspace == "focus":
            if not was_focus:
                self._pre_focus = before
        else:
            self._pre_focus = None
        self._render_panels()
        if name == "recon":
            self.show_viewer3d(True)

    def set_panel_visible(self, panel: str, visible: bool) -> None:
        self._pre_focus = None
        self._panel_state.set_visible(panel, visible)
        self._render_panels()

    _viewer3d = None
    _viewer3d_loaded = False
    _viewer3d_pending: list = []

    def _viewer3d_ensure(self):
        if self._viewer3d is None:
            view = QWebEngineView()
            page = _ViewerPage(view)
            self._viewer3d_bridge = ViewerBridge(view)
            self._viewer3d_bridge.hoverChanged.connect(self._viewer3d_set_hover)
            self._viewer3d_bridge.viewerEvent.connect(self._viewer3d_on_event)
            self._viewer3d_channel = QWebChannel(page)
            self._viewer3d_channel.registerObject("bridge", self._viewer3d_bridge)
            page.setWebChannel(self._viewer3d_channel)
            view.setPage(page)
            # The page is our own local file; it must read models/*.glb beside it.
            view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
            )
            view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            view.loadFinished.connect(self._viewer3d_on_loaded)
            self._viewer3d_pending = []
            view.load(QUrl.fromLocalFile(
                str(BASE_DIR / "assets" / "viewer3d" / "index.html")
            ))
            self._hud_cam_stack.addWidget(view)
            self._viewer3d = view
        return self._viewer3d

    _viewer3d_hover_state: dict = {"name": "", "text": ""}
    _viewer3d_models: dict = {}
    _viewer3d_active: str = ""
    _viewer3d_look: dict = {}
    _LOOK_COMMANDS = ("setLighting", "setMaterialStyle")
    _viewer3d_last_error: str = ""
    _viewer3d_shot = None  # {"event": threading.Event, "path": str, "error": str} while a screenshot is awaited

    def _viewer3d_on_event(self, name: str, payload: dict) -> None:
        """Events from viewer.js (QWebChannel), already whitelisted and size-checked."""
        from core.viewer3d import save_screenshot
        if name == "modelLoaded":
            self._viewer3d_models = {**self._viewer3d_models, str(payload.get("id")): payload}
            self._viewer3d_active = str(payload.get("id"))
            self.hud.set_projection_status(f"MODEL READY / {payload.get('id', '')}")
            self.show_viewer3d(True)
            if self._viewer3d_loaded:
                for look_script in self._viewer3d_look.values():
                    self._viewer3d.page().runJavaScript(look_script)
        elif name == "modelRemoved":
            self._viewer3d_models = {k: v for k, v in self._viewer3d_models.items() if k != payload.get("id")}
            if self._viewer3d_active == str(payload.get("id")):
                self._viewer3d_active = next(reversed(self._viewer3d_models), "")
            self.hud.set_projection_status(
                f"MODEL READY / {self._viewer3d_active}"
                if self._viewer3d_active else "WAITING FOR 3D MODEL"
            )
        elif name == "activeModelChanged":
            self._viewer3d_active = str(payload.get("id"))
            if self._viewer3d_active in self._viewer3d_models:
                self.hud.set_projection_status(
                    f"MODEL READY / {self._viewer3d_active}"
                )
        elif name == "commandError":
            self._viewer3d_last_error = str(payload.get("message", ""))[:300]
            if payload.get("command") == "loadModel":
                self.hud.set_projection_status(
                    f"MODEL LOAD FAILED / {self._viewer3d_last_error}"
                )
                self.show_viewer3d(False)
            shot = self._viewer3d_shot
            if shot and payload.get("command") == "screenshot":
                shot["error"] = self._viewer3d_last_error
                shot["event"].set()
        elif name == "screenshot":
            shot = self._viewer3d_shot
            try:
                path = save_screenshot(payload.get("dataUrl"))
            except (ValueError, OSError) as exc:
                if shot:
                    shot["error"] = str(exc)
            else:
                if shot:
                    shot["path"] = str(path)
            if shot:
                shot["event"].set()

    def _viewer3d_set_hud_state(self, snapshot: dict) -> None:
        if self._viewer3d is None:
            return
        self.viewer3d_call(
            "setHudState",
            json.dumps([
                snapshot["state"],
                snapshot["core_color"],
                snapshot["ring_speed"],
                snapshot["glow_intensity"],
                snapshot["particle_count"],
                snapshot["transition_seconds"],
            ]),
        )

    def _active_hud_widget(self) -> QWidget:
        return self._hud_browser_view if self._hud_browser_loaded else self.hud

    def _load_hud_browser(self, url: str) -> None:
        target = QUrl(url)
        if (
            not target.isValid()
            or target.scheme() != "http"
            or target.host() not in ("127.0.0.1", "localhost")
            or not 1 <= target.port(-1) <= 65535
        ):
            self._log_sig.emit("SYS: HUD browser URL must use the local Jarvis bridge.")
            return
        self._hud_browser_view.load(target)

    def _on_hud_browser_load_finished(self, succeeded: bool) -> None:
        self._hud_browser_loaded = bool(succeeded)
        if succeeded:
            self._hud_cam_stack.setCurrentWidget(self._hud_browser_view)
            self._main_content_stack.setCurrentWidget(self._hud_cam_stack)
        else:
            self._hud_cam_stack.setCurrentWidget(self.hud)
            self._log_sig.emit(
                "SYS: Embedded HUD failed to load; using the native HUD instead."
            )

    def _viewer3d_set_hover(self, name: str, text: str) -> None:
        self._viewer3d_hover_state = {"name": name, "text": text}

    def _viewer3d_on_loaded(self, ok: bool) -> None:
        self._viewer3d_loaded = bool(ok)
        pending, self._viewer3d_pending = self._viewer3d_pending, []
        if ok:
            for script in pending:
                self._viewer3d.page().runJavaScript(script)
            self._viewer3d_set_hud_state(self.hud.animation_snapshot())

    def show_viewer3d(self, visible: bool) -> None:
        if visible:
            view = self._viewer3d_ensure()
            self._hud_cam_stack.setCurrentWidget(view)
            self._main_content_stack.setCurrentWidget(self._hud_cam_stack)
        elif self._viewer3d is not None:
            self._hud_cam_stack.setCurrentWidget(self._active_hud_widget())

    def viewer3d_call(self, function: str, args_json: str) -> None:
        from core.viewer3d import build_call
        function, args_json = build_call(function, json.loads(args_json))
        script = (
            f"try {{ window.jarvisViewer.{function}(...JSON.parse({json.dumps(args_json)})); }} "
            f"catch (e) {{ window.jarvisViewer.onEvent('commandError', "
            f"{{command: {json.dumps(function)}, message: String(e && e.message || e)}}); }}"
        )
        self._viewer3d_ensure()
        if function == "clearModel" or (function == "loadModel" and len(json.loads(args_json)) == 1):
            # A replacing load supersedes queued model commands from before page load.
            self._viewer3d_pending = [
                s for s in self._viewer3d_pending
                if not any(f"window.jarvisViewer.{n}(" in s for n in (
                    "loadModel", "clearModel", "removeModel", "setPartInfo",
                    "highlightPart", "explodeModel"))
            ]
        if function in ("flyTo", "addMarker", "setFlights", "loadModel"):
            self.show_viewer3d(True)
        if function in self._LOOK_COMMANDS:
            # Remembered and re-applied after every model load, so a look requested while
            # a model is still loading (or after a failed call) is never lost.
            self._viewer3d_look = {**self._viewer3d_look, function: script}
        if self._viewer3d_loaded:
            self._viewer3d.page().runJavaScript(script)
        else:
            self._viewer3d_pending.append(script)

    def _render_panels(self) -> None:
        widgets = {
            "header": self._header_panel,
            "content": self._content_panel,
            "footer": self._footer_panel,
            **self._docks,
        }
        for name, widget in widgets.items():
            widget.setVisible(self._panel_state.visible(name))

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        self._main_content_stack.setCurrentWidget(self._hud_cam_stack)
        if start:
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._hud_cam_stack.setCurrentWidget(self._active_hud_widget())
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    def load_gev(self) -> None:
        self._main_content_stack.setCurrentWidget(self._hud_cam_stack)
        self._hud_cam_stack.setCurrentWidget(self._gev_stack)
        if self._gev_load_started:
            return
        self._gev_load_started = True
        self._gev_ready_evt.clear()
        self._gev_placeholder.setText("AVVIO GOD'S EYE VIEW…")
        self._gev_stack.setCurrentWidget(self._gev_placeholder)
        self._gev_view.load(QUrl(_gev_url()))

    def show_gev_tab(self) -> None:
        """Expand GEV in the center pane and expose its main navigation panels."""
        if not self._gev_tab_open:
            self._gev_previous_content_visible = not self._content_panel.isHidden()
            self._gev_previous_split_sizes = self._center_split.sizes()
        self._gev_tab_open = True
        self._content_panel.hide()
        self.load_gev()
        self._center_split.setSizes([self._center_split.height(), 0])
        self._expand_gev_navigation_panels()

    def hide_gev_tab(self) -> None:
        """Return to Jarvis's HUD while keeping the GEV page loaded."""
        if not self._gev_tab_open:
            self._hud_cam_stack.setCurrentWidget(self._active_hud_widget())
            return
        self._gev_tab_open = False
        self._hud_cam_stack.setCurrentWidget(self._active_hud_widget())
        if self._gev_previous_content_visible:
            self._content_panel.show()
        else:
            self._content_panel.hide()
        if len(self._gev_previous_split_sizes) == 2:
            self._center_split.setSizes(self._gev_previous_split_sizes)
        self._gev_previous_split_sizes = []

    def _build_browser_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("IntegratedBrowser")
        panel.setStyleSheet(f"""
            QWidget#IntegratedBrowser {{ background: {C.DARK}; }}
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 5px 8px;
            }}
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QPushButton:hover {{ border-color: {C.PRI}; }}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        self._browser_back_button = QPushButton("←")
        self._browser_back_button.setToolTip("Back")
        self._browser_back_button.clicked.connect(self._browser_go_back)
        toolbar.addWidget(self._browser_back_button)

        self._browser_forward_button = QPushButton("→")
        self._browser_forward_button.setToolTip("Forward")
        self._browser_forward_button.clicked.connect(self._browser_go_forward)
        toolbar.addWidget(self._browser_forward_button)

        reload_button = QPushButton("⟳")
        reload_button.setToolTip("Reload")
        toolbar.addWidget(reload_button)

        self._browser_address = QLineEdit()
        self._browser_address.setPlaceholderText("https://example.com")
        self._browser_address.returnPressed.connect(self._navigate_browser_address)
        toolbar.addWidget(self._browser_address, stretch=1)

        close_button = QPushButton("CLOSE")
        close_button.clicked.connect(self.close_browser)
        toolbar.addWidget(close_button)
        gemini_button = QPushButton("GEMINI CHAT")
        gemini_button.setToolTip("Open Gemini chat inside JARVIS")
        gemini_button.clicked.connect(self._show_gemini_chat)
        toolbar.addWidget(gemini_button)
        layout.addLayout(toolbar)

        self._browser_status = QLabel("Ready")
        self._browser_status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        layout.addWidget(self._browser_status)

        self._browser_view = QWebEngineView()
        self._browser_page = _SafeBrowserPage(
            self._browser_view, self._on_browser_navigation_blocked
        )
        self._browser_view.setPage(self._browser_page)
        reload_button.clicked.connect(self._browser_view.reload)
        self._browser_view.urlChanged.connect(self._sync_browser_address)
        self._browser_view.loadStarted.connect(
            lambda: self._browser_status.setText("Loading…")
        )
        self._browser_view.loadFinished.connect(self._on_browser_load_finished)
        self._browser_view.urlChanged.connect(self._update_browser_navigation)
        layout.addWidget(self._browser_view, stretch=1)
        self._update_browser_navigation()
        return panel

    def _show_gemini_chat(self) -> None:
        panel = self._gemini_chat_panel
        if panel is not None and self._main_content_stack.indexOf(panel) >= 0:
            try:
                current = self._main_content_stack.currentWidget()
                if current is not panel:
                    self._gemini_previous_widget = current
                self._main_content_stack.setCurrentWidget(panel)
                return
            except RuntimeError as exc:
                self._gemini_chat_panel = None
                self._log_sig.emit(
                    f"Gemini chat: pannello interno non utilizzabile: {exc}"
                )

        self._log_sig.emit(
            "Gemini chat: pannello interno non disponibile; uso la finestra separata."
        )
        try:
            if self._gemini_chat_window is None:
                self._gemini_chat_window = GeminiChatWindow(self)
            self._gemini_chat_window.show()
            self._gemini_chat_window.raise_()
            self._gemini_chat_window.activateWindow()
        except Exception as exc:
            self._log_sig.emit(f"Gemini chat: apertura non riuscita: {exc}")

    def _close_gemini_chat(self) -> None:
        panel = self._gemini_chat_panel
        previous = self._gemini_previous_widget
        if panel is not None and self._main_content_stack.currentWidget() is panel:
            if (
                previous is not None
                and self._main_content_stack.indexOf(previous) >= 0
            ):
                self._main_content_stack.setCurrentWidget(previous)
            else:
                self._main_content_stack.setCurrentWidget(self._hud_cam_stack)
        self._gemini_previous_widget = None

    def _ask_open_streaming_in_chrome(self, url: str) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Streaming protetto")
        dialog.setText(
            "La riproduzione protetta (DRM) non è supportata nel pannello "
            "interno. Apro in Chrome?"
        )
        dialog.setInformativeText(
            "La pagina di ricerca resterà disponibile nel pannello JARVIS."
        )
        open_button = dialog.addButton(
            "Apri in Chrome", QMessageBox.ButtonRole.AcceptRole
        )
        cancel_button = dialog.addButton(
            "Annulla", QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is open_button

    def _ask_sf3d_fallback(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Generazione SF3D lenta")
        dialog.setText(
            "SF3D sta impiegando troppo. Vuoi annullare e usare TripoSR?"
        )
        fallback_button = dialog.addButton(
            "Annulla e usa TripoSR", QMessageBox.ButtonRole.AcceptRole
        )
        continue_button = dialog.addButton(
            "Continua SF3D", QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(continue_button)
        dialog.setEscapeButton(continue_button)
        dialog.exec()
        return dialog.clickedButton() is fallback_button

    def _handle_generation_fallback(self, response: object) -> None:
        if not isinstance(response, dict):
            return
        try:
            confirmed = self._ask_sf3d_fallback()
            response["use_triposr"] = confirmed
            if confirmed:
                self._set_generation_status("TripoSR")
        except Exception as exc:
            response["error"] = str(exc)
            self._log_sig.emit(f"Generazione 3D: dialog fallback non riuscito: {exc}")
        finally:
            event = response.get("event")
            if isinstance(event, threading.Event):
                event.set()

    def _set_generation_status(self, backend: str) -> None:
        backend = str(backend or "").strip()
        if not backend:
            self._generation_tmr.stop()
            self._generation_backend = ""
            self._generation_status_label.clear()
            self._generation_status_label.hide()
            return
        if not self._generation_backend:
            self._generation_started_at = time.monotonic()
            self._generation_elapsed = 0
        self._generation_backend = backend
        self._generation_status_label.show()
        self._tick_generation_status()
        self._generation_tmr.start(1000)

    def _set_generation_elapsed(self, elapsed: int) -> None:
        self._generation_elapsed = max(self._generation_elapsed, int(elapsed))
        self._tick_generation_status()

    def _tick_generation_status(self) -> None:
        if not self._generation_backend:
            return
        elapsed = max(
            self._generation_elapsed,
            int(time.monotonic() - self._generation_started_at),
        )
        self._generation_status_label.setText(
            f"Generazione in corso... [{self._generation_backend}] - {elapsed}s"
        )

    def _confirm_streaming_play_on_ui_thread(self, url: str, response: object) -> None:
        if not isinstance(response, dict):
            return
        try:
            response["confirmed"] = self._ask_open_streaming_in_chrome(url)
        except Exception as exc:
            response["error"] = str(exc)
            self._log_sig.emit(f"Streaming: dialog di conferma non riuscito: {exc}")
        finally:
            event = response.get("event")
            if isinstance(event, threading.Event):
                event.set()

    def _navigate_browser_address(self) -> None:
        try:
            self._open_url_in_webview(self._browser_address.text())
        except (TypeError, ValueError) as exc:
            self._browser_status.setText(f"Invalid URL: {exc}")
            self._log_sig.emit(f"Browser: URL rifiutato: {exc}")

    def _open_url_in_webview(self, url: str) -> None:
        normalized_url = normalize_http_url(url)
        if self._main_content_stack.currentWidget() is not self._browser_panel:
            self._browser_return_widget = self._main_content_stack.currentWidget()
        self._main_content_stack.setCurrentWidget(self._browser_panel)
        self._browser_address.setText(normalized_url)
        self._browser_view.setUrl(QUrl(normalized_url))
        self._browser_status.setText("Loading…")
        self._update_browser_navigation()

    def _sync_browser_address(self, url: QUrl) -> None:
        if not self._browser_address.hasFocus():
            self._browser_address.setText(url.toString())

    def _on_browser_load_finished(self, succeeded: bool) -> None:
        if succeeded:
            host = self._browser_view.url().host()
            self._browser_status.setText(f"Loaded {host}")
            self._log_sig.emit(f"Browser: pagina caricata ({host})")
        else:
            self._browser_status.setText("Page load failed")
            self._log_sig.emit("Browser: caricamento pagina non riuscito")
        self._update_browser_navigation()

    def _on_browser_navigation_blocked(self) -> None:
        self._browser_status.setText("Blocked non-HTTP(S) navigation")
        self._log_sig.emit("Browser: navigazione non HTTP(S) bloccata")

    def _press_key_in_webview(self, key: str) -> None:
        if self._main_content_stack.currentWidget() is not self._browser_panel:
            self._log_sig.emit("Browser: impossibile premere un tasto, pagina non attiva")
            return
        self._browser_view.setFocus()
        try:
            script = build_keyboard_event_script(key)
            self._browser_page.runJavaScript(
                script,
                lambda dispatched: self._browser_key_dispatch_finished(
                    key, dispatched
                ),
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            self._log_sig.emit(f"Browser: dispatch tasto non riuscito: {exc}")
            self._browser_native_key_fallback(key)

    def _browser_key_dispatch_finished(self, key: str, dispatched: object) -> None:
        if dispatched is True:
            self._log_sig.emit(f"Browser: KeyboardEvent {key} dispatch completato")
            return
        self._log_sig.emit(
            f"Browser: dispatch JavaScript {key} non riuscito; uso fallback Qt"
        )
        self._browser_native_key_fallback(key)

    def _browser_native_key_fallback(self, key: str) -> None:
        qt_keys = {
            "ArrowUp": Qt.Key.Key_Up,
            "ArrowDown": Qt.Key.Key_Down,
            "ArrowLeft": Qt.Key.Key_Left,
            "ArrowRight": Qt.Key.Key_Right,
            " ": Qt.Key.Key_Space,
            "Enter": Qt.Key.Key_Return,
            "Escape": Qt.Key.Key_Escape,
        }
        qt_key = qt_keys.get(key)
        if qt_key is None and len(key) == 1 and key.isascii() and key.isalpha():
            qt_key = Qt.Key(ord(key.upper()))
        if qt_key is None:
            self._log_sig.emit(f"Browser: fallback Qt non disponibile per {key}")
            return
        self._browser_view.setFocus()
        QTest.keyClick(self._browser_view, qt_key)
        self._log_sig.emit(f"Browser: fallback Qt eseguito per {key}")

    def _click_link_in_webview(self, link_text: str) -> None:
        if self._main_content_stack.currentWidget() is not self._browser_panel:
            self._log_sig.emit("Browser: impossibile cliccare, pagina non attiva")
            return
        try:
            script = build_click_link_script(link_text)
            self._browser_page.runJavaScript(
                script,
                self._browser_link_click_finished,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            self._log_sig.emit(f"Browser: click link non riuscito: {exc}")

    def _browser_link_click_finished(self, result: object) -> None:
        if not isinstance(result, dict):
            self._log_sig.emit("Browser: la pagina non ha restituito l'esito del click")
            return
        if result.get("ok") is True:
            self._log_sig.emit("Browser: link cliccato")
        elif result.get("reason") == "ambiguous":
            self._log_sig.emit("Browser: testo link ambiguo; nessun link cliccato")
        else:
            self._log_sig.emit("Browser: link visibile non trovato")

    def _read_page_aloud(self, mode: str = "page") -> None:
        if self._main_content_stack.currentWidget() is not self._browser_panel:
            self._log_sig.emit("Screen reader: aprire prima una pagina nel browser Jarvis")
            return
        if self._page_read_pending or self._page_reader.is_running:
            self._log_sig.emit("Screen reader: una lettura è già in corso")
            return
        try:
            script = build_page_read_script(mode)
        except ValueError as exc:
            self._log_sig.emit(f"Screen reader: {exc}")
            return
        self._page_read_pending = True
        self._page_read_mode = mode
        self._page_reader_audio_sig.emit(True)
        try:
            self._browser_page.runJavaScript(script, self._on_browser_page_text)
        except RuntimeError as exc:
            self._page_read_pending = False
            self._page_reader_audio_sig.emit(False)
            self._log_sig.emit(f"Screen reader: estrazione DOM non riuscita: {exc}")

    def _on_browser_page_text(self, page_text: object) -> None:
        if not self._page_read_pending:
            return
        self._page_read_pending = False
        if not isinstance(page_text, str):
            self._page_reader_audio_sig.emit(False)
            self._browser_status.setText("Page text unavailable")
            self._log_sig.emit("Screen reader: estrazione del testo pagina non riuscita")
            return
        try:
            plan = self._page_reader.start(page_text)
        except (TypeError, ValueError, RuntimeError) as exc:
            self._page_reader_audio_sig.emit(False)
            self._browser_status.setText("Page reading unavailable")
            self._log_sig.emit(f"Screen reader: {exc}")
            return
        suffix = "; testo limitato" if plan.truncated else ""
        mode = getattr(self, "_page_read_mode", "page")
        self._browser_status.setText(f"Reading {mode} ({len(plan.chunks)} chunks)")
        self._log_sig.emit(
            f"Screen reader: lettura {mode} avviata in {len(plan.chunks)} chunk{suffix}"
        )

    def _page_reader_started(self) -> None:
        self._page_reader_audio_sig.emit(True)

    def _page_reader_finished(self) -> None:
        self._page_reader_audio_sig.emit(False)

    def _stop_page_reading(self) -> None:
        if self._page_read_pending:
            self._page_read_pending = False
            self._page_reader_audio_sig.emit(False)
            self._log_sig.emit("Screen reader: lettura DOM annullata")
            return
        try:
            stopped = self._page_reader.stop()
        except Exception as exc:
            self._log_sig.emit(f"Screen reader: arresto non riuscito: {exc}")
            return
        if stopped:
            self._browser_status.setText("Page reading stop requested")
            self._log_sig.emit("Screen reader: arresto richiesto")
        else:
            self._log_sig.emit("Screen reader: nessuna lettura in corso")

    def _update_browser_navigation(self, _url: QUrl | None = None) -> None:
        self._browser_back_button.setEnabled(self._browser_view.history().canGoBack())
        self._browser_forward_button.setEnabled(
            self._browser_view.history().canGoForward()
        )

    def _browser_go_back(self) -> None:
        self._browser_view.back()
        self._update_browser_navigation()

    def _browser_go_forward(self) -> None:
        self._browser_view.forward()
        self._update_browser_navigation()

    def close_browser(self) -> None:
        previous = self._browser_return_widget
        if previous is not None and self._main_content_stack.indexOf(previous) >= 0:
            self._main_content_stack.setCurrentWidget(previous)
        else:
            self._main_content_stack.setCurrentWidget(self._hud_cam_stack)
        self._browser_return_widget = None

    def closeEvent(self, event) -> None:
        if self._focus_mode:
            self.set_focus_mode(False)
        self._layout_timer.stop()
        self._hud_reload_timer.stop()
        self._persist_layout(force=True)
        self._page_read_pending = False
        self._page_reader_audio_sig.emit(False)
        self.hud.stop_animations()
        if self._title_glow is not None:
            self._title_glow.stop()
        if self._scanline is not None:
            self._scanline.stop()
        try:
            self._page_reader.stop()
        except Exception as exc:
            self._log_sig.emit(f"Screen reader: arresto alla chiusura non riuscito: {exc}")
        super().closeEvent(event)

    def _expand_gev_navigation_panels(self) -> None:
        if not self._gev_tab_open or not self._gev_ready_evt.is_set():
            return
        script = """(() => {
            const panels = [
                ['data-panel', `[data-collapse-target="data-panel"]`],
                ['pp-toggles', `[data-collapse-target="pp-toggles"]`],
                ['global-context-panel', `[data-collapse-target="global-context-panel"]`],
            ];
            const opened = panels.map(([id, toggleSelector]) => {
                const panel = document.getElementById(id);
                if (!panel) return {id, expanded: false};
                if (panel.classList.contains('collapsed')) {
                    panel.querySelector(toggleSelector)?.click();
                }
                return {id, expanded: !panel.classList.contains('collapsed')};
            });
            const controls = ['location-bar', 'control-panel'].map(id => {
                const panel = document.getElementById(id);
                const toggle = panel?.querySelector(`[data-dock-toggle-target="${id}"]`);
                return {
                    id,
                    available: !!panel && !!toggle && !toggle.disabled &&
                        getComputedStyle(panel).display !== 'none',
                };
            });
            return [...opened, ...controls];
        })()"""
        self._gev_page.runJavaScript(script, self._on_gev_panels_expanded)

    def _on_gev_panels_expanded(self, result) -> None:
        expected_open = {"data-panel", "pp-toggles", "global-context-panel"}
        expected_available = {"location-bar", "control-panel"}
        if isinstance(result, list):
            opened = {
                item.get("id")
                for item in result
                if isinstance(item, dict) and item.get("expanded") is True
            }
            available = {
                item.get("id")
                for item in result
                if isinstance(item, dict) and item.get("available") is True
            }
        else:
            opened = set()
            available = set()
        if opened == expected_open and available == expected_available:
            self._log_sig.emit(
                "GEV: Data Layers, Display e Context aperti; Location e Visual Presets disponibili"
            )
        else:
            missing = ", ".join(
                sorted((expected_open - opened) | (expected_available - available))
            )
            self._log_sig.emit(
                f"GEV: controlli richiesti non disponibili ({missing})"
            )

    def _on_gev_load_finished(self, succeeded: bool) -> None:
        if succeeded:
            self._gev_stack.setCurrentWidget(self._gev_view)
            self._log_sig.emit("GEV: pagina caricata; attendo il segnale ready")
            return
        self._gev_load_started = False
        self._gev_ready_evt.clear()
        self._gev_placeholder.setText("GEV NON DISPONIBILE — controllare il server")
        self._gev_stack.setCurrentWidget(self._gev_placeholder)
        self._log_sig.emit(f"GEV: caricamento fallito da {_gev_url()}")

    def _on_gev_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "gev:ready":
            self._gev_ready_evt.set()
            self._log_sig.emit("GEV: ready")
            self._expand_gev_navigation_panels()
        elif message_type == "gev:view-applied" and message.get("ok") is False:
            self._log_sig.emit(
                f"GEV: vista non applicata: {message.get('error', message.get('steps', []))}"
            )
        elif message_type == "gev:historical-map-applied":
            if message.get("ok") is False:
                self._log_sig.emit(
                    f"GEV: mappa storica non applicata: {message.get('error', 'errore sconosciuto')}"
                )
            else:
                result = message.get("result", {})
                if not isinstance(result, dict):
                    result = {}
                year = result.get("year")
                requested = result.get("requestedYear")
                if year is not None:
                    self._log_sig.emit(
                        f"GEV: snapshot storico {year} caricato"
                        + (f" (richiesto {requested})" if requested != year else "")
                    )
                elif result.get("playing") is not None:
                    self._log_sig.emit(
                        "GEV: riproduzione storica "
                        + ("avviata" if result["playing"] else "fermata")
                    )
                elif result.get("cleared"):
                    self._log_sig.emit("GEV: overlay storico rimosso")
        if callable(self._gev_message_dispatch):
            self._gev_message_dispatch(message)

    def _on_gev_send(self, serialized_message: str) -> None:
        try:
            message = json.loads(serialized_message)
        except json.JSONDecodeError as exc:
            self._log_sig.emit(f"GEV: messaggio in uscita non valido: {exc}")
            return
        if not isinstance(message, dict):
            self._log_sig.emit("GEV: messaggio in uscita non valido (atteso object)")
            return

        action = message.get("action")
        params = message.get("params", {})
        if action == "open":
            self.load_gev()
            return
        if action == "open_tab":
            self.show_gev_tab()
            return
        if action == "hide_tab":
            self.hide_gev_tab()
            return
        if not self._gev_ready_evt.is_set():
            self._log_sig.emit(
                f"GEV: UI non pronta, azione '{action}' non inviata"
            )
            return

        if action == "historical_map":
            historical_message = {
                "type": "gev:historical-map",
                "id": f"jarvis-{time.time_ns()}",
                **params,
            }
            encoded_message = json.dumps(
                historical_message,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            self._gev_page.runJavaScript(
                f"window.postMessage({encoded_message}, '*');"
            )
            return

        if action.startswith("camera_"):
            camera = self._gev_view_state.get("camera", {})
            if not isinstance(camera, dict):
                camera = {}
            camera = {
                "lat": camera.get("lat", 0),
                "lon": camera.get("lon", 0),
                "altitude_m": camera.get("altitude_m", 800_000),
                "heading_deg": camera.get("heading_deg", 0),
                "pitch_deg": camera.get("pitch_deg", -90),
            }

            if action == "camera_set":
                for key in ("lat", "lon", "altitude_m", "heading_deg", "pitch_deg"):
                    if key in params:
                        camera[key] = params[key]
            elif action == "camera_zoom":
                altitude = camera["altitude_m"]
                level = params.get("level")
                if level == "in":
                    camera["altitude_m"] = max(50, altitude / 2)
                elif level == "out":
                    camera["altitude_m"] = min(20_000_000, altitude * 2)
                elif "altitude_m" in params:
                    camera["altitude_m"] = params["altitude_m"]
                else:
                    self._log_sig.emit("GEV: camera_zoom richiede level o altitude_m")
                    return
            elif action == "camera_tilt":
                if "pitch_deg" not in params:
                    self._log_sig.emit("GEV: camera_tilt richiede pitch_deg")
                    return
                camera["pitch_deg"] = params["pitch_deg"]
            elif action == "camera_rotate":
                if "heading_deg" not in params:
                    self._log_sig.emit("GEV: camera_rotate richiede heading_deg")
                    return
                camera["heading_deg"] = params["heading_deg"]
            elif action == "camera_fly":
                if "lat" not in params or "lon" not in params:
                    self._log_sig.emit("GEV: camera_fly richiede lat e lon")
                    return
                camera["lat"] = params["lat"]
                camera["lon"] = params["lon"]
                if "altitude_m" in params:
                    camera["altitude_m"] = params["altitude_m"]
            elif action == "camera_reset":
                camera = {
                    "lat": 0,
                    "lon": 0,
                    "altitude_m": 800_000,
                    "heading_deg": 0,
                    "pitch_deg": -90,
                }

            camera_ranges = {
                "lat": (-90, 90),
                "lon": (-180, 180),
                "altitude_m": (50, 20_000_000),
                "heading_deg": (0, 360),
                "pitch_deg": (-90, 0),
            }
            for key, (minimum, maximum) in camera_ranges.items():
                value = camera[key]
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or not minimum <= value <= maximum
                ):
                    self._log_sig.emit(f"GEV: valore camera non valido per {key}")
                    return

            self._gev_view_state["camera"] = camera
            self._gev_view_state["follow"] = None
        elif action == "layer":
            layer_id = _GEV_LAYERS[params["layer"]]
            layers = set(self._gev_view_state["layers"])
            if params["enabled"]:
                layers.add(layer_id)
            else:
                layers.discard(layer_id)
            self._gev_view_state["layers"] = sorted(layers)
        elif action == "track":
            kind = _GEV_FOLLOW_KINDS[params["target_type"]]
            self._gev_view_state["follow"] = {
                "kind": kind,
                "id": params["target_id"],
            }
            self._gev_view_state["layers"] = sorted(
                set(self._gev_view_state["layers"])
                | {"flights" if kind == "aircraft" else "satellites"}
            )
        elif action == "reset":
            self._gev_view_state.update({
                "camera": {
                    "lat": 0,
                    "lon": 0,
                    "altitude_m": 800_000,
                    "heading_deg": 0,
                    "pitch_deg": -90,
                },
                "layers": [],
                "style": None,
                "map": None,
                "follow": None,
                "annotations": [],
            })
        elif action == "annotate":
            annotations = list(self._gev_view_state["annotations"])
            annotations.append({
                "type": "label",
                "latitude": params["lat"],
                "longitude": params["lon"],
                "label": params["text"],
            })
            self._gev_view_state["annotations"] = annotations[-24:]
        else:
            self._log_sig.emit(f"GEV: azione non supportata '{action}'")
            return

        view_message = {
            "type": "gev:view",
            "id": f"jarvis-{time.time_ns()}",
            "view": self._gev_view_state,
        }
        encoded_message = json.dumps(
            view_message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        self._gev_page.runJavaScript(
            f"window.postMessage({encoded_message}, '*');"
        )

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    @staticmethod
    def _get_desktop_dir() -> Path:
        """
        Resolve the user's REAL desktop directory instead of assuming
        ~/Desktop, which breaks when:
          • OneDrive "Known Folder Move" relocates the desktop
            (C:/Users/x/OneDrive/Desktop) — very common on Win 10/11;
          • the XDG desktop is localized on Linux (~/Masaüstü,
            ~/Schreibtisch, ~/Bureau, …).
        Falls back to ~/Desktop only as a last resort.
        """
        home = Path.home()
        _os = platform.system()

        if _os == "Windows":
            # ── 1) SHGetKnownFolderPath(FOLDERID_Desktop) — the canonical
            #       answer; follows OneDrive redirection. No dependencies. ──
            try:
                import ctypes
                from ctypes import wintypes

                class _GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD),
                                ("Data2", wintypes.WORD),
                                ("Data3", wintypes.WORD),
                                ("Data4", ctypes.c_ubyte * 8)]

                # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
                fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                                 0x9A, 0x87, 0xC6, 0x41))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(
                        ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    if p.is_dir():
                        return p
            except Exception:
                pass

            # ── 2) Registry: User Shell Folders (may contain %VARS%) ──────
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders") as key:
                    val, _t = winreg.QueryValueEx(key, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
            except Exception:
                pass

        elif _os == "Linux":
            # ── xdg-user-dir honours localized names (~/Masaüstü, …) ──────
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                     capture_output=True, text=True, timeout=5)
                p = Path(out.stdout.strip())
                if out.stdout.strip() and p != home and p.is_dir():
                    return p
            except Exception:
                pass
            try:
                cfg = home / ".config" / "user-dirs.dirs"
                for line in cfg.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR"):
                        val = line.split("=", 1)[1].strip().strip('"')
                        p = Path(val.replace("$HOME", str(home)))
                        if p != home and p.is_dir():
                            return p
            except Exception:
                pass

        # macOS: ~/Desktop is always the real path (localization is
        # display-only). Everything else lands here as a last resort.
        return home / "Desktop"

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = self._get_desktop_dir()

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "J.A.R.V.I.S.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "J.A.R.V.I.S.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )
        # Clipboard panel — bottom-center
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        # Quick drawer — reposition if open
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")
        self.hud.set_system_metrics(cpu, gpu)

        self._update_hud_runtime()

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")

    def _update_hud_runtime(self) -> None:
        if not callable(self.get_hud_runtime):
            snapshot = {
                "skills": {"active": 0, "total": 0},
                "task": {"status": "idle", "completed": 0, "total": 0, "progress": 0},
            }
        else:
            snapshot = self.get_hud_runtime()

        skills = snapshot["skills"]
        skill_total = int(skills["total"])
        skill_active = int(skills["active"])
        skill_pct = 100 * skill_active / skill_total if skill_total else 0
        self._gauge_skills.set_value(
            skill_pct,
            f"{skill_active}/{skill_total}" if skill_total else "N/A",
        )

        task = snapshot["task"]
        task_total = int(task["total"])
        task_done = int(task["completed"])
        task_pct = int(task["progress"])
        task_status = str(task["status"]).upper().replace("_", " ")
        task_reading = f"{task_done}/{task_total}" if task_total else task_status[:8]
        self._gauge_task.set_value(task_pct, task_reading)
        self._gauge_load.set_value(0, "N/A")
        self._task_runner_progress.setValue(task_pct)
        self._task_runner_label.setText(
            f"TASK RUNNER: {task_pct}% - {task_status}"
        )

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MARK LII", C.PRI_DIM))
        lay.addSpacing(8)
        self._drawer_btn = QPushButton("⚙")
        self._drawer_btn.setFixedSize(26, 26)
        self._drawer_btn.setFont(QFont("Courier New", 11))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setToolTip("Settings & Controls")
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
            QPushButton:checked {{ color: {C.PRI}; border-color: {C.PRI}; background: {C.PRI_GHO}; }}
        """)
        self._drawer_btn.setCheckable(True)
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(_disp)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(self._title_lbl)
        _sub_text = ("Just A Rather Very Intelligent System"
                     if _disp in ("JARVIS", "J.A.R.V.I.S")
                     else "Personal AI Assistant")
        self._sub_lbl = QLabel("")
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setFont(QFont("Courier New", 7))
        self._sub_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(self._sub_lbl)
        
        self._sub_text_full = _sub_text
        self._sub_type_idx = 0
        self._sub_timer = QTimer(self)
        def _type_char():
            if self._sub_type_idx <= len(self._sub_text_full):
                self._sub_lbl.setText(self._sub_text_full[:self._sub_type_idx])
                self._sub_type_idx += 1
            else:
                self._sub_timer.stop()
        self._sub_timer.timeout.connect(_type_char)
        self._sub_timer.start(50)
        
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _apply_theme(self) -> None:
        theme_path = Path(__file__).resolve().parent / "core" / "jarvis_theme.qss"
        theme = theme_path.read_text(encoding="utf-8")
        for name in ("BG", "DARK", "PANEL2", "PRI_DIM", "PRI", "TEXT", "WHITE"):
            theme = theme.replace(f"@{name}@", getattr(C, name))
        self.setStyleSheet(theme)

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SYS MONITOR")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        function_hint = QLabel("FUNCTION: Plugin Status & System Metrics")
        function_hint.setWordWrap(True)
        function_hint.setFont(QFont("Courier New", 6))
        function_hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(function_hint)

        for names in (("VOICE", "LOGIC", "DATA"), ("SEARCH", "VISION")):
            icon_row = QHBoxLayout()
            icon_row.setSpacing(3)
            for name in names:
                icon = QLabel(name)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
                icon.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: {C.PANEL2};"
                    f"border: 1px solid {C.BORDER}; padding: 3px 2px;"
                )
                icon_row.addWidget(icon, stretch=1)
            lay.addLayout(icon_row)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",  C.GREEN),
            ("SEC\nCLEARED",     C.PRI),
            ("PROTOCOL\nXLIX",   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            if col != C.TEXT_DIM:
                start_pulsing_glow(lbl, col, reduced_motion=self._reduced_motion)
            lay.addWidget(lbl)

        return w
    def _build_log_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        callout = QLabel("FUNCTION: Task Execution & Cognitive Load")
        callout.setWordWrap(True)
        callout.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        callout.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(callout)

        gauge_row = QHBoxLayout()
        gauge_row.setSpacing(2)
        self._gauge_skills = HudGauge("SKILLS", C.PRI)
        self._gauge_task = HudGauge("TASK", C.ACC)
        self._gauge_load = HudGauge("LOAD", C.ACC2)
        for gauge in (self._gauge_skills, self._gauge_task, self._gauge_load):
            gauge_row.addWidget(gauge)
        gauge_row.addStretch(1)
        lay.addLayout(gauge_row)

        load_note = QLabel("Cognitive-load telemetry: N/A")
        load_note.setFont(QFont("Courier New", 6))
        load_note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(load_note)

        self._log = LogWidget()
        self._log.setPlaceholderText("[JARVIS]: Ready, waiting for command")
        lay.addWidget(self._log, stretch=1)
        return w

    def _build_input_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._task_runner_label = QLabel("TASK RUNNER: 0% - IDLE")
        self._task_runner_label.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._task_runner_label.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent;"
        )
        lay.addWidget(self._task_runner_label)
        self._task_runner_progress = QProgressBar()
        self._task_runner_progress.setRange(0, 100)
        self._task_runner_progress.setValue(0)
        self._task_runner_progress.setTextVisible(True)
        self._task_runner_progress.setFormat("%p%")
        self._task_runner_progress.setFixedHeight(12)
        self._task_runner_progress.setStyleSheet(f"""
            QProgressBar {{
                background: {C.BAR_BG}; border: 1px solid {C.BORDER};
                border-radius: 2px; color: {C.TEXT}; text-align: center;
            }}
            QProgressBar::chunk {{ background: {C.PRI_DIM}; }}
        """)
        lay.addWidget(self._task_runner_progress)
        self._generation_status_label = QLabel()
        self._generation_status_label.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._generation_status_label.setStyleSheet(
            f"color: {C.ACC}; background: transparent;"
        )
        self._generation_status_label.hide()
        lay.addWidget(self._generation_status_label)

        self._interrupt_btn = QPushButton("✋  INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(34)
        self._interrupt_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: #140008; color: {C.MUTED_C};
                border: 1px solid {C.MUTED_C}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: #200010; border: 1px solid #ff6688;
            }}
            QPushButton:pressed {{
                background: #300018;
            }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        lay.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        return w

    def _build_quick_drawer(self) -> QWidget:
        """Floating overlay panel shown when the ⚙ header button is toggled."""
        _BTN_STYLE_PRI = f"""
            QPushButton {{
                background: #00091a; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """
        _BTN_STYLE_DIM = f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """

        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(f"""
            QWidget#QuickDrawer {{
                background: {C.DARK};
                border: 1px solid {C.BORDER_B};
                border-top: none;
                border-radius: 0 0 6px 6px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("◈ CONTROLS")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        remote_btn = QPushButton("◉  REMOTE CONTROL")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(_BTN_STYLE_PRI)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(_BTN_STYLE_DIM)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Courier New", 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(_BTN_STYLE_DIM)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        self._autostart_btn = QPushButton("◉  AUTO-START: OFF")
        self._autostart_btn.setFixedHeight(26)
        self._autostart_btn.setFont(QFont("Courier New", 7))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        cust_btn = QPushButton("⚙  CUSTOMISE ASSISTANT")
        cust_btn.setFixedHeight(26)
        cust_btn.setFont(QFont("Courier New", 7))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(_BTN_STYLE_DIM)
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        self._brief_btn = QPushButton()
        self._brief_btn.setFixedHeight(26)
        self._brief_btn.setFont(QFont("Courier New", 7))
        self._brief_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brief_btn.clicked.connect(self._toggle_brief)
        lay.addWidget(self._brief_btn)

        audio_btn = QPushButton("🎧  AUDIO DEVICES")
        audio_btn.setFixedHeight(26)
        audio_btn.setFont(QFont("Courier New", 7))
        audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        audio_btn.setStyleSheet(_BTN_STYLE_DIM)
        audio_btn.clicked.connect(self._open_audio_devices)
        lay.addWidget(audio_btn)

        mem_btn = QPushButton("🧠  MEMORY")
        mem_btn.setFixedHeight(26)
        mem_btn.setFont(QFont("Courier New", 7))
        mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mem_btn.setStyleSheet(_BTN_STYLE_DIM)
        mem_btn.clicked.connect(self._open_memory_panel)
        lay.addWidget(mem_btn)

        plugin_btn = QPushButton("🧩  PLUGINS")
        plugin_btn.setFixedHeight(26)
        plugin_btn.setFont(QFont("Courier New", 7))
        plugin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plugin_btn.setStyleSheet(_BTN_STYLE_DIM)
        plugin_btn.clicked.connect(self._open_plugin_manager)
        lay.addWidget(plugin_btn)

        self._dictation_btn = QPushButton("🎙  OFFLINE DICTATION")
        self._dictation_btn.setCheckable(True)
        self._dictation_btn.setFixedHeight(30)
        self._dictation_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._dictation_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dictation_btn.setToolTip(
            "Records up to 60 seconds in RAM. Requires faster-whisper and a cached model."
        )
        self._dictation_btn.setStyleSheet(_BTN_STYLE_DIM)
        self._dictation_btn.toggled.connect(self._toggle_dictation)
        lay.addWidget(self._dictation_btn)

        w.adjustSize()
        return w

    def _toggle_dictation(self, enabled: bool) -> None:
        callback = getattr(self, "on_dictation_toggle", None)
        if not callable(callback):
            accepted = False
            self._log_sig.emit("ERR: Offline dictation is not connected")
        else:
            accepted = callback(enabled) is not False
        if not accepted:
            self._dictation_btn.blockSignals(True)
            self._dictation_btn.setChecked(not enabled)
            self._dictation_btn.blockSignals(False)
            return
        self._dictation_btn.setText(
            "■  STOP DICTATION" if enabled else "🎙  OFFLINE DICTATION"
        )

    def _set_dictation_busy(self, busy: bool) -> None:
        self._dictation_btn.setEnabled(not busy)

    def _on_dictation_result(self, success: bool, value: str) -> None:
        self._set_dictation_busy(False)
        self._dictation_btn.blockSignals(True)
        self._dictation_btn.setChecked(False)
        self._dictation_btn.setText("🎙  OFFLINE DICTATION")
        self._dictation_btn.blockSignals(False)
        if not success:
            self._log_sig.emit(f"ERR: Offline dictation — {value}")
            return
        existing = self._input.text().strip()
        self._input.setText(f"{existing} {value}".strip())
        self._input.setFocus()
        self._log_sig.emit(
            "SYS: Dictation ready for review; it has not been sent."
        )

    def _toggle_drawer(self, checked: bool):
        if checked:
            self._position_quick_drawer()
            self._quick_drawer.show()
            self._quick_drawer.raise_()
        else:
            self._quick_drawer.hide()

    def _position_quick_drawer(self):
        if not hasattr(self, '_quick_drawer'):
            return
        _W = 220
        self._quick_drawer.setFixedWidth(_W)
        self._quick_drawer.adjustSize()
        self._quick_drawer.setGeometry(12, 54, _W, self._quick_drawer.sizeHint().height())

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("> Waiting for input...")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Collapsible panel below the HUD — shows search results, news, briefings.
        Hidden by default; appears when show_content() is called.
        """
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(5)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)

        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Courier New", 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 3px;
                padding: 6px 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)
        lay.addWidget(self._content_display)

        return w

    def _hide_content_if(self, prefix: str) -> None:
        """Close the content panel, but only if it still shows a result whose title starts with prefix."""
        title = self._content_title_lbl.text().upper()
        if self._content_panel.isVisible() and title.startswith(prefix.upper()):
            self._content_panel.hide()

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        import time as _time
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

    # ── Widget system ────────────────────────────────────────────────────────
    def _build_widget_dock(self) -> QWidget:
        """Creates the floating overlay widget area (bottom-left corner)."""
        dock = QFrame(self)
        dock.setObjectName("widget_dock")
        dock.setStyleSheet("""
            QFrame#widget_dock {
                background: rgba(1,13,20,220);
                border: 1px solid #0d2233;
                border-radius: 8px;
            }
        """)
        dock.setFixedWidth(260)
        dock.setMinimumHeight(40)
        dock.setMaximumHeight(400)
        dock.hide()  # shown only when widgets are added
        self._widget_dock       = dock
        self._widget_dock_lay   = QVBoxLayout(dock)
        self._widget_dock_lay.setContentsMargins(8, 6, 8, 6)
        self._widget_dock_lay.setSpacing(6)
        return dock

    def _build_toast_area(self) -> QWidget:
        """Vertical stack for temporary toast notifications."""
        area = QWidget(self)
        area.setObjectName("toast_area")
        area.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._toast_area     = area
        self._toast_area_lay = QVBoxLayout(area)
        self._toast_area_lay.setContentsMargins(0, 0, 0, 0)
        self._toast_area_lay.setSpacing(4)
        self._toast_area_lay.setAlignment(Qt.AlignmentFlag.AlignBottom)
        area.hide()
        return area

    def _reposition_widget_overlays(self) -> None:
        """Called on resize to keep overlay areas anchored."""
        if hasattr(self, '_widget_dock'):
            margin = 12
            self._widget_dock.move(margin, self.height() - self._widget_dock.height() - margin - 30)
        if hasattr(self, '_toast_area'):
            w = 360
            self._toast_area.setFixedWidth(w)
            self._toast_area.move((self.width() - w) // 2, self.height() - 200)

    def _place_widget(self, widget: QWidget, area: str) -> None:
        if area == "overlay":
            if not hasattr(self, '_widget_dock'):
                self._build_widget_dock()
            self._widget_dock_lay.addWidget(widget)
            self._widget_dock.adjustSize()
            self._widget_dock.show()
            self._reposition_widget_overlays()
        elif area == "toast":
            if not hasattr(self, '_toast_area'):
                self._build_toast_area()
            self._toast_area_lay.addWidget(widget)
            self._toast_area.adjustSize()
            self._toast_area.show()
            self._reposition_widget_overlays()
        else:  # default: "content" panel
            self._content_title_lbl.setText(self._spec_title(widget))
            # Clear previous widget-based content
            while self._content_panel.layout() and self._content_panel.layout().count() > 2:
                item = self._content_panel.layout().takeAt(2)
                if item and item.widget():
                    item.widget().deleteLater()
            # Remove text display, add widget
            self._content_display.hide()
            self._content_panel.layout().addWidget(widget)
            first_show = not self._content_panel.isVisible()
            self._content_panel.show()
            if first_show:
                total = self._center_split.height()
                self._center_split.setSizes([max(total - 280, 120), 280])

    @staticmethod
    def _spec_title(widget: QWidget) -> str:
        lbl = widget.findChild(QLabel)
        return lbl.text() if lbl else "WIDGET"

    def _on_widget(self, spec: dict) -> None:
        """Slot — runs on Qt main thread. Dispatches widget specs to renderers."""
        import time as _t
        from core.widget_registry import registry
        from core.widget_renderers import ToastRenderer  # noqa: F401 — ensure registered

        wid_id   = spec.get("id", "")
        wid_type = spec.get("type", "")
        payload  = spec.get("payload", {})

        # ── Remove ─────────────────────────────────────────────────────────
        if wid_type == "__remove__":
            w = self._active_widgets.pop(wid_id, None)
            if w:
                w.setParent(None)
                w.deleteLater()
            t = self._toast_timers.pop(wid_id, None)
            if t:
                t.stop()
            if hasattr(self, '_widget_dock') and not self._active_widgets:
                self._widget_dock.hide()
            return

        # ── Update in-place ────────────────────────────────────────────────
        if wid_id in self._active_widgets:
            self._active_widgets[wid_id].update_payload(payload)
            return

        # ── Create new ────────────────────────────────────────────────────
        renderer_cls = registry.get_renderer(wid_type)
        if renderer_cls is None:
            print(f"[WidgetSystem] No renderer for type '{wid_type}'")
            return

        area   = spec.get("area", "content")
        widget = renderer_cls(spec)
        self._place_widget(widget, area)
        self._active_widgets[wid_id] = widget

        # ── TTL auto-remove ────────────────────────────────────────────────
        ttl = spec.get("ttl")
        if ttl and isinstance(ttl, (int, float)) and ttl > 0:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda _id=wid_id: self._on_widget({"id": _id, "type": "__remove__", "payload": {}}))
            timer.start(int(ttl * 1000))
            self._toast_timers[wid_id] = timer

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("By FatihMakes", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell {self._assistant_name} what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    # ── Auto-start ──────────────────────────────────────────────────────────────

    def _check_autostart(self) -> bool:
        """Returns True if auto-start is currently registered on this OS."""
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "JARVIS_AI")
                    return True
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
            elif _OS == "Darwin":
                return (Path.home() / "Library" / "LaunchAgents"
                        / "com.jarvis.assistant.plist").exists()
            else:
                return (Path.home() / ".config" / "autostart" / "jarvis.desktop").exists()
        except Exception:
            return False

    def _toggle_autostart(self):
        currently_on = self._check_autostart()
        try:
            script = str(Path(__file__).resolve().parent / "main.py")
            if _OS == "Windows":
                import winreg
                reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                if currently_on:
                    winreg.DeleteValue(reg, "JARVIS_AI")
                else:
                    pythonw = Path(sys.executable).parent / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else sys.executable)
                    winreg.SetValueEx(reg, "JARVIS_AI", 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
                winreg.CloseKey(reg)
            elif _OS == "Darwin":
                plist_dir = Path.home() / "Library" / "LaunchAgents"
                plist_dir.mkdir(parents=True, exist_ok=True)
                plist = plist_dir / "com.jarvis.assistant.plist"
                if currently_on:
                    plist.unlink(missing_ok=True)
                else:
                    plist.write_text(
                        '<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                        '<plist version="1.0"><dict>\n'
                        '  <key>Label</key><string>com.jarvis.assistant</string>\n'
                        '  <key>ProgramArguments</key><array>\n'
                        f'    <string>{sys.executable}</string>\n'
                        f'    <string>{script}</string>\n'
                        '  </array>\n'
                        '  <key>RunAtLoad</key><true/>\n'
                        '</dict></plist>\n'
                    )
            else:
                desk_dir = Path.home() / ".config" / "autostart"
                desk_dir.mkdir(parents=True, exist_ok=True)
                desk = desk_dir / "jarvis.desktop"
                if currently_on:
                    desk.unlink(missing_ok=True)
                else:
                    desk.write_text(
                        "[Desktop Entry]\n"
                        f"Name={self._assistant_name}\n"
                        f"Exec={sys.executable} {script}\n"
                        "Type=Application\nTerminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n"
                    )
            enabled = not currently_on
            self._update_autostart_btn(enabled)
            self._log.append_log(
                f"SYS: Auto-start {'enabled' if enabled else 'disabled'}.")
        except Exception as e:
            self._log.append_log(f"ERR: Auto-start failed — {e}")

    def _update_autostart_btn(self, enabled: bool):
        if not hasattr(self, '_autostart_btn'):
            return
        if enabled:
            self._autostart_btn.setText("◉  AUTO-START: ON")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._autostart_btn.setText("◉  AUTO-START: OFF")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        new_val = not get_brief_enabled()
        save_brief_enabled(new_val)
        self._update_brief_btn(new_val)

    def _update_brief_btn(self, enabled: bool):
        if not hasattr(self, '_brief_btn'):
            return
        if enabled:
            self._brief_btn.setText("☀  MORNING BRIEF: ON")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._brief_btn.setText("☀  MORNING BRIEF: OFF")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    # ── Customization ────────────────────────────────────────────────────────────

    def _open_customize(self):
        cfg = _read_full_config()
        from memory.config_manager import (
            get_full_duplex_enabled,
            get_page_reader_engine,
            get_page_reader_speed,
            get_wake_word_enabled,
        )

        if self._customize_overlay:
            self._customize_overlay.hide()
        cw = self.centralWidget()
        ov = CustomizeOverlay(
            cfg.get("assistant_name", "JARVIS") or "JARVIS",
            cfg.get("user_name", ""),
            cfg.get("ui_color", "") or DEFAULT_UI_COLOR,
            cfg.get("voice_name", ""),
            get_page_reader_engine(),
            get_wake_word_enabled(),
            get_full_duplex_enabled(),
            get_page_reader_speed(),
            parent=cw,
        )
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        oh = min(oh, cw.height() - 16)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.on_preview = self._preview_ui_color
        ov.saved.connect(self._apply_name_update)
        ov.install_wake_word_requested.connect(self._install_wake_word)
        ov.show()
        self._customize_overlay = ov

    def _install_wake_word(self):
        if self._wake_word_setup_active:
            return
        self._wake_word_setup_active = True
        button = getattr(self._customize_overlay, "_wake_word_install_btn", None)
        if button is not None:
            button.setEnabled(False)

        def install():
            from core.wake_word import install_and_download

            success, message = install_and_download(logger=self._log_sig.emit)
            self._wake_word_setup_result_sig.emit(success, message)

        threading.Thread(
            target=install,
            name="wake-word-setup",
            daemon=True,
        ).start()

    def _on_wake_word_setup_result(self, success: bool, message: str):
        self._wake_word_setup_active = False
        button = getattr(self._customize_overlay, "_wake_word_install_btn", None)
        if button is not None:
            button.setEnabled(True)
        prefix = "SYS" if success else "ERR"
        self._log_sig.emit(f"{prefix}: Wake word setup — {message}")

    def _preview_ui_color(self, hex_color: str):
        """Canlı önizleme — tüm arayüzü yeni renge boyar (config'e YAZMAZ)."""
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())

    def _apply_name_update(self, name: str, user_name: str, ui_color: str = "",
                           voice: str = "", page_reader_engine: str = "",
                           wake_word_enabled: bool | None = None,
                           full_duplex_enabled: bool | None = None,
                           page_reader_speed: float | None = None):
        """Update all name/theme-dependent UI elements and persist to config."""
        self._assistant_name = name.strip() or "JARVIS"
        display = self._assistant_name.upper()
        self.setWindowTitle(f"{display} — MARK LII")
        self._title_lbl.setText(display)
        if display in ("JARVIS", "J.A.R.V.I.S"):
            self._sub_lbl.setText("Just A Rather Very Intelligent System")
        else:
            self._sub_lbl.setText("Personal AI Assistant")
        self._log._ai_name_lc = self._assistant_name.lower()
        self.hud._assistant_name = display

        color_changed = False
        if ui_color:
            old = current_palette()
            if apply_ui_accent(ui_color):
                # Tüm arayüzü (paneller, butonlar, kenarlıklar, HUD) canlı boya
                retheme_all_widgets(old, current_palette())
                color_changed = old["PRI"] != C.PRI

        # Voice change → persist and, if it actually changed, rebuild the Live
        # session so the new voice takes effect (it's fixed at connect time).
        voice_changed = False
        if voice:
            from memory.config_manager import get_voice, save_voice
            if voice != get_voice():
                save_voice(voice)
                voice_changed = True

        try:
            data = _read_full_config()
            data["assistant_name"] = self._assistant_name
            data["user_name"] = user_name.strip()
            if ui_color:
                data["ui_color"] = ui_color.strip().lower()
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            self._log.append_log(f"SYS: Identity updated — {display}")
            if color_changed:
                self._log.append_log(f"SYS: UI colour applied — {ui_color}")
            if voice_changed:
                self._log.append_log(f"SYS: Voice set — {voice}")
        except Exception as e:
            self._log.append_log(f"ERR: Config save failed — {e}")

        if page_reader_engine in {"system", "kokoro"}:
            from memory.config_manager import (
                get_page_reader_engine,
                save_page_reader_engine,
            )

            try:
                reader_engine_changed = (
                    page_reader_engine != get_page_reader_engine()
                )
                save_page_reader_engine(page_reader_engine)
                if reader_engine_changed:
                    self._log.append_log(
                        f"SYS: Page reader voice set — {page_reader_engine}"
                    )
            except (OSError, ValueError) as exc:
                self._log.append_log(f"ERR: Page reader setting not saved — {exc}")

        if page_reader_speed is not None:
            from memory.config_manager import (
                get_page_reader_speed,
                save_page_reader_speed,
            )

            try:
                speed = float(page_reader_speed)
                speed_changed = speed != get_page_reader_speed()
                save_page_reader_speed(speed)
                if speed_changed:
                    self._log.append_log(
                        f"SYS: Page reader speed set — {speed:g}x"
                    )
            except (OSError, TypeError, ValueError) as exc:
                self._log.append_log(f"ERR: Page reader speed not saved — {exc}")

        wake_word_changed = False
        full_duplex_changed = False
        if isinstance(wake_word_enabled, bool):
            from memory.config_manager import (
                get_wake_word_enabled,
                save_wake_word_enabled,
            )

            try:
                wake_word_changed = wake_word_enabled != get_wake_word_enabled()
                save_wake_word_enabled(wake_word_enabled)
                if wake_word_changed:
                    self._log.append_log(
                        "SYS: Wake word "
                        + ("enabled" if wake_word_enabled else "disabled")
                    )
            except (OSError, ValueError) as exc:
                self._log.append_log(f"ERR: Wake word setting not saved — {exc}")
                wake_word_changed = False

        if isinstance(full_duplex_enabled, bool):
            from memory.config_manager import (
                get_full_duplex_enabled,
                save_full_duplex_enabled,
            )

            try:
                full_duplex_changed = (
                    full_duplex_enabled != get_full_duplex_enabled()
                )
                save_full_duplex_enabled(full_duplex_enabled)
                if full_duplex_changed:
                    self._log.append_log(
                        "SYS: Experimental voice interruption "
                        + ("enabled" if full_duplex_enabled else "disabled")
                    )
            except (OSError, ValueError) as exc:
                self._log.append_log(
                    f"ERR: Full-duplex setting not saved — {exc}"
                )
                full_duplex_changed = False

        if voice_changed and self.on_voice_change:
            self.on_voice_change()
        if (wake_word_changed or full_duplex_changed) and self.on_audio_input_mode_change:
            self.on_audio_input_mode_change()

    def _centre_overlay(self, ov) -> None:
        """Place a floating overlay in the middle of the HUD and show it."""
        cw = self.centralWidget()
        ov.adjustSize()
        ov.setGeometry(
            max(0, (cw.width()  - ov.width())  // 2),
            max(0, (cw.height() - ov.height()) // 2),
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()

    # ── Audio devices ────────────────────────────────────────────────────────

    def _open_audio_devices(self):
        ov = AudioDeviceOverlay(parent=self.centralWidget())
        ov.picked.connect(self._on_audio_devices_applied)
        self._centre_overlay(ov)
        self._audio_overlay = ov            # keep a reference so it isn't GC'd

    def _on_audio_devices_applied(self):
        self._log.append_log("SYS: Audio devices updated.")
        if self.on_audio_device_change:
            self.on_audio_device_change()

    # ── Memory panel ─────────────────────────────────────────────────────────

    def _open_memory_panel(self):
        ov = MemoryOverlay(parent=self.centralWidget())
        self._centre_overlay(ov)
        self._memory_overlay = ov

    # ── Irreversible-action confirmation ─────────────────────────────────────

    def _show_confirm_banner(self, title: str, detail: str):
        self._hide_confirm_banner()
        ov = ConfirmBanner(title, detail, parent=self.centralWidget())
        ov.answered.connect(self._on_confirm_answered)
        self._centre_overlay(ov)
        self._confirm_overlay = ov

    def _hide_confirm_banner(self):
        ov = getattr(self, "_confirm_overlay", None)
        if ov is not None:
            ov.hide()
            ov.deleteLater()
            self._confirm_overlay = None

    def _on_confirm_answered(self, accepted: bool):
        # Tear the banner down first: core.confirm.resolve() may be about to
        # shut the machine down, and a live widget mid-callback is not where you
        # want to be when that happens.
        self._hide_confirm_banner()
        try:
            from core.confirm import resolve
            resolve(bool(accepted))
        except Exception as e:
            self._log.append_log(f"ERR: Confirmation failed — {e}")

    def _open_plugin_manager(self):
        plugins = self.get_plugins() if self.get_plugins else []
        cw = self.centralWidget()
        ov = PluginManagerOverlay(plugins, parent=cw)
        ov.adjustSize()
        ov.setGeometry(
            (cw.width()  - ov.width())  // 2,
            (cw.height() - ov.height()) // 2,
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()
        self._plugin_manager_overlay = ov   # keep a reference so it isn't GC'd

    # ── Clipboard intelligence ───────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text().strip()
            if len(text) >= 10:
                self._clipboard_sig.emit(text)
        except Exception:
            pass

    def _show_clipboard_panel(self, text: str):
        self._clipboard_panel.show_clipboard(text)
        self._position_clipboard_panel()

    def _position_clipboard_panel(self):
        cw = self.centralWidget()
        pw = ClipboardPanel._W
        ph = self._clipboard_panel.sizeHint().height() or ClipboardPanel._H
        x = (cw.width() - pw) // 2
        y = cw.height() - ph - 6
        self._clipboard_panel.setGeometry(x, y, pw, ph)
        self._clipboard_panel.raise_()

    def _on_clipboard_action(self, cmd: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,), daemon=True).start()

    # ────────────────────────────────────────────────────────────────────────────

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if wants_chat(txt):
            self._show_gemini_chat()
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _on_log_message(self, text: str) -> None:
        self._log.append_log(text)
        if text.lstrip().startswith("ERR:"):
            self._apply_state("ERROR")

    def _apply_state(self, state: str):
        self.hud.state    = state
        state_map = {
            "SLEEPING": "idle",
            "INITIALISING": "idle",
            "MUTED": "idle",
            "PROCESSING": "thinking",
        }
        visual_state = state_map.get(state.upper(), state.lower())
        if visual_state not in _JARVIS_VISUAL_STATES:
            visual_state = "idle"
        self.hud.set_jarvis_state(visual_state)
        self.hud.speaking = (state.upper() == "SPEAKING")

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            from core.api_keys import gemini_api_key
            return bool(gemini_api_key(API_FILE.parent)) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _warn_plaintext_key(self) -> None:
        if os.environ.get("JARVIS_ALLOW_PLAINTEXT_KEY") == "1":
            log_message = (
                "SYS: WARNING - secure storage unavailable: the API key was written "
                "in PLAIN TEXT to config/api_keys.json. Do not share that file."
            )
            dialog_message = (
                "L'archiviazione sicura non è disponibile: la chiave API è stata salvata "
                "IN CHIARO in config/api_keys.json.\n\nNon condividere quel file."
            )
        else:
            log_message = (
                "SYS: secure storage unavailable: the new API key was not saved. "
                "config/api_keys.json may still contain a previously saved key. "
                "Configure secure storage or explicitly allow plaintext fallback."
            )
            dialog_message = (
                "L'archiviazione sicura non è disponibile e la nuova chiave non è stata salvata. "
                "config/api_keys.json potrebbe contenere una chiave salvata in precedenza. "
                "Configura l'archiviazione sicura oppure abilita esplicitamente il fallback "
                "in chiaro impostando JARVIS_ALLOW_PLAINTEXT_KEY=1."
            )
        self._log.append_log(
            log_message
        )
        QMessageBox.warning(
            self, "Chiave API non protetta",
            dialog_message,
        )

    def _on_setup_done(self, key: str, os_name: str):
        from core.api_keys import save_gemini_key
        if not save_gemini_key(CONFIG_DIR, key, os_name):
            self._warn_plaintext_key()
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "JARVIS") or "JARVIS"
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. {self._assistant_name} online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win._gev_message_dispatch = self._dispatch_gev_message
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def focus_mode(self) -> bool:
        return self._win._focus_mode

    def set_focus_mode(self, active: bool) -> None:
        """Thread-safe: callable from tool threads."""
        self._win._focus_mode_sig.emit(bool(active))

    def apply_workspace(self, name: str) -> None:
        self._win._workspace_sig.emit(str(name))

    def set_panel_visible(self, panel: str, visible: bool) -> None:
        self._win._panel_sig.emit(str(panel), bool(visible))

    def float_panel(self, panel: str, floating: bool | None = None) -> None:
        self._win._float_sig.emit(str(panel), -1 if floating is None else int(bool(floating)))

    def restore_layout(self) -> None:
        self._win._restore_layout_sig.emit()

    def viewer3d_show(self, visible: bool) -> None:
        self._win._viewer_show_sig.emit(bool(visible))

    def viewer3d_call(self, function: str, args: list) -> None:
        """Validated here so the tool thread gets the error, not the Qt slot."""
        from core.viewer3d import build_call
        function, args_json = build_call(function, args)
        self._win._viewer_call_sig.emit(function, json.dumps(json.loads(args_json)))

    def viewer3d_hover(self) -> dict:
        """Part currently under the mouse in the 3D viewer ({'name','text'}, empty if none)."""
        return dict(self._win._viewer3d_hover_state)

    def viewer3d_info(self) -> dict:
        """Models loaded in the viewer ({id: {name, parts, nodes, animations}}) and the last page error."""
        return {"models": dict(self._win._viewer3d_models), "active": self._win._viewer3d_active, "last_error": self._win._viewer3d_last_error}

    def viewer3d_screenshot(self, timeout: float = 10.0) -> str:
        """Ask the page for a PNG, wait for Python to save it, return the file path (tool thread)."""
        import threading
        win = self._win
        shot = {"event": threading.Event(), "path": "", "error": ""}
        win._viewer3d_shot = shot
        try:
            self.viewer3d_call("screenshot", [])
            if not shot["event"].wait(timeout):
                raise RuntimeError("the viewer did not answer in time")
        finally:
            win._viewer3d_shot = None
        if shot["error"]:
            raise RuntimeError(shot["error"])
        return shot["path"]

    def panel_status(self) -> dict:
        win = self._win
        return {
            "workspace": win._panel_state.workspace,
            "panels": win._panel_state.snapshot(),
            "floating": dict(win._dock_floating),
        }

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_voice_change(self):
        return self._win.on_voice_change

    @on_voice_change.setter
    def on_voice_change(self, cb):
        self._win.on_voice_change = cb

    @property
    def on_audio_device_change(self):
        return self._win.on_audio_device_change

    @on_audio_device_change.setter
    def on_audio_device_change(self, cb):
        self._win.on_audio_device_change = cb

    def show_confirm(self, title: str, detail: str) -> None:
        """Thread-safe: raise the irreversible-action gate. Called from action
        handlers running in executor threads, so it goes through a signal."""
        self._win._confirm_sig.emit(str(title)[:120], str(detail)[:300])

    def hide_confirm(self) -> None:
        """Thread-safe: take the gate down."""
        self._win._confirm_hide_sig.emit()

    @property
    def get_plugins(self):
        return self._win.get_plugins

    @get_plugins.setter
    def get_plugins(self, cb):
        self._win.get_plugins = cb

    def set_audio_level(self, level: float) -> None:
        """Thread-safe: feed a 0.0–1.0 live audio level to the HUD waveform.
        Called from the audio threads; a plain float store is atomic under the
        GIL, so no signal/lock is needed for this cosmetic value."""
        try:
            self._win.hud.set_audio_level(level)
        except Exception:
            pass

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_jarvis_state(self, state: str) -> None:
        """Thread-safe state API for the reactive HUD."""
        normalized = state.strip().lower()
        if normalized not in _JARVIS_VISUAL_STATES:
            expected = ", ".join(sorted(_JARVIS_VISUAL_STATES))
            raise ValueError(f"state must be one of: {expected}")
        self._win._state_sig.emit(normalized.upper())

    def set_generation_status(self, backend: str) -> None:
        """Thread-safe: start, update or clear the live 3D generation HUD status."""
        self._win._generation_status_sig.emit(str(backend or ""))

    def update_generation_progress(self, elapsed: int) -> None:
        """Thread-safe elapsed-time update from the local worker monitor."""
        self._win._generation_elapsed_sig.emit(int(elapsed))

    def request_triposr_fallback(self) -> bool:
        """Ask on the UI thread before cancelling a slow SF3D process."""
        response = {"event": threading.Event(), "use_triposr": False}
        self._win._generation_fallback_sig.emit(response)
        if not response["event"].wait(1800):
            self.write_log("Generazione 3D: conferma fallback scaduta; SF3D continua.")
            return False
        return bool(response["use_triposr"])

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def show_hud_browser(self, url: str) -> None:
        """Load the bridge HUD in Jarvis's central UI without opening a browser."""
        self._win._hud_browser_sig.emit(str(url))

    def load_gev(self) -> None:
        self.send_to_gev({"action": "open"})

    def show_gemini_chat(self) -> None:
        """Thread-safe: show the embedded Gemini chat panel."""
        self._win._gemini_chat_sig.emit()

    def confirm_streaming_play_in_chrome(self, url: str, timeout: float = 120) -> bool:
        """Ask on the Qt UI thread before opening protected streaming in Chrome."""
        if QThread.currentThread() == self._win.thread():
            return self._win._ask_open_streaming_in_chrome(url)

        response: dict = {"event": threading.Event()}
        self._win._streaming_play_confirm_sig.emit(url, response)
        if not response["event"].wait(timeout):
            self.write_log(
                "Streaming: conferma DRM scaduta; Chrome non è stato aperto."
            )
            return False
        if "error" in response:
            self.write_log(
                f"Streaming: conferma non disponibile; Chrome non è stato aperto: "
                f"{response['error']}"
            )
            return False
        return response.get("confirmed") is True

    def open_url_in_webview(self, url: str) -> str:
        normalized_url = normalize_http_url(url)
        self._win._browser_open_sig.emit(normalized_url)
        return normalized_url

    def press_key_in_webview(self, key: str) -> str:
        normalized_key = normalize_web_key(key)
        self._win._browser_key_sig.emit(normalized_key)
        return normalized_key

    def click_link_in_webview(self, link_text: str) -> str:
        normalized_text = normalize_link_text(link_text)
        self._win._browser_click_sig.emit(normalized_text)
        return normalized_text

    def read_page_aloud(self, mode: str = "page") -> None:
        self._win._browser_read_page_sig.emit(mode)

    def stop_reading(self) -> None:
        self._win._browser_stop_reading_sig.emit()

    def close_webview(self) -> None:
        self._win._browser_close_sig.emit()

    def send_to_gev(self, message: dict) -> None:
        if not isinstance(message, dict):
            raise TypeError("GEV message must be a dict")

        action = message.get("action")
        if action not in {
            "open", "open_tab", "hide_tab", "track", "layer", "reset",
            "annotate", "historical_map",
            "camera_set", "camera_fly", "camera_zoom", "camera_tilt",
            "camera_rotate", "camera_reset",
        }:
            raise ValueError(f"Unsupported GEV action: {action}")
        params = message.get("params", {})
        if not isinstance(params, dict):
            raise TypeError("GEV action params must be a dict")
        if action == "historical_map":
            command = params.get("command")
            if command not in {"show", "animate", "stop", "clear"}:
                raise ValueError(f"Unsupported historical map command: {command}")
            if command == "show" and (
                not isinstance(params.get("year"), int)
                or isinstance(params.get("year"), bool)
                or abs(params["year"]) > _GEV_MAX_SAFE_JS_INTEGER
            ):
                raise ValueError("Historical show command requires an integer year")
            if command == "animate":
                for key in ("start_year", "end_year"):
                    if (
                        not isinstance(params.get(key), int)
                        or isinstance(params.get(key), bool)
                        or abs(params[key]) > _GEV_MAX_SAFE_JS_INTEGER
                    ):
                        raise ValueError(f"Historical animate command requires integer {key}")
                speed = params.get("speed", 3)
                if (
                    not isinstance(speed, (int, float))
                    or isinstance(speed, bool)
                    or not 0.5 <= speed <= 30
                    or not math.isfinite(speed)
                    or params["start_year"] > params["end_year"]
                ):
                    raise ValueError("Historical animate command has invalid range or speed")
        if action == "track" and params.get("target_type") not in _GEV_FOLLOW_KINDS:
            raise ValueError(
                f"GEV cannot track target type: {params.get('target_type')}"
            )
        if action == "layer" and params.get("layer") not in _GEV_LAYERS:
            raise ValueError(f"Unsupported GEV layer: {params.get('layer')}")
        if (
            action not in {"open", "open_tab", "hide_tab"}
            and not self._win._gev_ready_evt.is_set()
        ):
            raise RuntimeError("GEV interface is not ready")

        serialized = json.dumps(
            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        self._win._gev_send_sig.emit(serialized)

    def wait_for_gev(self, timeout: float = 30.0) -> bool:
        """Wait off the Qt thread until the embedded GEV reports it is ready."""
        return self._win._gev_ready_evt.wait(timeout)

    def on_gev_message(self, callback) -> None:
        self._win._gev_message_callback = callback

    def _dispatch_gev_message(self, message: dict) -> None:
        callback = getattr(self._win, "_gev_message_callback", None)
        if callable(callback):
            callback(message)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def hide_content(self, prefix: str = "IMAGES"):
        """Thread-safe: close the content panel if it is showing a result titled with prefix."""
        self._win._content_hide_sig.emit(prefix)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    # ── Widget system API ────────────────────────────────────────────────────
    def show_widget(
        self,
        id: str,
        type: str,
        title: str,
        payload: dict,
        ttl: int = None,
        area: str = "content",
        priority: int = 0,
    ) -> None:
        """
        Thread-safe: show or update a widget in the JARVIS HUD.

        Args:
            id:       Unique identifier (same id = update in-place, not create)
            type:     Widget type: 'text' | 'progress' | 'image' | 'table' |
                      'list' | 'toast' | 'gauge' | 'toggle_list' | 'countdown'
            title:    Short label shown above the widget
            payload:  Type-specific data dict (validated by WidgetRegistry)
            ttl:      Auto-remove after this many seconds (None = permanent)
            area:     'content' | 'overlay' | 'toast'
            priority: Higher = preferred when space is limited
        """
        from core.widget_registry import registry
        import core.widget_renderers  # ensure renderers are registered  # noqa: F401
        spec = {
            "id": id, "type": type, "title": title,
            "payload": payload, "ttl": ttl, "area": area, "priority": priority,
        }
        err = registry.validate(spec)
        if err:
            self.write_log(f"[Widget] Rejected spec for '{id}': {err}")
            return
        self._win._widget_sig.emit(spec)

    def update_widget(self, id: str, payload: dict) -> None:
        """Thread-safe: update an existing widget's payload in-place."""
        from core.widget_registry import registry
        self._win._widget_sig.emit({"id": id, "type": "__update__", "payload": payload})

    def remove_widget(self, id: str) -> None:
        """Thread-safe: remove a widget by id."""
        self._win._widget_sig.emit({"id": id, "type": "__remove__", "payload": {}})

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")