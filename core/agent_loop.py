"""Session-approved, bounded desktop automation using Computer Use primitives."""
from __future__ import annotations

import asyncio
import inspect
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core import computer_use


DEFAULT_MAX_STEPS = 10
MAX_CONFIGURED_STEPS = 50
MAX_STEP_TIMEOUT = 30


def _configured_max_steps() -> int:
    raw = os.environ.get("JARVIS_AGENT_MAX_STEPS")
    if raw is None:
        return DEFAULT_MAX_STEPS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("JARVIS_AGENT_MAX_STEPS must be an integer.") from exc
    if not 1 <= value <= MAX_CONFIGURED_STEPS:
        raise ValueError(
            f"JARVIS_AGENT_MAX_STEPS must be between 1 and {MAX_CONFIGURED_STEPS}."
        )
    return value


def resolve_max_steps(requested: int | None = None) -> int:
    hard_limit = _configured_max_steps()
    if requested is None:
        return hard_limit
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError("max_steps must be a positive integer.")
    return min(requested, hard_limit)


def _prompt_for(goal: str, elements: dict[str, Any], history: list[dict[str, Any]], step: int) -> str:
    previous = history[-1] if history else {}
    return (
        "Sei un agente desktop. Pianifica una sola azione per questo passo.\n"
        f"Obiettivo: {goal}\n"
        f"Elementi disponibili: {json.dumps(elements, ensure_ascii=False)}\n"
        f"Azione precedente: {previous.get('action', 'nessuna')}\n"
        f"Risultato: {previous.get('result', 'nessuno')}\n"
        f"Passo: {step}\n"
        "Rispondi esclusivamente con JSON valido nel formato "
        '{"action":"click|type|hotkey|scroll|done|fail",'
        '"target":"coordinate o testo del controllo",'
        '"value":"testo, tasti o direzione",'
        '"reason":"motivazione breve"}. '
        "Per click, target può essere testo esatto oppure un oggetto con x e y "
        "o bbox [x, y, larghezza, altezza]. Per type, il campo da compilare "
        "deve già avere il focus. Per scroll, value è up o down. Scegli done "
        "solo quando l'obiettivo è completato; non inventare controlli."
    )


def _decode_plan(response: Any) -> dict[str, Any]:
    text = getattr(response, "text", response)
    if isinstance(text, dict):
        plan = text
    else:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini returned an empty desktop plan.")
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
        try:
            plan = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError("Gemini returned a plan that is not valid JSON.") from exc
    if not isinstance(plan, dict):
        raise ValueError("Gemini plan must be a JSON object.")
    action = plan.get("action")
    if action not in {"click", "type", "hotkey", "scroll", "done", "fail"}:
        raise ValueError(f"Gemini returned unsupported action: {action!r}.")
    if not isinstance(plan.get("reason", ""), str):
        raise ValueError("Gemini plan reason must be text.")
    return plan


def _gemini_plan(
    goal: str,
    elements: dict[str, Any],
    history: list[dict[str, Any]],
    step: int,
    frame: Any,
    timeout: int,
) -> dict[str, Any]:
    from google.genai import types
    from core import gemini

    image = io.BytesIO()
    frame.save(image, format="JPEG", quality=80)
    image_part = types.Part.from_bytes(data=image.getvalue(), mime_type="image/jpeg")
    response = gemini.call(
        [_prompt_for(goal, elements, history, step), image_part],
        tier=gemini.SMART,
        timeout_ms=timeout * 1000,
    )
    if response is None:
        raise RuntimeError("Gemini could not produce a desktop plan.")
    return _decode_plan(response)


def _target_point(target: Any) -> tuple[int, int]:
    if isinstance(target, str) and target.strip():
        raise TypeError("text targets are handled as UI Automation controls.")
    if not isinstance(target, dict):
        raise ValueError("click target must be text or a coordinate object.")
    if "bbox" in target:
        bounds = target["bbox"]
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) for value in bounds)
        ):
            raise ValueError("bbox must contain four integer values.")
        x, y, width, height = bounds
        if width <= 0 or height <= 0:
            raise ValueError("bbox width and height must be positive.")
        return x + width // 2, y + height // 2
    x, y = target.get("x"), target.get("y")
    if (
        isinstance(x, bool)
        or not isinstance(x, int)
        or isinstance(y, bool)
        or not isinstance(y, int)
    ):
        raise ValueError("click target x and y must be integer screen coordinates.")
    return x, y


