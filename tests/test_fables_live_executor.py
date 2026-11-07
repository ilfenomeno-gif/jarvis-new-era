from __future__ import annotations

import json
from dataclasses import replace

import pytest

from core.fables_live_executor import (
    FablesFormMapping,
    FablesLiveExecutor,
    LiveExecutionBlocked,
    select_world_url,
)
from core.fables_world import WORLD_CATEGORIES, WorldElement, WorldModel
from core.internal_workflow import FABLES_WORLD_URL


def _world() -> WorldModel:
    elements = tuple(
        WorldElement(
            id=f"entry-{category}",
            category=category,
            name=f"Entry {category}",
            card={"summary": f"Design card for {category}."},
            consistency="Matches the world premise and established facts.",
            links=(
                f"entry-{WORLD_CATEGORIES[(index + 1) % len(WORLD_CATEGORIES)]}",
            ),
        )
        for index, category in enumerate(WORLD_CATEGORIES)
    )
    return WorldModel(
        id="live-test-world",
        name="The Meridian",
        premise="A world organized around a luminous inland sea.",
        elements=elements,
    )


def _mappings() -> dict[str, FablesFormMapping]:
    return {
        category: FablesFormMapping(
            create_label=f"Add {category}",
            name_label="Name",
            card_label="Description",
            submit_label="Save",
        )
        for category in WORLD_CATEGORIES
    }


def _adapters(*, network_status=201):
    current_url = ["https://fables.gg/"]
    visible_text = [""]
    responses: list[dict] = []
    browser_calls: list[dict] = []
    input_calls: list[dict] = []

    def browser_action(parameters):
        browser_calls.append(dict(parameters))
        action = parameters["action"]
        if action == "get_url":
            return current_url[0]
        if action == "go_to":
            current_url[0] = parameters["url"]
            return f"Opened: {current_url[0]}"
        if action == "get_text":
            return visible_text[0]
        if action == "get_diagnostics":
            return json.dumps(
                {
                    "network_responses": list(responses),
                    "dom_errors": [],
                    "console_errors": [],
                }
            )
        if action == "clear_diagnostics":
            responses.clear()
            return "Browser diagnostics cleared."
        if action == "wait":
            return f"Waited {parameters.get('seconds', 1)}s."
        if action == "smart_click":
            return f"Clicked: {parameters['description']}"
        if action == "smart_type":
            return f"Typed: {parameters['description']}"
        raise AssertionError(f"Unexpected browser action: {parameters}")

    def input_action(parameters):
        input_calls.append(dict(parameters))
        if parameters["action"] == "screen_click":
            visible_text[0] = parameters["description"]
            if network_status is not None:
                responses.append(
                    {"method": "POST", "url": "/api/world/elements", "status": network_status}
                )
            # The mock confirms only a UI-level observation for the name saved last.
            if network_status is not None and network_status in range(200, 300):
                last_name = next(
                    (
                        call.get("text")
                        for call in reversed(browser_calls)
                        if call.get("action") == "smart_type"
                        and call.get("description") == "Name"
                    ),
                    "",
                )
                visible_text[0] += f" {last_name}"
            return f"Clicked {parameters['description']}"
        raise AssertionError(f"Unexpected input action: {parameters}")

    return browser_action, input_action, browser_calls, input_calls


def _execute(executor, browser_action, input_action, **kwargs):
    return executor.execute(
        _world(),
        FABLES_WORLD_URL,
        _mappings(),
        live_flag=True,
        confirm_live=True,
        runtime_confirmation=f"AUTORIZZO ESECUZIONE FABLES {FABLES_WORLD_URL}",
        browser_action=browser_action,
        input_action=input_action,
        **kwargs,
    )


def test_world_url_selector_prefers_world_path_over_homepage():
    homepage = "https://fables.gg/"
    world_url = FABLES_WORLD_URL

    assert select_world_url([homepage, world_url]) == world_url
    assert select_world_url([homepage], fallback=world_url) == world_url


