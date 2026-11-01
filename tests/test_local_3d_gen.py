"""Local 3D generation: orchestration with a fake subprocess runner (no GPU, no models)."""
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone

import pytest

from actions import generate_3d_model as tool
from core import local_3d_gen as gen
from core import model_gen
from tests.glb_helper import make_glb

READY = {"torch": True, "cuda": True, "gpu": "RTX 4060", "vram_gb": 8.0, "missing": []}


@pytest.fixture(autouse=True)
def isolate_generation_log(monkeypatch, tmp_path):
    monkeypatch.setattr(
        gen,
        "_LOG_PATH",
        tmp_path.parent / f"{tmp_path.name}-local_3d_gen.log",
    )
    monkeypatch.setattr(
        gen,
        "CACHE_DIR",
        tmp_path.parent / f"{tmp_path.name}-cache-3d",
    )


def line(payload):
    return gen.RESULT_PREFIX + json.dumps(payload)


def make_runner(probe=READY, result=None, writer=make_glb, raises=None, stderr=""):
    calls = []

    def runner(cmd, timeout):
        calls.append(cmd)
        if "--probe" in cmd:
            return 0, "noise\n" + line(probe), ""
        if raises:
            raise raises
        if result is None or result.get("ok"):
            writer(cmd[cmd.index("--out") + 1])
        return 0, "log\n" + (line(result) if result is not None else line({"ok": True})), stderr
    runner.calls = calls
    return runner


def test_readiness_messages():
    assert gen.readiness_problem(READY) is None
    assert "not installed" in gen.readiness_problem({"torch": False})
    assert "missing" in gen.readiness_problem({**READY, "missing": ["rembg"]})
    assert "No CUDA" in gen.readiness_problem({**READY, "cuda": False})
    low = gen.readiness_problem({**READY, "vram_gb": 4.0})
    assert "4.0 GB" in low and "Tripo" in low


def test_generate_success(tmp_path):
    runner = make_runner()
    path = gen.generate_local("a simple chair", tmp_path, runner)
    assert path.name == model_gen.model_name("a simple chair") and path.read_bytes()[:4] == b"glTF"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]
    assert any("--prompt" in c for c in runner.calls)


