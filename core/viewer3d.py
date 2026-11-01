"""Validation for commands sent to the 3D viewer. No Qt imports.

The page executes only functions in ALLOWED, with arguments passed as JSON
(never interpolated into script text).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
ALLOWED = {
    "flyTo": 2,
    "addMarker": 3,
    "clearMarkers": 0,
    "spin": 1,
    "setFlights": 1,
    "clearFlights": 0,
    "loadModel": 1,
    "clearModel": 0,
    "explodeModel": 1,
    "highlightPart": 1,
    "setHologram": 1,
    "setMaterialStyle": 1,
    "setPartInfo": 1,
    "setControls": 1,
    "setClipping": 2,
    "applyPhysics": 1,
    "setHudState": 6,
}
STYLES = ("hologram", "blueprint", "realistic", "flat", "toon")
HUD_STATES = frozenset({"idle", "listening", "thinking", "speaking", "error", "generating_3d"})
MAX_PART_INFO = 200

MODELS_DIR = Path(__file__).resolve().parent.parent / "assets" / "viewer3d" / "models"
MAX_MODEL_BYTES = 40 * 1024 * 1024
_MODEL_NAME = re.compile(r"^((cad|downloads)/)?[A-Za-z0-9][A-Za-z0-9_\-. ]{0,100}\.(glb|gltf)$")
SUBFOLDERS = ("cad", "downloads")


def _ensure_pc_cad(folder: Path) -> None:
    """cad/pc.glb is built from code, not downloaded: create it on first use (needs trimesh)."""
    try:
        from core.make_pc_cad import make_pc_cad
        make_pc_cad(folder)
    except Exception:
        pass


def model_file(name, base: Path | None = None) -> Path:
    """Resolve a model name (plain, or 'cad/<name>') to a file in the models folder, or raise ValueError."""
    base = (base or MODELS_DIR).resolve()
    name = str(name or "").strip()
    if not _MODEL_NAME.match(name) or ".." in name:
        raise ValueError("model must be a .glb/.gltf file name (optionally cad/<name>)")
    path = (base / name).resolve()
    if path.parent not in (base, *(base / sub for sub in SUBFOLDERS)):
        raise ValueError("model must be inside the models folder")
    if not path.is_file() and name == "cad/pc.glb":
        _ensure_pc_cad(base / "cad")
    if not path.is_file():
        raise ValueError(f"model '{name}' not found in the models folder")
    if path.stat().st_size > MAX_MODEL_BYTES:
        raise ValueError("model file is too large")
    return path


def list_models(base: Path | None = None) -> dict[str, list[str]]:
    """Model names available to loadModel: generated, pre-downloaded CAD and web-downloaded ones."""
    base = (base or MODELS_DIR).resolve()
    out = {"generated": [], "cad": [], "downloads": []}
    if not (base / "cad" / "pc.glb").is_file():
        _ensure_pc_cad(base / "cad")
    for key, folder, prefix in (("generated", base, ""), ("cad", base / "cad", "cad/"),
                                ("downloads", base / "downloads", "downloads/")):
        if folder.is_dir():
            out[key] = sorted(
                prefix + p.name for p in folder.iterdir()
                if p.is_file() and _MODEL_NAME.match(prefix + p.name)
            )
    return out


def part_names(path: Path, limit: int = 60) -> list[str]:
    """Node names of a .glb/.gltf as the viewer sees them (three.js sanitises names)."""
    import struct

    data = path.read_bytes()
    if data[:4] == b"glTF":
        length = struct.unpack_from("<I", data, 12)[0]
        doc = json.loads(data[20:20 + length].decode("utf-8"))
    else:
        doc = json.loads(data.decode("utf-8"))
    names = []
    for node in doc.get("nodes", []):
        name = re.sub(r"[\[\].:/]", "", re.sub(r"\s", "_", str(node.get("name") or "")))
        if name and name not in names:
            names.append(name)
    return names[:limit]

MAX_FLIGHTS = 400


def is_viewer_url_allowed(url: str, viewer_dir) -> bool:
    """True only for file:// URLs that resolve inside the local viewer3d folder."""
    from pathlib import Path
    from urllib.parse import unquote, urlparse
    try:
        parsed = urlparse(str(url))
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            return False
        path = unquote(parsed.path)
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]  # /C:/dir -> C:/dir
        resolved = Path(path).resolve()
        resolved.relative_to(Path(viewer_dir).resolve())
        return True
    except (ValueError, OSError):
        return False


def sanitize_hover(name, text) -> dict | None:
    """Validate hover fields received from the viewer; None if they are not strings."""
    if not isinstance(name, str) or not isinstance(text, str):
        return None
    return {"name": name.strip()[:60], "text": text.strip()[:300]}

REGIONS = {
    "europe": (35.0, 72.0, -12.0, 40.0),
    "usa": (24.0, 50.0, -125.0, -66.0),
    "world": (-90.0, 90.0, -180.0, 180.0),
}
OPENSKY_URL = "https://opensky-network.org/api/states/all"


