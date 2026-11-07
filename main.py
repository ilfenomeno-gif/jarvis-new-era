import platform as _platform
import subprocess as _subprocess

# ── Console encoding ─────────────────────────────────────────────────────────
# Windows consoles default to a legacy codepage — cp1254 in Turkey, cp1251 in
# Russia, cp932 in Japan. Printing an emoji there raises UnicodeEncodeError, and
# several of these prints sit inside except handlers, so the handler itself dies
# and skips the recovery code after it. Reconfiguring to UTF-8 with a
# replacement fallback costs nothing and makes the app behave in every locale.
import sys as _sys

for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(_sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass          # pythonw / redirected pipes / anything exotic — never fatal

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **                       kw)

    _subprocess.Popen = _Popen

# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import collections
import logging
import os
import re
import threading
import time
import json
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, pop_last_session,
    search_memory, set_trim_notifier,
)

from actions.file_processor import file_processor
from actions.open_app          import open_app
from actions.app_launcher      import _canonical_app_name
from actions.computer_settings import computer_settings
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.youtube_video     import youtube_video
from actions.browser_control   import browser_control, read_active_page
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from agents.supervisor_agent   import supervisor_action
from agents.research_agent     import research_action
from agents.coder_agent        import coder_action
from agents.debugger_agent     import debugger_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from actions.web_search        import _news as _fetch_news_sync
from memory.config_manager     import (
    get_jarvis_voice, get_iris_voice,
    get_input_device, get_output_device,
)
from core.plugin_loader        import discover_plugins
from core.action_loader        import discover_actions
from core.hud_bridge           import HudBridge
from core.intent_router        import route_tool
from core.geo_router           import classify_and_route
from core.prompt_router        import PromptRouter
from core.tool_router          import ToolRouter
from core.brain_router         import get_router, ollama_tool_declarations
from core                      import undo as undo_stack
from core                      import confirm as confirm_gate
from core                      import audio_devices
from core                      import pattern_learner
from core.guardrails           import (
    install_subprocess_guards, require_policy_file, append_rule,
)
from core.accessibility        import (
    ACCESSIBILITY_HOTKEYS_ENV,
    AccessibilityController,
    accessibility_hotkeys_enabled,
    ocr_screen_region,
)
from core.page_reader          import PAGE_READ_MODES
from core.stt                  import (
    DictationBuffer,
    WhisperSTT,
    route_microphone_audio,
)

install_subprocess_guards()

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# RMS below which 16-bit PCM is treated as room silence; above _LEVEL_FULL it
# reads as a full-height waveform. Tuned so ordinary speech lands mid-range and
# the bars still move for a quiet talker — language- and device-independent.
_LEVEL_FLOOR = 60.0
_LEVEL_FULL  = 2600.0


