import pytest

from core.internal_workflow import (
    FABLES_CHECKLIST,
    FABLES_WORLD_URL,
    InternalWorkflowStore,
    is_fables_request,
)


def test_fables_plan_is_persistent_idempotent_and_records_prompt_policy(tmp_path):
    database = tmp_path / "jarvis-private.sqlite3"
    first_store = InternalWorkflowStore(database)
    first = first_store.create_fables_plan(
        "Jarvis, puoi creare mondi su Fables?",
        FABLES_WORLD_URL,
    )
    second = InternalWorkflowStore(database).create_fables_plan(
        "Pianifica il mondo",
        FABLES_WORLD_URL,
    )

    assert first["id"] == second["id"]
    assert first["status"] == "planned"
    assert len(first["categories"]) == 12 == len(FABLES_CHECKLIST)
    assert first["plan"]["decisions"]["other_unique_modes"].startswith("solo valutazione")
    assert first["plan"]["reasoning_policy"].startswith("Ragionamento interno")
    assert not list(tmp_path.glob("*.txt"))


def test_sensitive_fables_features_are_explicitly_disabled(tmp_path):
    workflow = InternalWorkflowStore(tmp_path / "state.sqlite3").create_fables_plan(
        "Pianifica la creazione del mondo",
        FABLES_WORLD_URL,
    )
    categories = {step["step_key"]: step for step in workflow["categories"]}

    assert categories["5e_defaults"]["enabled"] is False
    assert categories["areas"]["enabled"] is False
    assert categories["points_of_interest"]["enabled"] is False
    assert categories["5e_defaults"]["state"] == "excluded"
    assert categories["areas"]["state"] == "excluded"
    assert categories["points_of_interest"]["state"] == "excluded"
    assert categories["unique_modes"]["state"] == "planned"
    assert all(
        categories[key]["state"] == "planned"
        for key in ("races", "classes", "feats", "monsters", "items", "spells")
    )


def test_simulation_records_acceptance_and_stops_at_unverified_transition(tmp_path):
    store = InternalWorkflowStore(tmp_path / "simulation.sqlite3")
    workflow = store.create_fables_plan(
        "Simula la richiesta accettata ma senza transizione.",
        FABLES_WORLD_URL,
        simulated=True,
    )

    result = store.run_fables_simulation(workflow["id"])
    phases = {step["step_key"]: step for step in result["simulation_steps"]}
    event_keys = [event["event_key"] for event in result["events"]]

    assert result["status"] == "blocked"
    assert result["cycles"] == 4
    assert phases["request_received"]["state"] == "done"
    assert phases["request_accepted"]["state"] == "done"
    assert phases["world_transition"]["state"] == "needs_review"
    assert phases["diagnosis"]["state"] == "done"
    assert "transizione" in phases["diagnosis"]["evidence"]
    assert event_keys.count("simulation:request_accepted") == 1
    assert all(
        next(step for step in result["categories"] if step["step_key"] == key)["state"] == "excluded"
        for key in ("areas", "points_of_interest", "5e_defaults")
    )


def test_repeated_simulation_is_idempotent_and_does_not_repeat_acceptance(tmp_path):
    store = InternalWorkflowStore(tmp_path / "repeat.sqlite3")
    workflow = store.create_fables_plan(
        "Simula l'accettazione Fables.",
        FABLES_WORLD_URL,
        simulated=True,
    )
    first = store.run_fables_simulation(workflow["id"])
    repeated = store.run_fables_simulation(workflow["id"])

    assert repeated["cycles"] == first["cycles"] == 4
    assert [event["event_key"] for event in repeated["events"]].count(
        "simulation:request_accepted"
    ) == 1
    assert repeated["status"] == "blocked"


def test_paused_simulation_resumes_from_checkpoint_without_replaying_done_steps(tmp_path):
    store = InternalWorkflowStore(tmp_path / "resume.sqlite3")
    workflow = store.create_fables_plan(
        "Simula e riprendi il task Fables.",
        FABLES_WORLD_URL,
        simulated=True,
    )
    store._advance_simulation_step(
        workflow["id"],
        next(
            step for step in workflow["simulation_steps"] if step["step_key"] == "request_received"
        ),
    )
    store.pause(workflow["id"], "Interruzione simulata dopo il checkpoint.")

    resumed = store.resume_fables_simulation(workflow["id"])

    assert resumed["status"] == "blocked"
    assert resumed["cycles"] == 4
    assert [event["event_key"] for event in resumed["events"]].count(
        "simulation:request_received"
    ) == 1


