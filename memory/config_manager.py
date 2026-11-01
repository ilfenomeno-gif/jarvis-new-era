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