def _pcm_level(samples) -> float:
    """Map a block of int16 PCM samples to a 0.0–1.0 loudness level for the HUD
    waveform. Returns 0.0 on empty/invalid input so it can never raise."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


def _get_api_key() -> str:
    from core.api_keys import gemini_api_key
    key = gemini_api_key(API_CONFIG_PATH.parent)
    if not key:
        raise KeyError("gemini_api_key")
    return key


def _load_system_prompt() -> str:
    try:
        policy = require_policy_file()
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        logging.getLogger(__name__).info(
            "Prompt caricato: %s. Lingua forzata: italiano.", PROMPT_PATH
        )
        return prompt + "\n\nSECURITY POLICY (MANDATORY):\n" + policy
    except Exception:
        logging.getLogger(__name__).info(
            "Prompt caricato: fallback. Lingua forzata: italiano."
        )
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool.\n\n"
            "Lingua di risposta: italiano. Rispondi SEMPRE in italiano, "
            "indipendentemente dal contesto precedente. Non mescolare mai "
            "lingue diverse nella stessa risposta."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _append_transcript(buffer: list[str], text: str) -> None:
    """Merge cumulative Live transcription updates without echoing fragments."""
    if not text:
        return
    if not buffer:
        buffer.append(text)
        return
    previous = buffer[-1]
    if text == previous or previous.startswith(text):
        return
    if text.startswith(previous):
        buffer[-1] = text
        return
    buffer.append(text)


DEFAULT_LOCAL_TOOL_CYCLES = 12
MAX_CONFIGURED_LOCAL_TOOL_CYCLES = 50


def _configured_local_tool_cycles() -> int:
    raw = os.environ.get("JARVIS_LOCAL_TOOL_CYCLES")
    if raw is None:
        return DEFAULT_LOCAL_TOOL_CYCLES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("JARVIS_LOCAL_TOOL_CYCLES must be an integer.") from exc
    if not 1 <= value <= MAX_CONFIGURED_LOCAL_TOOL_CYCLES:
        raise ValueError(
            "JARVIS_LOCAL_TOOL_CYCLES must be between 1 and "
            f"{MAX_CONFIGURED_LOCAL_TOOL_CYCLES}."
        )
    return value


def _run_fables_workflow_action(parameters: dict, objective: str = "") -> str:
    from core.internal_workflow import (
        FABLES_WORLD_URL,
        InternalWorkflowStore,
        format_workflow_summary,
    )

    action = str(parameters.get("action") or "plan").strip().casefold()
    store = InternalWorkflowStore()
    if action == "plan":
        workflow = store.create_fables_plan(
            str(parameters.get("objective") or objective or "Pianifica un mondo Fables"),
            parameters.get("world_url") or FABLES_WORLD_URL,
        )
    elif action == "simulate":
        workflow = store.create_fables_plan(
            str(parameters.get("objective") or objective or "Simulazione workflow Fables"),
            parameters.get("world_url") or FABLES_WORLD_URL,
            simulated=True,
        )
        workflow = store.run_fables_simulation(workflow["id"])
    elif action in {"status", "resume"}:
        workflow_id = str(parameters.get("workflow_id") or "").strip()
        if not workflow_id:
            raise ValueError(f"{action} requires workflow_id.")
        workflow = store.get(workflow_id)
        if action == "resume":
            workflow = store.resume_fables_simulation(workflow_id)
    else:
        raise ValueError("Fables action must be plan, status, simulate, or resume.")
    return format_workflow_summary(workflow)


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Compatibility handler for websites, media files, and Steam handoffs. "
            "For Windows desktop applications, use app_launcher and obtain explicit confirmation. "
            "For websites, use open_website. This includes GeoGuessr and speech-recognition "
            "variants such as 'Gio Gasser', 'Jao Gasser', or 'Geo Guesser'; "
            "send those to Steam search instead of using web_search. "
            "Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": (
                        "Application or program name, not a website URL. "
                        "GeoGuessr variants are normalized automatically. Examples: "
                        "'WhatsApp', 'Chrome', 'Spotify', 'GeoGuessr'."
                    )
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "open_website",
        "description": (
            "Opens a website inside Jarvis's integrated browser. Use for website "
            "names such as YouTube or an HTTP(S) URL; when the user only asks to open "
            "YouTube, use this tool with https://www.youtube.com. Do not launch an "
            "external browser."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {
                    "type": "STRING",
                    "description": "Website name or URL using only http or https.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "press_key",
        "description": (
            "Press one allowed key in Jarvis's integrated browser page. "
            "Allowed: A-Z, arrow keys, Space, Enter and Escape. "
            "Use this for controls in the currently open web page."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {
                    "type": "STRING",
                    "description": "One key: A-Z, ArrowUp/Down/Left/Right, Space, Enter or Escape.",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "click_link",
        "description": (
            "Clicks a visible link in Jarvis's integrated browser by its displayed "
            "text. If the text is ambiguous, no link is clicked."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "link_text": {
                    "type": "STRING",
                    "description": "The visible text of the link to click.",
                },
            },
            "required": ["link_text"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items), 'images' (direct picture links: "
            "use it to find a photo to turn into a 3D hologram with generate_3d_model image_url)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare | images"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Use only for YouTube media actions: playing or searching for videos, "
            "summarizing a video's content, getting video info, or showing trending "
            "videos. If the user only asks to open YouTube itself, use open_website "
            "instead. For a playback request, search and play the first relevant "
            "result. If playback fails, return the targeted search URL."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "accessibility_read_screen",
        "description": (
            "Reads visible interface text aloud using local OCR. Use this when the user asks "
            "for an accessible text reading of the screen, buttons, labels, or a screen region. "
            "This does not send the screenshot to an external vision model."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "language": {"type": "STRING", "description": "Tesseract language code, e.g. ita or eng"},
                "x": {"type": "INTEGER", "description": "Optional region left coordinate"},
                "y": {"type": "INTEGER", "description": "Optional region top coordinate"},
                "width": {"type": "INTEGER", "description": "Optional region width"},
                "height": {"type": "INTEGER", "description": "Optional region height"},
            },
            "required": []
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. "
            "restart, shutdown and toggle_wifi put a confirmation on the user's screen "
            "and do NOT happen until they press it — never claim they are done. "
            "close_app and close_window also require confirmation because unsaved work "
            "may be lost. "
            "Volume, brightness and dark mode can be reversed with the `undo` tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                # The exact vocabulary, spelled out.
                #
                # This used to say only "The action to perform", so the model
                # usually filled `description` instead — and computer_settings
                # then made a SECOND Gemini call, inside the tool, purely to
                # translate that sentence into one of these names. Every
                # "turn the volume down" cost two model round trips.
                "action": {
                    "type": "STRING",
                    "description": (
                        "The exact action. Prefer this over `description` — pick one of: "
                        "volume_up | volume_down | volume_set | mute | "
                        "brightness_up | brightness_down | sleep_display | "
                        "pause_video | close_app | close_window | full_screen | "
                        "minimize | maximize | snap_left | snap_right | "
                        "switch_window | show_desktop | task_manager | focus_search | "
                        "refresh_page | close_tab | new_tab | next_tab | prev_tab | "
                        "go_back | go_forward | zoom_in | zoom_out | zoom_reset | "
                        "find_on_page | scroll_up | scroll_down | scroll_top | "
                        "scroll_bottom | page_up | page_down | copy | paste | cut | "
                        "undo | redo | select_all | save | enter | escape | press_key | "
                        "type_text | screenshot | lock_screen | open_settings | "
                        "file_explorer | open_run | dark_mode | toggle_wifi | "
                        "restart | shutdown"
                    ),
                },
                "description": {
                    "type": "STRING",
                    "description": (
                        "Fallback only, when no action name above fits. "
                        "Resolved locally — no extra model call."
                    ),
                },
                "value":       {"type": "STRING", "description": "Optional value: volume level 0-100, text to type, key name, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the user's external web browser. For a website that should open "
            "inside Jarvis, use open_website instead. Use this for searching, clicking "
            "elements, filling forms, scrolling, screenshots, navigation, or an explicit "
            "request to use an external browser. Simple open/search requests launch the "
            "user's browser normally (their real profile "
            "and logged-in accounts); interactive actions (click, type, fill_form...) attach an "
            "automation browser. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "read_active_page",
        "description": (
            "Reads and analyzes the currently open browser page. "
            "Use this when the user asks to read, summarize, or answer questions about a page that is already open. "
            "It first attempts to extract DOM text; if unavailable, it uses a visual screenshot analyzed by AI. "
            "Always prefer this over asking the user to copy-paste content."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {"type": "STRING", "description": "What to find or summarize on the page"},
                "browser":  {"type": "STRING", "description": "chrome | edge | firefox | opera | brave (optional)"},
            },
            "required": []
        }
    },
    {
        "name": "read_page",
        "description": (
            "Reads content from Jarvis's integrated browser aloud using the "
            "configured local speech engine. mode: page (default), headings, "
            "links, or selection (text currently selected in the page). "
            "Use stop_reading to interrupt."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {
                    "type": "STRING",
                    "enum": ["page", "headings", "links", "selection"],
                    "description": "Page content to read aloud; defaults to page.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "stop_reading",
        "description": "Stops Jarvis's integrated browser page reader.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "supervisor_agent",
        "description": "Multi-agent coordinator. Breaks down complex tasks (coding projects, research, builds) into step-by-step plans for sub-agents. Use for complex multi-step autonomous workflows.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task": {"type": "STRING", "description": "Full description of the complex task to plan and execute."},
            },
            "required": ["task"]
        }
    },
    {
        "name": "research_agent",
        "description": "Research agent. Searches for technical documentation, API references, and code examples for a given topic.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "description": "The technical topic or API to research."},
            },
            "required": ["topic"]
        }
    },
    {
        "name": "coder_agent",
        "description": "Coder agent. Writes production-quality code to a local file based on a task description and optional research context.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":      {"type": "STRING", "description": "What to code."},
                "context":   {"type": "STRING", "description": "Optional research context or API documentation."},
                "file_path": {"type": "STRING", "description": "Absolute path where to write the code file."},
            },
            "required": ["task", "file_path"]
        }
    },
    {
        "name": "debugger_agent",
        "description": "Debugger agent. Runs a command (compile/test/execute), intercepts errors, and returns an AI-generated fix suggestion.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "Shell command to run, e.g. 'python main.py'."},
                "cwd":     {"type": "STRING", "description": "Working directory for the command."},
            },
            "required": ["command"]
        }
    },
    {
        "name": "fables_workflow",
        "description": (
            "Plans and tracks a Fables world workflow in Jarvis's private SQLite store. "
            "Actions: plan (persist a checklist only), status (read a workflow), "
            "simulate (run a local dry-run only), resume (continue a paused or interrupted simulation). "
            "This tool never clicks Fables, creates real content, enables D&D 5e defaults, "
            "or creates Areas/Points of Interest. Do not claim a real world was changed. "
            "The workflow coordinates the existing supervisor, research, and debugger "
            "agent roles; its fast path does not call their AI APIs. For an explicitly "
            "authorized live browser task, use the existing browser_control tool; do not "
            "perform Areas/POI or enable 5e defaults."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "plan | status | simulate | resume (default: plan)",
                },
                "objective": {
                    "type": "STRING",
                    "description": "World-creation objective or simulation scenario.",
                },
                "world_url": {
                    "type": "STRING",
                    "description": "HTTPS URL on fables.gg; defaults to the requested world.",
                },
                "workflow_id": {
                    "type": "STRING",
                    "description": "Workflow identifier for status or resume.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "Use for Steam or Epic operations that manage games: opening, installing, "
            "downloading, updating, listing installed games, checking download status, "
            "or scheduling updates. Opening a named game should launch it through Steam "
            "when it is in the Steam catalog. "
            "This tool has priority over file search for every videogame request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "JARVIS checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_jarvis",
        "capabilities": {
            "effects": ["destructive"],
            "sensitive_arguments": [],
            "requires_confirmation": True,
        },
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "capabilities": {
        "effects": ["write", "destructive"],
        "sensitive_arguments": ["file_path", "action", "content"],
        "requires_confirmation": True,
    },
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, ask whether the target is a local file or a game/application; never guess."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Look up a fact you have stored about the user but which is NOT in "
            "the memory block of your system prompt. "
            "The prompt lists the keys it did not have room for under "
            "'[ALSO REMEMBERED]' — if the user asks about anything named there, "
            "call this FIRST. "
            "Also call it before saying you do not know something personal, and "
            "when the user asks what you remember about them (leave query empty "
            "for everything). "
            "This is a local file search: it is instant and costs nothing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Keyword to search for — a name, a topic, a category "
                        "(e.g. 'ayse', 'coffee', 'projects'). "
                        "Leave empty to list everything stored."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "undo",
        "description": (
            "Reverse the last change YOU made to this computer — a file you "
            "moved, renamed, created or wrote, or a setting you changed such as "
            "volume, brightness, dark mode or WiFi. "
            "Call this whenever the user says undo, revert, take it back, put it "
            "back, cancel that, or tells you that you did the wrong thing, in ANY "
            "language. "
            "Use action='list' when they ask what can be undone. "
            "This only covers your own actions — it is not the Ctrl+Z of whatever "
            "application is on screen (that is computer_settings with action 'undo')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "undo (default) — reverse the last change | list — show what can be undone",
                },
            },
            "required": [],
        },
    },
]

class _ReconnectSignal(Exception):
    """Raised inside the session TaskGroup to force a clean, voluntary reconnect
    (e.g. the user picked a new voice — the voice is fixed at connect time, so
    the session must be rebuilt).

    Carries `keep_context`: True for an ordinary rebuild, where the stored
    resumption handle is replayed and the conversation continues; False when the
    new session must genuinely start clean (see the voice-change note in
    _on_voice_change)."""

    def __init__(self, keep_context: bool = True):
        super().__init__()
        self.keep_context = keep_context


def _is_reconnect_signal(exc: BaseException) -> bool:
    """True if `exc` is a _ReconnectSignal, or a(n) (Base)ExceptionGroup that
    wraps one — TaskGroup bundles child exceptions into a group."""
    if isinstance(exc, _ReconnectSignal):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_reconnect_signal(sub) for sub in exc.exceptions)
    return False


def _keep_context_of(exc: BaseException) -> bool:
    """Read `keep_context` off a reconnect signal, unwrapping the group the
    TaskGroup put it in. Defaults to True: an unexpected shape must not silently
    wipe the conversation."""
    if isinstance(exc, _ReconnectSignal):
        return getattr(exc, "keep_context", True)
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            if _is_reconnect_signal(sub):
                return _keep_context_of(sub)
    return True


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        require_policy_file()
        self.ui             = ui
        self._asst_name     = "JARVIS"   # updated each session from config
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._page_reader_audio_active = threading.Event()
        self._wake_word_gate = None
        self._echo_guard = None
        self._duplex_audio_gate = None
        self._dictation_capture = DictationBuffer(max_seconds=60)
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_voice_change   = self._on_voice_change     # voice picker → rebuild session
        self.ui.on_audio_input_mode_change = self._on_audio_input_mode_change
        self.ui._win.on_dictation_toggle = self._set_dictation
        self.ui.on_audio_device_change = self._on_audio_device_change
        self.ui._win._page_reader_audio_sig.connect(
            self._set_page_reader_audio_active
        )
        self._reconnect_event: asyncio.Event | None = None
        self._reconnect_keep = True   # False → next rebuild drops the resumption handle
        self._iris_voice_active = False

        # ── Session resumption ─────────────────────────────────────────
        # The server issues a resumption handle every few seconds and reissues
        # it as the conversation moves on. Before this, session_resumption was
        # switched ON in the config and the update was never read, so the handle
        # was thrown away and EVERY reconnect — a dropped packet, a voice change,
        # switching microphone — started an empty session. "Unlimited sessions"
        # leaked through exactly this hole.
        #
        # Deliberately in RAM only, never written to disk. Persisting it would
        # make a fresh launch continue yesterday's conversation, which sounds
        # appealing but breaks the session-summary flow: _save_session_summary
        # runs at shutdown and the morning briefing pops it the next day. A
        # conversation that never ends never produces a summary, and the
        # "yesterday we talked about…" line silently disappears.
        self._resume_handle: str | None = None
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []          # conversation turns for end-of-session summary
        self._last_user_text = ""                  # latest transcript for intent routing
        self._pattern_context = ""
        self._pattern_style = None
        self._prompt_router = PromptRouter()
        self._tool_router = ToolRouter()
        self._brain_router = get_router()
        from agents.computer_agent import ComputerAgent
        from core.browser_automation import BrowserAutomation
        from core.chat_orchestrator import ChatOrchestrator
        from core.chatbot_bridge import MockChatbot
        from core.terminal_agent import TerminalAgent

        def guard_local_computer_action():
            from core.computer_use import (
                arm_emergency_stop,
                emergency_stop_triggered,
                require_allowed_foreground,
            )

            arm_emergency_stop()
            if emergency_stop_triggered():
                raise RuntimeError("Computer Use was stopped by Ctrl+Alt+Esc.")
            require_allowed_foreground()

        self._terminal_agent = TerminalAgent()
        self._browser_automation = BrowserAutomation()
        self._computer_agent = ComputerAgent(
            browser=self._browser_automation,
            before_local_action=guard_local_computer_action,
        )
        self._computer_loop = None
        if os.environ.get("JARVIS_COMPUTER_LOOP", "0") == "1":
            from core.audit_log import AuditLog
            from core.computer_loop import ComputerLoop

            self._computer_loop = ComputerLoop(
                terminal_agent=self._terminal_agent,
                audit_log=AuditLog(BASE_DIR / "config" / "audit.jsonl"),
                browser_automation=self._browser_automation,
                max_retries=int(os.environ.get("JARVIS_COMPUTER_LOOP_MAX_RETRIES", "3")),
                timeout_seconds=float(os.environ.get("JARVIS_COMPUTER_LOOP_TIMEOUT", "30")),
            )
        self._chat_orchestrator = ChatOrchestrator(
            chatbots={"MockChatbot": MockChatbot()}
        )
        self._local_messages: list[dict[str, object]] = []
        self._local_chat_lock = asyncio.Lock()
        self._local_pending_confirmation: dict[str, object] | None = None
        self._computer_input_confirmation_available = False
        self._recent_user_texts: collections.deque[str] = collections.deque(maxlen=6)
        self._tools_used: set[str] = set()
        # Native accessibility methods are available immediately, while global
        # hotkeys remain opt-in through start_accessibility_hotkeys().
        self.accessibility = AccessibilityController(speech=self)

        self._enhanced_live = True  # affective dialog + proactive audio; auto-disabled if the server rejects them
        self._thinking_enabled = True
        # Engine layer (ported from Mark-LVI): None = Gemini Live; a dict of
        # capabilities = a local pipeline engine is holding the conversation.
        self._engine_caps        = None
        self._engine             = None
        _core_names = {t["name"] for t in TOOL_DECLARATIONS}
        self._action_registry = discover_actions(
            actions_dir=Path(__file__).resolve().parent / "actions",
            reserved_names=_core_names,
            logger=lambda msg: (
                print(f"[Actions] {msg}"),
                self.ui.write_log(f"SYS: {msg}"),
            ),
        )
        self._harness_runtime = None
        if os.environ.get("JARVIS_HARNESS", "0") == "1":
            from core.harness.adapters import AgentLoopAdapter, ComputerLoopAdapter
            from core.harness.runtime import HarnessRuntime

            adapters = {"agent_loop": AgentLoopAdapter()}
            if self._computer_loop is not None:
                adapters["computer_use_loop"] = ComputerLoopAdapter(self._computer_loop)
            self._harness_runtime = HarnessRuntime(
                adapters=adapters,
                enabled=True,
                action_registry=self._action_registry,
            )
        from core.plugin_terminal_computer import install as install_terminal_computer
        install_terminal_computer(self.ui)
        _core_names.update(self._action_registry.names())
        from core import task_runner
        task_runner.configure(
            self._action_registry,
            lambda: {"player": self.ui, "speak": self.speak, "response": None, "session_memory": None},
        )
        self._plugin_registry = discover_plugins(
            plugins_dir=Path(__file__).resolve().parent / "plugins",
            core_tool_names=_core_names,
            logger=lambda msg: (print(f"[Plugins] {msg}"), self.ui.write_log(f"SYS: {msg}")),
        )
        # GEV lifecycle hook
        self._shutdown_event = threading.Event()
        # GEV lifecycle hook
        self._plugins_stopped_evt = threading.Event()
        # GEV lifecycle hook
        threading.Thread(
            target=self._plugin_registry.start_all,
            name="gev-start",
            daemon=True,
        ).start()
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.get_hud_runtime = self._hud_runtime_snapshot
        self.ui.request_say = self.plugin_say   # plugins: mid-task speech channel
        self._hud = HudBridge()
        self._hud.on_message = self._on_hud_message
        self._hud.on_plugin = self._on_hud_plugin_toggle
        self._hud.on_system = self.ui.system_action   # SISTEMA tab → UI actions
        self._hud.on_iris_visibility = self._on_hud_iris_visibility
        # Let tools drive the HUD 3D map (open_system, tour, run scenario, …).
        self.ui.hud_command = self._hud.command
        set_ui_state = self.ui.set_state

        def set_ui_and_hud_state(state: str) -> None:
            set_ui_state(state)
            self._hud.set_state(state)

        self.ui.set_state = set_ui_and_hud_state

    def _sync_hud_plugins(self) -> None:
        plugins = (
            {"name": item["name"], "active": item["enabled"]}
            for item in self._plugin_registry.list_for_ui()
            if item["valid"]
        )
        self._hud.set_plugins(plugins)

    def _on_hud_plugin_toggle(self, name: str) -> None:
        from memory.config_manager import save_plugin_enabled

        plugins = {
            item["name"]: item
            for item in self._plugin_registry.list_for_ui()
            if item["valid"]
        }
        plugin = plugins.get(name)
        if plugin is None:
            self.ui.write_log(f"ERR: HUD requested unknown plugin: {name}")
            self._sync_hud_plugins()
            return

        enabled = not plugin["enabled"]
        try:
            save_plugin_enabled(name, enabled)
        except OSError as exc:
            self.ui.write_log(f"ERR: Could not update HUD plugin {name}: {exc}")
            self._sync_hud_plugins()
            return

        self._sync_hud_plugins()
        state = "enabled" if enabled else "disabled"
        self.ui.write_log(f"SYS: HUD plugin {name} {state}.")
        if self.session is not None:
            self.request_reconnect(
                keep_context=True,
                reason=f"HUD plugin {name} {state}",
            )

    def _hud_runtime_snapshot(self) -> dict:
        from core.jarvis_runtime import get_runtime
        from core import task_runner

        skills = get_runtime().skills.view()
        runner = task_runner.get_runner()
        task = runner.snapshot() if runner else {
            "status": "idle",
            "completed": 0,
            "total": 0,
            "progress": 0,
        }
        snapshot = {
            "skills": {
                "active": sum(item["status"] == "active" for item in skills),
                "total": len(skills),
            },
            "task": task,
        }
        hud = getattr(self, "_hud", None)
        if hud is not None:
            hud.set_runtime(snapshot)
        return snapshot

    def accessibility_speak(self, text: str) -> None:
        """Speak a short accessibility status through JARVIS's active session."""
        self.accessibility.speak(text)

    def ocr_screen(self, bbox=None, language: str = "ita") -> str:
        """Read visible screen text through the native accessibility controller."""
        return self.accessibility.read_screen(bbox=bbox, language=language)

    def click_and_type(self, target_text: str, text_to_type: str) -> bool:
        """Find a visible OCR label, focus it, and type only after a match."""
        return self.accessibility.click_and_type(target_text, text_to_type)

    def start_accessibility_hotkeys(
        self,
        read_combination: str = "ctrl+alt+r",
        status_combination: str = "ctrl+alt+s",
    ) -> None:
        """Enable global accessibility shortcuts explicitly."""
        self.accessibility.start_hotkeys(read_combination, status_combination)

    def stop_accessibility_hotkeys(self) -> None:
        """Remove global accessibility shortcuts."""
        self.accessibility.stop_hotkeys()

    def plugin_say(self, instruction: str) -> None:
        """
        Thread-safe speech channel for plugins: lets a plugin ask JARVIS to
        say something short WHILE its run() is still executing (plugins block
        their executor thread, so they can't speak through the tool response
        until they finish). The instruction is injected into the Live session
        exactly like a proactive check-in; Gemini phrases it naturally in the
        user's language. Silently a no-op when no session is connected.
        """
        loop = getattr(self, "_loop", None)
        if not loop or not self.session:
            return

        async def _say():
            try:
                await self.session.send_client_content(
                    turns={"parts": [{"text": instruction}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[PluginSay] {e}")

        try:
            asyncio.run_coroutine_threadsafe(_say(), loop)
        except Exception as e:
            print(f"[PluginSay] {e}")

    def request_reconnect(self, keep_context: bool = True, reason: str = ""):
        """Thread-safe: ask the run loop to tear down and rebuild the Live
        session. Called from the Qt thread. No-op until the async loop and
        reconnect event exist.

        `keep_context=False` drops the resumption handle so the new session
        starts empty — only for changes the server cannot apply to a resumed
        session."""
        loop = getattr(self, "_loop", None)
        ev   = self._reconnect_event
        self._reconnect_keep   = keep_context
        self._reconnect_reason = reason
        if loop and ev is not None:
            loop.call_soon_threadsafe(ev.set)

    def _on_voice_change(self):
        """Voice picker applied.

        The voice is baked into the session at connect time, so a rebuild is
        required. It is rebuilt WITHOUT the resumption handle on purpose:
        resuming restores the server's own session state, and the safe reading
        is that it restores the voice with it — which would make the picker
        appear to do nothing. Losing context here is acceptable because changing
        voice is a deliberate, rare act; losing it on a dropped packet was not."""
        self.request_reconnect(keep_context=False, reason="new voice")

    def _on_audio_device_change(self):
        """Microphone or speaker changed. Both streams are opened inside the
        session TaskGroup, so they can only be re-opened by rebuilding it —
        but the conversation is kept, which is the whole reason resumption
        landed before this feature did."""
        self.request_reconnect(keep_context=True, reason="audio device")

    def _on_audio_input_mode_change(self):
        """Apply local microphone-routing preferences at a session boundary."""
        self.request_reconnect(keep_context=True, reason="voice input mode")

    def _set_dictation(self, enabled: bool) -> bool:
        if enabled:
            from core.stt import whisper_available, WHISPER_MISSING_MESSAGE
            if not whisper_available():
                self.ui.write_log(f"ERR: {WHISPER_MISSING_MESSAGE}")
                return False
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if jarvis_speaking or self.ui.muted or self._phone_active:
                self.ui.write_log(
                    "ERR: Offline dictation requires an idle, unmuted PC microphone."
                )
                return False
            try:
                self._dictation_capture.start()
            except RuntimeError as exc:
                self.ui.write_log(f"ERR: {exc}")
                return False
            self.ui.write_log(
                "SYS: Offline dictation recording locally (maximum 60 seconds)."
            )
            return True

        if not self._dictation_capture.is_recording:
            return True
        audio = self._dictation_capture.stop()
        if audio.size == 0:
            self.ui._win._dictation_result_sig.emit(
                False, "No microphone audio was captured."
            )
            return True
        self.ui._win._dictation_busy_sig.emit(True)
        threading.Thread(
            target=self._transcribe_dictation,
            args=(audio,),
            name="jarvis-offline-dictation",
            daemon=True,
        ).start()
        return True

    def _transcribe_dictation(self, audio: np.ndarray) -> None:
        try:
            recognizer = WhisperSTT(
                model_name="base",
                language="auto",
                local_files_only=True,
            )
            transcript = recognizer.transcribe(audio)
            seconds = audio.size / 16000
            peak = float(np.abs(audio).max()) if audio.size else 0.0
            if not transcript and peak >= 0.02:
                transcript = recognizer.transcribe(audio, vad_filter=False)
            if not transcript:
                hint = (
                    "microphone level is almost silent: check the input device"
                    if peak < 0.02
                    else "no speech recognised"
                )
                raise ValueError(
                    f"Whisper returned no text ({seconds:.1f}s captured, "
                    f"peak level {peak:.3f}): {hint}."
                )
        except Exception as exc:
            self.ui._win._dictation_result_sig.emit(False, str(exc))
        else:
            self.ui._win._dictation_result_sig.emit(True, transcript)
        finally:
            audio.fill(0)

    async def _watch_reconnect(self):
        """Session-scoped task: when a voluntary reconnect is requested, raise a
        signal that unwinds the TaskGroup so the run loop rebuilds the session."""
        assert self._reconnect_event is not None
        await self._reconnect_event.wait()
        self._reconnect_event.clear()
        keep   = self._reconnect_keep
        reason = getattr(self, "_reconnect_reason", "") or "settings"
        self.ui.write_log(
            f"SYS: Applying {reason} — reconnecting"
            + ("..." if keep else " (starting a fresh conversation)...")
        )
        raise _ReconnectSignal(keep_context=keep)

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _observe_pattern_feedback(self, text: str) -> None:
        context = getattr(self, "_pattern_context", "")
        if not context:
            return
        try:
            pattern_learner.observe_correction(
                context, text, getattr(self, "_pattern_style", None)
            )
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Pattern observation unavailable: %s", exc)

    def _observe_pattern_tool_result(self, name: str, args: dict, result: str) -> None:
        try:
            if name == "app_launcher" and result.startswith(
                ("Launch requested", "Launch started", "Launch completed")
            ):
                pattern_learner.observe_app_launch(
                    pattern_learner.context_for(self._last_user_text),
                    args.get("name", ""),
                )
            elif name == "search_3d_model":
                context = pattern_learner.model_context_for(args.get("query") or self._last_user_text)
                self._pattern_context = context
                self._pattern_style = None
                if result.startswith(("No exact ready-made 3D model found", "Tool 'search_3d_model' failed:")):
                    pattern_learner.observe_tool_failure(context)
                elif result.startswith("Found 3D model"):
                    self._pattern_style = "realistic"
            elif name == "generate_3d_model" and not result.startswith(
                ("Tool 'generate_3d_model' failed:", "3D generation failed", "Invalid request")
            ):
                context = pattern_learner.model_context_for(
                    args.get("model") or args.get("prompt") or self._last_user_text
                )
                style = (
                    pattern_learner.style_for_text(args.get("style"))
                    or pattern_learner.style_for_text(result)
                    or pattern_learner.style_for_text(self._last_user_text)
                )
                self._pattern_context = context
                self._pattern_style = style
            elif name == "viewer_3d":
                mode = str(args.get("mode") or "").casefold()
                if mode == "load_model":
                    self._pattern_context = pattern_learner.model_context_for(
                        args.get("model") or self._last_user_text
                    )
                    self._pattern_style = None
                elif mode == "set_material_style":
                    style = pattern_learner.style_for_text(args.get("style"))
                    if style:
                        context = getattr(self, "_pattern_context", "") or pattern_learner.model_context_for(
                            self._last_user_text
                        )
                        pattern_learner.observe_style_preference(
                            context,
                            style,
                            getattr(self, "_pattern_style", None),
                        )
                        self._pattern_context = context
                        self._pattern_style = style
            elif name != "viewer_3d":
                self._pattern_context = pattern_learner.context_for(self._last_user_text)
                self._pattern_style = None
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Pattern observation unavailable: %s", exc)

    def _on_hud_message(self, text: str) -> None:
        self._on_text_command(text, from_hud=True)

    @staticmethod
    def _hud_visibility_request(text: str) -> bool | None:
        normalized = re.sub(r"[^\w\s]", "", text.casefold())
        normalized = " ".join(normalized.split())
        if normalized == "iris rivelati":
            return True
        if normalized == "iris nasconditi":
            return False
        return None

    def _set_hud_humanoid_visible(self, visible: bool) -> None:
        self._set_iris_voice_mode(visible)
        try:
            self._hud.command("reveal", on=visible)
        except Exception as exc:
            logging.getLogger(__name__).exception("HUD humanoid visibility command failed")
            self.ui.write_log(f"ERR: Impossibile aggiornare l'umanoide HUD: {exc}")
            return

        message = "Iris è attiva nella HUD." if visible else "Iris nascosta; mappa 3D attiva."
        self.ui.write_log(f"SYS: {message}")

    def _set_iris_voice_mode(self, visible: bool) -> None:
        if getattr(self, "_iris_voice_active", False) == visible:
            return
        self._iris_voice_active = visible
        self.request_reconnect(
            keep_context=False,
            reason="Iris feminine voice" if visible else "Jarvis masculine voice",
        )

    def _on_hud_iris_visibility(self, visible: bool) -> None:
        self._set_iris_voice_mode(visible)

    def _speech_voice_name(self) -> str:
        if getattr(self, "_iris_voice_active", False):
            return get_iris_voice()
        return get_jarvis_voice()

    def _on_text_command(self, text: str, *, from_hud: bool = False):
        if not from_hud:
            self._hud.push_chat("user", text)
        if self._try_handle_fables_text(text):
            return
        if self._try_handle_copilot_handoff(text):
            return
        if not self._loop:
            if from_hud:
                self._hud.push_chat("system", "Jarvis non è ancora connesso.")
            return

        lowered = text.strip().lower()
        visibility_request = self._hud_visibility_request(text)
        if visibility_request is not None:
            self._set_hud_humanoid_visible(visibility_request)
            return
        if "passa al cervello locale" in lowered or "usa ollama" in lowered:
            self._brain_router.switch("local")
            model = self._brain_router.model_name()
            self.ui.write_log(
                f"SYS: Cervello locale attivo ({model}). "
                "La trascrizione vocale usa ancora Gemini."
            )
            if self.session:
                self.speak("Cervello locale attivo")
            return
        if "torna al cloud" in lowered or "usa gemini" in lowered:
            self._brain_router.switch("gemini")
            self._local_pending_confirmation = None
            self.ui.write_log("SYS: Cervello cloud attivo.")
            if self.session:
                self.speak("Torno al cloud")
            return

        if self._brain_router.backend == "local":
            future = asyncio.run_coroutine_threadsafe(
                self._handle_local_text(text), self._loop
            )
            future.add_done_callback(self._report_local_chat_error)
            return

        if not self.session:
            if from_hud:
                self._hud.push_chat("system", "Sessione Gemini non disponibile.")
            self.ui.write_log("ERR: Sessione Gemini non disponibile.")
            return

        self._observe_pattern_feedback(text)
        self._schedule_geo_route(text)
        dynamic_instruction = self._prompt_router.instruction_for(text)
        try:
            learned_hints = pattern_learner.get_hints_for(text)
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Pattern hints unavailable: %s", exc)
            learned_hints = ""
        if learned_hints:
            dynamic_instruction += f"\n[LEARNED PREFERENCES]\n{learned_hints}"
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [
                    {"text": dynamic_instruction},
                    {"text": text},
                ]},
                turn_complete=True
            ),
            self._loop
        )

    def _handle_internal_fables_request(self, text: str) -> str | None:
        import sqlite3

        from core.internal_workflow import (
            FABLES_WORLD_URL,
            InternalWorkflowStore,
            format_workflow_summary,
            is_fables_request,
        )

        if not is_fables_request(text):
            return None
        simulation = bool(
            re.search(
                r"\b(?:simula|simulazione|dry[\s-]?run|diagnostica|"
                r"accett\w*\s+ma\s+non\s+(?:va|procede|parte|funziona)|"
                r"accept\w*.*(?:doesn.?t|does not|won.?t)\s+(?:go|work|proceed))\b",
                text,
                re.IGNORECASE,
            )
        )
        capability_question = bool(
            re.search(
                r"\b(?:puoi|può|riesci|capace|can you|could you)\b",
                text,
                re.IGNORECASE,
            )
        )
        if not simulation and not capability_question:
            return None
        try:
            from core.fables_live_executor import select_world_url

            urls = re.findall(r"https://[^\s<>\"']+", text, re.IGNORECASE)
            world_url = select_world_url(urls, fallback=FABLES_WORLD_URL)
            store = InternalWorkflowStore()
            workflow = store.create_fables_plan(
                text,
                world_url,
                simulated=simulation,
            )
            if simulation:
                workflow = store.run_fables_simulation(workflow["id"])
            return format_workflow_summary(workflow)
        except (OSError, sqlite3.Error, ValueError) as exc:
            logging.getLogger(__name__).exception("Fables workflow request failed")
            return (
                "Workflow Fables non completato: "
                f"{type(exc).__name__}: {exc}"
            )

    def _try_handle_fables_text(self, text: str) -> bool:
        reply = self._handle_internal_fables_request(text)
        if reply is None:
            return False
        self.ui.write_log(f"{self._asst_name}: {reply}")
        self._hud.push_chat("assistant", reply)
        self._session_log.append(f"User: {text}")
        self._session_log.append(f"{self._asst_name}: {reply}")
        return True

    def _try_handle_copilot_handoff(self, text: str) -> bool:
        from core.copilot_bridge import CopilotBridge, handle_copilot_chat_handoff

        bridge = CopilotBridge(repo_root=BASE_DIR)
        reply = handle_copilot_chat_handoff(
            text,
            bridge,
            confirm_gate.request,
        )
        if reply is None:
            return False
        self.ui.write_log(f"{self._asst_name}: {reply}")
        self._hud.push_chat("assistant", reply)
        self._session_log.append(f"User: {text}")
        self._session_log.append(f"{self._asst_name}: {reply}")
        if self.session and "[CONFIRMATION_PENDING]" in reply:
            self.speak(reply)
        return True

    def _route_voice_transcript(self, text: str) -> bool:
        lowered = text.strip().lower()
        if self._try_handle_fables_text(text):
            return True
        if self._try_handle_copilot_handoff(text):
            return True
        visibility_request = self._hud_visibility_request(text)
        if visibility_request is not None:
            self._set_hud_humanoid_visible(visibility_request)
            return True
        if "passa al cervello locale" in lowered or "usa ollama" in lowered:
            self._brain_router.switch("local")
            self.ui.write_log(
                f"SYS: Cervello locale attivo ({self._brain_router.model_name()}). "
                "La trascrizione vocale usa ancora Gemini."
            )
            return True
        if "torna al cloud" in lowered or "usa gemini" in lowered:
            self._brain_router.switch("gemini")
            self._local_pending_confirmation = None
            self.ui.write_log("SYS: Cervello cloud attivo.")
            return True
        if self._brain_router.backend != "local":
            return False

        task = asyncio.create_task(self._handle_local_text(text))
        task.add_done_callback(self._report_local_chat_error)
        return True

    def _report_local_chat_error(self, future) -> None:
        try:
            future.result()
        except Exception as exc:
            logging.getLogger(__name__).exception("Local brain request failed")
            self.ui.write_log(f"ERR: Cervello locale non disponibile: {exc}")

    @staticmethod
    def _is_explicit_app_launch(text: str, args: dict) -> bool:
        opening_verb = re.search(
            r"\b(?:apri|aprimi|avvia|avvii|apra|aprite|lancia|launch|open|start)\b",
            text,
            re.I,
        )
        app_name = args.get("name") or args.get("app_name")
        if not opening_verb or not isinstance(app_name, str):
            return False

        requested_app = _canonical_app_name(app_name)
        if requested_app is None:
            return False
        requested_words = re.findall(r"[\w.]+", requested_app.casefold())
        tail = text[opening_verb.end():]
        tail = re.sub(
            r"^\s*(?:(?:il|lo|la|i|gli|le|un|uno|una|the|a|an)\s+)+",
            "",
            tail,
            flags=re.I,
        )
        words = re.findall(r"[\w.]+", tail.casefold())
        max_window = max(2, len(requested_words))
        for size in range(1, max_window + 1):
            for start in range(len(words) - size + 1):
                candidate = _canonical_app_name(" ".join(words[start:start + size]))
                if candidate and candidate.casefold() == requested_app.casefold():
                    return True
        return False

    @staticmethod
    def _explicit_app_type_request(text: str) -> dict[str, str] | None:
        app_pattern = (
            r"(?:blocco\s+note|notepad(?:\.exe)?|google\s+chrome|chrome(?:\.exe)?|"
            r"microsoft\s+edge|msedge(?:\.exe)?|edge|firefox(?:\.exe)?|"
            r"visual\s+studio\s+code|code(?:\.exe)?)"
        )
        opening = re.search(
            rf"\b(?:apri|aprimi|avvia|apra|aprite)\s+(?P<app>{app_pattern})"
            r"\s*(?:,|\b(?:e|poi|quindi)\b)\s*"
            r"(?:scrivi|digita|type|write)\s+(?P<text>.+?)\s*$",
            text,
            re.I,
        )
        writing = None if opening else re.search(
            rf"\b(?:scrivi|digita|type|write)\s+(?P<text>.+?)\s+"
            rf"(?:in|su|nel|nella|dentro)\s+(?P<app>{app_pattern})\s*$",
            text,
            re.I,
        )
        match = opening or writing
        if match is None:
            return None

        app_name = _canonical_app_name(match.group("app"))
        content = match.group("text").strip()
        if not app_name or not content or len(content) > 1000:
            return None

        process_names = {
            "notepad": "notepad.exe",
            "notepad.exe": "notepad.exe",
            "chrome": "chrome.exe",
            "chrome.exe": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
            "msedge": "msedge.exe",
            "msedge.exe": "msedge.exe",
            "firefox": "firefox.exe",
            "firefox.exe": "firefox.exe",
            "code": "code.exe",
            "code.exe": "code.exe",
            "visual studio code": "code.exe",
        }
        process_name = process_names.get(app_name.casefold())
        if process_name is None:
            return None
        return {
            "app_name": app_name,
            "process_name": process_name,
            "text": content,
            "opens_app": opening is not None,
        }

    @staticmethod
    def _is_explicit_confirmation(text: str) -> bool:
        return bool(re.fullmatch(
            r"(?:s[iì](?:\s*,?\s*(?:confermo|procedo)(?:\s+.+)?)?|"
            r"confermo(?:\s+.+)?|procedi(?:\s+.+)?|procedo(?:\s+.+)?|approvo(?:\s+.+)?|"
            r"yes(?:\s*,?\s*i confirm)?|confirm|go ahead)[.!]?",
            text.strip().lower(),
        ))

    def _action_requires_confirmation(self, name: str, args: dict | None = None) -> bool:
        if name in {"computer_input", "agent_loop"}:
            return False
        if (
            name == "computer_use_loop"
            and os.environ.get("JARVIS_COMPUTER_LOOP", "0") != "1"
        ):
            return False
        if os.environ.get("JARVIS_HARNESS", "0") == "1":
            runtime = getattr(self, "_harness_runtime", None)
            delegated = (
                runtime.approval_policy.policy.get("confirmation_delegated_tools", {})
                if runtime is not None
                else {}
            )
            if delegated.get(name) is True:
                return False
            decision = self._harness_approval_decision(name, args or {})
            if decision is not None:
                return decision.requires_confirm
        registry = getattr(self, "_action_registry", None)
        has_action = getattr(registry, "has", None)
        risk_class = getattr(registry, "risk_class", None)
        return bool(
            callable(has_action)
            and has_action(name)
            and callable(risk_class)
            and risk_class(name) == "destructive"
        )

    def _harness_approval_decision(self, name: str, args: dict):
        runtime = getattr(self, "_harness_runtime", None)
        registry = getattr(self, "_action_registry", None)
        has_action = getattr(registry, "has", None)
        if runtime is None:
            return None
        spec = {"name": name}
        risk_is_declared = getattr(registry, "risk_class_declared", None)
        get_risk = getattr(registry, "risk_class", None)
        if (
            callable(has_action)
            and has_action(name)
            and callable(risk_is_declared)
            and risk_is_declared(name)
            and callable(get_risk)
        ):
            spec["risk_class"] = get_risk(name)
        return runtime.approval_policy.evaluate(
            spec,
            args,
            None,
            registry=registry,
        )

    async def _stream_local_chat_events(
        self,
        tools: list[dict],
    ) -> list[dict]:
        loop = asyncio.get_running_loop()
        event_queue: asyncio.Queue[tuple[bool, object]] = asyncio.Queue()
        sentinel = object()

        def publish_from_worker(item: tuple[bool, object]) -> None:
            loop.call_soon_threadsafe(event_queue.put_nowait, item)

        def produce_events() -> None:
            try:
                for event in self._brain_router.stream_chat(
                    self._local_messages,
                    tools=tools,
                ):
                    publish_from_worker((True, event))
            except Exception as exc:
                publish_from_worker((False, exc))
            finally:
                publish_from_worker((True, sentinel))

        hud = getattr(self, "_hud", None)
        publish_chat_stream = getattr(hud, "push_chat_stream", None)
        stream_started = False
        events = []
        failure: Exception | None = None
        worker = threading.Thread(
            target=produce_events,
            name="jarvis-local-chat-stream",
            daemon=True,
        )
        try:
            if callable(publish_chat_stream):
                publish_chat_stream("start")
                stream_started = True
            worker.start()

            while True:
                succeeded, event = await event_queue.get()
                if event is sentinel:
                    break
                if not succeeded:
                    failure = (
                        event
                        if isinstance(event, Exception)
                        else RuntimeError("Local model stream failed unexpectedly")
                    )
                    continue
                if not isinstance(event, dict):
                    raise TypeError("Local model stream events must be objects")
                events.append(event)
                if event.get("type") == "content" and callable(publish_chat_stream):
                    publish_chat_stream("append", event.get("text", ""))
            worker.join()
            if failure is not None:
                raise failure
        finally:
            if stream_started:
                publish_chat_stream("end")
        return events

    async def _handle_local_text(self, text: str) -> None:
        async with self._local_chat_lock:
            self.ui.set_state("THINKING")
            try:
                self._last_user_text = text
                pending = self._local_pending_confirmation
                self._computer_input_confirmation_available = bool(
                    pending
                    and pending.get("name") == "computer_input"
                    and self._is_explicit_confirmation(text)
                )
                if await self._resolve_local_tool_confirmation(text):
                    return
                if not self._local_messages:
                    self._local_messages.append({
                        "role": "system",
                        "content": (
                            _load_system_prompt()
                            + "\n\nLOCAL TOOL POLICY:\n"
                            "For informational or conversational requests, answer directly "
                            "without tools. Use only a tool provided for the current request; "
                            "never call unrelated tools, create notes, or save memory unless "
                            "the user explicitly asks. Never repeat a state-changing tool call. "
                            "A desktop app launch requires a separate explicit user confirmation. "
                            "A direct request to open a recognized app is itself explicit "
                            "confirmation; indirect or ambiguous requests still require a "
                            "separate confirmation. Every terminal command requires a separate "
                            "explicit user confirmation before execution. Computer Use inputs "
                            "still require confirmation unless the user's request already "
                            "specifies both the recognized app and exact text to type. "
                            "The bounded agent loop instead requires session approval bound to "
                            "the exact goal and action limit; its screen images are sent to "
                            "Gemini cloud."
                        ),
                    })
                self._local_messages.append({"role": "user", "content": text})
                selected_tools = self._select_local_tool_declarations(text)
                allowed_tool_names = {tool["name"] for tool in selected_tools}
                tools = ollama_tool_declarations(selected_tools)
                assistant_text = ""
                completed_mutations: set[str] = set()
                compound_request = self._explicit_app_type_request(text)
                launched_compound_app = False
                for _ in range(_configured_local_tool_cycles()):
                    if os.environ.get("JARVIS_STREAM_TOKEN", "0") == "1":
                        events = await self._stream_local_chat_events(tools)
                    else:
                        events = await asyncio.to_thread(
                            lambda: list(self._brain_router.stream_chat(
                                self._local_messages, tools=tools
                            ))
                        )
                    if not any(event.get("type") == "done" for event in events):
                        raise RuntimeError("Local model ended without a completion event")
                    assistant_text = "".join(
                        event.get("text", "")
                        for event in events
                        if event.get("type") == "content"
                    )
                    tool_calls = [
                        event for event in events
                        if event.get("type") == "tool_call"
                    ]
                    if compound_request and compound_request["opens_app"]:
                        tool_calls.sort(
                            key=lambda call: call.get("name") != "app_launcher"
                        )
                    if not tool_calls:
                        if assistant_text:
                            self._local_messages.append({
                                "role": "assistant",
                                "content": assistant_text,
                            })
                        break

                    self._local_messages.append({
                        "role": "assistant",
                        "content": assistant_text,
                        "tool_calls": [
                            {
                                "id": call.get("id") or f"call_{index}",
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": call.get("args", {}),
                                },
                            }
                            for index, call in enumerate(tool_calls)
                        ],
                    })
                    for index, call in enumerate(tool_calls):
                        name = call.get("name")
                        if not isinstance(name, str) or not name:
                            raise ValueError("Ollama returned a tool call without a name")
                        call_id = call.get("id") or f"call_{index}"
                        args = call.get("args", {})
                        if not isinstance(args, dict):
                            raise ValueError(f"Ollama returned invalid arguments for {name}")
                        should_stop = False
                        pending_confirmation = False
                        skip_compound_input = bool(
                            name == "computer_input"
                            and compound_request
                            and compound_request["opens_app"]
                            and not launched_compound_app
                        )
                        if name == "computer_input" and compound_request and not skip_compound_input:
                            args = {
                                "action": "type_text",
                                "text": compound_request["text"],
                            }
                        declaration = next(
                            (tool for tool in selected_tools if tool["name"] == name),
                            {},
                        )
                        risk_class = declaration.get("risk_class", "read")
                        if risk_class == "destructive" or name in {
                            "app_launcher",
                            "terminal_run",
                            "computer_input",
                            "agent_loop",
                        }:
                            args = {
                                key: value
                                for key, value in args.items()
                                if key != "confirmed"
                            }
                            if name == "app_launcher" and self._is_explicit_app_launch(text, args):
                                args["confirmed"] = True
                            if (
                                name == "computer_input"
                                and compound_request
                                and not skip_compound_input
                            ):
                                args["confirmed"] = True

                        if skip_compound_input:
                            tool_result = {
                                "result": (
                                    "The requested application was not confirmed "
                                    "in the foreground; no input was sent."
                                )
                            }
                            assistant_text = (
                                "L'applicazione non è in primo piano; "
                                "non ho inviato il testo."
                            )
                            should_stop = True
                        elif name not in allowed_tool_names:
                            tool_result = {
                                "result": "Tool not available for this request; no action was taken."
                            }
                            assistant_text = (
                                "Non posso eseguire uno strumento non pertinente alla richiesta."
                            )
                            should_stop = True
                        elif name in completed_mutations:
                            tool_result = {
                                "result": (
                                    "This state-changing tool already ran for this request; "
                                    "no repeated action was taken."
                                )
                            }
                            assistant_text = (
                                "Ho interrotto un tentativo di ripetere la stessa azione."
                            )
                            should_stop = True
                        else:
                            function_response = await self._execute_tool(SimpleNamespace(
                                id=call_id,
                                name=name,
                                args=args,
                            ))
                            tool_result = function_response.response
                            if risk_class in {"write", "destructive"} or name in {
                                "quick_notes",
                                "save_memory",
                                "app_launcher",
                                "computer_input",
                            }:
                                completed_mutations.add(name)
                            result_value = tool_result.get("result", "")
                            if isinstance(result_value, dict):
                                result_text = str(result_value.get("result", ""))
                            else:
                                result_text = str(result_value)
                            if (
                                name == "app_launcher"
                                and compound_request
                                and compound_request["opens_app"]
                            ):
                                launched_compound_app = result_text.startswith(
                                    ("Launch completed", "Launch requested", "Launch started")
                                )
                                if not launched_compound_app:
                                    assistant_text = result_text or (
                                        "L'applicazione non è stata avviata; "
                                        "non ho inviato il testo."
                                    )
                                    should_stop = True
                            if (
                                "Ask the user for explicit confirmation" in result_text
                            ):
                                existing_pending = self._local_pending_confirmation
                                if not (
                                    existing_pending
                                    and existing_pending.get("id") == call_id
                                    and existing_pending.get("name") == name
                                ):
                                    self._local_pending_confirmation = {
                                        "id": call_id,
                                        "name": name,
                                        "args": args,
                                    }
                                if name == "terminal_run":
                                    assistant_text = (
                                        "Signore, eseguire questo comando? "
                                        f"`{args.get('command', '')}`. Risponda «Sì, confermo» "
                                        "per procedere."
                                    )
                                elif name == "computer_input":
                                    from core.computer_use import describe_input_request

                                    action_description = describe_input_request(args)
                                    assistant_text = (
                                        "Signore, autorizza questa singola azione di input "
                                        f"nella finestra attiva: {action_description}? "
                                        "Risponda «Sì, confermo» per procedere."
                                    )
                                elif name == "agent_loop":
                                    assistant_text = str(
                                        tool_result.get("prompt")
                                        or (
                                            f"Obiettivo: {args.get('goal', '')}. "
                                            f"Procedo con un massimo di "
                                            f"{args.get('max_steps', 10)} azioni? "
                                            "Ctrl+Alt+Esc interrompe. Le immagini dello "
                                            "schermo saranno inviate a Gemini cloud. "
                                            "Risponda «Sì, procedo»."
                                        )
                                    )
                                else:
                                    target = args.get("name") or args.get("app_name") or name
                                    assistant_text = (
                                        f"Signore, per completare {target} è necessaria la Sua "
                                        "conferma esplicita. Risponda «Sì, confermo» per procedere."
                                    )
                                pending_confirmation = True
                        self._local_messages.append({
                            "role": "tool",
                            "name": name,
                            "content": json.dumps(
                                tool_result,
                                ensure_ascii=False,
                                default=str,
                            ),
                        })
                        if should_stop or pending_confirmation:
                            for skipped_call in tool_calls[index + 1:]:
                                self._local_messages.append({
                                    "role": "tool",
                                    "name": skipped_call.get("name") or "unknown",
                                    "content": json.dumps({
                                        "result": (
                                            "Skipped because this request requires confirmation "
                                            "or the previous tool call was rejected."
                                        )
                                    }),
                                })
                            self._local_messages.append({
                                "role": "assistant",
                                "content": assistant_text,
                            })
                            break
                    if self._local_pending_confirmation is not None or should_stop:
                        break
                else:
                    raise RuntimeError("Local model exceeded the tool-call limit")

                if not assistant_text:
                    raise RuntimeError("Local model returned no response text")
                self._session_log.append(f"User: {text}")
                self._session_log.append(f"{self._asst_name}: {assistant_text}")
                self.ui.write_log(f"{self._asst_name}: {assistant_text}")
                self._local_messages = [
                    self._local_messages[0],
                    *self._local_messages[1:][-40:],
                ]
            finally:
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")

    async def _resolve_local_tool_confirmation(self, text: str) -> bool:
        pending = self._local_pending_confirmation
        if pending is None:
            return False

        normalized = text.strip().lower()
        affirmative = self._is_explicit_confirmation(text)
        if pending.get("name") == "computer_input":
            self._computer_input_confirmation_available = affirmative
        negative = re.fullmatch(
            r"(?:no|annulla|cancella|non procedere)(?:\s+.+)?[.!]?",
            normalized,
        )
        if not affirmative and not negative:
            self._local_pending_confirmation = None
            self.ui.write_log("SYS: Conferma dell'azione scaduta; richiesta diversa.")
            return False

        self._local_messages.append({"role": "user", "content": text})
        if negative:
            self._local_pending_confirmation = None
            assistant_text = "Azione annullata; non è stato avviato nulla."
        else:
            args = dict(pending["args"])
            args["confirmed"] = True
            if pending["name"] in {"computer_input", "agent_loop"}:
                self._local_pending_confirmation = pending
            else:
                self._local_pending_confirmation = None
            tool_call = SimpleNamespace(
                id=pending["id"],
                name=pending["name"],
                args=args,
            )
            registry_confirmation = self._action_requires_confirmation(
                pending["name"],
                pending["args"],
            )
            needs_user_confirmed = (
                pending["name"] in {"terminal_run", "agent_loop"}
                or registry_confirmation
            )
            response = (
                await self._execute_tool(tool_call, user_confirmed=True)
                if needs_user_confirmed
                else await self._execute_tool(tool_call)
            )
            response_result = response.response.get("result", "")
            assistant_text = (
                json.dumps(response.response, ensure_ascii=False, default=str)
                if pending["name"] == "terminal_run"
                else str(response_result)
            )
        self._local_messages.append({"role": "assistant", "content": assistant_text})
        self._session_log.append(f"User: {text}")
        self._session_log.append(f"{self._asst_name}: {assistant_text}")
        self.ui.write_log(f"{self._asst_name}: {assistant_text}")
        return True

    def _schedule_geo_route(self, text: str) -> None:
        decision = classify_and_route(text)
        if (
            decision["intent"] == "none"
            or not decision["location"]
            or decision["confidence"] < 0.7
        ):
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        parameters = {
            "action": "open_with_context",
            "location": decision["location"],
            "intent": decision["intent"],
            "theme": decision["theme"],
            "epoch": decision["epoch"],
        }
        if decision["epoch"].lstrip("-").isdigit():
            parameters["year"] = int(decision["epoch"])

        async def dispatch() -> None:
            try:
                result = await asyncio.to_thread(
                    self._plugin_registry.run,
                    "gev",
                    parameters,
                    player=self.ui,
                    session_memory=None,
                )
            except Exception as exc:
                self.ui.write_log(f"GEV: routing contestuale fallito: {exc}")
                return
            self.ui.write_log(f"GEV: {result}")

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(dispatch(), loop)
        else:
            if running_loop is loop:
                asyncio.create_task(dispatch())
            else:
                asyncio.run_coroutine_threadsafe(dispatch(), loop)

    def set_speaking(self, value: bool, level: float | None = None):
        with self._speaking_lock:
            self._is_speaking = value
        self._hud.set_speaking(value, level=level)
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _set_page_reader_audio_active(self, active: bool) -> None:
        if active:
            self._page_reader_audio_active.set()
            self.set_speaking(False)
        else:
            self._page_reader_audio_active.clear()

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _select_tool_declarations(self) -> list:
        """All tool schemas; with JARVIS_TOOL_ROUTING=1 and some context, only the relevant ones.

        The Live API takes the schemas once per (re)connection, so routing can only
        trim what is sent when the session is (re)built. The first connect has no
        user text and always gets the full set.
        """
        everything = self._all_tool_declarations()
        if os.environ.get("JARVIS_TOOL_ROUTING", "0") != "1" or not self._recent_user_texts:
            return everything
        selected = self._tool_router.select(" ".join(self._recent_user_texts), everything, self._tools_used)
        print(f"[JARVIS] 🧭 ToolRouter: {len(selected)}/{len(everything)} tool "
              f"({len(json.dumps(selected))}/{len(json.dumps(everything))} byte)")
        return selected

    def _all_tool_declarations(self) -> list:
        return (
            TOOL_DECLARATIONS
            + self._action_registry.get_tool_declarations()
            + self._plugin_registry.get_tool_declarations()
        )

    def _select_local_tool_declarations(self, text: str) -> list:
        return self._tool_router.select_for_request(text, self._all_tool_declarations())

    # ── Which engine holds the conversation ──────────────────────────────────
    # Everything in this section is inert on a default install: `_engine_mode()`
    # reads one key out of the config that is already loaded, gets "gemini", and
    # returns before the providers package is imported. Delete the folder and
    # the import below raises ImportError, which is caught and reported as
    # "providers are not installed" — the assistant then runs exactly as it did
    # before any of this existed.
    def _engine_mode(self) -> str:
        try:
            from memory.config_manager import get_provider_mode
            return get_provider_mode()
        except Exception:
            return "gemini"

    def _resolve_engine_caps(self):
        """What the chosen engine can do — or None for Gemini Live.

        Called BEFORE `_build_config()`, because the tool declarations depend on
        the answer. Building the providers here rather than later is deliberate:
        the registry caches them by configuration, so the objects made now are
        the same ones the engine gets a moment later, and a misconfiguration is
        reported while there is still a Gemini session to fall back to.
        """
        if self._engine_mode() != "pipeline":
            return None
        try:
            from memory.config_manager import get_pipeline, get_provider_config
            from providers import registry

            pipe = get_pipeline()
            llm_id = str(pipe.get("llm") or "").strip()
            if not llm_id:
                raise RuntimeError("no language model is chosen")
            missing = registry.missing_fields(llm_id, get_provider_config(llm_id))
            if missing:
                raise RuntimeError(f"{llm_id} needs: {', '.join(missing)}")
            llm = registry.build(llm_id, get_provider_config(llm_id))

            # Ask the model whether it can see, once, and remember the answer.
            #
            # This decides whether `screen_process` is declared at all, so it
            # has to be settled BEFORE the config is built. Leaving it to the
            # panel's TEST button meant that anybody who never pressed it ran a
            # vision model with its eyes switched off — silently, and for every
            # session. Measured once per model, in about a second, then read
            # from the settings for ever after.
            from memory.config_manager import save_provider_config
            ensure = getattr(llm, "ensure_vision_known", None)
            if ensure is not None:
                try:
                    seen = ensure(lambda v, _id=llm_id: save_provider_config(_id, v))
                    self.ui.write_log(
                        f"SYS: {llm_id} "
                        + ("can see images." if seen else "is text only."))
                except Exception as e:
                    print(f"[JARVIS] vision check skipped: {e}")

            caps = dict(getattr(llm, "caps", {}) or {})
            caps["audio_out"] = bool(str(pipe.get("tts") or "").strip())
            return caps
        except Exception as e:
            # A local engine that will not start must never mean no assistant.
            # Falling back to Live is the whole reason the ladder exists, and
            # the reason is said out loud rather than left in a console.
            self.ui.write_log(f"SYS: local engine unavailable ({e}) — "
                              f"using Gemini Live.")
            print(f"[JARVIS] Pipeline engine unavailable: {e}")
            return None

    @asynccontextmanager
    async def _open_session(self, live_model: str, config):
        """The conversation, from whichever engine is configured.

        Both branches yield an object with the same four methods and the same
        event shapes, which is the entire contract — see providers/base.py. The
        Live branch is unchanged from what it has always been, down to the
        client being rebuilt on every reconnect.
        """
        if self._engine_caps is None:
            client = genai.Client(
                api_key=_get_api_key(),
                http_options={"api_version":
                              "v1alpha" if self._enhanced_live else "v1beta"},
            )
            async with client.aio.live.connect(model=live_model,
                                               config=config) as session:
                yield session
            return

        from memory.config_manager import get_pipeline, get_provider_config
        from providers import registry
        from providers.engine_pipeline import PipelineEngine

        pipe = get_pipeline()

        def part(slot):
            pid = str(pipe.get(slot) or "").strip()
            if not pid:
                return None
            # `log` so a provider can say what it is doing — downloading a
            # voice, loading a model — in the activity log rather than only on a
            # console the user may not be watching.
            cfg = dict(get_provider_config(pid))
            cfg["log"] = self.ui.write_log
            return registry.build(pid, cfg)

        engine = PipelineEngine(part("llm"), part("stt"), part("tts"),
                                config=config, log=self.ui.write_log)
        # Without push-to-talk nothing else knows when a sentence ended, so the
        # engine finds it in the audio. With push-to-talk the key release is the
        # signal and the detector stays out of the way.
        engine.auto_turn = not getattr(self, "_ptt_enabled", False)
        self._engine = engine
        try:
            await engine.warmup()
            yield engine
        finally:
            self._engine = None
            await engine.close()

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        from core.action_loader import strip_meta

        # Load customization from config
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        try:
            sys_prompt = pattern_learner.add_hints_to_prompt(
                _load_system_prompt(), self._last_user_text or None
            )
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Pattern hints unavailable: %s", exc)
            sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        _addr = (f"ADDRESS: Always address the user formally as '{_user_name}', using respectful language."
                 if _user_name
                 else "ADDRESS: Address the user formally and respectfully in the selected language — "
                      "use honorifics and formal pronouns such as 'Signore'/'Lei' in Italian or 'Sir' in English. "
                      "Never use slang, buddy expressions, or informal pronouns.")
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"{_addr}\n\n"
        )

        parts = [time_ctx, identity_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{
                "function_declarations": strip_meta(
                    self._select_tool_declarations()
                )
            }],
            # Hand back the handle captured from the last session_resumption
            # update. `handle=None` is exactly the old behaviour (ask for
            # handles, start fresh), so the first connect of a run is unchanged.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle
            ),
            # Sliding-window compression: session never dies from a full context
            # window — JARVIS can stay in one conversation for hours
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._speech_voice_name()
                    )
                )
            ),
        )
        if getattr(self, "_thinking_enabled", True):
            cfg["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.HIGH,
                include_thoughts=False,
            )
        if self._enhanced_live:
            # Affective dialog: JARVIS hears tone/emotion and adapts its voice.
            # Proactive audio: JARVIS stays silent when speech isn't addressed
            # to it (background chatter, talking to someone else in the room).
            cfg["enable_affective_dialog"] = True
            cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)
        return types.LiveConnectConfig(**cfg)

    async def _execute_tool(
        self, fc, *, user_confirmed: bool = False
    ) -> types.FunctionResponse:
        require_policy_file()
        name = fc.name
        args = dict(fc.args or {})
        approval = self._harness_approval_decision(name, args)
        if approval is not None and not approval.allowed:
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={
                    "result": "Action blocked by harness approval policy.",
                    "reason": approval.reason,
                    "risk_level": approval.risk_level,
                },
            )
        local_mode = (
            getattr(getattr(self, "_brain_router", None), "backend", None) == "local"
        )
        speak = (
            (lambda text: self.ui.write_log(f"{self._asst_name}: {text}"))
            if local_mode
            else self.speak
        )

        logged_args = dict(args)
        if name == "open_website" and "url" in logged_args:
            logged_args["url"] = "[URL REDACTED]"
        if name == "computer_input" and "text" in logged_args:
            logged_args["text"] = "[REDACTED]"
        if name == "agent_loop" and "goal" in logged_args:
            logged_args["goal"] = "[GOAL REDACTED]"
        print(f"[JARVIS] 🔧 {name}  {logged_args}")
        self.ui.set_state("THINKING")

        decision = route_tool(name, args, self._last_user_text)
        if decision and decision.blocked:
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": decision.clarification, "blocked": True},
            )

        if name == "agent_loop":
            from core.agent_loop import resolve_max_steps
            from core.computer_use import (
                arm_emergency_stop,
                emergency_stop_triggered,
                require_allowed_foreground,
            )

            goal = args.get("goal")
            if not isinstance(goal, str) or not goal.strip():
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={"result": "failed", "reason": "A non-empty goal is required."},
                )
            try:
                max_steps = resolve_max_steps(args.get("max_steps"))
            except (TypeError, ValueError) as exc:
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={"result": "failed", "reason": str(exc)},
                )
            requested_args = {"goal": goal.strip(), "max_steps": max_steps}
            pending = getattr(self, "_local_pending_confirmation", None)
            explicit_confirmation = self._is_explicit_confirmation(
                getattr(self, "_last_user_text", "")
            )
            matches_pending = bool(
                pending
                and pending.get("name") == name
                and pending.get("args") == requested_args
            )
            if matches_pending and (user_confirmed or explicit_confirmation):
                try:
                    if emergency_stop_triggered():
                        raise RuntimeError("Computer Use was stopped by Ctrl+Alt+Esc.")
                    current_window, current_process = require_allowed_foreground()
                except Exception as exc:
                    self._local_pending_confirmation = None
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"result": "cancelled", "reason": str(exc)},
                    )
                if (
                    current_window != pending.get("window_handle")
                    or current_process != pending.get("process_name")
                ):
                    self._local_pending_confirmation = None
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "result": "cancelled",
                            "reason": "The foreground window changed after approval.",
                        },
                    )
                args = {
                    **requested_args,
                    "_session_approved": True,
                }
                self._local_pending_confirmation = None
            else:
                if (
                    pending
                    and pending.get("name") == name
                    and explicit_confirmation
                    and not matches_pending
                ):
                    self._local_pending_confirmation = None
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "result": "cancelled",
                            "reason": (
                                "The goal or action limit changed after approval; "
                                "a new session confirmation is required."
                            ),
                        },
                    )
                try:
                    arm_emergency_stop()
                    if emergency_stop_triggered():
                        raise RuntimeError("Computer Use was stopped by Ctrl+Alt+Esc.")
                    window_handle, process_name = require_allowed_foreground()
                except Exception as exc:
                    self._local_pending_confirmation = None
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"result": "failed", "reason": f"Input disabled: {exc}"},
                    )
                prompt = (
                    f"Obiettivo: {requested_args['goal']}. Procedo con un massimo di "
                    f"{max_steps} azioni? Ctrl+Alt+Esc interrompe. Le immagini dello "
                    "schermo saranno inviate a Gemini cloud per pianificare le azioni. "
                    "Risponda «Sì, procedo»."
                )
                self._local_pending_confirmation = {
                    "id": fc.id,
                    "name": name,
                    "args": requested_args,
                    "window_handle": window_handle,
                    "process_name": process_name,
                }
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={
                        "result": "Ask the user for explicit confirmation",
                        "prompt": prompt,
                    },
                )

        if name == "terminal_run":
            pending = getattr(self, "_local_pending_confirmation", None)
            if user_confirmed:
                args["confirmed"] = True
            elif (
                pending
                and pending.get("name") == name
                and pending.get("args", {}).get("command") == args.get("command")
                and self._is_explicit_confirmation(getattr(self, "_last_user_text", ""))
            ):
                args = dict(pending["args"])
                args["confirmed"] = True
            else:
                args.pop("confirmed", None)
                self._local_pending_confirmation = {
                    "id": fc.id,
                    "name": name,
                    "args": args,
                }
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={
                        "result": "Ask the user for explicit confirmation",
                        "command": args.get("command", ""),
                    },
                )
            self._local_pending_confirmation = None

        if name == "computer_input":
            compound_request = self._explicit_app_type_request(
                getattr(self, "_last_user_text", "")
            )
            if compound_request:
                args = {
                    "action": "type_text",
                    "text": compound_request["text"],
                    "confirmed": True,
                }
            pending = getattr(self, "_local_pending_confirmation", None)
            requested_args = {
                key: value
                for key, value in args.items()
                if key != "confirmed" and not key.startswith("_")
            }
            from core.computer_use import (
                arm_emergency_stop,
                describe_input_request,
                require_allowed_foreground,
                validate_input_request,
            )

            try:
                validate_input_request(requested_args)
            except (TypeError, ValueError) as exc:
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={"result": f"Invalid input request: {exc}"},
                )
            if compound_request:
                try:
                    arm_emergency_stop()
                    hwnd, process_name = require_allowed_foreground()
                except Exception as exc:
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"result": f"Input disabled: {exc}"},
                    )
                if process_name != compound_request["process_name"]:
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "result": (
                                f"{compound_request['app_name']} is not the foreground app; "
                                "no input was sent."
                            )
                        },
                    )
                args = {
                    **requested_args,
                    "confirmed": True,
                    "_expected_window": hwnd,
                    "_expected_process": process_name,
                }
                self._local_pending_confirmation = None
                self._computer_input_confirmation_available = False
            elif (
                pending
                and pending.get("name") == name
                and pending.get("args") == requested_args
                and getattr(
                    self, "_computer_input_confirmation_available", False
                )
                and self._is_explicit_confirmation(
                    getattr(self, "_last_user_text", "")
                )
            ):
                try:
                    hwnd, process_name = require_allowed_foreground()
                except Exception as exc:
                    self._local_pending_confirmation = None
                    self._computer_input_confirmation_available = False
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"result": f"Input disabled: {exc}"},
                    )
                if (
                    hwnd != pending.get("window_handle")
                    or process_name != pending.get("process_name")
                ):
                    self._local_pending_confirmation = None
                    self._computer_input_confirmation_available = False
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "result": (
                                "The foreground window changed after the request. "
                                "No input was sent; request the action again."
                            )
                        },
                    )
                args = dict(pending["args"])
                args["confirmed"] = True
                args["_expected_window"] = pending["window_handle"]
                args["_expected_process"] = pending["process_name"]
                self._local_pending_confirmation = None
                self._computer_input_confirmation_available = False
            elif (
                pending
                and pending.get("name") == name
                and getattr(
                    self, "_computer_input_confirmation_available", False
                )
            ):
                self._local_pending_confirmation = None
                self._computer_input_confirmation_available = False
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={
                        "result": (
                            "The requested input differs from the action the user "
                            "confirmed. No input was performed; ask for confirmation again."
                        ),
                        "action": describe_input_request(requested_args),
                    },
                )
            elif pending and pending.get("name") == name:
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={
                        "result": "Ask the user for explicit confirmation",
                        "action": describe_input_request(pending["args"]),
                    },
                )
            else:
                try:
                    validate_input_request(requested_args)
                    arm_emergency_stop()
                    hwnd, process_name = require_allowed_foreground()
                except Exception as exc:
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"result": f"Input disabled: {exc}"},
                    )
                self._local_pending_confirmation = {
                    "id": fc.id,
                    "name": name,
                    "args": requested_args,
                    "window_handle": hwnd,
                    "process_name": process_name,
                }
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={
                        "result": "Ask the user for explicit confirmation",
                        "action": describe_input_request(requested_args),
                    },
                )

        if self._action_requires_confirmation(name, args):
            requested_args = {
                key: value
                for key, value in args.items()
                if key != "confirmed"
            }
            pending = getattr(self, "_local_pending_confirmation", None)
            explicit_confirmation = self._is_explicit_confirmation(
                getattr(self, "_last_user_text", "")
            )
            matches_pending = bool(
                pending
                and pending.get("name") == name
                and pending.get("args") == requested_args
            )
            if user_confirmed:
                args = {**requested_args, "confirmed": True}
                if pending and pending.get("name") == name:
                    self._local_pending_confirmation = None
            elif matches_pending and explicit_confirmation:
                args = {**requested_args, "confirmed": True}
                self._local_pending_confirmation = None
            else:
                if pending and pending.get("name") == name and explicit_confirmation:
                    self._local_pending_confirmation = None
                    return types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "result": (
                                "The action differs from the one the user approved; "
                                "no action was taken."
                            )
                        },
                    )
                self._local_pending_confirmation = {
                    "id": fc.id,
                    "name": name,
                    "args": requested_args,
                }
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={
                        "result": "Ask the user for explicit confirmation",
                        "action": name,
                        "parameters": requested_args,
                    },
                )

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                if category.lower() in {"rules", "regole", "policy"}:
                    append_rule(value)
                    category = "notes"
                    key = f"rule_{key}"
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if self._action_registry.has(name):
                def run_action():
                    ctx = {
                        "player": self.ui,
                        "speak": speak,
                        "response": None,
                        "session_memory": None,
                        "terminal_agent": getattr(self, "_terminal_agent", None),
                        "browser_automation_client": getattr(
                            self, "_browser_automation", None
                        ),
                        "computer_agent": getattr(self, "_computer_agent", None),
                        "computer_loop": getattr(self, "_computer_loop", None),
                        "chat_orchestrator": getattr(
                            self, "_chat_orchestrator", None
                        ),
                        "harness_runtime": getattr(self, "_harness_runtime", None),
                    }
                    if name == "generate_3d_model":
                        from core import task_runner

                        runner = task_runner.get_runner()
                        if runner:
                            tracked_result = runner.run_direct(name, args)
                            if tracked_result is not None:
                                return tracked_result
                    return self._action_registry.run(
                        name,
                        args,
                        ctx=ctx,
                    )
                result = await loop.run_in_executor(None, run_action)

            elif name == "recall_memory":
                # Local file search: no network, no second model. Kept out of
                # the executor deliberately — it is a dictionary scan over a few
                # hundred short strings, and a thread hop would cost more than
                # the work itself.
                result = search_memory(args.get("query", ""), limit=8)

            elif name == "undo":
                if str(args.get("action", "")).lower().strip() == "list":
                    items = undo_stack.history()
                    result = ("Things I can undo, most recent first:\n"
                              + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                              ) if items else "I have not changed anything I can undo yet."
                else:
                    result = await loop.run_in_executor(None, undo_stack.undo_last)

            elif name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "open_website":
                self.ui.open_url_in_webview(args.get("url"))
                result = "Opening the website inside Jarvis."

            elif name == "press_key":
                key = self.ui.press_key_in_webview(args.get("key"))
                result = f"Requested a {key} key press in the integrated browser."

            elif name == "click_link":
                link_text = self.ui.click_link_in_webview(args.get("link_text"))
                result = f"Requested click on the visible link '{link_text}'."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "fables_workflow":
                result = await asyncio.to_thread(
                    _run_fables_workflow_action,
                    args,
                    getattr(self, "_last_user_text", ""),
                )

            elif name == "read_active_page":
                r = await loop.run_in_executor(None, lambda: read_active_page(parameters=args, player=self.ui))
                result = r or "Could not read the page."

            elif name == "read_page":
                mode = args.get("mode", "page")
                if mode not in PAGE_READ_MODES:
                    raise ValueError(f"Unsupported page reader mode: {mode!r}")
                self.ui.read_page_aloud(mode)
                result = f"Requested local reading of browser content (mode: {mode})."

            elif name == "stop_reading":
                self.ui.stop_reading()
                result = "Requested that the integrated browser page reader stop."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE short natural sentence in the user's own language, "
                        f"telling them you are looking at their {_stall} right now. "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "accessibility_read_screen":
                region_values = [args.get(key) for key in ("x", "y", "width", "height")]
                if any(value is not None for value in region_values):
                    if not all(isinstance(value, int) and value >= 0 for value in region_values):
                        result = "For a screen region, provide non-negative integer x, y, width, and height."
                    else:
                        bbox = tuple(region_values)
                        result = await loop.run_in_executor(
                            None,
                            lambda: ocr_screen_region(
                                bbox=bbox,
                                language=args.get("language", "ita"),
                            ),
                        )
                else:
                    result = await loop.run_in_executor(
                        None,
                        lambda: ocr_screen_region(language=args.get("language", "ita")),
                    )
                result = result or "No readable text was detected on the screen."

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=speak))
                result = r or "Done."

            elif name == "supervisor_agent":
                r = await loop.run_in_executor(None, lambda: supervisor_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "research_agent":
                r = await loop.run_in_executor(None, lambda: research_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "coder_agent":
                r = await loop.run_in_executor(None, lambda: coder_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "debugger_agent":
                r = await loop.run_in_executor(None, lambda: debugger_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=speak))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    await self._save_session_summary()
                    if self.session:
                        try:
                            await self.session.send_client_content(
                                turns={"parts": [{"text": "Say a brief natural goodbye to the user."}]},
                                turn_complete=True,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(1.5)
                    import os as _os
                    # GEV lifecycle hook
                    if not self._plugins_stopped_evt.is_set():
                        self._plugins_stopped_evt.set()
                        try:
                            self._plugin_registry.stop_all(timeout=5.0)
                        except Exception:
                            pass
                    _os._exit(0)
                asyncio.create_task(_do_shutdown())

            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            if local_mode:
                self.ui.write_log(f"ERR: {name} — {str(e)[:120]}")
            else:
                self.speak_error(name, e)

        if isinstance(result, str):
            self._observe_pattern_tool_result(name, args, result)

        if name == "terminal_run" and isinstance(result, dict):
            terminal_output = "\n".join(
                value.strip()
                for value in (result.get("stdout", ""), result.get("stderr", ""))
                if isinstance(value, str) and value.strip()
            )
            if terminal_output:
                self.ui.write_log(f"TERM: {terminal_output}")

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        response = (
            result
            if name == "terminal_run" and isinstance(result, dict)
            else {"result": result}
        )
        return types.FunctionResponse(id=fc.id, name=name, response=response)

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()
        wake_detector = None
        wake_gate = None
        from memory.config_manager import (
            get_full_duplex_enabled,
            get_wake_word_enabled,
        )

        wake_word_enabled = get_wake_word_enabled()
        full_duplex_enabled = get_full_duplex_enabled()
        if full_duplex_enabled and not wake_word_enabled:
            from core.echo import EchoGuard, FullDuplexAudioGate

            self._echo_guard = EchoGuard()
            self._duplex_audio_gate = FullDuplexAudioGate()
            self.ui.write_log(
                "SYS: Voice interruption is experimental; test echo behavior "
                "with your microphone and speakers."
            )
        elif full_duplex_enabled:
            self.ui.write_log(
                "ERR: Wake word is active; it takes priority over experimental "
                "full-duplex interruption."
            )

        if wake_word_enabled:
            from core.wake_word import (
                WakeWordAudioGate,
                WakeWordDetector,
                is_ready as wake_word_is_ready,
            )

            def on_wake_detected():
                if wake_gate is not None:
                    wake_gate.activate()
                loop.call_soon_threadsafe(
                    self.ui.write_log,
                    "SYS: Wake phrase detected; microphone sent to JARVIS.",
                )

            wake_detector = WakeWordDetector(
                on_detect=on_wake_detected,
                logger=lambda message: print(f"[WakeWord] {message}"),
                notify=lambda message: loop.call_soon_threadsafe(
                    self.ui.write_log, f"ERR: {message}"
                ),
            )
            wake_gate = WakeWordAudioGate(wake_detector)
            self._wake_word_gate = wake_gate
            if wake_word_is_ready():
                detector_started = await asyncio.to_thread(wake_detector.start)
            else:
                detector_started = False
            if detector_started:
                self.ui.write_log(
                    "SYS: Wake word attivo; dire «Hey Jarvis» per aprire il microfono."
                )
            else:
                wake_detector.stop()
                self.ui.write_log(
                    "ERR: Wake word non disponibile; audio PC bloccato verso Gemini. "
                    "Usare i comandi testuali o il pulsante di setup."
                )

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            audio_allowed = not self.ui.muted and not self._phone_active

            permitted_frames = ()
            if self._duplex_audio_gate is not None:
                if jarvis_speaking and audio_allowed:
                    gate_was_open = self._duplex_audio_gate.is_open
                    if gate_was_open:
                        detected_speech = True
                    else:
                        detected_speech = self._echo_guard.is_user_speech(
                            indata,
                            SEND_SAMPLE_RATE,
                            _pcm_level(indata),
                        )
                    buffered_frames = self._duplex_audio_gate.process(
                        indata,
                        assistant_speaking=True,
                        user_speech=detected_speech,
                    )
                    if detected_speech and buffered_frames and not gate_was_open:
                        loop.call_soon_threadsafe(self.interrupt)
                    if detected_speech and buffered_frames:
                        try:
                            permitted_frames = tuple(
                                data
                                for frame in buffered_frames
                                for data in route_microphone_audio(
                                    frame,
                                    self._dictation_capture,
                                )
                            )
                        except (TypeError, ValueError) as exc:
                            loop.call_soon_threadsafe(
                                self.ui.write_log,
                                f"ERR: Full-duplex audio rejected — {exc}",
                            )
                else:
                    self._duplex_audio_gate.reset()

            if not jarvis_speaking and audio_allowed:
                try:
                    permitted_frames = route_microphone_audio(
                        indata,
                        self._dictation_capture,
                        wake_gate,
                    )
                except (TypeError, ValueError) as exc:
                    loop.call_soon_threadsafe(
                        self.ui.write_log,
                        f"ERR: Offline dictation audio rejected — {exc}",
                    )
                    permitted_frames = ()

            for data in permitted_frames:
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

            if not jarvis_speaking and audio_allowed:
                # Feed the live mic level to the HUD so the waveform reacts to
                # the user's actual voice while listening. Purely cosmetic — any
                # failure here must never disturb the mic.
                try:
                    self.ui.set_audio_level(_pcm_level(indata))
                except Exception:
                    pass

        try:
            def _open_mic(dev):
                return sd.InputStream(
                    samplerate=SEND_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                    device=dev,
                    callback=callback,
                )

            # Which microphone. resolve() returns None for "system default" and
            # for a saved device that is no longer present — so a headset
            # unplugged since the last run falls back to the built-in mic
            # instead of raising on startup and taking the session with it.
            _mic_name = get_input_device()
            _mic_dev  = audio_devices.resolve(_mic_name, "input")
            if _mic_dev is not None:
                print(f"[JARVIS] 🎤 Input device: {_mic_name}")
            try:
                _mic_stream = _open_mic(_mic_dev)
            except Exception as _e:
                # A device the picker listed but the driver will not open right
                # now — exclusive mode, a webcam already in use, a virtual mic
                # whose source went away. Chosen hardware failing must never
                # mean the assistant cannot hear at all.
                if _mic_dev is None:
                    raise
                print(f"[JARVIS] ⚠️  Mic '{_mic_name}' failed: {_e} — using default")
                self.ui.write_log(
                    f"SYS: Microphone '{_mic_name}' unavailable — using system default."
                )
                _mic_stream = _open_mic(None)

            with _mic_stream:
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise
        finally:
            if wake_detector is not None:
                wake_detector.stop()
            self._wake_word_gate = None
            self._duplex_audio_gate = None
            self._echo_guard = None
            if self._dictation_capture.is_recording:
                self._dictation_capture.discard()
                self.ui._win._dictation_result_sig.emit(
                    False,
                    "Dictation cancelled because the microphone session ended.",
                )

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    # ── Session resumption ───────────────────────────────────
                    # The server sends this periodically. `resumable` goes false
                    # while a turn is mid-flight — replaying a handle from that
                    # moment is what the flag exists to prevent — so only
                    # resumable handles are kept. This is three lines and it is
                    # the entire fix for "every reconnect forgets everything".
                    _sru = getattr(response, "session_resumption_update", None)
                    if _sru is not None:
                        if getattr(_sru, "resumable", False) and getattr(_sru, "new_handle", None):
                            if self._resume_handle is None:
                                print("[JARVIS] 🔗 Session resumption armed")
                            self._resume_handle = _sru.new_handle

                    if response.data and self._brain_router.backend != "local":
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            _append_transcript(out_buf, txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                _append_transcript(in_buf, txt)
                                self._last_user_speech = time.monotonic()

                        if sc.turn_complete:
                            if self._wake_word_gate is not None:
                                self._wake_word_gate.rearm()
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                continue

                            full_in = " ".join(in_buf).strip()
                            local_voice_handled = False
                            if full_in:
                                self._observe_pattern_feedback(full_in)
                                pending_confirmation = getattr(
                                    self, "_local_pending_confirmation", None
                                )
                                self._computer_input_confirmation_available = bool(
                                    pending_confirmation
                                    and pending_confirmation.get("name")
                                    == "computer_input"
                                    and self._is_explicit_confirmation(full_in)
                                )
                                pending_name = (
                                    pending_confirmation.get("name")
                                    if pending_confirmation
                                    else None
                                )
                                pending_registry_action = bool(
                                    pending_name
                                    and self._action_requires_confirmation(
                                        pending_name,
                                        pending_confirmation.get("args"),
                                    )
                                )
                                if (
                                    pending_confirmation
                                    and (
                                        pending_name
                                        in {"terminal_run", "computer_input", "agent_loop"}
                                        or pending_registry_action
                                    )
                                    and getattr(
                                        getattr(self, "_brain_router", None),
                                        "backend",
                                        None,
                                    ) != "local"
                                    and not self._is_explicit_confirmation(full_in)
                                ):
                                    self._local_pending_confirmation = None
                                self._last_user_text = full_in
                                self._recent_user_texts.append(full_in)
                                self._schedule_geo_route(full_in)
                                self.ui.write_log(f"You: {full_in}")
                                self._hud.push_chat("user", full_in)
                                from core.ui_panels import wants_chat
                                if wants_chat(full_in):
                                    self.ui.show_gemini_chat()
                                self._session_log.append(f"User: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                                local_voice_handled = self._route_voice_transcript(full_in)
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out and not local_voice_handled:
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._hud.say(full_out, speak=False)
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []

                            # Vision injection: model finished tool-response turn → now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                # Mark next turn_complete behaviour depending on angle
                                if self._vision_cam_active:
                                    # Camera: keep busy until JARVIS finishes speaking the answer
                                    self._vision_cam_active    = False
                                    self._vision_close_pending = True
                                else:
                                    # Screen-only: no camera to close; release busy flag now
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call and self._brain_router.backend != "local":
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            self._tools_used.add(fc.name)
                            fr = await self._execute_voice_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _execute_voice_tool(self, fc):
        from opentelemetry import trace
        from core.telemetry import record_span_error

        with trace.get_tracer("jarvis.voice").start_as_current_span(
            "voice.tool"
        ) as span:
            span.set_attribute("tool.name", str(getattr(fc, "name", "")))
            try:
                return await self._execute_tool(fc)
            except Exception as error:
                record_span_error(span, error)
                raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        _spk_name = get_output_device()
        _spk_dev  = audio_devices.resolve(_spk_name, "output")
        if _spk_dev is not None:
            print(f"[JARVIS] 🔊 Output device: {_spk_name}")

        def _open_spk(dev):
            st = sd.RawOutputStream(
                samplerate=RECEIVE_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=dev,
            )
            st.start()
            return st

        def _close_spk(st):
            for operation in ("stop", "close"):
                try:
                    getattr(st, operation)()
                except sd.PortAudioError as exc:
                    print(f"[JARVIS] ⚠️ Audio stream {operation} failed: {exc}")

        try:
            stream = _open_spk(_spk_dev)
        except Exception as _e:
            # A chosen output that the host API accepts by name but refuses to
            # open (exclusive mode, wrong sample rate, device asleep) must not
            # cost the user their voice. Fall back to the default and say so.
            if _spk_dev is None:
                raise
            print(f"[JARVIS] ⚠️  Output device '{_spk_name}' failed: {_e} — using default")
            self.ui.write_log(f"SYS: Speaker '{_spk_name}' unavailable — using system default.")
            stream = _open_spk(None)
            _spk_dev = None

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        if self._echo_guard is not None:
                            self._echo_guard.reset()
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                # Batch all immediately-available chunks into one write to reduce
                # thread-pool round-trips (was one asyncio.to_thread per 50ms slice).
                # Cap at ~200 ms so interrupt() still stops audio within ~200 ms.
                batch = bytearray(chunk)
                while len(batch) < 9600:   # 9600 bytes ≈ 200 ms at 24 kHz / 16-bit mono
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if stream is None:
                    continue

                # Drive the HUD waveform from JARVIS's own voice while speaking.
                if not self._page_reader_audio_active.is_set():
                    level = _pcm_level(
                        np.frombuffer(bytes(batch), dtype=np.int16)
                    )
                    self.set_speaking(True, level=level)
                    try:
                        self.ui.set_audio_level(level)
                    except Exception:
                        pass

                if self._page_reader_audio_active.is_set():
                    continue
                try:
                    if self._echo_guard is not None:
                        output_pcm = np.frombuffer(bytes(batch), dtype=np.int16)
                        self._echo_guard.note_output(
                            output_pcm,
                            RECEIVE_SAMPLE_RATE,
                            _pcm_level(output_pcm),
                        )
                    await asyncio.to_thread(stream.write, bytes(batch))
                except sd.PortAudioError as exc:
                    failed_device = _spk_dev
                    _close_spk(stream)
                    stream = None
                    if failed_device is not None:
                        try:
                            stream = _open_spk(None)
                            await asyncio.to_thread(stream.write, bytes(batch))
                        except sd.PortAudioError as fallback_exc:
                            if stream is not None:
                                _close_spk(stream)
                                stream = None
                            self.ui.write_log(
                                "ERR: Audio output unavailable; continuing without "
                                f"voice playback ({fallback_exc})."
                            )
                            print(
                                f"[JARVIS] ❌ Audio output unavailable: "
                                f"{fallback_exc}"
                            )
                            self.set_speaking(False)
                        else:
                            _spk_dev = None
                            self.ui.write_log(
                                "SYS: Selected speaker failed; switched to the "
                                "system default output."
                            )
                    else:
                        self.ui.write_log(
                            "ERR: Audio output unavailable; continuing without "
                            f"voice playback ({exc})."
                        )
                        print(f"[JARVIS] ❌ Audio output unavailable: {exc}")
                        self.set_speaking(False)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            if stream is not None:
                _close_spk(stream)

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to long_term.json."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from google import genai as _genai
            client = _genai.Client(api_key=_get_api_key())
            resp   = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-flash-latest",
                contents=prompt,
            )
            summary = (resp.text or "").strip()
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"parts": [{"text": alert}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            self.ui.write_log(f"SYS: Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                )
                await self.session.send_client_content(
                    turns={"parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._sync_hud_plugins()
        try:
            self._hud.start(window="none")
            self.ui.show_hud_browser(self._hud.url)
            self.ui.write_log(f"SYS: HUD available at {self._hud.url}")
        except OSError as exc:
            self._hud.stop()
            self.ui.write_log(f"SYS: HUD could not start: {exc}")
        # GEV lifecycle hook
        self._main_task = asyncio.current_task()
        self._reconnect_event = asyncio.Event()
        if accessibility_hotkeys_enabled():
            try:
                self.start_accessibility_hotkeys()
                self.ui.write_log(
                    "SYS: Accessibility hotkeys enabled "
                    "(Ctrl+Alt+R reads the screen; Ctrl+Alt+S reports status)."
                )
            except Exception as exc:
                message = (
                    f"SYS: Accessibility hotkeys requested via "
                    f"{ACCESSIBILITY_HOTKEYS_ENV} but could not be started: {exc}"
                )
                print(f"[Accessibility] {message}")
                self.ui.write_log(message)

        # ── Wire the shared core services to the interface ───────────────────
        # The confirmation gate is useless without a way to ask, and a memory
        # trim is invisible without a way to say so. Both are bound once here
        # rather than passed down through every action signature.
        confirm_gate.bind(
            show = self.ui.show_confirm,
            hide = self.ui.hide_confirm,
            log  = self.ui.write_log,
        )
        set_trim_notifier(self.ui.write_log)

        # Tell the device picker the exact rates the streams open at, from the
        # constants that actually open them — so it can never list a device that
        # cannot be opened at them.
        audio_devices.configure(SEND_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)

        # Enumerate audio devices off-thread. The settings drawer must never pay
        # for host-API enumeration on the Qt thread.
        audio_devices.prefetch()

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_capability_registry(self._action_registry)
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        # n8n outbox polling (n8n → desktop events, outbound-only, no open port).
        # Inert unless config/n8n.json has outbox.enabled=true. Events are shown
        # on the HUD and written to the activity log; they are data, never executed.
        try:
            from core.n8n_outbox import OutboxPoller
            from core.jarvis_runtime import get_runtime

            def _on_n8n_event(text: str) -> None:
                self.ui.write_log(f"SYS: n8n — {text}")
                try:
                    self._hud.say(text, speak=False)
                except Exception:
                    pass

            self._n8n_outbox = OutboxPoller(
                _on_n8n_event, get_runtime().secrets, audit=get_runtime().audit)
            if self._n8n_outbox.start():
                self.ui.write_log("SYS: n8n outbox polling attivo.")
        except Exception as e:
            print(f"[n8n outbox] Disabled: {e}")
            self._n8n_outbox = None

        # GEV lifecycle hook
        try:
            # GEV lifecycle hook
            while not self._shutdown_event.is_set():
                try:
                    print("[JARVIS] Connecting...")
                    self.ui.set_state("THINKING")
                    _resumed_with = self._resume_handle is not None

                    # Decided BEFORE the config is built, because the tool
                    # declarations depend on what the engine can serve. On a
                    # default install this returns None in a few microseconds
                    # and nothing below behaves any differently.
                    self._engine_caps = self._resolve_engine_caps()
                    config = self._build_config()

                    # The conversation itself. `_open_session` gives back a
                    # Gemini Live session or a local pipeline wearing the same
                    # interface — the Live branch still builds a fresh client on
                    # every reconnect to avoid stale HTTP state, and still asks
                    # for v1alpha when proactive audio is on.
                    async with (
                        self._open_session(LIVE_MODEL, config) as session,
                        asyncio.TaskGroup() as tg,
                    ):
                        self.session          = session
                        self.audio_in_queue   = asyncio.Queue()
                        self.out_queue        = asyncio.Queue(maxsize=200)
                        self._turn_done_event = asyncio.Event()

                        # Reset transient state that must not carry over from a previous session
                        self._pending_vision       = None
                        self._vision_cam_active    = False
                        self._vision_close_pending = False
                        self._vision_busy          = False
                        self._vision_last_time     = 0.0
                        self._interrupted          = False

                        print("[JARVIS] Connected.")
                        if _resumed_with:
                            # Say it plainly: the difference between "it reconnected"
                            # and "it reconnected and still knows what we were doing"
                            # is the whole point, and it is invisible otherwise.
                            self.ui.write_log("SYS: Reconnected — conversation restored.")
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: JARVIS online.")

                        if self._dashboard:
                            await self._dashboard.broadcast({"type": "status", "state": "active"})

                        self._reconnect_event.clear()  # ignore requests from before this session
                        tg.create_task(self._watch_reconnect())
                        tg.create_task(self._send_realtime())
                        tg.create_task(self._listen_audio())
                        tg.create_task(self._receive_audio())
                        tg.create_task(self._play_audio())
                        tg.create_task(self._run_system_monitor())
                        tg.create_task(self._run_background_monitor())
                        tg.create_task(self._run_proactive_mode())
                        if self._dashboard:
                            tg.create_task(self._relay_phone_audio())

                        # Morning briefing removed (JARVIS VII): no startup briefing.

                except KeyboardInterrupt:
                    raise
                except SystemExit:
                    raise
                except BaseException as e:
                    # Catches both Exception and BaseExceptionGroup (Python 3.11+
                    # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                    # externally, which `except Exception` would miss, letting the
                    # exception escape the while-loop and causing asyncio.run() to
                    # start shutdown — resulting in "executor after shutdown" errors).
                    # Voluntary reconnect (voice change) — not an error. Rebuild the
                    # session immediately with no backoff and no scary logs.
                    if _is_reconnect_signal(e):
                        print("[JARVIS] Voluntary reconnect requested.")
                        if not _keep_context_of(e):
                            # A deliberate clean slate (voice change) — drop the
                            # handle so the next connect really does start empty.
                            self._resume_handle = None
                        self._conn_backoff = 0
                        continue

                    err_str = str(e)
                    if self._thinking_enabled and "thinking" in err_str.casefold() and (
                        "invalid_argument" in err_str.casefold()
                        or "400" in err_str
                        or "unknown name" in err_str.casefold()
                        or "unexpected keyword" in err_str.casefold()
                    ):
                        self._thinking_enabled = False
                        self.ui.write_log(
                            "SYS: Native thinking config unavailable — reconnecting with provider defaults."
                        )
                        continue

                    # A resumption handle the server will not accept — expired, or
                    # belonging to a session it has since dropped. Without this, the
                    # same dead handle would be replayed on every retry and the
                    # assistant would never come back at all: the feature meant to
                    # survive a reconnect would be the thing preventing one. Drop it
                    # once and let the next attempt start clean.
                    if _resumed_with and (
                        "resum" in str(e).lower()
                        or "handle" in str(e).lower()
                        or "INVALID_ARGUMENT" in str(e)
                        or "NOT_FOUND" in str(e)
                    ):
                        print("[JARVIS] 🔗 Resumption handle rejected — starting a fresh session")
                        self.ui.write_log("SYS: Could not restore the conversation — starting fresh.")
                        self._resume_handle = None
                        self._conn_backoff = 0
                        continue

                    print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                    traceback.print_exc()

                    # Enhanced audio features rejected by the server (preview API
                    # drift) — drop them and reconnect with the plain config.
                    if self._enhanced_live and (
                        "INVALID_ARGUMENT" in err_str
                        or "affective" in err_str.lower()
                        or "proactiv" in err_str.lower()
                        or "Unknown name" in err_str
                        or "unexpected keyword" in err_str
                    ):
                        self._enhanced_live = False
                        self.ui.write_log(
                            "SYS: Advanced audio features unavailable — reconnecting without them."
                        )
                        continue

                    # Invalid API key — stop hammering the API, prompt re-configuration
                    if "API key not valid" in err_str or "1007" in err_str:
                        self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                        self.ui.set_state("SLEEPING")
                        self.ui.prompt_reconfig()
                        while not self.ui._win._ready:
                            await asyncio.sleep(1)
                        print("[JARVIS] New API key saved — reconnecting...")
                        _conn_backoff = 3
                        continue

                    # Network / timeout errors — log clearly and back off
                    is_net_err = any(k in err_str for k in (
                        "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                        "ConnectionRefusedError", "OSError", "Cannot connect",
                    ))
                    if is_net_err:
                        _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                        self._conn_backoff = _conn_backoff
                        self.ui.write_log(
                            f"NET: Bağlantı kurulamadı — {_conn_backoff}s sonra tekrar deneniyor. "
                            "(VPN gerekiyor olabilir)"
                        )
                    else:
                        self._conn_backoff = 3
                finally:
                    self.session = None
                    # Only save if there was a real conversation (≥3 turns)
                    if len(self._session_log) >= 3:
                        asyncio.create_task(self._save_session_summary())

                self.set_speaking(False)
                self.ui.set_state("SLEEPING")

                if self._dashboard:
                    await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

                delay = getattr(self, "_conn_backoff", 3)
                print(f"[JARVIS] Reconnecting in {delay}s...")
                await asyncio.sleep(delay)
        except KeyboardInterrupt:
            pass
        finally:
            self._hud.stop()
            browser_automation = getattr(self, "_browser_automation", None)
            if browser_automation is not None:
                try:
                    browser_automation.close()
                except Exception as exc:
                    message = (
                        "SYS: Browser automation could not be closed cleanly "
                        f"({type(exc).__name__})."
                    )
                    print(f"[Browser] {message}")
                    self.ui.write_log(message)
            try:
                self.stop_accessibility_hotkeys()
            except RuntimeError as exc:
                message = f"SYS: Accessibility hotkeys could not be fully removed: {exc}"
                print(f"[Accessibility] {message}")
                self.ui.write_log(message)
            try:
                from core.computer_use import stop_emergency_stop

                stop_emergency_stop()
            except RuntimeError as exc:
                message = f"SYS: Emergency input hotkey could not be fully removed: {exc}"
                print(f"[Computer Use] {message}")
                self.ui.write_log(message)
            # GEV lifecycle hook
            if not self._plugins_stopped_evt.is_set():
                self._plugins_stopped_evt.set()
                try:
                    self._plugin_registry.stop_all(timeout=5.0)
                except Exception:
                    pass

def _handle_fables_cli(
    argv: list[str],
    *,
    input_fn=input,
    browser_action=browser_control,
    input_action=computer_control,
    output=print,
) -> int | None:
    if "--simulate-fables-workflow" in argv and "--live-fables-workflow" in argv:
        output("Richiesta rifiutata: simulazione e preflight live sono modalità separate.")
        return 2

    if "--simulate-fables-workflow" in argv:
        from core.internal_workflow import (
            format_workflow_summary,
            simulate_fables_workflow,
        )

        workflow = simulate_fables_workflow()
        output(format_workflow_summary(workflow))
        output(f"Workflow ID: {workflow['id']}")
        return 0 if workflow["status"] == "blocked" and workflow["cycles"] == 4 else 1

    if "--live-fables-workflow" not in argv:
        return None

    import argparse

    from core.fables_live import run_read_only_preflight
    from core.internal_workflow import (
        FABLES_WORLD_URL,
        InternalWorkflowStore,
        format_workflow_summary,
    )

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--live-fables-workflow", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--world", default=FABLES_WORLD_URL)
    parser.add_argument("--world-draft-id")
    parser.add_argument("--forms-config")
    parser.add_argument("--diagnose-accepted-request", action="store_true")
    parser.add_argument("--request-page")
    parser.add_argument("--request-id")
    parser.add_argument("--accept-label")
    args, _ = parser.parse_known_args(argv)
    if not args.confirm_live:
        output(
            "Live non eseguito: specificare --confirm-live e confermare la frase "
            "esatta a runtime."
        )
        return 2

    if args.diagnose_accepted_request:
        from core.fables_live_executor import (
            FablesLiveExecutor,
            select_world_url,
        )

        if not args.request_page or not args.request_id or not args.accept_label:
            output(
                "Diagnosi non eseguita: specificare --request-page, --request-id "
                "e --accept-label verificato."
            )
            return 2
        try:
            expected_world_url = select_world_url((args.world,))
        except ValueError as exc:
            output(f"Diagnosi non eseguita: {exc}")
            return 2
        expected = (
            "AUTORIZZO DIAGNOSI RICHIESTA FABLES "
            f"{args.request_page.strip()} -> {expected_world_url} [{args.request_id.strip()}]"
        )
        try:
            confirmation = input_fn(
                f"Per autorizzare il click e la diagnosi, digitare esattamente: "
                f"{expected}\n> "
            ).strip()
        except (EOFError, OSError):
            output("Diagnosi non eseguita: conferma runtime non disponibile.")
            return 2
        try:
            result = FablesLiveExecutor().diagnose_request_transition(
                args.request_page,
                expected_world_url,
                args.request_id,
                args.accept_label,
                live_flag=args.live_fables_workflow,
                confirm_live=args.confirm_live,
                runtime_confirmation=confirmation,
                browser_action=browser_action,
                input_action=input_action,
            )
        except (ValueError, RuntimeError) as exc:
            output(f"Diagnosi Fables bloccata: {exc}")
            return 2
        output(
            f"Richiesta {result.request_state}; URL prima={result.before_url}; "
            f"URL dopo={result.after_url}; causa={result.diagnosis.cause}; "
            f"evidenze={len(result.diagnosis.evidence)}; "
            f"diagnosi SQLite={result.diagnosis.id}"
        )
        return 0

    if args.world_draft_id:
        import json
        from pathlib import Path

        from agents.world_designer_agent import WorldDesignerAgent
        from core.fables_live_executor import (
            FablesFormMapping,
            FablesLiveExecutor,
        )

        draft = WorldDesignerAgent().resume(args.world_draft_id)
        if draft is None:
            output(f"Live non eseguito: bozza mondo non trovata: {args.world_draft_id}")
            return 2
        mapping_path = Path(args.forms_config) if args.forms_config else (
            BASE_DIR / "config" / "fables_forms.json"
        )
        if not mapping_path.is_absolute():
            mapping_path = BASE_DIR / mapping_path
        try:
            raw_mappings = json.loads(mapping_path.read_text(encoding="utf-8"))
            if not isinstance(raw_mappings, dict):
                raise ValueError("Il file deve contenere un oggetto JSON.")
            mappings = {
                category: FablesFormMapping(**values)
                for category, values in raw_mappings.items()
                if isinstance(values, dict)
            }
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            output(f"Live non eseguito: configurazione UI non valida ({mapping_path}): {exc}")
            return 2

        expected = f"AUTORIZZO ESECUZIONE FABLES {args.world}"
        output(
            "Questa modalità inserisce la bozza nel mondo reale. Aree, POI e 5e "
            "Defaults restano esclusi. Le azioni già accettate non vengono ripetute."
        )
        try:
            confirmation = input_fn(
                f"Per autorizzare l'esecuzione, digitare esattamente: {expected}\n> "
            ).strip()
        except (EOFError, OSError):
            output("Live non eseguito: conferma runtime non disponibile.")
            return 2
        try:
            result = FablesLiveExecutor().execute(
                draft.world,
                args.world,
                mappings,
                live_flag=args.live_fables_workflow,
                confirm_live=args.confirm_live,
                runtime_confirmation=confirmation,
                browser_action=browser_action,
                input_action=input_action,
            )
        except (ValueError, RuntimeError) as exc:
            output(f"Live Fables bloccato: {exc}")
            return 2
        output(
            f"Workflow live {result.state}: {len(result.executions)} elementi verificati; "
            f"{len(result.excluded)} categorie escluse."
        )
        if result.stop_reason:
            output(f"Stop: {result.stop_reason}")
        for execution in result.executions:
            output(
                f"{execution.element_id}: {execution.request_state}; "
                f"diagnosi={execution.diagnosis.cause}; "
                f"evidenze={len(execution.diagnosis.evidence)}"
            )
        return 0 if result.state == "completed" else 2

    expected = f"AUTORIZZO SOLO ISPEZIONE FABLES {args.world}"
    output(
        "Questa modalità effettua soltanto navigazione e lettura visibile. "
        "Non accetta richieste, non invoca agenti e non crea contenuti."
    )
    if input_fn(f"Per autorizzare, digitare: {expected}\n> ").strip() != expected:
        output("Live non eseguito: conferma runtime assente o non corrispondente.")
        return 2

    store = InternalWorkflowStore()
    workflow = run_read_only_preflight(store, args.world, browser_action)
    output(format_workflow_summary(workflow))
    output(f"Workflow ID: {workflow['id']}")
    output(
        "Live preflight registrato; richiesta non verificata. "
        "Accettazione e popolamento non eseguiti."
    )
    return 0


def main(argv=None):
    import argparse

    from core.logging_config import configure_logging

    configure_logging()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--hud-port", type=int)
    parser.add_argument("--startup-smoke", action="store_true")
    runtime_options, _remaining_args = parser.parse_known_args(
        sys.argv[1:] if argv is None else argv
    )
    if runtime_options.hud_port is not None:
        if not 0 <= runtime_options.hud_port <= 65535:
            parser.error("--hud-port must be between 0 and 65535.")
        os.environ["JARVIS_HUD_PORT"] = str(runtime_options.hud_port)

    if runtime_options.startup_smoke:
        from PyQt6.QtCore import QTimer

        ui = JarvisUI("face.png")
        hud = HudBridge()
        try:
            hud.start(window="none")
            ui.show_hud_browser(hud.url)
            print(f"JARVIS_STARTUP_READY {hud.url}", flush=True)
            QTimer.singleShot(15_000, ui._app.quit)
            ui.root.mainloop()
            return
        finally:
            hud.stop()

    if "--copilot-handoff" in sys.argv[1:]:
        from core.copilot_bridge import handle_copilot_handoff_cli

        copilot_exit_code = handle_copilot_handoff_cli(
            sys.argv[1:],
            repo_root=BASE_DIR,
        )
        if copilot_exit_code is not None:
            raise SystemExit(copilot_exit_code)

    fables_exit_code = _handle_fables_cli(sys.argv[1:])
    if fables_exit_code is not None:
        raise SystemExit(fables_exit_code)

    ui = JarvisUI("face.png")
    from core import actions_bridge
    actions_bridge.set_ui(ui)

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        # GEV lifecycle hook
        ui._jarvis = jarvis
        try:
            asyncio.run(jarvis.run())
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    # GEV lifecycle hook
    runner_thread = threading.Thread(target=runner, daemon=True)
    runner_thread.start()
    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        # GEV lifecycle hook
        jarvis_live = getattr(ui, "_jarvis", None)
        if jarvis_live is not None:
            jarvis_live._shutdown_event.set()
            loop_ref = getattr(jarvis_live, "_loop", None)
            task_ref = getattr(jarvis_live, "_main_task", None)
            if loop_ref is not None and task_ref is not None:
                try:
                    loop_ref.call_soon_threadsafe(task_ref.cancel)
                except RuntimeError:
                    pass
        runner_thread.join(timeout=6.0)

if __name__ == "__main__":
    main()