def parse_states(payload: dict, limit: int = MAX_FLIGHTS) -> list[list]:
    """OpenSky state vectors -> [[lat, lon, callsign, altitude_m], ...], airborne only."""
    flights = []
    for row in (payload or {}).get("states") or []:
        try:
            lon, lat, on_ground = row[5], row[6], row[8]
        except (IndexError, TypeError):
            continue
        if lat is None or lon is None or on_ground:
            continue
        altitude = row[7] if len(row) > 7 and row[7] is not None else 0
        flights.append([lat, lon, str(row[1] or "").strip()[:12], altitude])
    # Evenly thinned so a capped list still covers the whole region.
    if len(flights) > limit:
        step = len(flights) / limit
        flights = [flights[int(i * step)] for i in range(limit)]
    return flights


def fetch_flights(region: str = "europe", opener=None, timeout: float = 15.0) -> list[list]:
    """Blocking HTTP call: run it in a worker thread, never on the UI thread."""
    import urllib.request

    if region not in REGIONS:
        raise ValueError(f"Unknown region '{region}'. Use: {', '.join(REGIONS)}.")
    lamin, lamax, lomin, lomax = REGIONS[region]
    url = f"{OPENSKY_URL}?lamin={lamin}&lamax={lamax}&lomin={lomin}&lomax={lomax}"
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis-viewer3d"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"OpenSky not reachable: {exc}") from None
    return parse_states(payload)


def _coord(value, low: float, high: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number


def build_call(function: str, args: list) -> tuple[str, str]:
    """Return (function, args_json) or raise ValueError."""
    if function not in ALLOWED:
        raise ValueError(f"Unknown viewer function '{function}'.")
    if len(args) != ALLOWED[function]:
        raise ValueError(f"{function} takes {ALLOWED[function]} argument(s).")
    if function in ("flyTo", "addMarker"):
        clean = [_coord(args[0], -90, 90, "lat"), _coord(args[1], -180, 180, "lon")]
        if function == "addMarker":
            clean.append(str(args[2])[:60])
    elif function == "setFlights":
        if not isinstance(args[0], list) or any(
            not isinstance(f, (list, tuple)) or len(f) < 3 for f in args[0]
        ):
            raise ValueError("setFlights takes a list of [lat, lon, callsign]")
        clean = [[
            [_coord(f[0], -90, 90, "lat"), _coord(f[1], -180, 180, "lon"), str(f[2])[:12]]
            for f in args[0][:MAX_FLIGHTS]
        ]]
    elif function == "loadModel":
        # Existence is checked by model_file() in the tool; here only the shape.
        if not isinstance(args[0], str) or not _MODEL_NAME.match(args[0]):
            raise ValueError("model must be a plain .glb/.gltf file name")
        clean = [args[0]]
    elif function in ("explodeModel", "setHologram", "setControls"):
        if not isinstance(args[0], bool):
            raise ValueError(f"{function} takes true or false")
        clean = [args[0]]
    elif function == "highlightPart":
        if not isinstance(args[0], str):
            raise ValueError("part must be text")
        clean = [args[0].strip()[:60]]
    elif function == "setMaterialStyle":
        style = args[0].strip().lower() if isinstance(args[0], str) else ""
        if style not in STYLES:
            raise ValueError(f"style must be one of: {', '.join(STYLES)}")
        clean = [style]
    elif function == "setClipping":
        axis = args[0].strip().lower() if isinstance(args[0], str) else ""
        if axis not in ("x", "y", "z", "off", "none"):
            raise ValueError("axis must be x, y, z or off")
        clean = [axis, _coord(args[1], 0, 1, "position")]
    elif function == "applyPhysics":
        mode = args[0].strip().lower() if isinstance(args[0], str) else ""
        if mode not in ("drop", "impulse"):
            raise ValueError("physics mode must be drop or impulse")
        clean = [mode]
    elif function == "setPartInfo":
        if not isinstance(args[0], dict):
            raise ValueError("part info must be an object of part name -> description")
        clean = [{
            str(k).strip()[:60]: str(v).strip()[:300]
            for k, v in list(args[0].items())[:MAX_PART_INFO]
            if str(k).strip()
        }]
    elif function == "setHudState":
        state, color = args[0], args[1]
        if not isinstance(state, str) or state not in HUD_STATES:
            raise ValueError("unsupported HUD state")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("core color must be a #RRGGBB value")
        clean = [
            state, color.lower(),
            _coord(args[2], 0, 5, "ring speed"),
            _coord(args[3], 0, 3, "glow intensity"),
            _coord(args[4], 0, 100, "particle count"),
            _coord(args[5], 0, 5, "transition"),
        ]
    elif function == "spin":
        if not isinstance(args[0], bool):
            raise ValueError("spin takes true or false")
        clean = [args[0]]
    else:
        clean = []
    return function, json.dumps(clean)
