"""Heavy worker for local text-to-3D. Runs in its own process (see core/local_3d_gen.py).

Stage 1: SD-Turbo makes a picture of the prompt. Stage 2: TripoSR reconstructs it as a
mesh, saved as .glb. The models are loaded one after the other to fit in 8 GB of VRAM.
The last stdout line is ``JARVIS_RESULT {json}``.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

RESULT_PREFIX = "JARVIS_RESULT "
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.prompt_3d import build_image_prompt  # noqa: E402

TEXT2IMG_MODEL = os.environ.get("JARVIS_3D_TEXT2IMG", "stabilityai/sd-turbo")
TRIPOSR_MODEL = os.environ.get("JARVIS_3D_TRIPOSR", "stabilityai/TripoSR")
SF3D_MODEL = os.environ.get("JARVIS_3D_SF3D", "stabilityai/stable-fast-3d")  # gated on Hugging Face (needs a token)
# (marching-cubes resolution, chunk size): retried smaller after an out-of-memory.
# 192 is the default: 256 costs far more extraction time for little visible gain on a hologram.
QUALITY_STEPS = [(192, 4096), (128, 2048)]


def half_precision() -> bool:
    return os.environ.get("JARVIS_3D_HALF", "1") != "0"


def lap(stage: str, since: float) -> float:
    now = time.perf_counter()
    print("TIMING " + json.dumps({"stage": stage, "seconds": round(now - since, 2)}), flush=True)
    return now


def emit(payload: dict) -> None:
    print(RESULT_PREFIX + json.dumps(payload), flush=True)


def backend() -> str:
    """JARVIS_3D_BACKEND=sf3d|triposr (default triposr; sf3d falls back on failure)."""
    value = os.environ.get("JARVIS_3D_BACKEND", "triposr").strip().lower()
    return value if value in ("sf3d", "triposr") else "triposr"


def sf3d_dir() -> Path:
    return Path(os.environ.get("SF3D_DIR") or Path(__file__).resolve().parent.parent / "third_party" / "stable-fast-3d")


def sf3d_ready() -> bool:
    import importlib.util
    return (sf3d_dir() / "sf3d").is_dir() and all(importlib.util.find_spec(m) is not None for m in ("texture_baker", "uv_unwrapper"))


def triposr_dir() -> Path:
    return Path(os.environ.get("TRIPOSR_DIR") or Path(__file__).resolve().parent.parent / "third_party" / "TripoSR")


def _missing_modules() -> list[str]:
    import importlib.util
    needed = ["diffusers", "transformers", "rembg", "trimesh", "omegaconf", "einops", "PIL", "huggingface_hub"]
    missing = [name for name in needed if importlib.util.find_spec(name) is None]
    if not (triposr_dir() / "tsr").is_dir():
        missing.append("TripoSR sources (run: python -m core.local_3d_gen setup)")
    return missing


def probe() -> dict:
    try:
        import torch
    except ImportError:
        return {"torch": False, "cuda": False, "missing": ["torch"]}
    info = {"torch": True, "torch_version": torch.__version__, "cuda": bool(torch.cuda.is_available()),
            "missing": _missing_modules(), "backend": backend(), "sf3d_ready": sf3d_ready()}
    if info["cuda"]:
        props = torch.cuda.get_device_properties(0)
        info.update(gpu=props.name, vram_gb=round(props.total_memory / 1024 ** 3, 2))
    return info


def _free(torch) -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def candidate_count() -> int:
    try:
        return max(1, min(6, int(os.environ.get("JARVIS_3D_CANDIDATES", "3"))))
    except ValueError:
        return 3


def _text_to_images(prompt: str, torch, count: int) -> list:
    from diffusers import AutoPipelineForText2Image
    pipe = AutoPipelineForText2Image.from_pretrained(TEXT2IMG_MODEL, torch_dtype=torch.float16, variant="fp16")
    pipe.to("cuda")
    try:
        images = []
        for _ in range(count):
            seed = int.from_bytes(os.urandom(4), "little")
            generator = torch.Generator("cuda").manual_seed(seed)
            # SD-Turbo is distilled for one step without guidance
            images.append(pipe(prompt=prompt, num_inference_steps=2, guidance_scale=0.0,
                               width=512, height=512, generator=generator).images[0])
        return images
    finally:
        del pipe
        _free(torch)


def _install_marching_cubes_fallback() -> None:
    """torchmcubes has no Windows wheel and must be compiled; use scikit-image instead.

    torchmcubes returns vertices as (axis2, axis1, axis0) with inside = value < level;
    skimage returns (axis0, axis1, axis2), so reverse the axes and the face winding.
    """
    try:
        import torchmcubes  # noqa: F401
        return
    except ImportError:
        pass
    import types

    import numpy as np
    import torch
    from skimage.measure import marching_cubes as sk_marching_cubes

    def marching_cubes(vol, thresh):
        volume = vol.detach().cpu().numpy().astype(np.float32)
        verts, faces, _, _ = sk_marching_cubes(volume, level=float(thresh))
        verts = np.ascontiguousarray(verts[:, ::-1])
        faces = np.ascontiguousarray(faces[:, ::-1])
        return torch.from_numpy(verts.copy()).float(), torch.from_numpy(faces.astype(np.int64))

    module = types.ModuleType("torchmcubes")
    module.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = module


def debug_dir() -> Path | None:
    """Debug images are only written when JARVIS_3D_DEBUG_DIR is set explicitly."""
    configured = os.environ.get("JARVIS_3D_DEBUG_DIR")
    if not configured:
        return None
    path = Path(configured)
    path.mkdir(parents=True, exist_ok=True)
    return path


def cutout_stats(alpha) -> dict:
    """Coverage of the rembg mask: how much of the frame is object, and how crisp the edge is."""
    import numpy as np
    a = np.asarray(alpha).astype(np.float32) / 255.0
    solid = float((a > 0.9).mean())
    soft = float(((a > 0.1) & (a <= 0.9)).mean())
    ys, xs = np.where(a > 0.5)
    box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None
    return {"object_ratio": round(float((a > 0.5).mean()), 3), "solid": round(solid, 3),
            "soft_edge": round(soft, 3), "bbox": box}


def _largest_component_share(mask) -> float:
    """Share of the object pixels in its biggest 4-connected blob (numpy only, on a coarse grid)."""
    step = max(1, min(mask.shape) // 64)
    grid = mask[::step, ::step]
    seen = ~grid
    best = 0
    for y, x in zip(*grid.nonzero()):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack, size = [(y, x)], 0
        while stack:
            cy, cx = stack.pop()
            size += 1
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < grid.shape[0] and 0 <= nx < grid.shape[1] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        best = max(best, size)
    return best / max(1, int(grid.sum()))


def score_cutout(alpha) -> float:
    """Heuristic 0..1: one dominant, centred, well-framed object scores high; blobs, crops and empty masks low."""
    import numpy as np
    mask = np.asarray(alpha) > 127
    total = mask.size
    ratio = float(mask.sum()) / total
    if ratio < 0.05:
        return 0.0
    dominance = _largest_component_share(mask)
    ys, xs = np.where(mask)
    h, w = mask.shape
    touches = int(xs.min() == 0) + int(ys.min() == 0) + int(xs.max() == w - 1) + int(ys.max() == h - 1)
    cx, cy = (xs.mean() / w - 0.5), (ys.mean() / h - 0.5)
    off_center = min(1.0, (cx * cx + cy * cy) ** 0.5 * 2)
    size_fit = 1.0 - min(1.0, abs(ratio - 0.3) / 0.3)
    return round(max(0.0, 0.4 * dominance + 0.3 * size_fit + 0.3 * (1 - off_center) - 0.25 * touches), 3)


def _pick_cutout(images, session):
    """rembg every candidate, return (index, best cutout, scores)."""
    import numpy as np
    from tsr.utils import remove_background
    cuts = [remove_background(image, session) for image in images]
    scores = [score_cutout(np.array(cut)[:, :, 3]) for cut in cuts]
    best = max(range(len(cuts)), key=lambda i: scores[i])
    return best, cuts[best], scores


def _cutout_from_images(images):
    """rembg every candidate and return the best RGBA cutout, framed at 85% (SF3D/TripoSR share this step)."""
    began = time.perf_counter()
    _install_marching_cubes_fallback()
    sys.path.insert(0, str(triposr_dir()))
    import rembg
    from tsr.utils import resize_foreground

    began = lap("imports", began)
    # rembg's default (bria-rmbg) takes ~9 s per image on CPU; isnet gives the same cutouts in well under 1 s
    session = rembg.new_session(os.environ.get("JARVIS_3D_REMBG", "isnet-general-use"))
    began = lap("rembg_session", began)
    out = debug_dir()
    if out:
        for number, candidate in enumerate(images):
            candidate.save(out / f"jarvis_3d_debug_candidate{number}.png")
    best, cut, scores = _pick_cutout(images, session)
    lap("cutout_pick", began)
    print("CANDIDATES " + json.dumps({"scores": scores, "chosen": best}), flush=True)
    if out:
        images[best].save(out / "jarvis_3d_debug.png")
        cut.save(out / "jarvis_3d_debug_cutout.png")
    return resize_foreground(cut, 0.85)


def sf3d_texture_resolution() -> int:
    """Return SF3D's texture bake resolution (512 by default; 1024 is sharper but slower)."""
    return int(os.environ.get("JARVIS_3D_TEXTURE", "512"))


