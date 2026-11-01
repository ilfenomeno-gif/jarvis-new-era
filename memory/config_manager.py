import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"
VOICE_SETTINGS_FILE = CONFIG_DIR / "voice_settings.json"
PAGE_READER_ENGINES = {"system", "kokoro"}
PAGE_READER_SPEEDS = {0.75, 1.0, 1.25, 1.5}

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Assistant voice ──────────────────────────────────────────────────────────
# Gemini Live prebuilt voices. Names are proper nouns — identical in every
# language, so this list is safe to show verbatim in any locale.
AVAILABLE_VOICES = ["Charon", "Puck", "Kore", "Fenrir", "Aoede"]
DEFAULT_VOICE    = "Charon"


def get_voice() -> str:
    """Return the configured Live voice, falling back to the default if unset
    or if the stored value is not a voice we recognise."""
    v = load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE
    return v if v in AVAILABLE_VOICES else DEFAULT_VOICE


def get_page_reader_engine() -> str:
    """Return the local page-reader backend, defaulting to the system voice."""
    if not VOICE_SETTINGS_FILE.exists():
        return "system"
    try:
        data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("voice settings must contain a JSON object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"❌ Failed to load voice_settings.json: {exc}")
        return "system"

    engine = data.get("page_reader_engine", "system")
    if not isinstance(engine, str) or engine not in PAGE_READER_ENGINES:
        print(f"❌ Unsupported page reader engine in voice settings: {engine!r}")
        return "system"
    return engine


def save_page_reader_engine(engine: str) -> None:
    """Persist a validated local page-reader backend without touching API keys."""
    if not isinstance(engine, str) or engine not in PAGE_READER_ENGINES:
        raise ValueError(f"Unsupported page reader engine: {engine!r}")
    ensure_config_dir()
    data: dict = {}
    if VOICE_SETTINGS_FILE.exists():
        try:
            data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot update voice settings: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Cannot update voice settings: expected a JSON object")
    data["page_reader_engine"] = engine
    VOICE_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_page_reader_speed() -> float:
    """Return a validated local reader speed, defaulting to normal pace."""
    if not VOICE_SETTINGS_FILE.exists():
        return 1.0
    try:
        data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("voice settings must contain a JSON object")
        raw_speed = data.get("page_reader_speed", 1.0)
        if isinstance(raw_speed, bool):
            raise ValueError("page reader speed must be numeric")
        speed = float(raw_speed)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"❌ Failed to load page reader speed: {exc}")
        return 1.0
    if speed not in PAGE_READER_SPEEDS:
        print(f"❌ Unsupported page reader speed: {speed!r}")
        return 1.0
    return speed


