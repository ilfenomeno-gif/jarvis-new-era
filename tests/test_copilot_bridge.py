from __future__ import annotations

import hashlib
import sqlite3

import pytest

from core.copilot_bridge import (
    CopilotBridge,
    CopilotHandoffInvalid,
    CopilotPromptEmpty,
    CopilotPromptModified,
    CopilotPromptNotFound,
    handle_copilot_chat_handoff,
    handle_copilot_handoff_cli,
    open_handoff_in_vscode,
    prompt_state,
)


def _repo(tmp_path, prompt: bytes | None = b"Original Copilot prompt\r\n"):
    root = tmp_path / "repo"
    (root / "prompts").mkdir(parents=True)
    if prompt is not None:
        (root / "prompts" / "copilot_prompt.md").write_bytes(prompt)
    (root / "src").mkdir()
    attached = root / "src" / "feature.py"
    attached.write_bytes(b"print('feature')\r\n")
    bridge = CopilotBridge(root, tmp_path / "state.sqlite3")
    return root, bridge, attached


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (" \n\t", "empty"),
        ("  \n# BOZZA del prompt\nContenuto", "draft"),
        ("# Prompt approvato\nContenuto", "approved"),
    ],
)
def test_prompt_state_classifies_empty_draft_and_approved(content, expected):
    assert prompt_state(content) == expected


def test_missing_prompt_raises_without_creating_file_or_database(tmp_path):
    root, bridge, _ = _repo(tmp_path, prompt=None)

    with pytest.raises(CopilotPromptNotFound) as error:
        bridge.load_prompt()

    assert str(root / "prompts" / "copilot_prompt.md") in str(error.value)
    assert not (root / "prompts" / "copilot_prompt.md").exists()
    assert not bridge.database_path.exists()


def test_zero_byte_prompt_raises_empty_with_path_and_size(tmp_path):
    root, bridge, _ = _repo(tmp_path, prompt=b"")

    with pytest.raises(CopilotPromptEmpty) as error:
        bridge.load_prompt()

    assert str(root / "prompts" / "copilot_prompt.md") in str(error.value)
    assert "size=0 byte" in str(error.value)


def test_whitespace_only_prompt_raises_empty(tmp_path):
    _, bridge, _ = _repo(tmp_path, prompt=b"\n\n \t")

    with pytest.raises(CopilotPromptEmpty, match="size=4 byte"):
        bridge.load_prompt()


def test_package_handoff_propagates_empty_prompt_without_record(tmp_path):
    _, bridge, attached = _repo(tmp_path, prompt=b" \r\n ")

    with pytest.raises(CopilotPromptEmpty):
        bridge.package_handoff([attached], "Implement feature")

    assert not bridge.database_path.exists()


def test_cli_empty_prompt_returns_error_and_does_not_record(tmp_path):
    _, bridge, attached = _repo(tmp_path, prompt=b"")
    output: list[str] = []
    asked = []

    result = handle_copilot_handoff_cli(
        [
            "--copilot-handoff",
            "--task",
            "Implement feature",
            "--files",
            str(attached),
        ],
        bridge=bridge,
        input_fn=lambda prompt: asked.append(prompt) or "SI",
        output=output.append,
    )

    assert result == 2
    assert any("stato=empty" in line for line in output)
    assert not asked
    assert not bridge.database_path.exists()


def test_chat_intent_with_empty_prompt_reports_error_without_confirmation(tmp_path):
    _, bridge, attached = _repo(tmp_path, prompt=b" \n")
    confirmation_requests = []

    result = handle_copilot_chat_handoff(
        f"passa a Copilot task: Implement feature | files: {attached}",
        bridge,
        lambda *args: confirmation_requests.append(args) or "pending",
    )

    assert result is not None and "Prompt Copilot vuoto" in result
    assert not confirmation_requests
    assert not bridge.database_path.exists()


def test_explicit_prompt_is_returned_byte_identical(tmp_path):
    _, bridge, _ = _repo(tmp_path)
    prompt_path = tmp_path / "external-prompt.md"
    original = b"# Original\r\nLine two\t\r\n"
    prompt_path.write_bytes(original)

    prompt = bridge.load_prompt(prompt_path)

    assert prompt.encode("utf-8") == original
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == hashlib.sha256(
        original
    ).hexdigest()


