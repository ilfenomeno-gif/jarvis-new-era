from core.action_loader import ActionRegistry
from core.task_runner import TaskRunner, plan_for


def make_registry(log, fail=()):
    from core.action_loader import ActionRecord

    def rec(name, risk):
        def handler(parameters, **_):
            log.append((name, dict(parameters)))
            return "No ready-made model" if name in fail else f"{name} ok"
        return ActionRecord(name=name, description="d", parameters={"type": "OBJECT"}, handler=handler,
                            file=name + ".py", valid=True, risk_class=risk)

    return ActionRegistry({n: rec(n, r) for n, r in (
        ("viewer_3d", "read"), ("search_3d_model", "write"), ("generate_3d_model", "write"),
        ("task_runner_start", "read"))}, lambda m: None)


def runner(log, **kw):
    return TaskRunner(make_registry(log, **kw), run_async=False)


def test_pc_explanation_runs_all_read_steps_without_pausing():
    log = []
    r = runner(log)
    out = r.start("Smonta il PC e spiegami la CPU evidenziandola")
    assert r.status == "done"
    assert [c[1]["mode"] for c in log] == ["load_model", "explode_model", "highlight_part"]
    assert log[0][1]["model"] == "cad/pc.glb" and log[2][1]["part"] == "cpu"
    assert "done" in out


def test_ferrari_task_pauses_on_write_then_continues_after_confirm():
    log = []
    r = runner(log)
    r.start("Cerca una Ferrari, creala in 3D e passala in realistic")
    assert r.status == "awaiting_confirmation" and log == []
    assert "task_runner_confirm" in r.status_text()
    r.confirm()
    assert r.status == "done"
    assert [c[0] for c in log] == ["search_3d_model", "viewer_3d"]
    assert log[0][1]["query"] == "ferrari"
    assert log[1][1] == {"mode": "set_material_style", "style": "realistic"}


def test_failed_search_uses_the_generation_fallback():
    log = []
    r = runner(log, fail=("search_3d_model",))
    r.start("Cerca una Ferrari, creala in 3D e passala in realistic")
    r.confirm()
    assert [c[0] for c in log] == ["search_3d_model", "generate_3d_model", "viewer_3d"]
    assert r.status == "done"


def test_cancel_stops_before_running_write_steps():
    log = []
    r = runner(log)
    r.start("Cerca una Ferrari, creala in 3D e passala in realistic")
    assert r.cancel() == "Task cancelled."
    assert r.status == "cancelled" and log == []
    assert r.confirm() == "No step is waiting for confirmation."


def test_custom_steps_validation_and_single_task():
    log = []
    r = runner(log)
    assert "Invalid plan" in r.start("x", [{"tool": "nope"}])
    assert "Invalid plan" in r.start("x", [{"tool": "task_runner_start"}])
    assert "could not plan" in r.start("racconta una barzelletta")
    r.start("x", [{"tool": "viewer_3d", "args": {"mode": "clear_model"}},
                  {"tool": "generate_3d_model", "args": {"prompt": "a"}}])
    assert r.status == "awaiting_confirmation"
    assert "already active" in r.start("y", [{"tool": "viewer_3d"}])


def test_async_run_completes_in_background():
    log = []
    r = TaskRunner(make_registry(log))
    r.start("Smonta il PC e spiegami la RAM")
    r.wait(5)
    assert r.status == "done" and log[-1][1]["part"] == "ram"


def test_plan_for_unknown_objective_is_empty():
    assert plan_for("che ore sono") == []


def test_snapshot_reports_real_progress_for_idle_waiting_and_done_tasks():
    r = runner([])
    assert r.snapshot() == {
        "status": "idle", "completed": 0, "total": 0, "progress": 0,
    }
    r.start("x", [{"tool": "search_3d_model", "args": {"query": "q"}}])
    assert r.snapshot() == {
        "status": "awaiting_confirmation", "completed": 0, "total": 1, "progress": 0,
    }
    r.confirm()
    assert r.snapshot() == {
        "status": "done", "completed": 1, "total": 1, "progress": 100,
    }


