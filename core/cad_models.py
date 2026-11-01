"""Pre-downloaded multi-part CAD models (KhronosGroup) for explode_model. No Qt imports.

Files are pinned to a commit and a SHA-256, fetched only over https from
raw.githubusercontent.com, size-capped and checked for the glTF signature.
They are saved in assets/viewer3d/models/cad/, which is git-ignored: they are
never redistributed by this repository.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from core.viewer3d import MODELS_DIR

_RAW = "https://raw.githubusercontent.com/KhronosGroup/"
_OLD = "glTF-Sample-Models/d7a3cc8e51d7c573771ae77a57f16b0662a905c6/2.0/"
_ASSETS = "glTF-Sample-Assets/edc7c9e67c639d230715049ee31f9a96a6babbbe/Models/"
MAX_BYTES = 10 * 1024 * 1024

CAD_MODELS = {
    "engine.glb": {
        "url": _RAW + _OLD + "2CylinderEngine/glTF-Binary/2CylinderEngine.glb",
        "sha256": "bb5fbccc73a3f68c52f26687fbb25b4a1248ab5f8a115ec55e7ac6a4451c47ee",
        "title": "2 Cylinder Engine (KhronosGroup/glTF-Sample-Models)",
        "about": "Two-cylinder engine: pistons, crankshaft, rods. Parts are unnamed ('Parte N').",
    },
    "gearbox.glb": {
        "url": _RAW + _OLD + "GearboxAssy/glTF-Binary/GearboxAssy.glb",
        "sha256": "8536ac06ec3c37e229a1eefa91803196c5cf281b8f4a88377daf0e943ce91c36",
        "title": "Gearbox Assy (KhronosGroup/glTF-Sample-Models)",
        "about": "Gearbox assembly: gears, shafts, housing. Parts are unnamed ('Parte N').",
    },
    "saw.glb": {
        "url": _RAW + _OLD + "ReciprocatingSaw/glTF-Binary/ReciprocatingSaw.glb",
        "sha256": "44b818a96bedaa521096ef1bd4dfb8c8b59023763f0ca069cec39edfa527c0db",
        "title": "Reciprocating Saw (KhronosGroup/glTF-Sample-Models)",
        "about": "Power tool: motor, gears, blade. Parts are unnamed ('Parte N').",
    },
    "milk_truck.glb": {
        "url": _RAW + _ASSETS + "CesiumMilkTruck/glTF-Binary/CesiumMilkTruck.glb",
        "sha256": "09371b34608116de5842d23abe260bf11acf3e1554daf334a647eb566eee5c49",
        "title": "Cesium Milk Truck (KhronosGroup/glTF-Sample-Assets, CC-BY 4.0, (c) Cesium)",
        "about": "Truck with named parts: Wheels, Cesium_Milk_Truck.",
    },
}

NOTICE = """\
CAD models downloaded by `python -m core.registry_cli download-cad-models`.
Source: https://github.com/KhronosGroup (glTF-Sample-Models / glTF-Sample-Assets), pinned commits.
Check each model's own README/license there before redistributing.
Cesium Milk Truck: CC-BY 4.0, attribution to Cesium (https://cesium.com).
There is no PC model in the Khronos samples.
"""


def _fetch(url: str) -> bytes:
    if not url.startswith(_RAW):
        raise ValueError("refusing to download from an unlisted host")
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis-cad"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("file is larger than the allowed size")
    return data


def download_cad_models(dest: Path | None = None, fetch=_fetch, catalog=None) -> dict[str, str]:
    """Download every catalog model into dest (default models/cad). Returns name -> outcome text."""
    dest = Path(dest or MODELS_DIR / "cad")
    dest.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, spec in (catalog or CAD_MODELS).items():
        target = dest / name
        try:
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == spec["sha256"]:
                results[name] = "already present"
                continue
            data = fetch(spec["url"])
            if data[:4] != b"glTF":
                raise ValueError("not a binary glTF file")
            if hashlib.sha256(data).hexdigest() != spec["sha256"]:
                raise ValueError("SHA-256 mismatch")
            target.write_bytes(data)
            results[name] = f"downloaded ({len(data)} bytes)"
        except Exception as exc:
            results[name] = f"FAILED: {exc}"
    (dest / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    return results