def test_prompt_lookup_uses_repository_then_config_then_environment(tmp_path, monkeypatch):
    root, bridge, _ = _repo(tmp_path)
    default_prompt = root / "prompts" / "copilot_prompt.md"
    configured_prompt = root / "configured.md"
    environment_prompt = tmp_path / "environment.md"
    configured_prompt.write_text("Configured prompt", encoding="utf-8")
    environment_prompt.write_text("Environment prompt", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "copilot.yaml").write_text(
        'prompt_path: "configured.md"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_COPILOT_PROMPT", str(environment_prompt))

    assert bridge.load_prompt() == "Original Copilot prompt\r\n"
    default_prompt.unlink()
    assert bridge.load_prompt() == "Configured prompt"
    (root / "config" / "copilot.yaml").unlink()
    assert bridge.load_prompt() == "Environment prompt"


def test_configured_relative_prompt_path_is_resolved_from_repository(tmp_path):
    root, bridge, _ = _repo(tmp_path, prompt=None)
    configured_prompt = root / "private-prompt.md"
    configured_prompt.write_text("Configured source", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "copilot.yaml").write_text(
        "prompt_path: private-prompt.md\n",
        encoding="utf-8",
    )

    assert bridge.load_prompt() == "Configured source"


def test_single_file_package_has_correct_hash_size_and_relative_path(tmp_path):
    _, bridge, attached = _repo(tmp_path)

    package = bridge.package_handoff([attached], "Implement feature")

    assert package.files[0].path == "src/feature.py"
    assert package.files[0].sha256 == hashlib.sha256(attached.read_bytes()).hexdigest()
    assert package.files[0].size == attached.stat().st_size
    assert package.prompt_hash == hashlib.sha256(package.prompt.encode("utf-8")).hexdigest()


def test_multiple_file_package_records_all_hashes_and_sizes(tmp_path):
    root, bridge, first = _repo(tmp_path)
    second = root / "src" / "second.py"
    second.write_bytes(b"second")

    package = bridge.package_handoff([first, second], "Implement both")

    assert [item.path for item in package.files] == ["src/feature.py", "src/second.py"]
    assert [item.sha256 for item in package.files] == [
        hashlib.sha256(first.read_bytes()).hexdigest(),
        hashlib.sha256(second.read_bytes()).hexdigest(),
    ]
    assert [item.size for item in package.files] == [
        first.stat().st_size,
        second.stat().st_size,
    ]


@pytest.mark.parametrize("bad_attachment", ["missing", "outside"])
def test_invalid_attachment_is_rejected_without_database_write(tmp_path, bad_attachment):
    root, bridge, attached = _repo(tmp_path)
    supplied = (
        root / "src" / "missing.py"
        if bad_attachment == "missing"
        else tmp_path / "outside.py"
    )

    with pytest.raises(CopilotHandoffInvalid):
        bridge.package_handoff([attached, supplied], "Implement feature")

    assert not bridge.database_path.exists()


def test_handoff_requires_a_nonempty_task_and_at_least_one_file(tmp_path):
    _, bridge, attached = _repo(tmp_path)

    with pytest.raises(CopilotHandoffInvalid, match="task"):
        bridge.package_handoff([attached], " ")
    with pytest.raises(CopilotHandoffInvalid, match="almeno un file"):
        bridge.package_handoff([], "Implement feature")


def test_recording_is_idempotent_and_resumable_after_restart(tmp_path):
    _, bridge, attached = _repo(tmp_path)
    package = bridge.package_handoff([attached], "Implement feature")

    first_id = bridge.record_handoff(package)
    second_id = bridge.record_handoff(package)
    restarted = CopilotBridge(bridge.repo_root, bridge.database_path)
    resumed = restarted.resume_handoff(first_id)

    with sqlite3.connect(bridge.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM copilot_handoffs").fetchone()[0]

    assert first_id == second_id
    assert count == 1
    assert resumed is not None
    assert resumed["task"] == package.task
    assert resumed["prompt"] == package.prompt


def test_recording_adds_prompt_state_column_to_existing_handoff_table(tmp_path):
    _, bridge, attached = _repo(
        tmp_path, prompt=b"# BOZZA\nPrompt Copilot non ancora approvato."
    )
    with sqlite3.connect(bridge.database_path) as connection:
        connection.execute(
            """
            CREATE TABLE copilot_handoffs (
                handoff_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                task TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                files_hash_set TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    package = bridge.package_handoff([attached], "Implement feature")
    bridge.record_handoff(package)

    with sqlite3.connect(bridge.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(copilot_handoffs)")
        }
        state = connection.execute(
            "SELECT prompt_state FROM copilot_handoffs"
        ).fetchone()
    assert "prompt_state" in columns
    assert state == ("draft",)


def test_prompt_intact_check_accepts_original_and_rejects_modified_file(tmp_path):
    _, bridge, _ = _repo(tmp_path)
    prompt_path = bridge.repo_root / "prompts" / "copilot_prompt.md"
    original = bridge.load_prompt()

    assert bridge.verify_prompt_intact(original, prompt_path)
    prompt_path.write_text("Modified prompt", encoding="utf-8")
    with pytest.raises(CopilotPromptModified):
        bridge.verify_prompt_intact(original, prompt_path)


def test_record_rejects_prompt_or_attachment_changed_after_packaging(tmp_path):
    root, bridge, attached = _repo(tmp_path)
    package = bridge.package_handoff([attached], "Implement feature")
    attached.write_bytes(b"changed attachment")

    with pytest.raises(CopilotHandoffInvalid, match="file allegato è cambiato"):
        bridge.record_handoff(package)

    assert not bridge.database_path.exists()

    attached.write_bytes(b"print('feature')\r\n")
    package = bridge.package_handoff([attached], "Implement feature")
    (root / "prompts" / "copilot_prompt.md").write_text(
        "Changed prompt",
        encoding="utf-8",
    )
    with pytest.raises(CopilotPromptModified):
        bridge.record_handoff(package)
    assert not bridge.database_path.exists()


def test_cli_happy_path_requires_confirmation_and_records_without_sending(tmp_path):
    _, bridge, attached = _repo(tmp_path)
    output: list[str] = []
    confirmations: list[str] = []
    opened = []

    result = handle_copilot_handoff_cli(
        [
            "--copilot-handoff",
            "--task",
            "Implement feature",
            "--files",
            str(attached),
        ],
        bridge=bridge,
        input_fn=lambda prompt: confirmations.append(prompt) or "SI",
        output=output.append,
        open_handoff=lambda path: opened.append(path) or True,
    )

    assert result == 0
    assert len(confirmations) == 1
    assert any("nessun invio automatico a Copilot" in line for line in output)
    assert any("registrato in SQLite" in line for line in output)
    assert len(opened) == 1
    brief = opened[0].read_text(encoding="utf-8")
    assert "Implement feature" in brief
    assert "Original Copilot prompt" in brief
    assert "print('feature')" in brief
    with sqlite3.connect(bridge.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM copilot_handoffs").fetchone()[0]
    assert count == 1


def test_cli_declined_confirmation_does_not_create_record(tmp_path):
    _, bridge, attached = _repo(tmp_path)

    result = handle_copilot_handoff_cli(
        [
            "--copilot-handoff",
            "--task",
            "Implement feature",
            "--files",
            str(attached),
        ],
        bridge=bridge,
        input_fn=lambda _: "no",
        output=lambda _: None,
    )

    assert result == 2
    assert not bridge.database_path.exists()


def test_handoff_opens_in_vscode_without_shell(monkeypatch, tmp_path):
    calls = []
    handoff_path = tmp_path / "copilot_task.md"
    monkeypatch.setattr(
        "core.copilot_bridge.subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert open_handoff_in_vscode(handoff_path) is True
    assert calls == [
        (["code", "--reuse-window", str(handoff_path)], {"shell": False})
    ]


def test_draft_prompt_handoff_warns_and_records_prompt_state(tmp_path):
    _, bridge, attached = _repo(
        tmp_path, prompt=b"# BOZZA\nPrompt Copilot non ancora approvato.\r\n"
    )
    output: list[str] = []

    result = handle_copilot_handoff_cli(
        [
            "--copilot-handoff",
            "--task",
            "Implement feature",
            "--files",
            str(attached),
        ],
        bridge=bridge,
        input_fn=lambda _: "SI",
        output=output.append,
    )

    assert result == 0
    assert any("Stato prompt: draft" in line for line in output)
    assert any(
        "ATTENZIONE: Il prompt Copilot è attualmente in BOZZA." in line
        for line in output
    )
    with sqlite3.connect(bridge.database_path) as connection:
        row = connection.execute(
            "SELECT prompt_state FROM copilot_handoffs"
        ).fetchone()
    assert row == ("draft",)


def test_chat_handoff_requires_hud_confirmation_before_recording(tmp_path):
    _, bridge, attached = _repo(tmp_path)
    confirmation = {}

    def request(title, detail, run):
        confirmation.update(title=title, detail=detail, run=run)
        return "[CONFIRMATION_PENDING]"

    result = handle_copilot_chat_handoff(
        f"handoff copilot task: Implement feature | files: {attached}",
        bridge,
        request,
    )

    assert result == "[CONFIRMATION_PENDING]"
    assert "Implement feature" in confirmation["detail"]
    assert "Nessun invio a Copilot" in confirmation["detail"]
    assert not bridge.database_path.exists()
    assert confirmation["run"]().startswith("Handoff registrato:")
    assert bridge.database_path.exists()


def test_draft_chat_handoff_warns_and_records_prompt_state(tmp_path):
    _, bridge, attached = _repo(
        tmp_path, prompt=b"# BOZZA\nPrompt Copilot non ancora approvato.\r\n"
    )
    confirmation = {}

    def request(title, detail, run):
        confirmation.update(title=title, detail=detail, run=run)
        return "[CONFIRMATION_PENDING]"

    result = handle_copilot_chat_handoff(
        f"handoff copilot task: Implement feature | files: {attached}",
        bridge,
        request,
    )

    assert result == "[CONFIRMATION_PENDING]"
    assert "Stato prompt: draft" in confirmation["detail"]
    assert "ATTENZIONE: Il prompt Copilot è attualmente in BOZZA." in confirmation["detail"]
    confirmation["run"]()
    with sqlite3.connect(bridge.database_path) as connection:
        row = connection.execute(
            "SELECT prompt_state FROM copilot_handoffs"
        ).fetchone()
    assert row == ("draft",)


def test_unqualified_chat_intent_requests_task_and_files(tmp_path):
    _, bridge, _ = _repo(tmp_path)

    result = handle_copilot_chat_handoff(
        "passa a Copilot",
        bridge,
        lambda *_: pytest.fail("Confirmation must wait for task and files."),
    )

    assert result is not None
    assert "task:" in result and "files:" in result


def test_no_visible_txt_files_are_created_for_handoff(tmp_path):
    root, bridge, attached = _repo(tmp_path)
    package = bridge.package_handoff([attached], "Implement feature")
    bridge.record_handoff(package)

    assert not list(root.rglob("*.txt"))


def test_main_cli_routes_copilot_handoff_before_starting_ui(monkeypatch):
    import sys

    import main as jarvis_main
    import core.copilot_bridge as copilot_bridge

    calls = []
    monkeypatch.setattr(
        copilot_bridge,
        "handle_copilot_handoff_cli",
        lambda argv, repo_root: calls.append((argv, repo_root)) or 7,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--copilot-handoff", "--task", "Implement", "--files", "src/a.py"],
    )

    with pytest.raises(SystemExit) as exit_info:
        jarvis_main.main()

    assert exit_info.value.code == 7
    assert calls == [
        (
            ["--copilot-handoff", "--task", "Implement", "--files", "src/a.py"],
            jarvis_main.BASE_DIR,
        )
    ]


def test_main_chat_entry_uses_bridge_and_reports_empty_prompt(tmp_path, monkeypatch):
    import main as jarvis_main

    root = tmp_path / "chat-repo"
    (root / "prompts").mkdir(parents=True)
    (root / "prompts" / "copilot_prompt.md").write_bytes(b"")
    messages = []
    monkeypatch.setattr(jarvis_main, "BASE_DIR", root)
    monkeypatch.setattr(
        jarvis_main.confirm_gate,
        "request",
        lambda *_: pytest.fail("An empty prompt must not request confirmation."),
    )
    instance = object.__new__(jarvis_main.JarvisLive)
    instance._asst_name = "JARVIS"
    instance._session_log = []
    instance.session = None
    instance.ui = type("UI", (), {"write_log": lambda _self, text: messages.append(text)})()
    instance._hud = type("HUD", (), {"push_chat": lambda _self, _role, text: messages.append(text)})()

    assert instance._try_handle_copilot_handoff("passa a Copilot") is True
    assert any("Prompt Copilot vuoto" in message for message in messages)
    assert not list(root.rglob("*.txt"))