def _input_for_plan(plan: dict[str, Any], hwnd: int, process_name: str) -> dict[str, Any]:
    action = plan["action"]
    value = plan.get("value")
    target = plan.get("target")
    base = {
        "confirmed": True,
        "_expected_window": hwnd,
        "_expected_process": process_name,
    }
    if action == "click":
        if isinstance(target, str):
            return {**base, "action": "click_text", "target": target}
        x, y = _target_point(target)
        return {**base, "action": "click", "x": x, "y": y}
    if action == "type":
        if not isinstance(value, str) or not value:
            raise ValueError("type requires a non-empty text value.")
        return {**base, "action": "type", "text": value}
    if action == "hotkey":
        if not isinstance(value, str) or not value:
            raise ValueError("hotkey requires a non-empty key combination.")
        return {**base, "action": "hotkey", "keys": value}
    if action == "scroll":
        if isinstance(value, dict):
            direction = value.get("direction")
            amount = value.get("amount", 1)
        else:
            direction, amount = value, 1
        return {
            **base,
            "action": "scroll",
            "direction": direction,
            "amount": amount,
        }
    raise ValueError(f"Cannot execute terminal plan action {action!r}.")


class AgentLoop:
    def __init__(
        self,
        max_steps: int = DEFAULT_MAX_STEPS,
        step_timeout: int = MAX_STEP_TIMEOUT,
        no_change_limit: int = 3,
        *,
        confirm_session: Callable[[str], Any] | None = None,
        planner: Callable[..., Any] | None = None,
        capture: Callable[[], Any] | None = None,
        ocr: Callable[..., Any] | None = None,
        uia_tree: Callable[[], Any] | None = None,
        execute_input: Callable[[dict[str, Any]], Any] | None = None,
        wait_for_change: Callable[..., Any] | None = None,
        foreground: Callable[[], tuple[int, str]] | None = None,
        hash_frame: Callable[[Any], str] | None = None,
        kill_switch: Callable[[], bool] | None = None,
        arm_kill_switch: Callable[[], Any] | None = None,
        log_dir: Path | None = None,
    ):
        configured_limit = _configured_max_steps()
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer.")
        self.max_steps = (
            configured_limit
            if max_steps == DEFAULT_MAX_STEPS and os.environ.get("JARVIS_AGENT_MAX_STEPS")
            else min(max_steps, configured_limit)
        )
        if isinstance(step_timeout, bool) or not isinstance(step_timeout, int) or not 1 <= step_timeout <= MAX_STEP_TIMEOUT:
            raise ValueError(f"step_timeout must be an integer from 1 to {MAX_STEP_TIMEOUT}.")
        if isinstance(no_change_limit, bool) or not isinstance(no_change_limit, int) or no_change_limit < 1:
            raise ValueError("no_change_limit must be a positive integer.")

        self.step_timeout = step_timeout
        self.no_change_limit = no_change_limit
        self._confirm_session = confirm_session
        self._planner = planner or _gemini_plan
        self._capture = capture or computer_use.capture_screen
        self._ocr = ocr or computer_use.ocr_screen
        self._uia_tree = uia_tree or computer_use.active_window_tree
        self._execute_input = execute_input or computer_use.execute_input
        self._wait_for_change = wait_for_change or computer_use.wait_for_screen_change
        self._foreground = foreground or computer_use.require_allowed_foreground
        self._hash_frame = hash_frame or computer_use.perceptual_hash
        self._kill_switch = kill_switch or computer_use.emergency_stop_triggered
        self._arm_kill_switch = arm_kill_switch or computer_use.arm_emergency_stop
        self._log_dir = log_dir or Path(__file__).resolve().parent.parent / "logs"
        self._log_path = self._log_dir / (
            "agent_loop_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".log"
        )

    async def _invoke(self, function: Callable, *args, **kwargs):
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)
        result = await asyncio.to_thread(function, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _check_session(self, expected: tuple[int, str]) -> str | None:
        if self._kill_switch():
            return "killed"
        try:
            current = self._foreground()
        except Exception as exc:
            return f"failed: foreground unavailable: {exc}"
        if current != expected:
            return "failed: foreground window changed; agent stopped."
        return None

    def _log_step(
        self,
        step: int,
        plan: dict[str, Any],
        timestamp: str,
        screen_hash: str,
    ) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "step": step,
            "action": plan.get("action"),
            "target": plan.get("target"),
            "timestamp": timestamp,
            "screenshot_hash": screen_hash,
        }
        with self._log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def run(self, goal: str) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string.")
        goal = goal.strip()
        prompt = (
            f"Obiettivo: {goal}. Procedo con un massimo di {self.max_steps} azioni? "
            "Ctrl+Alt+Esc interrompe. Le immagini dello schermo saranno inviate a "
            "Gemini cloud per pianificare le azioni. Risponda «Sì, procedo»."
        )
        if self._confirm_session is None:
            return {"result": "cancelled"}
        approved = await self._invoke(self._confirm_session, prompt)
        if approved is not True:
            return {"result": "cancelled"}

        try:
            await self._invoke(self._arm_kill_switch)
            expected_foreground = await self._invoke(self._foreground)
        except Exception as exc:
            return {"result": "failed", "reason": f"Input disabled: {exc}"}

        history: list[dict[str, Any]] = []
        unchanged_steps = 0
        for step in range(1, self.max_steps + 1):
            stopped = self._check_session(expected_foreground)
            if stopped:
                if stopped == "killed":
                    return {"result": "killed"}
                return {"result": "failed", "reason": stopped.removeprefix("failed: ")}

            try:
                frame, monitor = await self._invoke(self._capture)
                screen_hash = await self._invoke(self._hash_frame, frame)
                stopped = self._check_session(expected_foreground)
                if stopped:
                    if stopped == "killed":
                        return {"result": "killed"}
                    return {"result": "failed", "reason": stopped.removeprefix("failed: ")}
                words = await self._invoke(
                    self._ocr, image=frame, monitor=monitor
                )
                stopped = self._check_session(expected_foreground)
                if stopped:
                    if stopped == "killed":
                        return {"result": "killed"}
                    return {"result": "failed", "reason": stopped.removeprefix("failed: ")}
                tree = await self._invoke(self._uia_tree)
                stopped = self._check_session(expected_foreground)
                if stopped:
                    if stopped == "killed":
                        return {"result": "killed"}
                    return {"result": "failed", "reason": stopped.removeprefix("failed: ")}
                elements = {"ocr": words, "uia": tree}
                plan = _decode_plan(await asyncio.wait_for(
                    self._invoke(
                        self._planner,
                        goal,
                        elements,
                        history.copy(),
                        step,
                        frame,
                        self.step_timeout,
                    ),
                    timeout=self.step_timeout,
                ))
                timestamp = datetime.now().astimezone().isoformat()
                self._log_step(step, plan, timestamp, screen_hash)

                if plan["action"] == "done":
                    return {
                        "result": "success",
                        "steps": len(history),
                        "reason": plan.get("reason", ""),
                    }
                if plan["action"] == "fail":
                    return {
                        "result": "failed",
                        "reason": plan.get("reason") or "Gemini could not complete the goal.",
                        "steps": len(history),
                    }

                stopped = self._check_session(expected_foreground)
                if stopped:
                    if stopped == "killed":
                        return {"result": "killed"}
                    return {"result": "failed", "reason": stopped.removeprefix("failed: ")}
                parameters = _input_for_plan(
                    plan, expected_foreground[0], expected_foreground[1]
                )
                action_result = await self._invoke(self._execute_input, parameters)
                result_text = (
                    json.dumps(action_result, ensure_ascii=False, default=str)
                    if isinstance(action_result, (dict, list))
                    else str(action_result)
                )
                history.append({
                    "action": plan["action"],
                    "target": plan.get("target"),
                    "value": plan.get("value"),
                    "result": result_text[:1000],
                })
                wait_result = await self._invoke(
                    self._wait_for_change,
                    initial_hash=screen_hash,
                    timeout=self.step_timeout,
                )
                stopped = self._check_session(expected_foreground)
                if stopped:
                    if stopped == "killed":
                        return {"result": "killed"}
                    return {"result": "failed", "reason": stopped.removeprefix("failed: ")}
                if isinstance(wait_result, dict):
                    changed = wait_result.get("changed") is True
                else:
                    changed = wait_result is True
                unchanged_steps = 0 if changed else unchanged_steps + 1
                if unchanged_steps >= self.no_change_limit:
                    return {
                        "result": "no_change",
                        "steps": len(history),
                        "reason": "The screen did not change after consecutive actions.",
                    }
            except asyncio.TimeoutError:
                return {
                    "result": "failed",
                    "reason": f"Step {step} exceeded the {self.step_timeout}s timeout.",
                    "steps": len(history),
                }
            except Exception as exc:
                if self._kill_switch():
                    return {"result": "killed"}
                return {
                    "result": "failed",
                    "reason": f"Step {step} failed: {exc}",
                    "steps": len(history),
                }

        return {
            "result": "max_steps",
            "steps": len(history),
            "reason": "The configured action limit was reached.",
        }