def test_persistent_cache_hit_reuses_valid_glb_without_worker(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache" / "3d"
    models_dir = tmp_path / "models"
    monkeypatch.setattr(gen, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    runner = make_runner()

    started = time.monotonic()
    first = gen.generate_local("  A   Test Cube  ", models_dir, runner)
    worker_calls = len(runner.calls)
    monkeypatch.setattr(gen, "probe", lambda runner=None: (_ for _ in ()).throw(
        AssertionError("cache hit must not probe or launch the worker")
    ))

    started = time.monotonic()
    second = gen.generate_local("a test cube", models_dir, runner)
    second_elapsed = time.monotonic() - started

    assert first == second
    assert second.read_bytes()[:4] == b"glTF"
    assert len(runner.calls) == worker_calls
    assert second_elapsed < 1
    metadata = next(cache_dir.glob("*.json"))
    item = json.loads(metadata.read_text(encoding="utf-8"))
    assert item["prompt"] == "  A   Test Cube  "
    assert item["backend"] == "triposr"
    assert item["size_bytes"] == first.stat().st_size
    assert len(item["key"]) == 64
    assert gen._cache_key(" A   Test Cube ", "triposr") == item["key"]


def test_cache_key_tracks_backend_model_parameters_and_image(tmp_path, monkeypatch):
    image = tmp_path / "input.png"
    image.write_bytes(b"image one")
    base = gen._cache_key("a chair", "triposr", image)
    assert gen._cache_key(" A   CHAIR ", "triposr", image) == base
    assert gen._cache_key("a chair", "sf3d", image) != base
    monkeypatch.setenv("JARVIS_3D_TEXTURE", "512")
    sf3d_512 = gen._cache_key("a chair", "sf3d", image)
    monkeypatch.setenv("JARVIS_3D_TEXTURE", "768")
    assert gen._cache_key("a chair", "sf3d", image) != sf3d_512
    image.write_bytes(b"image two")
    assert gen._cache_key("a chair", "triposr", image) != base


def test_cache_disabled_bypasses_reads_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("JARVIS_3D_CACHE", "0")
    runner = make_runner()
    first = gen.generate_local("a chair", tmp_path / "models", runner)
    calls_after_first = len(runner.calls)
    second = gen.generate_local("a chair", tmp_path / "models", runner)
    assert first == second
    assert len(runner.calls) > calls_after_first
    assert not gen.CACHE_DIR.exists()


def test_invalid_cache_policy_fails_before_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_3D_CACHE_TTL_DAYS", "nan")
    monkeypatch.setattr(
        gen,
        "probe",
        lambda runner=None: (_ for _ in ()).throw(
            AssertionError("invalid cache settings must fail before probing")
        ),
    )
    with pytest.raises(ValueError, match="finite non-negative"):
        gen.generate_local("a chair", tmp_path, make_runner())


def test_corrupt_cache_entry_is_discarded_and_regenerated(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    models_dir = tmp_path / "models"
    first = gen.generate_local("a chair", models_dir, make_runner())
    key = gen._cache_key("a chair", "triposr")
    glb_path, _ = gen._cache_paths(key)
    glb_path.write_bytes(b"corrupt")

    runner = make_runner()
    second = gen.generate_local("a chair", models_dir, runner)
    assert second == first
    assert second.read_bytes()[:4] == b"glTF"
    assert any("--prompt" in cmd for cmd in runner.calls)
    assert glb_path.read_bytes()[:4] == b"glTF"


def test_expired_cache_entry_is_regenerated(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    models_dir = tmp_path / "models"
    gen.generate_local("a chair", models_dir, make_runner())
    key = gen._cache_key("a chair", "triposr")
    _, metadata_path = gen._cache_paths(key)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["created_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    runner = make_runner()
    gen.generate_local("a chair", models_dir, runner)
    assert any("--prompt" in cmd for cmd in runner.calls)
    refreshed = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert datetime.fromisoformat(refreshed["created_at"]) > datetime.now(timezone.utc) - timedelta(days=1)


def test_cache_size_limit_skips_cache_without_failing_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    monkeypatch.setenv("JARVIS_3D_CACHE_MAX_GB", "0.000000001")
    path = gen.generate_local("a chair", tmp_path / "models", make_runner())
    assert path.read_bytes()[:4] == b"glTF"
    assert gen.cache_size_bytes() == 0


def test_cache_size_limit_evicts_oldest_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    monkeypatch.setenv("JARVIS_3D_CACHE_MAX_GB", "0.000001")
    models_dir = tmp_path / "models"
    gen.generate_local("first chair", models_dir, make_runner())
    gen.generate_local("second chair", models_dir, make_runner())

    entries = gen.cache_entries()
    assert len(entries) == 1
    assert entries[0]["prompt"] == "second chair"
    assert gen.cache_size_bytes() <= 1024 * 1024 * 0.000001 * 1024


def test_cache_cli_list_size_and_confirmed_clear(tmp_path, monkeypatch):
    from core import registry_cli

    monkeypatch.setattr(gen, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)
    gen.generate_local("a test cube", tmp_path / "models", make_runner())
    unrelated = gen.CACHE_DIR / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")

    listing = registry_cli.run(["cache-3d", "list"], None)
    assert "a test cube" in listing and "triposr" in listing and "bytes" in listing
    size = registry_cli.run(["cache-3d", "size"], None)
    assert "3D cache:" in size and "MiB" in size
    assert registry_cli.run(["cache-3d", "clear"], None).startswith("error:")
    assert "files removed" in registry_cli.run(["cache-3d", "clear", "--yes"], None)
    assert registry_cli.run(["cache-3d", "list"], None) == "3D cache is empty"
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_generation_logs_fallback_and_timings_without_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "_LOG_PATH", tmp_path / "local_3d_gen.log")
    monkeypatch.setattr(gen, "probe", lambda runner=None: READY)

    def runner(cmd, timeout):
        if "--probe" in cmd:
            raise AssertionError("readiness is supplied by the test")
        make_glb(cmd[cmd.index("--out") + 1])
        output = "\n".join((
            'TIMING {"stage":"triposr_load","seconds":12.5}',
            'BACKEND_FALLBACK {"from":"sf3d","to":"triposr","reason":"OutOfMemoryError: CUDA out of memory"}',
            line({"ok": True, "backend": "triposr"}),
        ))
        return 0, output, ""

    gen.generate_local("private prompt must not be logged", tmp_path, runner)
    log = (tmp_path / "local_3d_gen.log").read_text(encoding="utf-8")
    assert '"event": "backend_fallback"' in log
    assert '"category": "oom"' in log
    assert '"stage": "triposr_load"' in log and '"seconds": 12.5' in log
    assert '"backend": "triposr"' in log
    assert "private prompt must not be logged" not in log
    assert "CUDA out of memory" not in log
    with pytest.raises(RuntimeError, match="out of memory"):
        gen.generate_local(
            "private prompt", tmp_path, make_runner(result={"ok": False, "code": "oom"})
        )
    log = (tmp_path / "local_3d_gen.log").read_text(encoding="utf-8")
    assert '"category": "oom"' in log


def test_generate_errors_and_cleanup(tmp_path):
    with pytest.raises(RuntimeError, match="out of memory"):
        gen.generate_local("x", tmp_path, make_runner(result={"ok": False, "code": "oom"}))
    with pytest.raises(RuntimeError, match="failed: ValueError"):
        gen.generate_local("x", tmp_path, make_runner(result={"ok": False, "code": "error", "message": "ValueError: bad"}))
    with pytest.raises(RuntimeError, match="timed out"):
        gen.generate_local("x", tmp_path, make_runner(raises=subprocess.TimeoutExpired("c", 1)))
    with pytest.raises(RuntimeError, match="not a valid"):
        gen.generate_local("x", tmp_path, make_runner(writer=lambda p: open(p, "wb").write(b"nope")))
    with pytest.raises(RuntimeError, match="not installed"):
        gen.generate_local("x", tmp_path, make_runner(probe={"torch": False}))
    assert list(tmp_path.iterdir()) == []


def test_crash_without_result_and_native_oom(tmp_path):
    def crash(cmd, timeout):
        if "--probe" in cmd:
            return 0, line(READY), ""
        return 3, "", "Traceback...\nRuntimeError: boom"
    with pytest.raises(RuntimeError, match="crashed .exit 3.*boom"):
        gen.generate_local("x", tmp_path, crash)

    def native_oom(cmd, timeout):
        if "--probe" in cmd:
            return 0, line(READY), ""
        return 1, "", "CUDA error: out of memory"
    with pytest.raises(RuntimeError, match="out of memory"):
        gen.generate_local("x", tmp_path, native_oom)


def test_marching_cubes_fallback_matches_torchmcubes_convention():
    np = pytest.importorskip("numpy")
    torch = pytest.importorskip("torch")
    trimesh = pytest.importorskip("trimesh")
    pytest.importorskip("skimage")
    import sys
    from core import local_3d_worker as worker
    saved = sys.modules.pop("torchmcubes", None)
    try:
        worker._install_marching_cubes_fallback()
        from torchmcubes import marching_cubes
        n = 33
        ax = np.linspace(-1, 1, n)
        i, j, k = np.meshgrid(ax, ax, ax, indexing="ij")
        sdf = (i / 0.9) ** 2 + (j / 0.6) ** 2 + (k / 0.3) ** 2 - 1
        verts, faces = marching_cubes(torch.from_numpy(sdf).float(), 0.0)
        mesh = trimesh.Trimesh(verts.numpy(), faces.numpy())
        # vertices come out as (axis2, axis1, axis0), like torchmcubes
        assert [round(float(e)) for e in mesh.extents] == [10, 19, 29]
        assert mesh.is_watertight and mesh.volume > 0
    finally:
        sys.modules.pop("torchmcubes", None)
        if saved is not None:
            sys.modules["torchmcubes"] = saved


def test_y_up_conversion():
    trimesh = pytest.importorskip("trimesh")
    from core import local_3d_worker as worker
    tall_z = trimesh.creation.box(extents=[1, 2, 5])
    assert [round(float(e), 3) for e in worker._to_gltf_y_up(tall_z).extents] == [1.0, 5.0, 2.0]


def test_worker_probe_reports_missing_pieces(monkeypatch, tmp_path):
    from core import local_3d_worker as worker
    monkeypatch.setenv("TRIPOSR_DIR", str(tmp_path / "nowhere"))
    assert any("TripoSR" in item for item in worker._missing_modules())


def test_python_exe_avoids_pythonw(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").write_text("")
    (tmp_path / "python.exe").write_text("")
    monkeypatch.delenv("JARVIS_3D_PYTHON", raising=False)
    monkeypatch.setattr(gen.sys, "executable", str(tmp_path / "pythonw.exe"))
    assert gen.python_exe().endswith("python.exe")


def test_backend_config(tmp_path, monkeypatch):
    monkeypatch.delenv(model_gen.BACKEND_ENV, raising=False)
    assert model_gen.backend(tmp_path) == "local"
    monkeypatch.setenv(model_gen.BACKEND_ENV, "sf3d")
    assert model_gen.backend(tmp_path) == "local"
    monkeypatch.setenv(model_gen.BACKEND_ENV, "triposr")
    assert model_gen.backend(tmp_path) == "local"
    model_gen.set_backend("local", tmp_path)
    assert model_gen.backend(tmp_path) == "local"
    monkeypatch.setenv(model_gen.BACKEND_ENV, "tripo")
    assert model_gen.backend(tmp_path) == "tripo"
    monkeypatch.setenv(model_gen.BACKEND_ENV, "bogus")
    assert model_gen.backend(tmp_path) == "local"
    with pytest.raises(ValueError):
        model_gen.set_backend("bogus", tmp_path)


def test_tool_routes_to_local(monkeypatch, tmp_path):
    calls = []

    class P:
        def viewer3d_call(self, f, a):
            calls.append((f, a))

    monkeypatch.setattr(model_gen, "backend", lambda *a, **k: "local")
    monkeypatch.setattr(model_gen, "tripo_available", lambda: False)
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))
    monkeypatch.setattr(gen, "generate_local", lambda prompt: tmp_path / "chair.glb")
    out = tool.generate_3d_model({"prompt": "a simple chair"}, player=P())
    assert "blueprint" in out
    assert calls == [("setMaterialStyle", ["blueprint"]), ("loadModel", ["chair.glb"])]

    def boom(prompt):
        raise RuntimeError(gen.OOM_MESSAGE)
    monkeypatch.setattr(gen, "generate_local", boom)
    assert "out of memory" in tool.generate_3d_model({"prompt": "a chair"}, player=P())


def test_local_action_passes_hud_progress_and_fallback_callbacks(monkeypatch, tmp_path):
    received = {}

    class Player:
        def __init__(self):
            self.states = []
            self.statuses = []

        def set_jarvis_state(self, state):
            self.states.append(state)

        def set_generation_status(self, backend):
            self.statuses.append(backend)

        def update_generation_progress(self, elapsed):
            return elapsed

        def request_triposr_fallback(self):
            return True

        def viewer3d_call(self, function, args):
            pass

    player = Player()
    monkeypatch.setattr(model_gen, "backend", lambda *a, **k: "local")
    monkeypatch.setattr(model_gen, "tripo_available", lambda: False)
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))
    monkeypatch.setattr(gen, "configured_backend", lambda: "sf3d")

    def fake_generate(prompt, **kwargs):
        received.update(kwargs)
        return tmp_path / "apple.glb"

    monkeypatch.setattr(gen, "generate_local", fake_generate)
    result = tool.generate_3d_model(
        {"prompt": "an apple", "engine": "local"}, player=player
    )
    assert "generated and shown" in result
    assert callable(received["progress_callback"])
    assert callable(received["fallback_callback"])
    assert player.states == ["generating_3d", "listening"]
    assert player.statuses == ["Preparazione", "SF3D", ""]


def test_tool_auto_prefers_tripo_key_then_local_then_message(monkeypatch, tmp_path):
    monkeypatch.setattr(model_gen, "backend", lambda *a, **k: "auto")
    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    used = []
    monkeypatch.setattr(model_gen, "generate_model", lambda p, k: used.append("tripo") or tmp_path / "a.glb")
    monkeypatch.setattr(gen, "generate_local", lambda p: used.append("local") or tmp_path / "b.glb")

    monkeypatch.setattr(model_gen, "tripo_key", lambda *a, **k: "k")
    def availability(backend):
        if backend == "tripo":
            return bool(model_gen.tripo_key()), "available" if model_gen.tripo_key() else "no key"
        return gen.is_installed(), "available" if gen.is_installed() else gen.SETUP_MESSAGE
    monkeypatch.setattr(model_gen, "is_backend_available", availability)
    tool.generate_3d_model({"prompt": "a car"})
    monkeypatch.setattr(model_gen, "tripo_key", lambda *a, **k: "")
    monkeypatch.setattr(gen, "is_installed", lambda: True)
    tool.generate_3d_model({"prompt": "a car"})
    assert used == ["tripo", "local"]

    monkeypatch.setattr(gen, "is_installed", lambda: False)
    msg = tool.generate_3d_model({"prompt": "a car"})
    assert "set-tripo-key" in msg and "local_3d_gen setup" in msg


def test_engine_param_overrides_config_and_never_touches_tripo(monkeypatch, tmp_path):
    monkeypatch.setattr(model_gen, "backend", lambda *a, **k: "tripo")
    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda *a, **k: "key")
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))

    def no_tripo(*a, **k):
        raise AssertionError("Tripo must not be contacted when engine='local'")
    monkeypatch.setattr(model_gen, "generate_model", no_tripo)
    monkeypatch.setattr(gen, "generate_local", lambda prompt: tmp_path / "sedia.glb")
    assert "hologram" not in tool.generate_3d_model({"prompt": "una sedia", "engine": "local"})
    assert "saved" in tool.generate_3d_model({"prompt": "una sedia", "engine": "local"})

    used = []
    monkeypatch.setattr(model_gen, "generate_model", lambda p, k: used.append("tripo") or tmp_path / "t.glb")
    tool.generate_3d_model({"prompt": "una sedia", "engine": "tripo"})
    tool.generate_3d_model({"prompt": "una sedia"})
    assert used == ["tripo", "tripo"]
    assert "engine must be" in tool.generate_3d_model({"prompt": "x", "engine": "cloud"})
    props = tool.TOOL["parameters"]["properties"]["engine"]
    assert props["enum"] == ["auto", "local", "tripo"]