def save_page_reader_speed(speed: float) -> None:
    """Persist a supported page-reader speed without touching API keys."""
    if isinstance(speed, bool):
        raise ValueError("Page reader speed must be numeric")
    try:
        value = float(speed)
    except (TypeError, ValueError) as exc:
        raise ValueError("Page reader speed must be numeric") from exc
    if value not in PAGE_READER_SPEEDS:
        raise ValueError(f"Unsupported page reader speed: {speed!r}")
    ensure_config_dir()
    data: dict = {}
    if VOICE_SETTINGS_FILE.exists():
        try:
            data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot update voice settings: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Cannot update voice settings: expected a JSON object")
    data["page_reader_speed"] = value
    VOICE_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_wake_word_enabled() -> bool:
    """Return the explicit local wake-word opt-in; disabled by default."""
    if not VOICE_SETTINGS_FILE.exists():
        return False
    try:
        data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("voice settings must contain a JSON object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"❌ Failed to load voice_settings.json: {exc}")
        return False

    enabled = data.get("wake_word_enabled", False)
    if not isinstance(enabled, bool):
        print("❌ Invalid wake_word_enabled setting; wake word remains disabled")
        return False
    return enabled


def save_wake_word_enabled(enabled: bool) -> None:
    """Persist explicit wake-word consent without touching API keys."""
    if not isinstance(enabled, bool):
        raise ValueError("wake_word_enabled must be a boolean")
    ensure_config_dir()
    data: dict = {}
    if VOICE_SETTINGS_FILE.exists():
        try:
            data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot update voice settings: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Cannot update voice settings: expected a JSON object")
    data["wake_word_enabled"] = enabled
    VOICE_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_full_duplex_enabled() -> bool:
    """Return the experimental voice-interruption opt-in; disabled by default."""
    if not VOICE_SETTINGS_FILE.exists():
        return False
    try:
        data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("voice settings must contain a JSON object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"❌ Failed to load voice settings: {exc}")
        return False

    enabled = data.get("full_duplex_enabled", False)
    if not isinstance(enabled, bool):
        print("❌ Invalid full_duplex_enabled setting; full-duplex remains disabled")
        return False
    return enabled


def save_full_duplex_enabled(enabled: bool) -> None:
    """Persist the opt-in locally without touching API keys."""
    if not isinstance(enabled, bool):
        raise ValueError("full_duplex_enabled must be a boolean")
    ensure_config_dir()
    data: dict = {}
    if VOICE_SETTINGS_FILE.exists():
        try:
            data = json.loads(VOICE_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot update voice settings: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Cannot update voice settings: expected a JSON object")
    data["full_duplex_enabled"] = enabled
    VOICE_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice. Unknown names collapse to the default so a
    bad value can never reach the API and break the session."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    v = (voice_name or "").strip()
    data["voice_name"] = v if v in AVAILABLE_VOICES else DEFAULT_VOICE
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["morning_brief_enabled"] = enabled
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, and there is one place where a corrupt config file is
    handled instead of nine."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


# ── Per-plugin settings ("tokens" / connection details) ───────────────────────
# Generic store so a plugin can declare its own config fields (PLUGIN_SETTINGS)
# and the settings UI renders + persists them WITHOUT any core edit — keeping the
# drop-in model intact. Values live under plugin_config[<namespace>][<key>].
# A namespace defaults to the plugin name, but a suite of plugins (e.g. the
# several printer plugins) can share ONE namespace.
def get_plugin_config(namespace: str) -> dict:
    """All stored values for a namespace (empty dict if none set yet)."""
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    """A single value from a namespace, or `default` if unset."""
    return get_plugin_config(namespace).get(key, default)


def save_plugin_config(namespace: str, values: dict) -> None:
    """Merge `values` into a namespace's stored config (read-modify-write, like
    every other helper here). Only the provided keys are touched."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Providers: local STT/LLM/TTS and non-Gemini APIs ─────────────────────────
# Stored here rather than in a file of their own, for the same reason plugin
# settings are: one config to back up, one already in .gitignore, one place a
# user knows to look.
#
# The important property is what happens when nobody has configured anything.
# `get_provider_mode()` returns "gemini" on a config that has never heard of
# providers, and every caller checks that BEFORE importing the providers
# package — so an ordinary install never executes a line of it. This is the
# whole basis of the claim that the folder costs nothing when unused.
PROVIDER_MODE_GEMINI = "gemini"      # the conversation runs on the Live API
PROVIDER_MODE_PIPELINE = "pipeline"  # STT -> LLM -> TTS, assembled from providers


def get_providers() -> dict:
    """The whole providers block, or an empty dict."""
    val = load_api_keys().get("providers")
    return dict(val) if isinstance(val, dict) else {}


def get_provider_mode() -> str:
    """Which engine holds the conversation. Defaults to Gemini Live."""
    mode = str(get_providers().get("mode", "") or "").strip().lower()
    return mode if mode in (PROVIDER_MODE_GEMINI, PROVIDER_MODE_PIPELINE) \
        else PROVIDER_MODE_GEMINI


def get_provider_config(provider_id: str) -> dict:
    """Stored settings for one provider — address, model, key, limits."""
    creds = get_providers().get("creds")
    val = creds.get(provider_id) if isinstance(creds, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_pipeline() -> dict:
    """Which provider fills each slot of the pipeline engine."""
    val = get_providers().get("pipeline")
    return dict(val) if isinstance(val, dict) else {}


def get_sidecar_provider() -> str:
    """The provider id used for one-shot calls when Gemini cannot answer them,
    or '' for none.

    Separate from the conversation on purpose: these are different jobs with
    different failure modes. Gemini's Live quota and its text quota are separate
    pools, and on the free tier it is the text pool that runs out first — which
    kills document reading, screen reasoning and code generation while the
    conversation carries on. Being able to point only those at another model,
    without changing the voice at all, is the cheapest useful thing this whole
    folder does.
    """
    return str(get_providers().get("sidecar", "") or "").strip()


def _patch_providers(**fields) -> None:
    p = get_providers()
    p.update(fields)
    _patch_config(providers=p)


def save_provider_mode(mode: str) -> None:
    mode = (mode or "").strip().lower()
    _patch_providers(mode=mode if mode in (PROVIDER_MODE_GEMINI,
                                           PROVIDER_MODE_PIPELINE)
                     else PROVIDER_MODE_GEMINI)


def save_provider_config(provider_id: str, values: dict) -> None:
    """Merge settings for one provider. Only the given keys are touched, so the
    panel can save one field without reading and rewriting the rest."""
    p = get_providers()
    creds = p.get("creds")
    if not isinstance(creds, dict):
        creds = {}
    cur = creds.get(provider_id)
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    creds[provider_id] = cur
    p["creds"] = creds
    _patch_config(providers=p)


def save_pipeline(stt: str = None, llm: str = None, tts: str = None) -> None:
    """Set one or more pipeline slots. `None` leaves a slot alone; '' clears it."""
    p = get_providers()
    pipe = p.get("pipeline")
    pipe = dict(pipe) if isinstance(pipe, dict) else {}
    for slot, value in (("stt", stt), ("llm", llm), ("tts", tts)):
        if value is not None:
            pipe[slot] = str(value).strip()
    p["pipeline"] = pipe
    _patch_config(providers=p)


def save_sidecar_provider(provider_id: str) -> None:
    _patch_providers(sidecar=(provider_id or "").strip())


def get_sidecar_first() -> bool:
    """Whether the side-call provider is tried BEFORE Gemini rather than after.

    Off by default: measured in core/gemini.py, the Gemini rungs answer a short
    request in well under a second, and a local model on ordinary hardware does
    not. On means something specific — 'I would rather this stayed on my
    machine, and I accept it being slower' — so it is a choice someone makes,
    never a default they inherit.
    """
    return bool(get_providers().get("sidecar_first", False))


def save_sidecar_first(enabled: bool) -> None:
    _patch_providers(sidecar_first=bool(enabled))


def save_providers(mode: str = None, pipeline: dict = None, creds: dict = None,
                   sidecar: str = None, sidecar_first: bool = None) -> None:
    """Write the whole providers block in ONE file write.

    The settings panel used to call five setters in a row — one per provider's
    credentials, then the mode, then the pipeline, then the two side-call
    keys — and every one of them was a separate read-modify-write of
    api_keys.json. Five reads and five writes of the same file, in sequence,
    while the panel's own APPLY was already triggering a reconnect that makes
    main.py write to it too. Any interleaving loses whichever key was written
    first, and the one people noticed was the mode: set MY OWN SETUP, save,
    reopen, and it says Gemini again.

    `None` leaves a section alone; `creds` is merged per provider so a panel
    that only edited one does not have to send the others.
    """
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    block = data.get("providers")
    block = dict(block) if isinstance(block, dict) else {}

    if mode is not None:
        m = str(mode).strip().lower()
        block["mode"] = m if m in (PROVIDER_MODE_GEMINI,
                                   PROVIDER_MODE_PIPELINE) else PROVIDER_MODE_GEMINI
    if pipeline is not None:
        current = block.get("pipeline")
        current = dict(current) if isinstance(current, dict) else {}
        current.update({k: str(v or "").strip() for k, v in pipeline.items()})
        block["pipeline"] = current
    if creds is not None:
        store = block.get("creds")
        store = dict(store) if isinstance(store, dict) else {}
        for pid, values in (creds or {}).items():
            one = store.get(pid)
            one = dict(one) if isinstance(one, dict) else {}
            one.update(values or {})
            store[pid] = one
        block["creds"] = store
    if sidecar is not None:
        block["sidecar"] = str(sidecar or "").strip()
    if sidecar_first is not None:
        block["sidecar_first"] = bool(sidecar_first)

    data["providers"] = block
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")