def test_direct_write_action_is_tracked_and_completes_without_confirmation():
    log = []
    r = runner(log)

    result = r.run_direct("generate_3d_model", {"prompt": "a shiny red apple"})

    assert result == "generate_3d_model ok"
    assert log == [("generate_3d_model", {"prompt": "a shiny red apple"})]
    assert r.snapshot() == {
        "status": "done", "completed": 1, "total": 1, "progress": 100,
    }


def test_direct_write_action_does_not_replace_an_active_plan():
    log = []
    r = runner(log)
    r.start("x", [{"tool": "search_3d_model", "args": {"query": "q"}}])

    assert r.run_direct("generate_3d_model", {"prompt": "apple"}) is None
    assert r.status == "awaiting_confirmation" and log == []


def test_live_tool_dispatch_tracks_single_generation_without_confirmation(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    import main
    from core import task_runner as task_runner_module
    from core.action_loader import ActionRecord

    calls = []

    def generate(parameters, player=None):
        calls.append((parameters, player))
        return "Model generated and shown."

    registry = ActionRegistry(
        {
            "generate_3d_model": ActionRecord(
                name="generate_3d_model",
                description="Generate a model",
                parameters={"type": "OBJECT"},
                handler=generate,
                valid=True,
                risk_class="write",
            )
        },
        lambda _message: None,
    )

    class Ui:
        muted = False

        def set_state(self, _state):
            pass

    ui = Ui()
    r = TaskRunner(
        registry,
        lambda: {"player": ui},
        run_async=False,
        checkpoint_path=tmp_path / "task.json",
    )
    monkeypatch.setattr(task_runner_module, "get_runner", lambda: r)
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    jarvis = object.__new__(main.JarvisLive)
    jarvis.ui = ui
    jarvis._last_user_text = "crea una mela"
    jarvis.speak = lambda _text: None
    jarvis._action_registry = registry
    call = SimpleNamespace(
        id="generation-test",
        name="generate_3d_model",
        args={"prompt": "a shiny red apple"},
    )

    response = asyncio.run(jarvis._execute_tool(call))

    assert response.response["result"] == "Model generated and shown."
    assert calls == [({"prompt": "a shiny red apple"}, ui)]
    assert r.snapshot() == {
        "status": "done", "completed": 1, "total": 1, "progress": 100,
    }


def test_action_files_expose_the_four_tools():
    from pathlib import Path
    from core.action_loader import discover_actions
    names = discover_actions(Path(__file__).resolve().parent.parent / "actions", logger=lambda m: None).names()
    assert {"search_3d_model", "task_runner_start", "task_runner_status",
            "task_runner_cancel", "task_runner_confirm"} <= names


def test_read_step_with_write_fallback_requires_confirmation():
    log = []
    r = runner(log, fail=("viewer_3d",))
    r.start("x", [{"tool": "viewer_3d", "args": {"mode": "load_model"},
                   "fallback": {"tool": "generate_3d_model", "args": {"prompt": "a"}}}])
    assert r.status == "awaiting_confirmation" and log == []
    r.confirm()
    assert [c[0] for c in log] == ["viewer_3d", "generate_3d_model"]


def test_cancelled_thread_cannot_touch_new_run():
    import threading
    log, gate = [], threading.Event()
    reg = make_registry(log)
    slow = reg._actions["viewer_3d"].handler

    def blocking(parameters, **kw):
        gate.wait(5)
        return slow(parameters, **kw)

    reg._actions["viewer_3d"].handler = blocking
    r = TaskRunner(reg)
    r.start("a", [{"tool": "viewer_3d", "args": {"mode": "one"}}, {"tool": "viewer_3d", "args": {"mode": "two"}}])
    old = r._thread
    r.cancel()
    r.start("b", [{"tool": "search_3d_model", "args": {"query": "q"}}])
    gate.set()
    old.join(5)
    assert r.objective == "b" and r.status == "awaiting_confirmation" and r.index == 0
    assert [c[1].get("mode") for c in log] == ["one"]


def test_checkpoint_is_written(tmp_path):
    import json
    path = tmp_path / "cp.json"
    r = TaskRunner(make_registry([]), run_async=False, checkpoint_path=path)
    r.start("Smonta il PC e spiegami la RAM")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "done" and len(data["steps"]) == 3 and data["run_id"]