def test_local_errors_are_reported_verbatim(monkeypatch):
    monkeypatch.setattr(model_gen, "tripo_available", lambda: False)
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))
    for raised, expected in [
        (RuntimeError(gen.OOM_MESSAGE), "out of memory"),
        (RuntimeError("Local 3D generation timed out (x)"), "timed out"),
        (RuntimeError("No CUDA GPU found: y"), "No CUDA"),
        (OSError("disk full"), "OSError: disk full"),
    ]:
        def boom(prompt, raised=raised):
            raise raised
        monkeypatch.setattr(gen, "generate_local", boom)
        out = tool.generate_3d_model({"prompt": "una sedia", "engine": "local"})
        assert out.startswith("3D generation failed (local engine):") and expected in out, out


def test_worker_perf_defaults(monkeypatch):
    from core import local_3d_worker as worker
    assert worker.QUALITY_STEPS[0][0] == 192
    monkeypatch.delenv("JARVIS_3D_HALF", raising=False)
    assert worker.half_precision() is True
    monkeypatch.setenv("JARVIS_3D_HALF", "0")
    assert worker.half_precision() is False
    with open(worker.__file__, encoding="utf-8") as f:
        assert '"JARVIS_3D_REMBG", "isnet-general-use"' in f.read()


def test_backend_selection_defaults_to_triposr(monkeypatch):
    from core import local_3d_worker as worker
    monkeypatch.delenv("JARVIS_3D_BACKEND", raising=False)
    assert worker.backend() == "triposr"
    monkeypatch.setenv("JARVIS_3D_BACKEND", "TripoSR")
    assert worker.backend() == "triposr"
    monkeypatch.setenv("JARVIS_3D_BACKEND", "nonsense")
    assert worker.backend() == "triposr"