def test_browser_control_collects_redacted_network_dom_and_console_diagnostics():
    from types import SimpleNamespace

    from actions.browser_control import _BrowserSession

    class FakePage:
        def __init__(self):
            self.handlers = {}

        def on(self, event, callback):
            self.handlers[event] = callback

    session = object.__new__(_BrowserSession)
    session._watched_pages = set()
    session._diagnostics = {
        "network_responses": [],
        "dom_errors": [],
        "console_errors": [],
    }
    page = FakePage()
    session._watch_page(page)
    page.handlers["response"](
        SimpleNamespace(
            request=SimpleNamespace(method="POST"),
            url="https://fables.gg/api/create?access_token=secret",
            status=201,
        )
    )
    page.handlers["pageerror"](RuntimeError("DOM handler failed"))
    page.handlers["console"](SimpleNamespace(type="error", text="Console failure"))

    response = session._diagnostics["network_responses"][0]
    assert response["status"] == 201
    assert response["url"] == "https://fables.gg/api/create"
    assert "secret" not in str(session._diagnostics)
    assert "DOM handler failed" in session._diagnostics["dom_errors"][0]
    assert "Console failure" in session._diagnostics["console_errors"][0]


def test_selector_rejects_non_fables_or_non_world_url():
    with pytest.raises(ValueError, match="/worlds/"):
        select_world_url(["https://example.com/worlds/abc"])
    with pytest.raises(ValueError, match="/worlds/"):
        select_world_url(["https://fables.gg/"])


@pytest.mark.parametrize(
    ("live_flag", "confirm_live", "confirmation"),
    [
        (False, True, f"AUTORIZZO ESECUZIONE FABLES {FABLES_WORLD_URL}"),
        (True, False, f"AUTORIZZO ESECUZIONE FABLES {FABLES_WORLD_URL}"),
        (True, True, "AUTORIZZO ESECUZIONE FABLES wrong world"),
    ],
)
def test_live_executor_requires_flag_and_exact_runtime_confirmation(
    tmp_path,
    live_flag,
    confirm_live,
    confirmation,
):
    browser_action, input_action, browser_calls, input_calls = _adapters()
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")

    with pytest.raises(LiveExecutionBlocked):
        executor.execute(
            _world(),
            FABLES_WORLD_URL,
            _mappings(),
            live_flag=live_flag,
            confirm_live=confirm_live,
            runtime_confirmation=confirmation,
            browser_action=browser_action,
            input_action=input_action,
        )

    assert browser_calls == []
    assert input_calls == []


def test_missing_ui_mapping_blocks_before_browser_or_input_action(tmp_path):
    browser_action, input_action, browser_calls, input_calls = _adapters()
    mappings = _mappings()
    mappings.pop("feats")
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")

    with pytest.raises(LiveExecutionBlocked, match="feats"):
        executor.execute(
            _world(),
            FABLES_WORLD_URL,
            mappings,
            live_flag=True,
            confirm_live=True,
            runtime_confirmation=f"AUTORIZZO ESECUZIONE FABLES {FABLES_WORLD_URL}",
            browser_action=browser_action,
            input_action=input_action,
        )

    assert browser_calls == []
    assert input_calls == []


def test_mocked_live_execution_uses_browser_and_input_and_excludes_categories(tmp_path):
    browser_action, input_action, browser_calls, input_calls = _adapters()
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")

    result = _execute(executor, browser_action, input_action)

    assert result.state == "completed"
    assert len(result.executions) == len(WORLD_CATEGORIES)
    assert result.world_url == FABLES_WORLD_URL
    assert all(item.request_state == "accepted" for item in result.executions)
    assert all(
        any("Risposta network" in evidence for evidence in item.diagnosis.evidence)
        and any("Timestamp UTC" in evidence for evidence in item.diagnosis.evidence)
        for item in result.executions
    )
    assert len(input_calls) == len(WORLD_CATEGORIES)
    assert any(call["action"] == "go_to" for call in browser_calls)
    assert len(result.excluded) == 3
    assert any(item.startswith("areas:") for item in result.excluded)
    assert any(item.startswith("points_of_interest:") for item in result.excluded)
    assert any(item.startswith("5e_defaults:") for item in result.excluded)


