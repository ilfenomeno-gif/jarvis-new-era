"""TaskRunner: runs a planned sequence of tools on its own. No Qt imports.

Steps are {"tool", "args"} (optionally "fallback": another step, used when the tool fails).
`read` actions run back to back; the first `write` or `destructive` action pauses the task
(status ``awaiting_confirmation``) until task_runner_confirm, so the user always approves
changes. Narration stays with the model: the runner only drives tools.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Callable

MAX_STEPS = 12
_RISK_ORDER = {"read": 0, "write": 1, "destructive": 2}


def _risk_rank(risk: str) -> int:
    return _RISK_ORDER.get(risk, 1)  # unknown classes are treated as write
_FAIL_PREFIXES = ("No ready-made", "Invalid request", "3D generation failed", "Action '", "Tool '")
_PART_WORDS = {"cpu": "cpu", "processore": "cpu", "ram": "ram", "memoria": "ram", "ventola": "fan",
               "fan": "fan", "scheda madre": "motherboard", "motherboard": "motherboard", "case": "case"}


class TaskRunner:
    def __init__(self, registry, ctx_factory: Callable[[], dict] | None = None, run_async: bool = True,
                 checkpoint_path: str | Path | None = None):
        self._registry = registry
        self._ctx = ctx_factory or (lambda: {})
        self._async = run_async
        self._checkpoint = Path(checkpoint_path) if checkpoint_path else None
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self.objective = ""
        self.steps: list[dict] = []
        self.index = 0
        self.status = "idle"
        self._run_id: str | None = None
        self._thread: threading.Thread | None = None

    def _save(self) -> None:
        """Atomically serialise the task so it can be inspected/resumed after a crash."""
        if self._checkpoint is None:
            return
        with self._lock:
            data = {"run_id": self._run_id, "objective": self.objective, "status": self.status,
                    "index": self.index, "steps": self.steps}
            try:
                self._checkpoint.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._checkpoint.with_name(self._checkpoint.name + ".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                os.replace(tmp, self._checkpoint)
            except OSError:
                pass

    # ---- public API -------------------------------------------------
    def start(self, objective: str, steps=None) -> str:
        with self._lock:
            if self.status in ("running", "awaiting_confirmation"):
                return "A task is already active. Use task_runner_status, or task_runner_cancel first."
            plan = steps if steps else plan_for(objective)
            try:
                plan = self._normalise(plan)
            except ValueError as exc:
                return f"Invalid plan: {exc}"
            if not plan:
                return ("I could not plan this objective automatically. Pass 'steps' "
                        "(a list of {tool, args}) or run the tools one by one.")
            self._reset()
            self.objective, self.steps, self.status = objective, plan, "running"
            self._run_id = uuid.uuid4().hex
            run_id = self._run_id
            self._save()
        self._go(run_id)
        return self.status_text()

    def run_direct(self, tool: str, args: dict) -> str | None:
        """Track an explicitly requested single write action without a second approval prompt."""
        with self._lock:
            if self.status in ("running", "awaiting_confirmation"):
                return None
            plan = self._normalise([{"tool": tool, "args": args}])
            if plan[0]["risk"] != "write":
                raise ValueError("direct task tracking only accepts write actions")
            self._reset()
            self.objective = f"Direct action: {tool}"
            self.steps = plan
            self.steps[0]["confirmed"] = True
            self.status = "running"
            self._run_id = uuid.uuid4().hex
            run_id = self._run_id
            self._save()

        self._loop(run_id)
        with self._lock:
            return self.steps[0]["result"]

    def confirm(self) -> str:
        with self._lock:
            if self.status != "awaiting_confirmation":
                return "No step is waiting for confirmation."
            self.steps[self.index]["confirmed"] = True
            self.status = "running"
            run_id = self._run_id
            self._save()
        self._go(run_id)
        return self.status_text()

    def cancel(self) -> str:
        with self._lock:
            if self.status not in ("running", "awaiting_confirmation"):
                return "No active task to cancel."
            self._run_id = None  # invalidates any thread still working on this run
            self.status = "cancelled"
            for step in self.steps[self.index:]:
                if step["state"] in ("pending", "awaiting_confirmation"):
                    step["state"] = "cancelled"
            self._save()
        return "Task cancelled."

    def wait(self, timeout: float = 30.0) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def status_text(self) -> str:
        with self._lock:
            if self.status == "idle":
                return "No task has been started."
            lines = [f"Task '{self.objective}': {self.status}"]
            for i, step in enumerate(self.steps, 1):
                detail = f" -> {step['result'][:160]}" if step.get("result") else ""
                lines.append(f"{i}. {step['tool']} [{step['state']}]{detail}")
            if self.status == "awaiting_confirmation":
                step = self.steps[self.index]
                lines.append(f"Waiting for the user's OK before running {step['tool']} ({step['risk']}). "
                             "Ask them, then call task_runner_confirm (or task_runner_cancel).")
            return "\n".join(lines)

    def snapshot(self) -> dict[str, int | str]:
        """Return a small, lock-protected status summary for the HUD."""
        with self._lock:
            total = len(self.steps)
            completed = sum(step["state"] == "done" for step in self.steps)
            progress = 100 if self.status == "done" else (
                round(completed * 100 / total) if total else 0
            )
            return {
                "status": self.status,
                "completed": completed,
                "total": total,
                "progress": progress,
            }

    # ---- internals --------------------------------------------------
    def _normalise(self, plan) -> list[dict]:
        if not isinstance(plan, list) or len(plan) > MAX_STEPS:
            raise ValueError(f"steps must be a list of at most {MAX_STEPS} items")
        out = []
        for raw in plan:
            step = self._one(raw)
            if isinstance(raw, dict) and isinstance(raw.get("fallback"), dict):
                step["fallback"] = self._one(raw["fallback"])
                # the fallback can run without a second prompt, so gate on the worst case
                step["risk"] = max(step["risk"], step["fallback"]["risk"], key=_risk_rank)
            out.append(step)
        return out

    def _one(self, raw) -> dict:
        tool = raw.get("tool") if isinstance(raw, dict) else None
        if not tool or not self._registry.has(tool) or tool.startswith("task_runner"):
            raise ValueError(f"unknown or not allowed tool: {tool!r}")
        args = raw.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("args must be an object")
        return {"tool": tool, "args": dict(args), "risk": self._registry.risk_class(tool),
                "state": "pending", "result": "", "confirmed": False}

    def _go(self, run_id: str) -> None:
        if self._async:
            self._thread = threading.Thread(target=self._loop, args=(run_id,), name="task-runner", daemon=True)
            self._thread.start()
        else:
            self._loop(run_id)

    def _loop(self, run_id: str) -> None:
        while True:
            with self._lock:
                if self._run_id != run_id or self.status != "running":
                    return
                if self.index >= len(self.steps):
                    self.status = "done"
                    self._save()
                    return
                step = self.steps[self.index]
                if step["risk"] != "read" and not step["confirmed"]:
                    step["state"] = "awaiting_confirmation"
                    self.status = "awaiting_confirmation"
                    self._save()
                    return
                step["state"] = "running"
                self._save()
            self._run_step(step, run_id)
            with self._lock:
                if self._run_id != run_id:
                    return
                if step["state"] == "failed":
                    self.status = "failed"
                    self._save()
                    return
                self.index += 1
                self._save()

    def _run_step(self, step: dict, run_id: str) -> None:
        for candidate in (step, step.get("fallback")):
            if not candidate:
                continue
            with self._lock:
                if self._run_id != run_id:
                    return
            args = dict(candidate["args"])
            if candidate["risk"] == "destructive":
                args["confirmed"] = True
            try:
                result = str(self._registry.run(candidate["tool"], args, self._ctx()))
            except Exception as exc:
                result = f"Tool '{candidate['tool']}' failed: {exc}"
            step["result"] = result
            if not result.startswith(_FAIL_PREFIXES):
                step["state"] = "done"
                return
        step["state"] = "failed"


_RUNNER: TaskRunner | None = None


def configure(registry, ctx_factory: Callable[[], dict] | None = None) -> TaskRunner:
    """Called by main.py once the action registry exists."""
    global _RUNNER
    _RUNNER = TaskRunner(registry, ctx_factory,
                         checkpoint_path=Path(__file__).resolve().parent.parent / "config" / "task_checkpoint.json")
    return _RUNNER


def get_runner() -> TaskRunner | None:
    return _RUNNER


def plan_for(objective: str) -> list[dict]:
    """Deterministic plans for the known multi-step requests; [] when unsure."""
    text = str(objective or "").lower()
    plan: list[dict] = []
    wants_pc = re.search(r"\b(pc|computer)\b", text) is not None
    if wants_pc and re.search(r"smonta|esplod|disassembl|explode|spiega|explain", text):
        plan += [{"tool": "viewer_3d", "args": {"mode": "load_model", "model": "cad/pc.glb"}},
                 {"tool": "viewer_3d", "args": {"mode": "explode_model"}}]
        for word, part in _PART_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                plan.append({"tool": "viewer_3d", "args": {"mode": "highlight_part", "part": part}})
                break
        return plan
    found = re.search(r"cerca(?:re)?\s+(?:una?\s+|un'|il\s+|la\s+)?(.+?)(?:\s+(?:su\s+google|online|sul web))?\s*(?:,|\be\b|\bpoi\b|$)", text)
    if found and re.search(r"\b3d\b|ologramm|hologram", text):
        query = found.group(1).strip()
        plan = [{"tool": "search_3d_model", "args": {"query": query},
                 "fallback": {"tool": "generate_3d_model", "args": {"prompt": query}}}]
        style = next((s for s in ("realistic", "blueprint", "toon", "flat", "hologram") if s in text), None)
        if style:
            plan.append({"tool": "viewer_3d", "args": {"mode": "set_material_style", "style": style}})
        return plan
    return []