def _stub_backends(monkeypatch, worker, sf3d_error=None):
    calls = []
    monkeypatch.setattr(worker, "_cutout_from_images", lambda images: "cut")

    def sf3d(cut, torch):
        calls.append("sf3d")
        if sf3d_error:
            raise sf3d_error
        return "sf3d-mesh"

    monkeypatch.setattr(worker, "_image_to_mesh_sf3d", sf3d)
    monkeypatch.setattr(worker, "_cutout_to_triposr_mesh", lambda cut, torch, half: calls.append("triposr") or "tsr-mesh")
    monkeypatch.setattr(worker, "_free", lambda torch: None)
    return calls


def test_sf3d_is_used_when_it_works(monkeypatch):
    from core import local_3d_worker as worker
    monkeypatch.setenv("JARVIS_3D_BACKEND", "sf3d")
    calls = _stub_backends(monkeypatch, worker)
    assert worker._build_mesh([object()], None, True) == ("sf3d-mesh", "sf3d", True)
    assert calls == ["sf3d"]


def test_sf3d_failure_falls_back_to_triposr(monkeypatch, capsys):
    from core import local_3d_worker as worker
    monkeypatch.setenv("JARVIS_3D_BACKEND", "sf3d")
    calls = _stub_backends(monkeypatch, worker, sf3d_error=RuntimeError("gated repo"))
    assert worker._build_mesh([object()], None, True) == ("tsr-mesh", "triposr", False)
    assert calls == ["sf3d", "triposr"]
    assert "BACKEND_FALLBACK" in capsys.readouterr().out