def test_interrupted_simulation_resumes_from_sqlite_state(tmp_path):
    import sqlite3

    store = InternalWorkflowStore(tmp_path / "interrupted.sqlite3")
    workflow = store.create_fables_plan(
        "Simula un'interruzione dopo la richiesta ricevuta.",
        FABLES_WORLD_URL,
        simulated=True,
    )
    store._advance_simulation_step(
        workflow["id"],
        next(
            step for step in workflow["simulation_steps"] if step["step_key"] == "request_received"
        ),
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE workflows SET status = 'running' WHERE id = ?",
            (workflow["id"],),
        )

    resumed = store.resume_fables_simulation(workflow["id"])

    assert resumed["status"] == "blocked"
    assert resumed["cycles"] == 4
    assert [event["event_key"] for event in resumed["events"]].count(
        "simulation:request_received"
    ) == 1


def test_configured_cycle_limit_stops_before_unbounded_work(tmp_path):
    store = InternalWorkflowStore(tmp_path / "bounded.sqlite3")
    workflow = store.create_fables_plan(
        "Simula con un limite ridotto.",
        FABLES_WORLD_URL,
        simulated=True,
        max_cycles=2,
    )

    result = store.run_fables_simulation(workflow["id"])

    assert result["status"] == "paused"
    assert result["cycles"] == 2
    assert result["checkpoint"] == "request_accepted"
    assert sum(step["state"] == "pending" for step in result["simulation_steps"]) == 2


@pytest.mark.parametrize(
    "url",
    (
        "http://play.fables.gg/worlds/example",
        "https://fables.gg.evil.example/worlds/example",
        "https://example.com/worlds/example",
    ),
)
def test_fables_workflow_rejects_non_fables_or_non_https_urls(tmp_path, url):
    store = InternalWorkflowStore(tmp_path / "invalid.sqlite3")

    with pytest.raises(ValueError, match="https"):
        store.create_fables_plan("Pianifica Fables", url)


def test_fables_request_detection_covers_world_questions_and_failure_diagnosis():
    assert is_fables_request("Puoi creare mondi su https://fables.gg/?")
    assert is_fables_request("La richiesta Fables viene accettata ma non va.")
    assert not is_fables_request("Puoi creare mondi fantasy?")


def test_non_simulated_workflow_cannot_run_simulation(tmp_path):
    store = InternalWorkflowStore(tmp_path / "no-live.sqlite3")
    workflow = store.create_fables_plan("Pianifica un mondo.", FABLES_WORLD_URL)

    with pytest.raises(ValueError, match="explicitly enabled"):
        store.run_fables_simulation(workflow["id"])


def test_main_cli_simulation_uses_private_store_and_no_external_world_actions(
    tmp_path,
    monkeypatch,
):
    from main import _run_fables_workflow_action

    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(tmp_path / "cli.sqlite3"))
    store = InternalWorkflowStore(tmp_path / "cli.sqlite3")
    plan = store.create_fables_plan(
        "Crea e diagnostica in simulazione.",
        FABLES_WORLD_URL,
        simulated=True,
    )
    assert (
        "nessuna modifica al mondo"
        in _run_fables_workflow_action({"action": "status", "workflow_id": plan["id"]}).casefold()
    )
    result = _run_fables_workflow_action(
        {
            "action": "simulate",
            "objective": "Simula richiesta accettata ma senza passaggio al mondo.",
            "world_url": FABLES_WORLD_URL,
        }
    )
    assert "Workflow Fables blocked" in result


def test_main_text_command_answers_fables_capability_without_api_or_browser(
    tmp_path,
    monkeypatch,
):
    import main

    class UI:
        def __init__(self):
            self.logs = []

        def write_log(self, text):
            self.logs.append(text)

    class HUD:
        def __init__(self):
            self.messages = []

        def push_chat(self, role, text):
            self.messages.append((role, text))

    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(tmp_path / "main.sqlite3"))
    jarvis = object.__new__(main.JarvisLive)
    jarvis.ui = UI()
    jarvis._hud = HUD()
    jarvis._asst_name = "JARVIS"
    jarvis._session_log = []
    jarvis._loop = None

    jarvis._on_text_command("Jarvis, puoi creare mondi su https://fables.gg/?")

    assert jarvis._hud.messages[0] == (
        "user",
        "Jarvis, puoi creare mondi su https://fables.gg/?",
    )
    assert jarvis._hud.messages[1][0] == "assistant"
    assert "12 voci pianificate" in jarvis._hud.messages[1][1]
    assert "nessuna modifica al mondo" in jarvis._hud.messages[1][1]
    assert len(jarvis._session_log) == 2


