"""Generates a 3D model from text and shows it as a hologram in the viewer.

Backend: local GPU (core/local_3d_gen.py) or Tripo3D (consumes credits), chosen by
model_gen.backend(). Writes one .glb into assets/viewer3d/models/.
"""
import logging
import re
import time

from core import model_gen

_LOG = logging.getLogger(__name__)


def _scene_args(params: dict, path, label: str = ""):
    """(model_id, scale) when the model must be ADDED to the scene instead of replacing it."""
    model_id = re.sub(r"[^A-Za-z0-9_-]", "-", str(params.get("model_id") or "").strip())[:40]
    raw_scale = params.get("scale")
    scale = None
    if raw_scale not in (None, ""):
        try:
            scale = min(3.0, max(0.02, float(raw_scale)))
        except (TypeError, ValueError):
            scale = None
    if not model_id and scale is None:
        return "", None
    if not model_id:
        base = re.sub(r"[^A-Za-z0-9]+", "-", label or path.stem).strip("-").lower()[:24] or "model"
        model_id = f"{base}-{int(time.time())}"
    return model_id, scale


def _close_search_panel(player) -> None:
    """The image-search results panel has done its job once the model is loaded."""
    if player is not None and hasattr(player, "hide_content"):
        try:
            player.hide_content("IMAGES")
        except Exception:
            pass


def _load_in_scene(player, path, model_id: str, scale, params=None) -> None:
    # A scene has ONE look: inherit the current one, change it only on an explicit style.
    style = str((params or {}).get("style") or "").lower()
    if style in _IMAGE_STYLES:
        player.viewer3d_call("setMaterialStyle", [style])
    args = [path.name, model_id]
    if scale is not None:
        args += [None, scale]
    player.viewer3d_call("loadModel", args)
    _close_search_panel(player)


def generate_3d_model(parameters: dict, player=None, **_ignored) -> str:
    set_hud_state = getattr(player, "set_jarvis_state", None)
    set_generation_status = getattr(player, "set_generation_status", None)
    if callable(set_hud_state):
        set_hud_state("generating_3d")
    if callable(set_generation_status):
        set_generation_status("Preparazione")
    try:
        return _generate_3d_model(parameters, player, **_ignored)
    finally:
        if callable(set_generation_status):
            set_generation_status("")
        if callable(set_hud_state):
            set_hud_state("listening")


def _generate_3d_model(parameters: dict, player=None, **_ignored) -> str:
    params = parameters or {}
    image_path = str(params.get("image_path") or "").strip()
    image_url = str(params.get("image_url") or "").strip()
    if image_path or image_url:
        return _image_to_3d(params, image_path, image_url, player)
    try:
        prompt = model_gen.clean_prompt(params.get("prompt"))
    except ValueError as exc:
        return f"Invalid request: {exc}"
    from core import local_3d_gen
    engine = params.get("engine")
    if engine in (None, ""):
        choice = model_gen.backend()
    elif str(engine).lower() in model_gen.BACKENDS:
        choice = str(engine).lower()
    else:
        return f"Invalid request: engine must be one of {', '.join(model_gen.BACKENDS)}"
    use_local = choice == "local"
    fallback_reason = ""
    if not use_local:
        tripo_ready, tripo_reason = model_gen.is_backend_available("tripo")
        if tripo_ready:
            if tripo_reason.startswith("unverified:"):
                _LOG.info("Tripo preflight unverified; trying remote generation once")
        else:
            use_local = True
            fallback_reason = tripo_reason
            _LOG.warning(
                "Tripo non disponibile: uso %s locale (%s)",
                _local_backend_label(local_3d_gen),
                tripo_reason,
            )
    try:
        if use_local:
            local_ready, local_reason = model_gen.is_backend_available("local")
            if not local_ready:
                if fallback_reason:
                    tripo_message = _tripo_unavailable_message(tripo_reason)
                    return (
                        f"{tripo_message} Local fallback unavailable: {local_reason}"
                    )
                return f"3D generation failed (local engine): {local_reason}"
            path = _generate_local(prompt, player, local_3d_gen)
        else:
            _set_generation_status(player, "Tripo3D")
            key = model_gen.tripo_key()
            try:
                path = model_gen.generate_model(prompt, key)
            except RuntimeError as exc:
                if not model_gen.is_credit_error(exc):
                    raise
                fallback_reason = "Tripo credits unavailable"
                local_ready, local_reason = model_gen.is_backend_available("local")
                if not local_ready:
                    return (
                        "3D generation failed (Tripo credits unavailable); "
                        f"local fallback unavailable: {local_reason}"
                    )
                _LOG.warning(
                    "Tripo non disponibile: uso %s locale (crediti insufficienti)",
                    _local_backend_label(local_3d_gen),
                )
                use_local = True
                path = _generate_local(prompt, player, local_3d_gen)
    except RuntimeError as exc:
        if fallback_reason:
            return (
                f"3D generation failed (local fallback after Tripo issue: "
                f"{fallback_reason}): {exc}"
            )
        engine_name = "local" if use_local else "Tripo"
        return f"3D generation failed ({engine_name} engine): {exc}"
    if player is not None and hasattr(player, "viewer3d_call") and params.get("show", True) is not False:
        model_id, scale = _scene_args(params, path, prompt)
        if model_id:
            _load_in_scene(player, path, model_id, scale, params)
            return _scene_message(path, model_id, scale)
        if use_local:
            # TripoSR textures are blurry: show generated models as a clean solid blueprint.
            # The user can ask for "texture originali" (realistic) afterwards.
            player.viewer3d_call("setMaterialStyle", ["blueprint"])
        player.viewer3d_call("loadModel", [path.name])
        _close_search_panel(player)
        if use_local:
            return (f"Model '{path.name}' generated and shown in blueprint style (clean solid look; "
                    "say 'texture originali' for the realistic material). Drag with the mouse to rotate.")
        return f"Model '{path.name}' generated and shown as a hologram."
    return f"Model '{path.name}' generated and saved."


