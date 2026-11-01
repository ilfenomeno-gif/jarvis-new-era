import pytest

from actions import search_3d_model as tool
from core import image_input, model_search
from tests.glb_helper import make_glb

UID = "a" * 32


def glb_bytes(tmp_path):
    make_glb(tmp_path / "x.glb")
    return (tmp_path / "x.glb").read_bytes()


class FakePlayer:
    def __init__(self):
        self.calls = []

    def viewer3d_call(self, name, args):
        self.calls.append((name, args))


def fake_api(url, token=""):
    if "/search" in url:
        return {"results": [{"uid": UID, "name": "Ferrari F40", "viewerUrl": "https://sketchfab.com/m/" + UID,
                             "user": {"displayName": "Maker"}, "license": {"label": "CC Attribution"}}]}
    return {"glb": {"url": "https://cdn.example/model.glb"}}


def test_curated_match_is_generic_and_bilingual():
    assert model_search.curated_match("una Ferrari")["uid"] == "CarConcept"
    assert model_search.curated_match("un casco")["uid"] == "DamagedHelmet"
    assert model_search.curated_match("drago") is None


def test_sketchfab_with_token_downloads_and_credits(tmp_path):
    data = glb_bytes(tmp_path)
    seen = []
    result = model_search.search_and_download("ferrari", tmp_path / "dl", api=fake_api,
                                              fetch=lambda url: seen.append(url) or data, token="tok")
    assert result["ok"] and result["source"] == "sketchfab" and result["author"] == "Maker"
    assert result["path"].read_bytes()[:4] == b"glTF"
    assert seen == ["https://cdn.example/model.glb"]
    assert "Maker" in (tmp_path / "dl" / "ATTRIBUTION.txt").read_text(encoding="utf-8")


def test_without_token_falls_back_to_curated_library(tmp_path):
    data = glb_bytes(tmp_path)
    urls = []
    result = model_search.search_and_download("ferrari", tmp_path / "dl", api=fake_api,
                                              fetch=lambda url: urls.append(url) or data, token="")
    assert result["ok"] and result["source"] == "khronos"
    assert "generic" in result["note"] and urls[0].endswith("CarConcept/glTF-Binary/CarConcept.glb")


def test_not_found_and_bad_files(tmp_path):
    miss = model_search.search_and_download("drago", tmp_path / "dl", api=fake_api, fetch=lambda u: b"", token="")
    assert not miss["ok"]
    bad = model_search.search_and_download("auto", tmp_path / "dl", api=fake_api, fetch=lambda u: b"<html>", token="")
    assert not bad["ok"] and "glTF" in bad["reason"]
    assert not list((tmp_path / "dl").glob("*.glb"))


def test_download_refuses_private_hosts():
    with pytest.raises(ValueError):
        image_input.download_image("http://127.0.0.1/a.glb", max_bytes=1000, accept="*/*")


def test_tool_ferrari_loads_realistic_from_downloads(tmp_path, monkeypatch):
    data = glb_bytes(tmp_path)
    path = tmp_path / "ferrari-f40-aaaaaa.glb"
    path.write_bytes(data)
    monkeypatch.setattr(model_search, "search_and_download", lambda q: {
        "ok": True, "path": path, "source": "sketchfab", "name": "Ferrari F40", "author": "Maker",
        "license": "CC-BY", "note": ""})
    player = FakePlayer()
    out = tool.search_3d_model({"query": "una Ferrari"}, player=player)
    assert player.calls == [("setMaterialStyle", ["realistic"]), ("loadModel", ["downloads/ferrari-f40-aaaaaa.glb"])]
    assert "Maker" in out and "CC-BY" in out


def test_tool_not_found_points_to_generation(monkeypatch):
    monkeypatch.setattr(model_search, "search_and_download", lambda q: {"ok": False, "reason": "none"})
    assert "generate_3d_model" in tool.search_3d_model({"query": "drago"})
    assert "Invalid request" in tool.search_3d_model({"query": ""})


def test_downloads_models_are_loadable_and_listed(tmp_path):
    from core.viewer3d import list_models, model_file
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "car-aaaaaa.glb").write_bytes(b"glTF")
    assert list_models(tmp_path)["downloads"] == ["downloads/car-aaaaaa.glb"]
    assert model_file("downloads/car-aaaaaa.glb", tmp_path).name == "car-aaaaaa.glb"
    with pytest.raises(ValueError):
        model_file("downloads/../x.glb", tmp_path)
