"""Text-to-3D generation (Tripo3D) into the viewer's models folder. No Qt imports.

The SDK (tripo3d>=1.0, apiv3) is optional, like faster-whisper. The API key lives in
the SecretStore under ``tripo_api_key`` (or the TRIPO_API_KEY environment variable).
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from core.viewer3d import MAX_MODEL_BYTES, MODELS_DIR

SECRET_NAME = "tripo_api_key"
MAX_PROMPT = 300
DEFAULT_TIMEOUT = 300.0

SDK_MISSING_MESSAGE = (
    "3D generation needs the Tripo SDK: install it with "
    "'pip install \"tripo3d>=1.0.0,<2.0.0\"' (see requirements-optional.txt)."
)
KEY_MISSING_MESSAGE = (
    "No Tripo API key configured. Store it with "
    "'python -m core.registry_cli set-tripo-key' (hidden prompt)."
)


BACKENDS = ("auto", "local", "tripo")
BACKEND_ENV = "JARVIS_3D_BACKEND"
CONFIG_NAME = "model_gen.json"
TRIPO_PREFLIGHT_TIMEOUT = 4.0

_LOG = logging.getLogger(__name__)


def _config_path(config_dir: Path | None) -> Path:
    base = Path(config_dir) if config_dir else Path(__file__).resolve().parent.parent / "config"
    return base / CONFIG_NAME


def backend(config_dir: Path | None = None) -> str:
    """Return the configured engine; local is the default, auto prefers keyed Tripo."""
    value = os.environ.get(BACKEND_ENV, "").strip().lower()
    if value in ("sf3d", "triposr"):
        return "local"
    if value not in BACKENDS:
        try:
            value = str(json.loads(_config_path(config_dir).read_text(encoding="utf-8")).get("backend", ""))
        except (OSError, ValueError, AttributeError):
            value = ""
    return value if value in BACKENDS else "local"


def set_backend(value: str, config_dir: Path | None = None) -> str:
    if value not in BACKENDS:
        raise ValueError(f"backend must be one of {', '.join(BACKENDS)}")
    path = _config_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"backend": value}), encoding="utf-8")
    return value


def tripo_available() -> bool:
    return importlib.util.find_spec("tripo3d") is not None


async def _read_tripo_balance(key: str):
    import tripo3d

    async with tripo3d.TripoClient(api_key=key) as client:
        get_balance = getattr(client, "get_balance", None)
        if not callable(get_balance):
            return None
        return await get_balance()


def is_backend_available(backend: str) -> tuple[bool, str]:
    """Check backend prerequisites; the Tripo balance read never creates a task."""
    name = str(backend or "").strip().lower()
    if name == "tripo":
        key = tripo_key()
        if not key:
            return False, "no key"
        if not tripo_available():
            return False, "Tripo SDK unavailable"
        try:
            balance = asyncio.run(
                asyncio.wait_for(_read_tripo_balance(key), timeout=TRIPO_PREFLIGHT_TIMEOUT)
            )
        except AttributeError:
            return True, "unverified: balance check unsupported by installed Tripo SDK"
        except (asyncio.TimeoutError, TimeoutError):
            return False, "Tripo balance check timed out"
        except Exception as exc:
            _LOG.info("Tripo balance preflight failed (%s)", type(exc).__name__)
            return False, f"Tripo balance check failed ({type(exc).__name__})"
        if balance is None:
            return True, "unverified: balance check unsupported by installed Tripo SDK"
        try:
            available_balance = float(balance.balance)
        except (AttributeError, TypeError, ValueError):
            return True, "unverified: Tripo balance response was not interpretable"
        if available_balance <= 0:
            return False, "no credits"
        return True, "available"

    if name == "local":
        from core import local_3d_gen, local_3d_worker

        try:
            if not local_3d_gen.is_installed():
                return False, local_3d_gen.SETUP_MESSAGE
            missing = local_3d_worker._missing_modules()
            if missing:
                return False, "Local 3D generation is missing: " + ", ".join(missing)
            if local_3d_gen.configured_backend() == "sf3d" and not local_3d_worker.sf3d_ready():
                return False, "Stable Fast 3D is not installed or its extensions are unavailable"
        except Exception as exc:
            _LOG.info("Local backend preflight failed (%s)", type(exc).__name__)
            return False, f"Local backend check failed ({type(exc).__name__})"
        return True, "available"

    return False, "backend must be one of: tripo, local"


def is_credit_error(error: BaseException) -> bool:
    """Identify provider errors that specifically indicate exhausted/insufficient credits."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "insufficient credit",
            "not enough credit",
            "no credits",
            "insufficient balance",
            "balance not enough",
            "quota exceeded",
            "quota exhausted",
            "payment required",
            "http 402",
            "status_code=402",
        )
    )


def tripo_key(config_dir: Path | None = None, store=None) -> str:
    """The Tripo key, or "" when none is configured. Never raises."""
    try:
        if store is None:
            from core.secret_store import SecretStore
            base = Path(config_dir) if config_dir else Path(__file__).resolve().parent.parent / "config"
            store = SecretStore(base / "secrets.json")
        value = store.get(SECRET_NAME)
    except Exception:
        value = None
    return value or os.environ.get("TRIPO_API_KEY", "")


def clean_prompt(prompt) -> str:
    text = " ".join(str(prompt or "").split())
    if not text:
        raise ValueError("prompt is required")
    if len(text) > MAX_PROMPT:
        raise ValueError(f"prompt is too long (max {MAX_PROMPT} characters)")
    return text


def model_name(prompt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40] or "model"
    return f"{slug}-{hashlib.sha1(prompt.encode()).hexdigest()[:6]}.glb"


def _is_success(task) -> bool:
    return str(getattr(task.status, "value", task.status)).lower() == "success"


async def _generate(prompt, key, models_dir, client_factory, timeout) -> Path:
    tmp = models_dir / f".tmp-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True)
    try:
        async with client_factory(key) as client:
            task_id = await client.text_to_model(prompt=prompt)
            task = await client.wait_for_task(task_id, timeout=timeout)
            if not _is_success(task):
                detail = getattr(task, "error_msg", "") or getattr(task, "status", "unknown")
                raise RuntimeError(f"Tripo generation failed: {detail}")
            files = await client.download_task_models(task, str(tmp))
        source = files.get("model") or files.get("pbr_model")
        if not source or not Path(source).is_file():
            raise RuntimeError("Tripo returned no model file")
        source = Path(source)
        if source.stat().st_size > MAX_MODEL_BYTES:
            raise RuntimeError("generated model is too large")
        with source.open("rb") as handle:
            if handle.read(4) != b"glTF":
                raise RuntimeError("generated file is not a valid .glb")
        target = models_dir / model_name(prompt)
        shutil.move(str(source), target)
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def generate_model(prompt, key: str, models_dir: Path | None = None,
                   client_factory=None, timeout: float = DEFAULT_TIMEOUT) -> Path:
    """Blocking: run in a worker thread. Returns the saved .glb path."""
    prompt = clean_prompt(prompt)
    models_dir = Path(models_dir or MODELS_DIR)
    models_dir.mkdir(parents=True, exist_ok=True)
    if client_factory is None:
        import tripo3d
        client_factory = lambda k: tripo3d.TripoClient(api_key=k)  # noqa: E731
    try:
        return asyncio.run(_generate(prompt, key, models_dir, client_factory, timeout))
    except (asyncio.TimeoutError, TimeoutError):
        raise RuntimeError("Tripo generation timed out") from None
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Tripo request failed: {type(exc).__name__}: {exc}") from None
