"""Image-to-3D input: local files and web URLs become safe PNGs; the tool skips SD-Turbo."""
import io
import urllib.error

import pytest
from PIL import Image

from actions import generate_3d_model as tool
from core import image_input, local_3d_gen as gen
from tests.glb_helper import make_glb
from tests.test_local_3d_gen import READY, line


def png_bytes(size=(64, 48), mode="RGB", fmt="PNG"):
    buf = io.BytesIO()
    Image.new(mode, size, "red").save(buf, fmt)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def read(self, n=-1):
        return self.data[:n] if n >= 0 else self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def open(self, request, timeout=None):
        self.seen.append(request.full_url)
        target = self.routes[request.full_url]
        if isinstance(target, str):
            raise urllib.error.HTTPError(request.full_url, 302, "found", {"Location": target}, None)
        return FakeResponse(target)


ALLOW = lambda host: None


def test_local_image_is_sanitised_to_png(tmp_path):
    src = tmp_path / "foto.jpg"
    src.write_bytes(png_bytes((2000, 1000), fmt="JPEG"))
    out = image_input.prepare_image(str(src), None, tmp_path / "work")
    image = Image.open(out)
    assert out.suffix == ".png" and image.format == "PNG" and max(image.size) == image_input.MAX_SIDE


def test_local_image_rejects_bad_input(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    (tmp_path / "fake.png").write_bytes(b"not an image")
    for bad, message in [("", "empty"), (str(tmp_path / "a.txt"), "image file"),
                         (str(tmp_path / "missing.png"), "not found"), (str(tmp_path / "fake.png"), "not a readable image")]:
        with pytest.raises(ValueError, match=message):
            image_input.prepare_image(bad, None, tmp_path / "w")
    with pytest.raises(ValueError, match="not both"):
        image_input.prepare_image("a.png", "http://x/a.png", tmp_path)


def test_download_follows_public_redirects_only(tmp_path):
    opener = FakeOpener({"https://a.example/x": "https://b.example/y.png", "https://b.example/y.png": png_bytes()})
    data = image_input.download_image("https://a.example/x", opener=opener, resolver=ALLOW)
    assert data[:4] == b"\x89PNG" and opener.seen == ["https://a.example/x", "https://b.example/y.png"]


@pytest.mark.parametrize("url", ["file:///C:/secret.png", "ftp://a/b.png", "javascript:alert(1)",
                                 "https://user:pw@a.example/x.png", ""])
def test_download_rejects_non_http_urls(url):
    with pytest.raises(ValueError):
        image_input.download_image(url, opener=FakeOpener({}), resolver=ALLOW)


def test_download_blocks_private_addresses():
    for url in ("http://127.0.0.1/a.png", "http://localhost/a.png", "http://192.168.1.5/a.png",
                "http://169.254.169.254/latest"):
        with pytest.raises(ValueError, match="public"):
            image_input.download_image(url, opener=FakeOpener({}))
    # a public page must not be able to redirect to an internal one
    opener = FakeOpener({"https://a.example/x": "http://127.0.0.1/admin"})
    with pytest.raises(ValueError, match="public"):
        image_input.download_image("https://a.example/x", opener=opener,
                                   resolver=lambda h: image_input._check_public_host(h) if h == "127.0.0.1" else None)


def test_download_size_cap_and_redirect_loop(monkeypatch):
    monkeypatch.setattr(image_input, "MAX_IMAGE_BYTES", 100)
    with pytest.raises(ValueError, match="too large"):
        image_input.download_image("https://a.example/big", opener=FakeOpener({"https://a.example/big": b"x" * 500}), resolver=ALLOW)
    with pytest.raises(ValueError, match="redirects"):
        image_input.download_image("https://a.example/l", opener=FakeOpener({"https://a.example/l": "https://a.example/l"}), resolver=ALLOW)


def test_html_page_is_not_an_image(tmp_path):
    with pytest.raises(ValueError, match="not a readable image"):
        image_input.sanitise_image(b"<html>nope</html>", tmp_path)


def worker_runner(calls):
    def runner(cmd, timeout):
        calls.append(cmd)
        if "--probe" in cmd:
            return 0, line(READY), ""
        make_glb(cmd[cmd.index("--out") + 1])
        return 0, line({"ok": True}), ""
    return runner


def test_generate_local_with_image_skips_the_text_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    png = image_input.sanitise_image(png_bytes(), tmp_path / "w")
    calls = []
    path = gen.generate_local("image car", tmp_path, worker_runner(calls), image=png)
    cmd = next(c for c in calls if "--probe" not in c)
    assert "--image" in cmd and str(png) in cmd and "--prompt" not in cmd
    assert path.read_bytes()[:4] == b"glTF"


class FakePlayer:
    def __init__(self):
        self.calls = []

    def viewer3d_call(self, name, args):
        self.calls.append((name, args))


def photo_like(path, size=240):
    """Shaded sphere with sensor noise on a white background: soft gradients like a photograph."""
    import random
    rng = random.Random(3)
    image = Image.new("RGB", (size, size), "white")
    px = image.load()
    for y in range(size):
        for x in range(size):
            r = ((x - size / 2) ** 2 + (y - size / 2) ** 2) ** 0.5
            if r < size * 0.35:
                v = int(255 - r * 2) + rng.randint(-8, 8)
                px[x, y] = (v, v // 2, 40)
    image.save(path)


def flat_drawing(path, mode="RGB", blur=False):
    from PIL import ImageDraw
    image = Image.new(mode, (300, 300), "white" if mode == "RGB" else (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 40, 260, 260), fill=(255, 200, 0), outline=(0, 0, 0), width=5)
    draw.rectangle((100, 120, 200, 180), fill=(20, 20, 200))
    if blur:
        from PIL import ImageFilter
        image = image.filter(ImageFilter.GaussianBlur(1.0))
    image.save(path)


def test_is_2d_image_tells_drawings_from_photos(tmp_path):
    flat_drawing(tmp_path / "flat.png")
    flat_drawing(tmp_path / "cutout.png", mode="RGBA")
    flat_drawing(tmp_path / "soft.jpg", blur=True)
    photo_like(tmp_path / "photo.png")
    assert image_input.is_2d_image(tmp_path / "flat.png")
    assert image_input.is_2d_image(tmp_path / "cutout.png")
    assert image_input.is_2d_image(tmp_path / "soft.jpg")
    assert not image_input.is_2d_image(tmp_path / "photo.png")
    assert not image_input.is_2d_image(tmp_path / "missing.png")  # never raises


def test_photo_cutout_with_alpha_is_not_2d(tmp_path):
    photo_like(tmp_path / "p.png")
    image = Image.open(tmp_path / "p.png").convert("RGBA")
    px = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if px[x, y][:3] == (255, 255, 255):
                px[x, y] = (255, 255, 255, 0)
    image.save(tmp_path / "cut.png")
    assert not image_input.is_2d_image(tmp_path / "cut.png")


def test_tool_applies_toon_to_drawings_and_warns(tmp_path, monkeypatch):
    src = tmp_path / "isagi.png"
    flat_drawing(src)
    monkeypatch.setattr(gen, "is_installed", lambda: True)
    monkeypatch.setattr(gen, "generate_local", lambda prompt, image=None, **_: make_glb(tmp_path / "o.glb") or tmp_path / "o.glb")
    player = FakePlayer()
    out = tool.generate_3d_model({"image_path": str(src)}, player=player)
    assert "Rilevato disegno 2D: applico la modalità Toon per una resa migliore" in out
    assert player.calls[0] == ("setMaterialStyle", ["toon"])
    forced = FakePlayer()
    tool.generate_3d_model({"image_path": str(src), "style": "realistic"}, player=forced)
    assert forced.calls[0] == ("setMaterialStyle", ["realistic"])


def test_tool_image_path_never_contacts_tripo(tmp_path, monkeypatch):
    src = tmp_path / "chair.png"
    photo_like(src)
    seen = {}

    def fake_generate_local(prompt, image=None, **_):
        seen.update(prompt=prompt, image=image, existed=image.is_file())
        target = tmp_path / "out.glb"
        make_glb(target)
        return target

    monkeypatch.setattr(gen, "is_installed", lambda: True)
    monkeypatch.setattr(gen, "generate_local", fake_generate_local)
    monkeypatch.setattr(tool.model_gen, "generate_model", lambda *a, **k: pytest.fail("Tripo was contacted"))
    player = FakePlayer()
    out = tool.generate_3d_model({"image_path": str(src)}, player=player)
    assert "generated from the image" in out
    assert seen["existed"] and seen["prompt"].startswith("image chair")
    assert not seen["image"].exists()  # temp copy removed
    assert player.calls == [("setMaterialStyle", ["blueprint"]), ("loadModel", ["out.glb"])]


def test_tool_image_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "is_installed", lambda: True)
    assert "Invalid request" in tool.generate_3d_model({"image_path": str(tmp_path / "nope.png")})
    assert "Invalid request" in tool.generate_3d_model({"image_url": "http://127.0.0.1/a.png"})
    assert "only on the local" in tool.generate_3d_model({"image_url": "https://a.example/a.png", "engine": "tripo"})
    monkeypatch.setattr(gen, "is_installed", lambda: False)
    assert "not installed" in tool.generate_3d_model({"image_path": "a.png"})


def test_tool_reports_local_failure_text(tmp_path, monkeypatch):
    src = tmp_path / "c.png"
    src.write_bytes(png_bytes())
    monkeypatch.setattr(gen, "is_installed", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("The GPU ran out of memory.")
    monkeypatch.setattr(gen, "generate_local", boom)
    assert "local engine" in tool.generate_3d_model({"image_path": str(src)}) 


def test_schema_exposes_image_params_and_prompt_is_optional():
    props = tool.TOOL["parameters"]["properties"]
    assert "image_path" in props and "image_url" in props
    assert tool.TOOL["parameters"]["required"] == []


def test_web_search_images_mode_returns_direct_links(monkeypatch):
    from actions import web_search

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def images(self, query, max_results=0):
            return [{"image": "https://img.example/ferrari.jpg", "title": "Ferrari", "width": 800, "height": 600},
                    {"image": "ftp://bad/x.jpg", "title": "bad"}]

    monkeypatch.setattr(web_search, "_get_ddgs", lambda: FakeDDGS)
    out = web_search.web_search({"query": "ferrari", "mode": "images"})
    assert "https://img.example/ferrari.jpg" in out and "ftp://" not in out


def test_ferrari_request_routes_search_and_3d_tools():
    from core.tool_router import ToolRouter
    declared = [{"name": n} for n in ("web_search", "generate_3d_model", "viewer_3d", "weather_report", "reminder")]
    names = {d["name"] for d in ToolRouter().select("Cerca una Ferrari su Google e creala in 3D", declared)}
    assert {"web_search", "generate_3d_model", "viewer_3d"} <= names


def test_pc_cad_is_created_on_first_use(tmp_path):
    pytest.importorskip("trimesh")
    from core.viewer3d import list_models, model_file
    assert not (tmp_path / "cad" / "pc.glb").exists()
    assert "cad/pc.glb" in list_models(tmp_path)["cad"]
    (tmp_path / "cad" / "pc.glb").unlink()
    assert model_file("cad/pc.glb", tmp_path).read_bytes()[:4] == b"glTF"


def test_hand_tracking_is_gone():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert not (root / "plugins" / "hand_tracking.py").exists()
    assert "hand_tracking" not in (root / "core" / "tool_router.py").read_text(encoding="utf-8")
    assert "mediapipe" not in (root / "requirements.txt").read_text(encoding="utf-8")