def test_live_executor_stops_on_unverified_acceptance_and_persists_diagnosis(tmp_path):
    browser_action, input_action, _, _ = _adapters(network_status=None)
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")

    result = _execute(executor, browser_action, input_action)

    assert result.state == "blocked"
    assert result.executions[0].request_state == "pending"
    assert len(result.executions[0].diagnosis.evidence) >= 3
    assert "Stop on" in result.stop_reason


def test_successful_live_actions_are_idempotently_skipped_on_resume(tmp_path):
    browser_action, input_action, _, input_calls = _adapters()
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")

    first = _execute(executor, browser_action, input_action)
    count_after_first = len(input_calls)
    second = _execute(executor, browser_action, input_action)

    assert first.state == "completed"
    assert second.state == "completed"
    assert second.executions == ()
    assert len(input_calls) == count_after_first


def test_changed_world_element_after_checkpoint_is_blocked_without_resubmission(tmp_path):
    browser_action, input_action, _, input_calls = _adapters()
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")
    first = _execute(executor, browser_action, input_action)
    original_count = len(input_calls)
    changed = _world()
    elements = list(changed.elements)
    elements[0] = replace(
        elements[0],
        card={"summary": "Changed after the live checkpoint."},
    )
    changed = replace(changed, elements=tuple(elements))

    resumed = executor.execute(
        changed,
        FABLES_WORLD_URL,
        _mappings(),
        live_flag=True,
        confirm_live=True,
        runtime_confirmation=f"AUTORIZZO ESECUZIONE FABLES {FABLES_WORLD_URL}",
        browser_action=browser_action,
        input_action=input_action,
    )

    assert first.state == "completed"
    assert resumed.state == "blocked"
    assert "changed after checkpoint" in resumed.stop_reason
    assert len(input_calls) == original_count


def test_live_cli_runs_saved_draft_only_after_runtime_confirmation(tmp_path, monkeypatch):
    import main
    from agents.world_designer_agent import WorldDesignerAgent

    database = tmp_path / "jarvis.sqlite3"
    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(database))
    draft = WorldDesignerAgent(database).design(_world())
    mapping_file = tmp_path / "fables_forms.json"
    mapping_file.write_text(
        json.dumps(
            {
                category: {
                    "create_label": f"Add {category}",
                    "name_label": "Name",
                    "card_label": "Description",
                    "submit_label": "Save",
                }
                for category in WORLD_CATEGORIES
            }
        ),
        encoding="utf-8",
    )
    browser_action, input_action, browser_calls, input_calls = _adapters()
    output = []

    result = main._handle_fables_cli(
        [
            "--live-fables-workflow",
            "--world",
            FABLES_WORLD_URL,
            "--confirm-live",
            "--world-draft-id",
            draft.id,
            "--forms-config",
            str(mapping_file),
        ],
        input_fn=lambda _: f"AUTORIZZO ESECUZIONE FABLES {FABLES_WORLD_URL}",
        browser_action=browser_action,
        input_action=input_action,
        output=output.append,
    )

    assert result == 0
    assert len(input_calls) == len(WORLD_CATEGORIES)
    assert any("Workflow live completed" in line for line in output)
    assert any(call["action"] == "go_to" for call in browser_calls)


@pytest.mark.parametrize(
    ("live_flag", "confirm_live"),
    [(False, True), (True, False)],
)
def test_request_transition_diagnosis_requires_both_live_guards(
    tmp_path, live_flag, confirm_live
):
    browser_action, input_action, browser_calls, input_calls = _adapters()
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")
    request_page = "https://fables.gg/requests/req-42"

    with pytest.raises(LiveExecutionBlocked):
        executor.diagnose_request_transition(
            request_page,
            FABLES_WORLD_URL,
            "req-42",
            "Accept request",
            live_flag=live_flag,
            confirm_live=confirm_live,
            runtime_confirmation=(
                "AUTORIZZO DIAGNOSI RICHIESTA FABLES "
                f"{request_page} -> {FABLES_WORLD_URL} [req-42]"
            ),
            browser_action=browser_action,
            input_action=input_action,
        )

    assert browser_calls == []
    assert input_calls == []


