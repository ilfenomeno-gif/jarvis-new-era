"""generate_3d_model: Tripo flow with a fake client (no network, no key, no credits)."""
import io
import json
import pytest

from actions import generate_3d_model as tool
from core import model_gen
from tests.glb_helper import make_glb


class FakeTask:
    def __init__(self, status="success", error_msg=""):
        self.status, self.error_msg = status, error_msg


def fake_factory(status="success", writer=None, hang=False):
    class Client:
        def __init__(self, key):
            self.key = key
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def text_to_model(self, prompt): return "task1"
        async def wait_for_task(self, task_id, timeout=None):
            if hang:
                raise TimeoutError()
            return FakeTask(status, "bad prompt" if status != "success" else "")
        async def download_task_models(self, task, out):
            from pathlib import Path
            target = Path(out) / "task1_model.glb"
            (writer or make_glb)(target)
            return {"model": str(target), "pbr_model": str(target)}
    return Client


def test_generate_success_moves_glb_and_cleans_tmp(tmp_path):
    path = model_gen.generate_model("A glowing sword", "k", tmp_path, fake_factory())
    assert path.parent == tmp_path and path.suffix == ".glb"
    assert path.name == model_gen.model_name("A glowing sword")
    assert path.read_bytes()[:4] == b"glTF"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_generate_failure_modes(tmp_path):
    with pytest.raises(RuntimeError, match="bad prompt"):
        model_gen.generate_model("x", "k", tmp_path, fake_factory("failed"))
    with pytest.raises(RuntimeError, match="timed out"):
        model_gen.generate_model("x", "k", tmp_path, fake_factory(hang=True))
    with pytest.raises(RuntimeError, match="not a valid"):
        model_gen.generate_model("x", "k", tmp_path, fake_factory(writer=lambda p: open(p, "wb").write(b"nope")))
    assert list(tmp_path.iterdir()) == []


def test_prompt_validation():
    with pytest.raises(ValueError):
        model_gen.clean_prompt("   ")
    with pytest.raises(ValueError):
        model_gen.clean_prompt("a" * 301)
    assert model_gen.clean_prompt("  a   b ") == "a b"
    assert model_gen.model_name("../../x y").endswith(".glb")
    assert "/" not in model_gen.model_name("../../x y")


def test_tool_messages_without_sdk_or_key(monkeypatch):
    monkeypatch.setattr(model_gen, "backend", lambda *a, **k: "tripo")
    monkeypatch.setattr(model_gen, "tripo_available", lambda: False)
    monkeypatch.setattr(
        model_gen, "is_backend_available",
        lambda backend: (False, "Tripo SDK unavailable")
        if backend == "tripo" else (False, "local generator unavailable"),
    )
    assert "pip install" in tool.generate_3d_model({"prompt": "a car"})
    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda *a, **k: "")
    monkeypatch.setattr(
        model_gen, "is_backend_available",
        lambda backend: (False, "no key")
        if backend == "tripo" else (False, "local generator unavailable"),
    )
    assert "set-tripo-key" in tool.generate_3d_model({"prompt": "a car"})
    assert "Invalid" in tool.generate_3d_model({"prompt": ""})


def test_generation_sets_and_restores_hud_state(monkeypatch):
    states = []

    class Player:
        def set_jarvis_state(self, state):
            states.append(state)

    monkeypatch.setattr(
        tool, "_generate_3d_model",
        lambda parameters, player=None: "generated",
    )
    assert tool.generate_3d_model({"prompt": "apple"}, player=Player()) == "generated"
    assert states == ["generating_3d", "listening"]

    states.clear()
    monkeypatch.setattr(
        tool, "_generate_3d_model",
        lambda parameters, player=None: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    with pytest.raises(RuntimeError, match="failed"):
        tool.generate_3d_model({"prompt": "apple"}, player=Player())
    assert states == ["generating_3d", "listening"]


def test_tool_generates_and_loads(monkeypatch, tmp_path):
    monkeypatch.setattr(model_gen, "backend", lambda *a, **k: "tripo")
    calls = []
    class P:
        def viewer3d_call(self, f, a): calls.append((f, a))
    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda *a, **k: "secret")
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))
    monkeypatch.setattr(model_gen, "MODELS_DIR", tmp_path)
    real = model_gen.generate_model
    monkeypatch.setattr(model_gen, "generate_model",
                        lambda prompt, key: real(prompt, key, tmp_path, fake_factory()))
    out = tool.generate_3d_model({"prompt": "a car"}, player=P())
    assert "shown as a hologram" in out and calls[0][0] == "loadModel"
    assert "secret" not in out
    monkeypatch.setattr(model_gen, "generate_model",
                        lambda prompt, key: (_ for _ in ()).throw(RuntimeError("Tripo generation failed: x")))
    assert "failed" in tool.generate_3d_model({"prompt": "a car"}, player=P())


def test_key_lookup_and_cli(tmp_path, monkeypatch):
    from core.secret_store import SecretStore
    class Plain:
        def protect(self, d): return d
        def unprotect(self, d): return d
    store = SecretStore(tmp_path / "s.json", Plain())
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    assert model_gen.tripo_key(store=store) == ""
    store.set(model_gen.SECRET_NAME, "abc")
    assert model_gen.tripo_key(store=store) == "abc"
    monkeypatch.setenv("TRIPO_API_KEY", "envkey")
    store.delete(model_gen.SECRET_NAME)
    assert model_gen.tripo_key(store=store) == "envkey"

    from core import registry_cli
    class RT:
        secrets = store
    out = registry_cli.run(["set-tripo-key"], RT(), read_token=lambda prompt: "  newkey ")
    assert "stored" in out and "newkey" not in out and store.get(model_gen.SECRET_NAME) == "newkey"
    assert registry_cli.run(["set-tripo-key"], RT(), read_token=lambda p: " ").startswith("error")


def test_real_sdk_names_exist_when_installed():
    tripo3d = pytest.importorskip("tripo3d")
    for name in ("text_to_model", "wait_for_task", "download_task_models"):
        assert hasattr(tripo3d.TripoClient, name)
    assert tripo3d.TaskStatus.SUCCESS.value == "success"