def test_main_text_command_simulates_accept_but_no_progress(tmp_path, monkeypatch):
    import main

    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(tmp_path / "accepted-stall.sqlite3"))
    jarvis = object.__new__(main.JarvisLive)

    reply = jarvis._handle_internal_fables_request("Fables request accepted but it doesn't go.")

    assert reply is not None
    assert "Workflow Fables blocked" in reply
    assert "non determinabile" in reply
    assert "nessuna modifica al mondo" in reply


def test_main_capability_request_prefers_world_url_over_fables_homepage(
    tmp_path,
    monkeypatch,
):
    import sqlite3
    import main

    database = tmp_path / "world-url.sqlite3"
    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(database))
    jarvis = object.__new__(main.JarvisLive)
    world_url = FABLES_WORLD_URL

    reply = jarvis._handle_internal_fables_request(
        "Jarvis, puoi creare mondi su https://fables.gg/ ? "
        f"Il mondo è {world_url}"
    )

    assert reply is not None
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT world_url FROM workflows").fetchall()
    assert rows == [(world_url,)]


def test_read_only_live_preflight_records_evidence_without_clicking(tmp_path):
    import json

    from core.fables_live import run_read_only_preflight

    store = InternalWorkflowStore(tmp_path / "live-preflight.sqlite3")
    calls = []

    def browser_action(parameters):
        calls.append(parameters)
        if parameters["action"] == "get_url":
            return FABLES_WORLD_URL
        if parameters["action"] == "go_to":
            return f"Opened: {parameters['url']}"
        if parameters["action"] == "get_text":
            return "Untitled World. No invitation or request is visible."
        raise AssertionError(f"Unexpected browser action: {parameters}")

    workflow = run_read_only_preflight(store, FABLES_WORLD_URL, browser_action)

    assert workflow["status"] == "blocked"
    assert [call["action"] for call in calls] == [
        "get_url",
        "go_to",
        "get_url",
        "get_text",
    ]
    event = next(event for event in workflow["events"] if event["event_type"] == "live_observation")
    evidence = json.loads(event["evidence"])
    assert evidence["before_url"] == FABLES_WORLD_URL
    assert evidence["after_url"] == FABLES_WORLD_URL
    assert evidence["mutations_performed"] is False
    assert evidence["request_state"].startswith("not established")
    assert evidence["network_or_console_evidence"].startswith("unavailable")


def test_live_cli_requires_both_flags_and_exact_runtime_confirmation(
    tmp_path,
    monkeypatch,
):
    import main

    actions = []
    output = []
    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(tmp_path / "cli-live.sqlite3"))

    assert main._handle_fables_cli(
        ["--simulate-fables-workflow", "--live-fables-workflow"],
        browser_action=lambda parameters: actions.append(parameters),
        output=output.append,
    ) == 2
    assert actions == []

    assert main._handle_fables_cli(
        ["--live-fables-workflow"],
        browser_action=lambda parameters: actions.append(parameters),
        output=output.append,
    ) == 2
    assert actions == []

    assert main._handle_fables_cli(
        ["--live-fables-workflow", "--confirm-live"],
        input_fn=lambda _prompt: "no",
        browser_action=lambda parameters: actions.append(parameters),
        output=output.append,
    ) == 2
    assert actions == []

    world_url = FABLES_WORLD_URL
    expected = f"AUTORIZZO SOLO ISPEZIONE FABLES {world_url}"
    assert main._handle_fables_cli(
        [
            "--live-fables-workflow",
            "--world",
            world_url,
            "--confirm-live",
        ],
        input_fn=lambda _prompt: expected,
        browser_action=lambda parameters: (
            actions.append(parameters)
            or {
                "get_url": world_url,
                "go_to": f"Opened: {world_url}",
                "get_text": "Untitled World; no request visible.",
            }[parameters["action"]]
        ),
        output=output.append,
    ) == 0
    assert [call["action"] for call in actions] == [
        "get_url",
        "go_to",
        "get_url",
        "get_text",
    ]
    assert any("Accettazione e popolamento non eseguiti" in line for line in output)


def test_local_tool_cycle_limit_is_configurable_and_bounded(monkeypatch):
    from main import _configured_local_tool_cycles

    monkeypatch.delenv("JARVIS_LOCAL_TOOL_CYCLES", raising=False)
    assert _configured_local_tool_cycles() == 12
    monkeypatch.setenv("JARVIS_LOCAL_TOOL_CYCLES", "20")
    assert _configured_local_tool_cycles() == 20
    monkeypatch.setenv("JARVIS_LOCAL_TOOL_CYCLES", "51")
    with pytest.raises(ValueError, match="between 1 and 50"):
        _configured_local_tool_cycles()