def _scene_message(path, model_id: str, scale) -> str:
    size = f" at scale {scale:g}" if scale is not None else ""
    return (f"Model '{path.name}' generated and ADDED to the scene with id '{model_id}'{size}, next to the "
            "existing models (nothing was replaced); it inherits the scene's current material style. Use viewer_3d "
            "set_material_style to change the look of the whole scene.")


def _set_generation_status(player, backend: str) -> None:
    callback = getattr(player, "set_generation_status", None)
    if callable(callback):
        callback(backend)


def _generation_callbacks(player) -> dict:
    callbacks = {}
    progress = getattr(player, "update_generation_progress", None)
    fallback = getattr(player, "request_triposr_fallback", None)
    if callable(progress):
        callbacks["progress_callback"] = progress
    if callable(fallback):
        callbacks["fallback_callback"] = fallback
    return callbacks


def _local_backend_label(local_3d_gen) -> str:
    return "SF3D" if local_3d_gen.configured_backend() == "sf3d" else "TripoSR"


def _tripo_unavailable_message(reason: str) -> str:
    if reason == "no key":
        return model_gen.KEY_MISSING_MESSAGE
    if reason == "Tripo SDK unavailable":
        return model_gen.SDK_MISSING_MESSAGE
    return f"Tripo unavailable: {reason}."


def _generate_local(prompt, player, local_3d_gen):
    _set_generation_status(player, _local_backend_label(local_3d_gen))
    try:
        return local_3d_gen.generate_local(prompt, **_generation_callbacks(player))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from None


def _show_local(player, params, path, style: str = "blueprint", note: str = "") -> str:
    if player is not None and hasattr(player, "viewer3d_call") and params.get("show", True) is not False:
        model_id, scale = _scene_args(params, path, str(params.get("prompt") or ""))
        if model_id:
            _load_in_scene(player, path, model_id, scale, params)
            return note + _scene_message(path, model_id, scale)
        # TripoSR textures are blurry: show generated models as a clean solid blueprint.
        player.viewer3d_call("setMaterialStyle", [style])
        player.viewer3d_call("loadModel", [path.name])
        _close_search_panel(player)
        return (f"{note}Model '{path.name}' generated from the image and shown in {style} style (say "
                "'texture originali' for the realistic material). Drag with the mouse to rotate.")
    return f"{note}Model '{path.name}' generated from the image and saved."


_IMAGE_STYLES = ("blueprint", "realistic", "toon", "flat")


def _image_style(params: dict, image) -> tuple:
    """Explicit style wins; otherwise drawings get toon and photographs keep blueprint."""
    wanted = str(params.get("style") or "").lower()
    if wanted in _IMAGE_STYLES:
        return wanted, ""
    from core import image_input
    if image_input.is_2d_image(image):
        return "toon", "Rilevato disegno 2D: applico la modalità Toon per una resa migliore. "
    return "blueprint", ""


