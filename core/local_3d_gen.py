"""Local text-to-3D (SD-Turbo -> TripoSR), no external API. No torch import here.

The heavy work runs in a subprocess (core/local_3d_worker.py): VRAM is released when it
exits, a crash cannot take JARVIS down, and out-of-memory becomes a clear message.
TripoSR is image-to-3D only, so the prompt is first turned into a picture.
Setup: see requirements-3d.txt and ``python -m core.local_3d_gen setup``.
Backend fallback categories and per-stage timings are recorded in
``logs/local_3d_gen.log`` without storing prompts or credentials.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.model_gen import clean_prompt, model_name
from core.viewer3d import MAX_MODEL_BYTES, MODELS_DIR

BASE = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE / "cache" / "3d"
CACHE_PIPELINE_VERSION = "1"
DEFAULT_CACHE_TTL_DAYS = 30
DEFAULT_CACHE_MAX_GB = 5
TRIPOSR_DIR = Path(os.environ.get("TRIPOSR_DIR") or BASE / "third_party" / "TripoSR")
TRIPOSR_REPO = "https://github.com/VAST-AI-Research/TripoSR.git"
SF3D_DIR = Path(os.environ.get("SF3D_DIR") or BASE / "third_party" / "stable-fast-3d")
SF3D_REPO = "https://github.com/Stability-AI/stable-fast-3d.git"
MIN_VRAM_GB = 6.0
DEFAULT_TIMEOUT = 1800.0
RESULT_PREFIX = "JARVIS_RESULT "
_LOG_PATH = BASE / "logs" / "local_3d_gen.log"
_LOG_LOCK = threading.Lock()
_LOGGER = logging.getLogger("jarvis.local_3d_gen")
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False

SETUP_MESSAGE = (
    "Local 3D generation is not installed. Run 'python -m core.local_3d_gen setup', then "
    "'pip install -r requirements-3d.txt' (see the file for the CUDA build of torch)."
)
SF3D_SLOW_AFTER_SECONDS = 180
OOM_MESSAGE = (
    "The GPU ran out of memory. Close other GPU programs (games, video editors, browsers "
    "with hardware acceleration) and retry, or use the Tripo backend."
)


def _log_event(event: str, **fields) -> None:
    with _LOG_LOCK:
        path = str(_LOG_PATH.resolve())
        handler = next(
            (
                item for item in _LOGGER.handlers
                if getattr(item, "_jarvis_3d_log", False)
                and item.baseFilename == path
            ),
            None,
        )
        for item in tuple(_LOGGER.handlers):
            if getattr(item, "_jarvis_3d_log", False) and item is not handler:
                _LOGGER.removeHandler(item)
                item.close()
        if handler is None:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                _LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
            handler._jarvis_3d_log = True
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            _LOGGER.addHandler(handler)
        _LOGGER.info("%s", json.dumps({"event": event, **fields}, sort_keys=True))


def _failure_category(text: str) -> str:
    lowered = text.lower()
    if "out of memory" in lowered or "cuda oom" in lowered:
        return "oom"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if any(term in lowered for term in ("401", "403", "gated", "unauthorized", "token")):
        return "model_access"
    return "other"


def _captured_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _log_worker_diagnostics(stdout: str) -> None:
    for line in (stdout or "").splitlines():
        if line.startswith("TIMING "):
            try:
                item = json.loads(line[len("TIMING "):])
                stage, seconds = item.get("stage"), item.get("seconds")
                if isinstance(stage, str) and isinstance(seconds, (int, float)):
                    _log_event("stage_complete", stage=stage[:60], seconds=round(seconds, 2))
            except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                _log_event("invalid_worker_timing")
        elif line.startswith("BACKEND_FALLBACK "):
            try:
                item = json.loads(line[len("BACKEND_FALLBACK "):])
                reason = str(item.get("reason") or "")
                _log_event(
                    "backend_fallback",
                    source=str(item.get("from") or "")[:30],
                    target=str(item.get("to") or "")[:30],
                    error_type=reason.split(":", 1)[0][:80],
                    category=_failure_category(reason),
                )
            except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                _log_event("invalid_worker_fallback")
        elif line.startswith("HALF_FALLBACK "):
            _log_event(
                "precision_fallback",
                category=_failure_category(line[len("HALF_FALLBACK "):]),
            )


def python_exe() -> str:
    exe = os.environ.get("JARVIS_3D_PYTHON") or sys.executable
    path = Path(exe)
    if path.name.lower() == "pythonw.exe":  # pythonw has no stdout to read the result from
        sibling = path.with_name("python.exe")
        if sibling.exists():
            return str(sibling)
    return exe


def is_installed() -> bool:
    """Cheap check (no torch import): torch present and the TripoSR sources cloned."""
    return importlib.util.find_spec("torch") is not None and (TRIPOSR_DIR / "tsr").is_dir()


HF_SECRET_NAME = "hf_token"


def hf_token(config_dir: Path | None = None, store=None) -> str:
    """Hugging Face token: SecretStore first, then HF_TOKEN / HUGGING_FACE_HUB_TOKEN. Never raises."""
    try:
        if store is None:
            from core.secret_store import SecretStore
            base = Path(config_dir) if config_dir else BASE / "config"
            store = SecretStore(base / "secrets.json")
        value = store.get(HF_SECRET_NAME)
    except Exception:
        value = None
    return value or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or ""


def _run(cmd: list[str], timeout: float):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = _worker_env()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=flags, cwd=str(BASE), env=env)
    return proc.returncode, proc.stdout, proc.stderr


def _worker_env(backend_override: str | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "TRIPOSR_DIR": str(TRIPOSR_DIR),
        "SF3D_DIR": str(SF3D_DIR),
    }
    token = hf_token()
    if token:
        env["HF_TOKEN"] = token
    if backend_override:
        env["JARVIS_3D_BACKEND"] = backend_override
    return env


def configured_backend() -> str:
    """Return the local worker backend, defaulting safely to TripoSR."""
    return "sf3d" if os.environ.get("JARVIS_3D_BACKEND", "").strip().lower() == "sf3d" else "triposr"


def _stop_worker(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


def _run_monitored(cmd: list[str], timeout: float, backend_name: str,
                   progress_callback=None, fallback_callback=None):
    """Run the worker while reporting elapsed time and optionally restarting on SF3D timeout."""
    started = time.monotonic()
    deadline = started + timeout
    selected_backend = backend_name
    prompted = False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = None
    try:
        while True:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", creationflags=flags,
                cwd=str(BASE), env=_worker_env(selected_backend),
            )
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_worker(proc)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                try:
                    stdout, stderr = proc.communicate(timeout=min(1.0, remaining))
                    return proc.returncode, stdout, stderr
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - started
                    if callable(progress_callback):
                        progress_callback(int(elapsed))
                    if (
                        selected_backend == "sf3d"
                        and elapsed >= SF3D_SLOW_AFTER_SECONDS
                        and not prompted
                    ):
                        prompted = True
                        _log_event("sf3d_slow", elapsed_seconds=round(elapsed, 2))
                        use_triposr = bool(fallback_callback()) if callable(fallback_callback) else False
                        if use_triposr:
                            _stop_worker(proc)
                            if "--out" in cmd:
                                Path(cmd[cmd.index("--out") + 1]).unlink(missing_ok=True)
                            _log_event(
                                "backend_fallback",
                                source="sf3d",
                                target="triposr",
                                category="timeout",
                                reason="user_confirmed",
                            )
                            selected_backend = "triposr"
                            break
    finally:
        if proc is not None and proc.poll() is None:
            _stop_worker(proc)


def _parse_result(stdout: str) -> dict | None:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                return json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                return None
    return None


def probe(runner=None, timeout: float = 180.0) -> dict:
    """Hardware/dependency report from the worker: {torch, cuda, gpu, vram_gb, missing}."""
    runner = runner or _run
    try:
        code, out, err = runner([python_exe(), "-m", "core.local_3d_worker", "--probe"], timeout)
    except Exception as exc:
        return {"torch": False, "cuda": False, "missing": [f"probe failed: {type(exc).__name__}"]}
    result = _parse_result(out)
    if result is None:
        return {"torch": False, "cuda": False, "missing": ["torch"]}
    return result


def readiness_problem(info: dict) -> str | None:
    """A user-facing reason why local generation cannot run, or None when it can."""
    if not info.get("torch"):
        return SETUP_MESSAGE
    if info.get("missing"):
        return "Local 3D generation is missing: " + ", ".join(info["missing"]) + ". " + SETUP_MESSAGE
    if not info.get("cuda"):
        return ("No CUDA GPU found: local 3D generation on CPU would take far too long. "
                "Install the CUDA build of torch (requirements-3d.txt) or use the Tripo backend.")
    vram = float(info.get("vram_gb") or 0)
    if vram < MIN_VRAM_GB:
        return (f"The GPU ({info.get('gpu', '?')}) has {vram:.1f} GB of VRAM; TripoSR needs about "
                f"{MIN_VRAM_GB:.0f} GB. Use the Tripo backend instead.")
    return None


def _cache_enabled() -> bool:
    return os.environ.get("JARVIS_3D_CACHE", "1").strip() != "0"


def _cache_policy() -> tuple[float, int]:
    try:
        ttl_days = float(os.environ.get("JARVIS_3D_CACHE_TTL_DAYS", DEFAULT_CACHE_TTL_DAYS))
        max_gb = float(os.environ.get("JARVIS_3D_CACHE_MAX_GB", DEFAULT_CACHE_MAX_GB))
    except ValueError as exc:
        raise ValueError("JARVIS_3D_CACHE_TTL_DAYS and JARVIS_3D_CACHE_MAX_GB must be numbers") from exc
    if not math.isfinite(ttl_days) or not math.isfinite(max_gb) or ttl_days < 0 or max_gb < 0:
        raise ValueError("3D cache TTL and maximum size must be finite non-negative numbers")
    try:
        max_bytes = int(max_gb * 1024**3)
    except OverflowError as exc:
        raise ValueError("JARVIS_3D_CACHE_MAX_GB is too large") from exc
    return ttl_days, max_bytes


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cache_key(prompt: str, backend_name: str, image: Path | None = None) -> str:
    normalized_prompt = re.sub(r"\s+", " ", prompt.strip().lower())
    try:
        candidates = max(1, min(6, int(os.environ.get("JARVIS_3D_CANDIDATES", "3"))))
    except ValueError:
        candidates = 3
    parameters = {
        "pipeline": CACHE_PIPELINE_VERSION,
        "text2img_model": os.environ.get("JARVIS_3D_TEXT2IMG", "stabilityai/sd-turbo"),
        "backend": backend_name,
        "half_precision": os.environ.get("JARVIS_3D_HALF", "1") != "0",
        "candidates": candidates,
        "triposr_model": os.environ.get("JARVIS_3D_TRIPOSR", "stabilityai/TripoSR"),
    }
    if backend_name == "sf3d":
        parameters.update(
            sf3d_model=os.environ.get("JARVIS_3D_SF3D", "stabilityai/stable-fast-3d"),
            texture_resolution=os.environ.get("JARVIS_3D_TEXTURE", "512"),
        )
    if image is not None:
        parameters["image_sha256"] = _sha256_file(Path(image))
    payload = json.dumps(
        {"prompt": normalized_prompt, "parameters": parameters},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_paths(key: str) -> tuple[Path, Path]:
    return CACHE_DIR / f"{key}.glb", CACHE_DIR / f"{key}.json"


def _remove_cache_entry(key: str) -> None:
    for path in _cache_paths(key):
        path.unlink(missing_ok=True)


def _read_cache_metadata(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _valid_glb(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if not path.is_file() or size <= 0 or size > MAX_MODEL_BYTES:
            return False
        with path.open("rb") as handle:
            return handle.read(4) == b"glTF"
    except OSError:
        return False


def _cache_lookup(key: str, models_dir: Path) -> Path | None:
    glb_path, metadata_path = _cache_paths(key)
    if not glb_path.exists() and not metadata_path.exists():
        return None
    ttl_days, _ = _cache_policy()
    metadata = _read_cache_metadata(metadata_path)
    if metadata is None or metadata.get("key") != key or not _valid_glb(glb_path):
        _remove_cache_entry(key)
        _log_event("cache_invalidated", reason="invalid_entry")
        return None
    try:
        created_at = datetime.fromisoformat(str(metadata["created_at"]))
        if ttl_days and datetime.now(timezone.utc) - created_at > timedelta(days=ttl_days):
            _remove_cache_entry(key)
            _log_event("cache_invalidated", reason="expired")
            return None
        if metadata.get("sha256") != _sha256_file(glb_path):
            _remove_cache_entry(key)
            _log_event("cache_invalidated", reason="checksum_mismatch")
            return None
        cached_name = str(metadata["model_name"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,100}\.glb", cached_name):
            _remove_cache_entry(key)
            _log_event("cache_invalidated", reason="invalid_model_name")
            return None
    except (KeyError, TypeError, ValueError, OSError) as exc:
        _remove_cache_entry(key)
        _log_event("cache_invalidated", reason=f"invalid_metadata_{type(exc).__name__}")
        return None

    target = models_dir / cached_name
    if not _valid_glb(target) or _sha256_file(target) != metadata["sha256"]:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(glb_path, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        if not _valid_glb(target) or _sha256_file(target) != metadata["sha256"]:
            target.unlink(missing_ok=True)
            return None
    metadata["last_accessed_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(metadata_path, metadata)
    _log_event(
        "cache_hit",
        backend=str(metadata.get("backend") or "unknown")[:30],
        output_bytes=glb_path.stat().st_size,
    )
    return target


def _write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _enforce_cache_limits(new_key: str) -> bool:
    ttl_days, max_bytes = _cache_policy()
    now = datetime.now(timezone.utc)
    entries = []
    for metadata_path in CACHE_DIR.glob("*.json"):
        key = metadata_path.stem
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            continue
        metadata = _read_cache_metadata(metadata_path)
        glb_path, _ = _cache_paths(key)
        try:
            created_at = datetime.fromisoformat(str(metadata["created_at"])) if metadata else None
        except (KeyError, TypeError, ValueError):
            created_at = None
        if metadata is None or created_at is None or not glb_path.is_file():
            _remove_cache_entry(key)
            continue
        if ttl_days and now - created_at > timedelta(days=ttl_days):
            _remove_cache_entry(key)
            continue
        entries.append((created_at, key, glb_path.stat().st_size + metadata_path.stat().st_size))
    for glb_path in CACHE_DIR.glob("*.glb"):
        if (
            re.fullmatch(r"[a-f0-9]{64}", glb_path.stem)
            and not glb_path.with_suffix(".json").is_file()
        ):
            glb_path.unlink(missing_ok=True)

    total = sum(size for _, _, size in entries)
    if not max_bytes:
        return True
    for _, key, size in sorted(entries):
        if total <= max_bytes:
            break
        if key == new_key:
            continue
        _remove_cache_entry(key)
        total -= size
    if total > max_bytes:
        _remove_cache_entry(new_key)
        return False
    return True


def _cache_store(
    key: str,
    source: Path,
    prompt: str,
    backend_name: str,
    model_filename: str,
) -> bool:
    if not _cache_enabled():
        return False
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ttl_days, max_bytes = _cache_policy()
    glb_path, metadata_path = _cache_paths(key)
    size = source.stat().st_size
    if max_bytes and size > max_bytes:
        _log_event("cache_write_skipped", reason="entry_exceeds_size_limit")
        return False
    temporary = CACHE_DIR / f".{key}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, glb_path)
        metadata = {
            "key": key,
            "prompt": prompt,
            "backend": backend_name,
            "model_name": model_filename,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_accessed_at": datetime.now(timezone.utc).isoformat(),
            "size_bytes": size,
            "sha256": _sha256_file(glb_path),
            "ttl_days_at_creation": ttl_days,
        }
        _write_json_atomic(metadata_path, metadata)
        if not _enforce_cache_limits(key):
            _log_event("cache_write_skipped", reason="cache_size_limit")
            return False
    except OSError:
        _remove_cache_entry(key)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return glb_path.is_file() and metadata_path.is_file()


def cache_entries() -> list[dict]:
    """Return cache metadata for the local CLI; prompts never enter application logs."""
    entries = []
    for metadata_path in sorted(CACHE_DIR.glob("*.json")):
        metadata = _read_cache_metadata(metadata_path)
        if metadata is None:
            raise ValueError(f"invalid 3D cache metadata: {metadata_path.name}")
        entries.append(metadata)
    return entries


def cache_size_bytes() -> int:
    if not CACHE_DIR.is_dir():
        return 0
    return sum(path.stat().st_size for path in CACHE_DIR.iterdir() if path.is_file())


def clear_cache(confirmed: bool = False) -> int:
    """Remove only cache-owned files after explicit confirmation."""
    if not confirmed:
        raise ValueError("clearing the 3D cache requires --yes")
    if not CACHE_DIR.is_dir():
        return 0
    removed = 0
    for path in CACHE_DIR.iterdir():
        if not path.is_file():
            continue
        owned_file = re.fullmatch(
            r"(?:[a-f0-9]{64}\.(?:glb|json)|"
            r"\.[a-f0-9]{64}\.[a-f0-9]{32}\.tmp|"
            r"\.[a-f0-9]{64}\.(?:glb|json)\.[a-f0-9]{32}\.tmp)",
            path.name,
        )
        if owned_file:
            path.unlink()
            removed += 1
    return removed


_GEN_LOCK = threading.Lock()


def generate_local(*args, **kwargs) -> Path:
    """One generation at a time (the GPU cannot hold two). The lock is always released, even on timeout/crash."""
    if not _GEN_LOCK.acquire(blocking=False):
        raise RuntimeError("Another 3D generation is still running; wait for it to finish.")
    try:
        return _generate_local(*args, **kwargs)
    finally:
        _GEN_LOCK.release()


def _generate_local(prompt, models_dir: Path | None = None, runner=None,
                    timeout: float = DEFAULT_TIMEOUT, image: Path | None = None,
                    progress_callback=None, fallback_callback=None) -> Path:
    """Blocking: run in a worker thread. Returns the saved .glb path.

    With ``image`` (a sanitised PNG from core.image_input) the SD-Turbo stage is skipped and
    TripoSR reconstructs the picture directly; ``prompt`` then only names the model file.
    """
    original_prompt = str(prompt or "")
    prompt = clean_prompt(prompt)
    models_dir = Path(models_dir or MODELS_DIR)
    models_dir.mkdir(parents=True, exist_ok=True)
    backend_name = configured_backend()
    cache_enabled = _cache_enabled()
    if cache_enabled:
        _cache_policy()
    cache_key = _cache_key(prompt, backend_name, image) if cache_enabled else ""
    if cache_key:
        try:
            cached_path = _cache_lookup(cache_key, models_dir)
            if cached_path is not None:
                return cached_path
        except OSError as exc:
            _log_event("cache_read_failed", error_type=type(exc).__name__)
    problem = readiness_problem(probe(runner))
    if problem:
        raise RuntimeError(problem)

    tmp = models_dir / f".tmp-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True)
    out_file = tmp / "model.glb"
    try:
        cmd = [python_exe(), "-m", "core.local_3d_worker", "--out", str(out_file)]
        cmd += ["--image", str(image)] if image else ["--prompt", prompt]
        started = time.monotonic()
        _log_event(
            "generation_started",
            backend=backend_name,
            timeout_seconds=timeout,
        )
        try:
            if runner is None:
                code, stdout, stderr = _run_monitored(
                    cmd, timeout, backend_name, progress_callback, fallback_callback
                )
            else:
                code, stdout, stderr = runner(cmd, timeout)
        except subprocess.TimeoutExpired as exc:
            _log_worker_diagnostics(_captured_text(exc.stdout))
            _log_event(
                "generation_failed",
                category="timeout",
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
            raise RuntimeError("Local 3D generation timed out (the first run downloads several GB "
                               "of models; retry once they are cached).") from None
        elapsed = round(time.monotonic() - started, 2)
        stdout = _captured_text(stdout)
        stderr = _captured_text(stderr)
        _log_worker_diagnostics(stdout)
        result = _parse_result(stdout)
        if result is None:
            combined_output = f"{stdout}\n{stderr}"
            _log_event(
                "generation_failed",
                category=_failure_category(combined_output),
                elapsed_seconds=elapsed,
                exit_code=code,
            )
            tail = " ".join(combined_output.strip().splitlines()[-2:])[:300]
            if _failure_category(combined_output) == "oom":
                raise RuntimeError(OOM_MESSAGE)
            raise RuntimeError(f"Local generator crashed (exit {code}): {tail or 'no output'}")
        if not result.get("ok"):
            failure_code = str(result.get("code") or "")
            failure_reason = " ".join(
                str(result.get(key) or "") for key in ("message", "code")
            )
            _log_event(
                "generation_failed",
                category=(
                    "oom"
                    if failure_code.lower() == "oom"
                    else _failure_category(failure_reason)
                ),
                elapsed_seconds=elapsed,
                exit_code=code,
                result_code=failure_code[:40] or "unknown",
            )
            if failure_code == "oom":
                raise RuntimeError(OOM_MESSAGE)
            raise RuntimeError(f"Local generation failed: {result.get('message', 'unknown error')}")
        if not out_file.is_file():
            raise RuntimeError("Local generator reported success but wrote no file")
        if out_file.stat().st_size > MAX_MODEL_BYTES:
            raise RuntimeError("generated model is too large")
        with out_file.open("rb") as handle:
            if handle.read(4) != b"glTF":
                raise RuntimeError("generated file is not a valid .glb")
        digest = hashlib.sha1(Path(image).read_bytes()).hexdigest() if image else ""
        target = models_dir / model_name(prompt + digest)
        shutil.move(str(out_file), target)
        if cache_key:
            try:
                _cache_store(
                    cache_key,
                    target,
                    original_prompt,
                    str(result.get("backend") or backend_name)[:30],
                    target.name,
                )
            except OSError as exc:
                _log_event("cache_write_failed", error_type=type(exc).__name__)
        _log_event(
            "generation_completed",
            backend=str(result.get("backend") or "unknown")[:30],
            elapsed_seconds=elapsed,
            output_bytes=target.stat().st_size,
        )
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _clone(repo: str, target: Path, marker: str, label: str) -> str:
    if (target / marker).is_dir():
        return f"{label} already present in {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["git", "clone", "--depth", "1", repo, str(target)], capture_output=True, text=True)
    if proc.returncode != 0:
        return f"{label}: git clone failed: " + (proc.stderr or "").strip()[-300:]
    return f"{label} cloned into {target}"


def setup() -> str:
    """Clone TripoSR (MIT) and Stable Fast 3D next to the code; torch etc. are pip-installed.

    SF3D is optional: its CUDA/C++ extensions (texture_baker, uv_unwrapper) must be built with MSVC
    (see requirements-3d.txt) and its weights are gated on Hugging Face. Without them the worker uses TripoSR.
    """
    return "\n".join([
        _clone(TRIPOSR_REPO, TRIPOSR_DIR, "tsr", "TripoSR"),
        _clone(SF3D_REPO, SF3D_DIR, "sf3d", "Stable Fast 3D"),
    ])

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "setup":
        print(setup())
    else:
        info = probe()
        print(json.dumps(info, indent=2))
        print(readiness_problem(info) or "Local 3D generation is ready.")