def _image_to_mesh_sf3d(cut_rgba, torch):
    """Stable Fast 3D: UV-unwrapped mesh with a baked PBR texture. Input is the RGBA cutout (not grey-composited)."""
    sys.path.insert(0, str(sf3d_dir()))
    from sf3d.system import SF3D

    started = time.perf_counter()
    model = SF3D.from_pretrained(SF3D_MODEL, config_name="config.yaml", weight_name="model.safetensors")
    try:
        model.to("cuda")
        model.eval()
        started = lap("sf3d_load", started)
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            mesh, _ = model.run_image([cut_rgba], bake_resolution=sf3d_texture_resolution(),
                                      remesh="none", vertex_count=-1)
        lap("sf3d_forward", started)
        return mesh
    finally:
        del model
        _free(torch)
        torch.cuda.empty_cache()


def _cutout_to_triposr_mesh(cut, torch, use_half: bool = True):
    began = time.perf_counter()
    import numpy as np
    from PIL import Image
    from tsr.system import TSR

    out = debug_dir()
    if out:
        cut.save(out / "jarvis_3d_debug_cutout.png")
    arr = np.array(cut).astype(np.float32) / 255.0
    stats = cutout_stats(arr[:, :, 3] * 255.0)
    arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
    prepared = Image.fromarray((arr * 255.0).astype(np.uint8))
    if out:
        prepared.save(out / "jarvis_3d_debug_tripo_input.png")
    print("CUTOUT " + json.dumps(stats), flush=True)
    lap("debug_images", began)
    started = time.perf_counter()
    model = TSR.from_pretrained(TRIPOSR_MODEL, config_name="config.yaml", weight_name="model.ckpt")
    model.to("cuda")
    # autocast keeps the weights in fp32 but runs the heavy matmuls in fp16, so float32 inputs still work
    precision = torch.autocast("cuda", dtype=torch.float16, enabled=use_half)
    started = lap("triposr_load", started)
    try:
        # the triplane codes do not depend on the quality step: compute them once
        with torch.no_grad(), precision:
            codes = model([prepared], device="cuda")
            if use_half and not bool(torch.isfinite(codes).all()):
                raise FloatingPointError("half precision produced non-finite triplane codes")
        started = lap("triposr_forward", started)
        # keep only a flag: holding the exception would pin its traceback (and the tensors) alive
        ran_out_of_memory = False
        for resolution, chunk in QUALITY_STEPS:
            ran_out_of_memory = False
            try:
                model.renderer.set_chunk_size(chunk)
                with torch.no_grad(), precision:
                    mesh = model.extract_mesh(codes, True, resolution=resolution)[0]
                lap("marching_cubes", started)
                return mesh
            except torch.cuda.OutOfMemoryError:
                ran_out_of_memory = True
            if ran_out_of_memory:
                _free(torch)
        raise torch.cuda.OutOfMemoryError("CUDA out of memory during mesh extraction")
    finally:
        del model
        _free(torch)

