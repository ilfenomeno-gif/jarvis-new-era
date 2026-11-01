"""Safe image input for image-to-3D: a local file or a web URL becomes a sanitised PNG.

Only the re-encoded PNG reaches the 3D worker. Downloads accept http/https only, refuse
private/loopback addresses (also after redirects), and are capped in size and time.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 1024
MAX_REDIRECTS = 4
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _check_public_host(host: str) -> None:
    if not host:
        raise ValueError("image_url has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise ValueError(f"cannot resolve host '{host}'") from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise ValueError("image_url must point to a public web address")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _open(url: str, opener, timeout: float, accept: str = "image/*"):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 jarvis-image-to-3d",
                                                   "Accept": accept})
    return opener.open(request, timeout=timeout)


def download_image(url, timeout: float = 20.0, opener=None, resolver=_check_public_host,
                   max_bytes: int | None = None, accept: str = "image/*") -> bytes:
    """Safe download (public http(s) only, redirects re-checked, size-capped). Also used for .glb files."""
    limit = max_bytes or MAX_IMAGE_BYTES
    url = str(url or "").strip()
    if len(url) > 2000:
        raise ValueError("image_url is too long")
    opener = opener or urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.username or parts.password:
            raise ValueError("image_url must be a plain http(s) link")
        resolver(parts.hostname or "")
        try:
            response = _open(url, opener, timeout, accept)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                continue
            raise ValueError(f"download failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(f"download failed: {getattr(exc, 'reason', exc)}") from None
        with response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"the file is too large (max {limit} bytes)")
        return data
    raise ValueError("too many redirects")


def sanitise_image(data: bytes, dest_dir: Path) -> Path:
    """Decode with Pillow (rejects non-images), shrink and re-encode as PNG in dest_dir."""
    from PIL import Image
    import io
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise ValueError("the file is not a readable image (png, jpg, webp, bmp, gif)") from None
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "transparency" in image.info or image.mode in ("LA", "PA") else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"input-{uuid.uuid4().hex[:8]}.png"
    image.save(target, "PNG")
    return target


def read_local_image(path) -> bytes:
    text = str(path or "").strip().strip('"')
    if not text:
        raise ValueError("image_path is empty")
    file = Path(text).expanduser().resolve()
    if file.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("image_path must be an image file (png, jpg, webp, bmp, gif)")
    if not file.is_file():
        raise ValueError(f"image not found: {file}")
    if file.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("the image is too large (max 15 MB)")
    return file.read_bytes()


def label_for(image_path=None, image_url=None) -> str:
    """Short readable name used for the saved model file."""
    raw = Path(str(image_path)).stem if image_path else Path(urllib.parse.urlsplit(str(image_url)).path).stem
    slug = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()[:60]
    return "image " + (slug or "model")


def prepare_image(image_path, image_url, dest_dir: Path, **kwargs) -> Path:
    """Validated PNG copy of the user's image; exactly one of image_path / image_url."""
    if image_path and image_url:
        raise ValueError("give either image_path or image_url, not both")
    if not image_path and not image_url:
        raise ValueError("image_path is empty")
    data = read_local_image(image_path) if image_path else download_image(image_url, **kwargs)
    return sanitise_image(data, dest_dir)


# Heuristic thresholds, tuned on flat artwork vs photographs (see tests/test_image_input.py).
_FLAT_TOP_COLOURS = 24
_FLAT_COVERAGE = 0.85        # share of pixels held by the 24 most common colours
_FLAT_NEIGHBOURS = 0.85      # share of horizontal neighbours with the same colour
_ALPHA_COVERAGE = 0.6        # relaxed thresholds when the PNG has real transparency
_ALPHA_NEIGHBOURS = 0.7
_TRANSPARENT_SHARE = 0.02
_MAX_GRADIENT = 0.08         # photographs and shaded renders exceed this share of soft steps


def image_2d_stats(path) -> dict:
    """Numbers behind is_2d_image: colour concentration, flat areas and transparency."""
    from collections import Counter
    from PIL import Image
    with Image.open(path) as source:
        image = source.convert("RGBA")
    image.thumbnail((128, 128))
    width, _ = image.size
    pixels = list(getattr(image, "get_flattened_data", image.getdata)())
    transparent = sum(1 for p in pixels if p[3] < 250) / max(1, len(pixels))
    # 4 bits per channel absorbs JPEG noise without merging real colours.
    quant = [(p[0] >> 4, p[1] >> 4, p[2] >> 4) for p in pixels if p[3] >= 128]
    if not quant:
        return {"coverage": 0.0, "neighbours": 0.0, "gradient": 1.0, "transparent": transparent}
    coverage = sum(c for _, c in Counter(quant).most_common(_FLAT_TOP_COLOURS)) / len(quant)
    same = total = soft = 0
    for i, p in enumerate(pixels[:-1]):
        if (i + 1) % width == 0 or p[3] < 128 or pixels[i + 1][3] < 128:
            continue
        total += 1
        q = pixels[i + 1]
        same += (p[0] >> 4, p[1] >> 4, p[2] >> 4) == (q[0] >> 4, q[1] >> 4, q[2] >> 4)
        # small but non-zero steps are the signature of shading and sensor noise
        soft += 4 <= max(abs(p[0] - q[0]), abs(p[1] - q[1]), abs(p[2] - q[2])) < 24
    return {"coverage": coverage, "neighbours": same / max(1, total),
            "gradient": soft / max(1, total), "transparent": transparent}


def is_2d_image(path) -> bool:
    """True for drawings, logos, comics and anime: flat colours, sharp outlines, few gradients.
    Photographs (and photo cut-outs on transparency) stay False. Never raises."""
    try:
        s = image_2d_stats(path)
    except Exception:
        return False
    if s["gradient"] > _MAX_GRADIENT:
        return False
    if s["transparent"] >= _TRANSPARENT_SHARE and s["coverage"] >= _ALPHA_COVERAGE and s["neighbours"] >= _ALPHA_NEIGHBOURS:
        return True
    return s["coverage"] >= _FLAT_COVERAGE and s["neighbours"] >= _FLAT_NEIGHBOURS