def _image_to_3d(params: dict, image_path: str, image_url: str, player) -> str:
    """Image-to-3D: TripoSR on the user's picture, skipping SD-Turbo. Local engine only."""
    import shutil
    import tempfile
    from pathlib import Path

    from core import image_input, local_3d_gen
    engine = str(params.get("engine") or "").lower()
    if engine == "tripo":
        return "Invalid request: image-to-3D runs only on the local generator (engine 'local' or 'auto')."
    if not local_3d_gen.is_installed():
        return "3D generation failed (local engine): " + local_3d_gen.SETUP_MESSAGE
    work = Path(tempfile.mkdtemp(prefix="jarvis_img3d_"))
    try:
        try:
            image = image_input.prepare_image(image_path or None, image_url or None, work)
        except ValueError as exc:
            return f"Invalid request: {exc}"
        label = str(params.get("prompt") or "").strip() or image_input.label_for(image_path, image_url)
        style, note = _image_style(params, image)
        try:
            label = model_gen.clean_prompt(label)
            backend = local_3d_gen.configured_backend()
            _set_generation_status(player, "SF3D" if backend == "sf3d" else "TripoSR")
            path = local_3d_gen.generate_local(
                label, image=image, **_generation_callbacks(player)
            )
        except RuntimeError as exc:
            return f"3D generation failed (local engine): {exc}"
        except Exception as exc:
            return f"3D generation failed (local engine): {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return _show_local(player, params, path, style, note)


TOOL = {
    "name": "generate_3d_model",
    "description": (
        "Creates a 3D model from a text description (default: local TripoSR GPU generator; optional Tripo3D "
        "API with credits; balance is checked before generation and an unavailable/credit-exhausted API "
        "automatically falls back to the local generator) and shows it as a hologram in the central display. Use when "
        "the user asks to create, build or show something in 3D, e.g. 'make a hologram "
        "of a jet engine'. Also turns a picture into a hologram (image_path for a local file, "
        "image_url for a web image): faster, no text-to-image step. Afterwards viewer_3d can explode_model, "
        "highlight_part or clear_model. Call this directly for one explicit model request; it is tracked as a "
        "single task without a second confirmation. Use task_runner_start for multi-step plans, where write steps "
        "pause for confirmation. "
        "To ADD an object to a scene that is already shown (e.g. 'carica il PC e aggiungi una mela') "
        "pass model_id and a small scale (0.1-0.3): the old models stay, the new one is placed next to them and "
        "takes the scene's current style (style is optional and, if given, restyles the whole scene)."
    ),
    "risk_class": "write",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "What to create, ideally in English (the image models understand it best), e.g. 'a wooden chair'. Max 300 characters. With image_path/image_url it is optional (just a name for the model)."},
            "image_path": {"type": "STRING", "description": "Image-to-3D: path of a local picture (png/jpg/webp) to turn into a 3D hologram, skipping the text-to-image step (faster). Local generator only."},
            "image_url": {"type": "STRING", "description": "Image-to-3D: direct http(s) link to a picture (e.g. an image found with web search) to turn into a 3D hologram. Use instead of image_path for web images."},
            "style": {"type": "STRING", "enum": ["blueprint", "realistic", "toon", "flat"], "description": "Omit it when adding to a scene (the new model inherits the scene style; an explicit style restyles the whole scene). Image-to-3D standalone: 2D drawings (anime, logos, comics) are detected automatically and shown in toon, photos in blueprint."},
            "model_id": {"type": "STRING", "description": "Add the generated model to the CURRENT scene instead of replacing it: it is placed next to the existing models on the floor. Use e.g. 'mela' when the user asks to add an object to a scene."},
            "scale": {"type": "NUMBER", "description": "Size relative to the default (1). Use 0.1-0.3 for small objects (apple, cup, phone) added next to big ones such as the PC. Setting it also adds the model to the scene (an id is made up if model_id is missing)."},
            "show": {"type": "BOOLEAN", "description": "Show it right away (default true)."},
            "engine": {
                "type": "STRING",
                "enum": ["auto", "local", "tripo"],
                "description": (
                    "Selects a preferred generator for this call only. 'local' uses the free GPU backend; "
                    "'tripo' prefers the paid API but automatically falls back to local if unavailable or "
                    "out of credits; omit to use the configured default. SF3D can be selected with "
                    "JARVIS_3D_BACKEND=sf3d."
                ),
            },
        },
        "required": [],
    },
    "handler": generate_3d_model,
}
