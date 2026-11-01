"""Authenticated, loopback-only WebSocket bridge for JARVIS."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import websockets

from core.gemini_chat import ask_gemini

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _BASE_DIR / "config" / "api_keys.json"
_LOG_PATH = _BASE_DIR / "logs" / "ws_server.log"
_HOST = "127.0.0.1"
_PORT = 8765
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3

_LOGGER = logging.getLogger("jarvis.ws_server")
_LOGGER.setLevel(logging.INFO)
_SERVER = None


def _configure_logging() -> None:
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == _LOG_PATH.resolve()
        for handler in _LOGGER.handlers
    ):
        return
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        _LOG_PATH,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    _LOGGER.addHandler(handler)


def _load_or_create_token() -> str:
    try:
        if _CONFIG_PATH.is_file():
            config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        else:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("config root must be a JSON object")

        token = config.get("ws_token")
        if isinstance(token, str) and token:
            return token

        token = secrets.token_urlsafe(32)
        config["ws_token"] = token
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps(config, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return token
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load or persist WebSocket token: {exc}") from exc


def _decode_message(raw_message: str | bytes) -> dict[str, Any]:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8")
    if not isinstance(raw_message, str):
        raise ValueError("message must be JSON text")
    try:
        message = json.loads(raw_message)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON message: {exc}") from exc
    if not isinstance(message, dict):
        raise ValueError("message must be a JSON object")
    return message


async def _send(websocket, message: dict[str, Any]) -> None:
    await websocket.send(json.dumps(message, ensure_ascii=False))


async def _send_status(websocket, state: str, detail: str) -> None:
    await _send(
        websocket,
        {"type": "status", "state": state, "detail": detail},
    )


def _valid_history(history: Any) -> bool:
    if history is None:
        return True
    if not isinstance(history, list):
        return False
    for turn in history:
        if not isinstance(turn, dict) or turn.get("role") not in {"user", "model"}:
            return False
        parts = turn.get("parts")
        if (
            not isinstance(parts, list)
            or not parts
            or any(
                not isinstance(part, dict)
                or not isinstance(part.get("text"), str)
                for part in parts
            )
        ):
            return False
    return True


async def _dispatch_message(websocket, message: dict[str, Any], plugin_registry) -> None:
    message_type = message.get("type")
    if message_type == "ping":
        await _send(websocket, {"type": "pong"})
        return

    if message_type == "chat":
        request_id = message.get("id")
        prompt = message.get("text")
        history = message.get("history")
        if not isinstance(request_id, (str, int)) or not isinstance(prompt, str) or not prompt.strip():
            await _send_status(websocket, "error", "chat requires id and non-empty text")
            return
        if not _valid_history(history):
            await _send_status(websocket, "error", "history must be a list of user/model turns")
            return

        await _send_status(websocket, "busy", "Gemini is responding")
        try:
            answer = await asyncio.to_thread(
                ask_gemini,
                prompt,
                history,
            )
        except Exception as exc:
            _LOGGER.exception("Gemini chat request failed")
            await _send_status(websocket, "error", str(exc))
            return
        await _send(websocket, {"type": "reply", "id": request_id, "text": answer})
        await _send_status(websocket, "ready", "Gemini response complete")
        return

    if message_type == "command":
        request_id = message.get("id")
        name = message.get("name")
        args = message.get("args", {})
        if (
            not isinstance(request_id, (str, int))
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(args, dict)
        ):
            await _send_status(
                websocket,
                "error",
                "command requires id, name, and an object args value",
            )
            return
        if plugin_registry is None or not callable(getattr(plugin_registry, "run", None)):
            await _send_status(websocket, "error", "plugin registry is unavailable")
            return

        await _send_status(websocket, "busy", f"Running plugin {name}")
        try:
            result = await asyncio.to_thread(
                plugin_registry.run,
                name,
                args,
                player=None,
                session_memory=None,
            )
        except Exception as exc:
            _LOGGER.exception("Plugin command %s failed", name)
            await _send_status(websocket, "error", str(exc))
            return
        await _send(
            websocket,
            {"type": "reply", "id": request_id, "text": str(result)},
        )
        await _send_status(websocket, "ready", f"Plugin {name} complete")
        return

    await _send_status(websocket, "error", "unsupported message type")


async def _handle_connection(websocket, token: str, plugin_registry=None) -> None:
    try:
        first_message = await websocket.recv()
        auth = _decode_message(first_message)
    except Exception as exc:
        _LOGGER.warning("WebSocket connection failed authentication parsing: %s", exc)
        await websocket.close(code=4001, reason="authentication required")
        return

    provided_token = auth.get("token")
    if (
        auth.get("type") != "auth"
        or not isinstance(provided_token, str)
        or not hmac.compare_digest(provided_token, token)
    ):
        _LOGGER.warning("Rejected WebSocket connection with invalid authentication")
        await websocket.close(code=4001, reason="invalid authentication")
        return

    await _send(websocket, {"type": "auth_ok"})
    await _send_status(websocket, "ready", "authenticated")
    async for raw_message in websocket:
        try:
            message = _decode_message(raw_message)
            if message.get("type") == "auth":
                await _send_status(websocket, "error", "authentication is already complete")
                continue
            await _dispatch_message(websocket, message, plugin_registry)
        except Exception as exc:
            _LOGGER.exception("Failed to process WebSocket message")
            await _send_status(websocket, "error", str(exc))


async def start_server(
    host: str = _HOST,
    port: int = _PORT,
    plugin_registry=None,
) -> None:
    """Start serving on loopback until stop_server() is called."""
    global _SERVER

    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("WebSocket server host must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("WebSocket server host must be a loopback IP address")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("WebSocket server port must be between 1 and 65535")
    if _SERVER is not None:
        raise RuntimeError("WebSocket server is already running")

    _configure_logging()
    token = _load_or_create_token()

    async def handler(websocket) -> None:
        await _handle_connection(websocket, token, plugin_registry)

    server = await websockets.serve(handler, host, port)
    _SERVER = server
    _LOGGER.info("WebSocket server listening on %s:%s", host, port)
    try:
        await server.wait_closed()
    finally:
        if _SERVER is server:
            _SERVER = None


async def stop_server() -> None:
    """Stop the active WebSocket server, if one is running."""
    global _SERVER
    server = _SERVER
    if server is None:
        return
    server.close()
    await server.wait_closed()
    if _SERVER is server:
        _SERVER = None
