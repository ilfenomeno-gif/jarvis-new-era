"""n8n Bridge — invoke n8n Cloud workflows as a JARVIS tool.

DESIGN (JARVIS VII, Opzione 2: Python brain, n8n as workflow engine)
    The desktop holds the conversation; n8n Cloud runs workflows. This action
    calls an n8n **Webhook** (production URL) over HTTPS with an auth header and
    a timeout, and maps the synchronous response onto the `outcome` protocol.

    Channel is OUTBOUND ONLY: the desktop posts to the webhook. n8n never opens
    a connection back (the desktop is behind NAT). Spontaneous n8n→desktop
    events use a separate polling "outbox" workflow (see P3).

CONFIGURATION — file-based, never hardcoded to a specific workflow
    config/n8n.json (git-ignored, local only):

        {
          "base_url": "https://your-instance.app.n8n.cloud",
          "webhook_path": "/webhook/jarvis-bridge",   // from the Webhook node
          "auth_header": "X-Jarvis-Token",             // header name
          "timeout_sec": 30
        }

    The webhook SECRET is stored in the DPAPI SecretStore under
    "n8n:webhook" — never in this file, never in the repo, never in logs.
    Set it once from the UI or with:

        python -m core.secret_store  # or via the connectors/secret UI

    No audio, screenshot or screen content is ever put in the payload — only
    the text of the task. This is a hard rule of the bridge.

OUTCOME PROTOCOL
    done       — n8n answered 2xx with a body we could read
    unverified — request sent, but the response was empty/unreadable
    failed     — auth rejected (401/403), timeout, network error, not configured
"""
from __future__ import annotations

import json
from pathlib import Path

from core import outcome
from core.jarvis_runtime import get_runtime

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config" / "n8n.json"
SECRET_NAME = "n8n:webhook"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAYLOAD_CHARS = 8000  # stay far under n8n's 16 MB webhook cap; text only


class N8nBridgeError(RuntimeError):
    pass


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise N8nBridgeError(
            f"not configured: create {CONFIG_PATH.name} in config/ "
            "(base_url, webhook_path, auth_header)")
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise N8nBridgeError(f"invalid config file: {exc}")
    if not isinstance(data, dict):
        raise N8nBridgeError("config must be a JSON object")
    return data


def _endpoint(cfg: dict) -> str:
    base = str(cfg.get("base_url") or "").strip().rstrip("/")
    path = str(cfg.get("webhook_path") or "").strip()
    if not base or not path:
        raise N8nBridgeError("config needs base_url and webhook_path")
    if not base.startswith("https://"):
        raise N8nBridgeError("base_url must be https:// (no plaintext webhook)")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _auth(cfg: dict) -> dict[str, str]:
    header = str(cfg.get("auth_header") or "").strip()
    if not header:
        raise N8nBridgeError("config needs auth_header")
    secret = get_runtime().secrets.get(SECRET_NAME)
    if not secret:
        raise N8nBridgeError(
            f"webhook secret missing: store it in the SecretStore as {SECRET_NAME!r}")
    return {header: secret}


def call_workflow(task: str, *, extra: dict | None = None,
                  timeout: float | None = None) -> str:
    """POST a task to the configured n8n webhook and return an outcome line.

    `task` is the user's request as text. `extra` is an optional dict of small
    string/number fields merged into the payload. Never pass audio, images or
    screen content here.
    """
    task = str(task or "").strip()
    if not task:
        return outcome.failed("n8n_bridge", "empty task")
    if len(task) > _MAX_PAYLOAD_CHARS:
        return outcome.failed("n8n_bridge", "task too long",
                              limit=_MAX_PAYLOAD_CHARS)

    try:
        cfg = _load_config()
        url = _endpoint(cfg)
        headers = _auth(cfg)
    except N8nBridgeError as exc:
        get_runtime().audit.record(tool="n8n_bridge", outcome="failed",
                                   detail=str(exc))
        return outcome.failed("n8n_bridge", str(exc))

    timeout = float(timeout if timeout is not None
                    else cfg.get("timeout_sec", _DEFAULT_TIMEOUT))
    payload = {"task": task, "source": "jarvis-vii"}
    if isinstance(extra, dict):
        for key, value in extra.items():
            if isinstance(value, (str, int, float, bool)) and value is not None:
                payload[str(key)] = value

    try:
        import httpx
    except ImportError:
        get_runtime().audit.record(tool="n8n_bridge", outcome="failed",
                                   detail="httpx not installed")
        return outcome.failed("n8n_bridge", "httpx is not installed")

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        get_runtime().audit.record(tool="n8n_bridge", outcome="failed",
                                   detail="timeout", arguments={"timeout": timeout})
        return outcome.failed("n8n_bridge", "the workflow did not answer in time",
                              timeout=timeout)
    except Exception as exc:
        get_runtime().audit.record(tool="n8n_bridge", outcome="failed",
                                   detail=type(exc).__name__)
        return outcome.failed("n8n_bridge", f"network error: {type(exc).__name__}")

    if response.status_code in (401, 403):
        get_runtime().audit.record(tool="n8n_bridge", outcome="failed",
                                   detail=f"auth rejected {response.status_code}")
        return outcome.failed("n8n_bridge",
                              "the webhook rejected authentication — check the token")
    if response.status_code >= 400:
        get_runtime().audit.record(tool="n8n_bridge", outcome="failed",
                                   detail=f"http {response.status_code}")
        return outcome.failed("n8n_bridge", f"the workflow returned HTTP {response.status_code}")

    body = response.text.strip()
    if not body:
        get_runtime().audit.record(tool="n8n_bridge", outcome="unverified",
                                   detail="empty 2xx body")
        return outcome.unverified("n8n_bridge",
                                  "the workflow ran but returned an empty response")
    get_runtime().audit.record(tool="n8n_bridge", outcome="done",
                               detail=f"http {response.status_code}",
                               arguments={"task_len": len(task)})
    return outcome.done("n8n_bridge", response=body[:2000])


def n8n_bridge(parameters: dict, player=None, session_memory=None) -> str:
    """Action entry point. `task` is required; `extra_json` optional."""
    params = parameters or {}
    task = str(params.get("task", "")).strip()
    extra = None
    raw_extra = params.get("extra_json")
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
            if not isinstance(extra, dict):
                extra = None
        except json.JSONDecodeError:
            return outcome.failed("n8n_bridge", "extra_json is not valid JSON")
    if player:
        try:
            player.write_log(f"[n8n] task: {task[:120]}")
        except Exception:
            pass
    return call_workflow(task, extra=extra)


TOOL = {
    "name": "n8n_bridge",
    "description": (
        "Send a task to an n8n Cloud workflow and return its result. Use for "
        "multi-step automations, scheduled jobs and integrations that live in "
        "n8n (NOT for local desktop actions — use the dedicated tools for those). "
        "Input is text only; never audio or screenshots."),
    "risk_class": "write",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {"type": "STRING",
                     "description": "The task for the n8n workflow, as text."},
            "extra_json": {"type": "STRING",
                           "description": "Optional extra fields as a JSON object string."},
        },
        "required": ["task"],
    },
    "handler": n8n_bridge,
}
