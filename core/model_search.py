"""Smart 3D search: find a ready-made .glb instead of generating a deformed one. No Qt imports.

Two sources, in this order:
1. Sketchfab (downloadable models). Searching is public; downloading needs an API token
   (SecretStore ``sketchfab_api_key`` or the SKETCHFAB_TOKEN environment variable).
2. A curated KhronosGroup library (no key): generic stand-ins, pinned to a commit.
Files are saved in assets/viewer3d/models/downloads/ (git-ignored) with an ATTRIBUTION.txt.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from core import image_input
from core.viewer3d import MODELS_DIR

DOWNLOADS_DIR = MODELS_DIR / "downloads"
MAX_BYTES = 40 * 1024 * 1024
_SKETCHFAB = "https://api.sketchfab.com/v3/"
_KHRONOS = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/edc7c9e67c639d230715049ee31f9a96a6babbbe/Models/"

# keyword (it/en) -> Khronos sample model. These are generic objects, not specific brands.
CURATED = {
    "CarConcept": (("auto", "macchina", "car", "ferrari", "lamborghini", "porsche", "supercar", "automobile"),
                   "Car Concept", "generic concept car"),
    "ToyCar": (("giocattolo", "toy car", "toycar"), "Toy Car", "toy car"),
    "CesiumMilkTruck": (("camion", "truck", "furgone", "van"), "Cesium Milk Truck", "milk truck"),
    "AntiqueCamera": (("fotocamera", "camera", "macchina fotografica"), "Antique Camera", "antique camera"),
    "BoomBox": (("stereo", "boombox", "radio"), "BoomBox", "boombox radio"),
    "Lantern": (("lanterna", "lantern", "lampada"), "Lantern", "lantern"),
    "WaterBottle": (("bottiglia", "bottle"), "Water Bottle", "water bottle"),
    "SheenChair": (("sedia", "chair", "poltrona"), "Sheen Chair", "chair"),
    "Duck": (("papera", "anatra", "duck"), "Duck", "rubber duck"),
    "Fox": (("volpe", "fox"), "Fox", "low-poly fox"),
    "CesiumMan": (("uomo", "persona", "man", "character", "personaggio"), "Cesium Man", "walking man"),
    "DamagedHelmet": (("casco", "helmet", "elmo"), "Damaged Helmet", "sci-fi helmet"),
}


def sketchfab_token(config_dir: Path | None = None, store=None) -> str:
    try:
        if store is None:
            from core.secret_store import SecretStore
            base = Path(config_dir) if config_dir else Path(__file__).resolve().parent.parent / "config"
            store = SecretStore(base / "secrets.json")
        value = store.get("sketchfab_api_key")
    except Exception:
        value = None
    return value or os.environ.get("SKETCHFAB_TOKEN", "")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "model"


def _api_json(url: str, token: str = "", timeout: float = 20.0) -> dict:
    if not url.startswith(_SKETCHFAB):
        raise ValueError("refusing an unlisted API host")
    headers = {"User-Agent": "jarvis-3d-search"}
    if token:
        headers["Authorization"] = "Token " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        return json.loads(response.read(2_000_000).decode("utf-8"))


def search_sketchfab(query: str, api=_api_json, limit: int = 5) -> list[dict]:
    url = _SKETCHFAB + "search?" + urllib.parse.urlencode(
        {"type": "models", "q": query, "downloadable": "true", "count": limit})
    out = []
    for item in api(url).get("results", [])[:limit]:
        user = item.get("user") or {}
        lic = item.get("license") or {}
        out.append({"source": "sketchfab", "uid": str(item.get("uid", "")), "name": item.get("name", query),
                    "author": user.get("displayName") or user.get("username", "unknown"),
                    "license": lic.get("label") or lic.get("slug", "unknown"),
                    "page": item.get("viewerUrl", "")})
    return [r for r in out if re.fullmatch(r"[0-9a-f]{32}", r["uid"])]


def curated_match(query: str) -> dict | None:
    words = " " + re.sub(r"[^a-z0-9àèéìòù ]+", " ", str(query).lower()) + " "
    for key, (keywords, title, about) in CURATED.items():
        if any(f" {k} " in words or (len(k) > 4 and k in words) for k in keywords):
            return {"source": "khronos", "uid": key, "name": title, "author": "KhronosGroup glTF-Sample-Assets",
                    "license": "see https://github.com/KhronosGroup/glTF-Sample-Assets (per-model license)",
                    "url": f"{_KHRONOS}{key}/glTF-Binary/{key}.glb", "generic": about}
    return None


def _save(data: bytes, hit: dict, dest: Path) -> Path:
    if data[:4] != b"glTF":
        raise ValueError("the downloaded file is not a binary glTF (.glb)")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{slugify(hit['name'])}-{hit['uid'][:6].lower()}.glb"
    target.write_bytes(data)
    with (dest / "ATTRIBUTION.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{target.name}: \"{hit['name']}\" by {hit['author']} - {hit['license']} - "
                 f"{hit.get('page') or hit.get('url', '')}\n")
    return target


def _sketchfab_glb_url(uid: str, token: str, api) -> str | None:
    info = api(f"{_SKETCHFAB}models/{uid}/download", token)
    return (info.get("glb") or {}).get("url")


def search_and_download(query: str, dest: Path | None = None, api=_api_json, fetch=None,
                        token: str | None = None) -> dict:
    """Return {"ok", "path", "name", "author", "license", "source", "note"} or {"ok": False, "reason"}."""
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "reason": "empty query"}
    dest = Path(dest or DOWNLOADS_DIR)
    fetch = fetch or (lambda url: image_input.download_image(url, max_bytes=MAX_BYTES, accept="*/*"))
    token = sketchfab_token() if token is None else token
    problems = []
    if token:
        try:
            for hit in search_sketchfab(query, api):
                url = _sketchfab_glb_url(hit["uid"], token, api)
                if not url:
                    continue
                path = _save(fetch(url), hit, dest)
                return {"ok": True, "path": path, "source": "sketchfab", "name": hit["name"],
                        "author": hit["author"], "license": hit["license"], "note": ""}
        except Exception as exc:
            problems.append(f"Sketchfab: {type(exc).__name__}: {exc}")
    else:
        problems.append("Sketchfab download skipped (no API token: set sketchfab_api_key or SKETCHFAB_TOKEN)")
    hit = curated_match(query)
    if hit:
        try:
            path = _save(fetch(hit["url"]), hit, dest)
            return {"ok": True, "path": path, "source": "khronos", "name": hit["name"], "author": hit["author"],
                    "license": hit["license"],
                    "note": f"This is a {hit['generic']} (generic sample model), not the exact object requested."}
        except Exception as exc:
            problems.append(f"Khronos: {type(exc).__name__}: {exc}")
    return {"ok": False, "reason": "; ".join(problems) or "no model found"}