def test_triposr_backend_skips_sf3d(monkeypatch):
    from core import local_3d_worker as worker
    monkeypatch.setenv("JARVIS_3D_BACKEND", "triposr")
    calls = _stub_backends(monkeypatch, worker)
    assert worker._build_mesh([object()], None, True)[1] == "triposr"
    assert calls == ["triposr"]


def test_sf3d_texture_resolution_defaults_to_512_and_can_be_overridden(monkeypatch):
    from core import local_3d_worker as worker
    monkeypatch.delenv("JARVIS_3D_TEXTURE", raising=False)
    assert worker.sf3d_texture_resolution() == 512
    monkeypatch.setenv("JARVIS_3D_TEXTURE", "1024")
    assert worker.sf3d_texture_resolution() == 1024


def test_local_worker_monitor_requests_confirmed_triposr_fallback(monkeypatch):
    clock = [0.0]
    launched = []
    progress = []

    class FakeProcess:
        def __init__(self, backend_name):
            self.backend_name = backend_name
            self.terminated = False
            self.poll_count = 0
            self.returncode = 0

        def communicate(self, timeout=None):
            if self.terminated:
                return "", ""
            self.poll_count += 1
            if self.backend_name == "sf3d":
                clock[0] += float(timeout or 1)
                raise subprocess.TimeoutExpired("worker", timeout)
            return "triposr result", ""

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True
            self.returncode = -15

    def fake_popen(cmd, **kwargs):
        backend_name = kwargs["env"]["JARVIS_3D_BACKEND"]
        launched.append(backend_name)
        return FakeProcess(backend_name)

    monkeypatch.setattr(gen.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(gen.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(gen, "SF3D_SLOW_AFTER_SECONDS", 2)
    code, stdout, _ = gen._run_monitored(
        ["worker"], 20, "sf3d", progress.append, lambda: True
    )
    assert code == 0 and stdout == "triposr result"
    assert launched == ["sf3d", "triposr"]
    assert progress == [1, 2]