def test_accepted_request_without_url_transition_is_diagnosed_and_not_repeated(tmp_path):
    import sqlite3

    browser_action, input_action, browser_calls, input_calls = _adapters(
        network_status=202
    )
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")
    request_page = "https://fables.gg/requests/req-42"
    confirmation = (
        "AUTORIZZO DIAGNOSI RICHIESTA FABLES "
        f"{request_page} -> {FABLES_WORLD_URL} [req-42]"
    )

    result = executor.diagnose_request_transition(
        request_page,
        FABLES_WORLD_URL,
        "req-42",
        "Accept request",
        live_flag=True,
        confirm_live=True,
        runtime_confirmation=confirmation,
        browser_action=browser_action,
        input_action=input_action,
    )

    assert result.request_state == "accepted"
    assert result.before_url == request_page
    assert result.after_url == request_page
    assert result.diagnosis.cause == "backend_ignored"
    assert len(result.diagnosis.evidence) >= 3
    assert any("Timestamp UTC" in item for item in result.diagnosis.evidence)
    assert any("Risposta network" in item for item in result.diagnosis.evidence)
    assert [call["action"] for call in input_calls] == ["screen_click"]
    assert any(call["action"] == "wait" for call in browser_calls)
    with sqlite3.connect(executor.database_path) as connection:
        row = connection.execute(
            "SELECT state, diagnosis_id, evidence_json FROM fables_live_requests"
        ).fetchone()
    assert row is not None
    assert row[0] == "accepted"
    assert row[1] == result.diagnosis.id
    assert '"request_state": "accepted"' in row[2]

    with pytest.raises(LiveExecutionBlocked, match="already checkpointed"):
        executor.diagnose_request_transition(
            request_page,
            FABLES_WORLD_URL,
            "req-42",
            "Accept request",
            live_flag=True,
            confirm_live=True,
            runtime_confirmation=confirmation,
            browser_action=browser_action,
            input_action=input_action,
        )
    assert [call["action"] for call in input_calls] == ["screen_click"]


def test_request_transition_classifies_permission_error_from_network_response(tmp_path):
    browser_action, input_action, _, _ = _adapters(network_status=403)
    executor = FablesLiveExecutor(tmp_path / "state.sqlite3")
    request_page = "https://fables.gg/requests/req-43"

    result = executor.diagnose_request_transition(
        request_page,
        FABLES_WORLD_URL,
        "req-43",
        "Accept request",
        live_flag=True,
        confirm_live=True,
        runtime_confirmation=(
            "AUTORIZZO DIAGNOSI RICHIESTA FABLES "
            f"{request_page} -> {FABLES_WORLD_URL} [req-43]"
        ),
        browser_action=browser_action,
        input_action=input_action,
    )

    assert result.request_state == "error"
    assert result.diagnosis.cause == "permissions"
    assert any('"status": 403' in item for item in result.diagnosis.evidence)


def test_request_transition_cli_prompts_confirms_and_records(tmp_path, monkeypatch):
    import main

    monkeypatch.setenv("JARVIS_WORKFLOW_DB", str(tmp_path / "jarvis.sqlite3"))
    request_page = "https://fables.gg/requests/req-77"
    expected = (
        "AUTORIZZO DIAGNOSI RICHIESTA FABLES "
        f"{request_page} -> {FABLES_WORLD_URL} [req-77]"
    )
    browser_action, input_action, _, input_calls = _adapters(network_status=200)
    output = []

    exit_code = main._handle_fables_cli(
        [
            "--live-fables-workflow",
            "--confirm-live",
            "--diagnose-accepted-request",
            "--request-page",
            request_page,
            "--request-id",
            "req-77",
            "--accept-label",
            "Accept request",
            "--world",
            FABLES_WORLD_URL,
        ],
        input_fn=lambda prompt: expected,
        browser_action=browser_action,
        input_action=input_action,
        output=output.append,
    )

    assert exit_code == 0
    assert len(input_calls) == 1
    assert any("causa=backend_ignored" in line for line in output)
    assert any("diagnosi SQLite=" in line for line in output)