def _build_mesh(images, torch, use_half: bool, allow_sf3d: bool = True):
    """Returns (mesh, backend_used, y_up). SF3D first unless disabled; any SF3D failure falls back to TripoSR."""
    cut = _cutout_from_images(images)
    if allow_sf3d and backend() == "sf3d":
        try:
            return _image_to_mesh_sf3d(cut, torch), "sf3d", True
        except Exception as exc:  # gated model, missing token, build problems, OOM...
            print("BACKEND_FALLBACK " + json.dumps({"from": "sf3d", "to": "triposr",
                                                    "reason": f"{type(exc).__name__}: {exc}"[:300]}), flush=True)
            _free(torch)
    return _cutout_to_triposr_mesh(cut, torch, use_half), "triposr", False


def _to_gltf_y_up(mesh):
    """TripoSR meshes are Z-up; glTF/Three.js are Y-up (y' = z, z' = -y)."""
    import numpy as np
    from trimesh.transformations import rotation_matrix
    mesh.apply_transform(rotation_matrix(-np.pi / 2, [1, 0, 0]))
    return mesh


def generate(prompt: str, out: Path, image: Path | None = None) -> dict:
    import torch
    if not torch.cuda.is_available():
        return {"ok": False, "code": "no_cuda", "message": "no CUDA GPU available"}
    try:
        _free(torch)
        began = time.perf_counter()
        if image is not None:
            # image-to-3D: the user's picture replaces the SD-Turbo stage
            from PIL import Image
            images = [Image.open(image).convert("RGB")]
            image_prompt = f"image:{Path(image).name}"
            lap("load_image", began)
        else:
            image_prompt, report = build_image_prompt(prompt)
            print("IMAGE_PROMPT " + json.dumps({"prompt": image_prompt, **report}), flush=True)
            images = _text_to_images(image_prompt, torch, candidate_count())
            lap("sd_turbo", began)
        try:
            mesh, used, y_up = _build_mesh(images, torch, half_precision())
        except FloatingPointError as exc:
            print("HALF_FALLBACK " + str(exc), flush=True)
            _free(torch)
            mesh, used, y_up = _build_mesh(images, torch, False, allow_sf3d=False)
        if not y_up:
            mesh = _to_gltf_y_up(mesh)
        lap("total", began)
        exported = time.perf_counter()
        tmp = out.with_name(out.name + ".tmp")
        try:
            mesh.export(str(tmp), file_type="glb")
            os.replace(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
        lap("export", exported)
        _free(torch)
    except torch.cuda.OutOfMemoryError:
        _free(torch)
        return {"ok": False, "code": "oom", "message": "CUDA out of memory"}
    except Exception as exc:
        return {"ok": False, "code": "error", "message": f"{type(exc).__name__}: {exc}"[:400]}
    return {"ok": True, "path": str(out), "vertices": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
            "image_prompt": image_prompt, "backend": used,
            "textured": getattr(getattr(mesh, "visual", None), "kind", None) == "texture"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--prompt")
    parser.add_argument("--image")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if args.probe:
        emit(probe())
        return 0
    if not (args.prompt or args.image) or not args.out:
        emit({"ok": False, "code": "error", "message": "--prompt (or --image) and --out are required"})
        return 2
    result = generate(args.prompt or "", Path(args.out), Path(args.image) if args.image else None)
    emit(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
