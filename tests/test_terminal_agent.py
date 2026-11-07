import sqlite3
import subprocess
from pathlib import Path

import pytest

from core.message_router import MessageRouter
from core.phone_channel import MockPhoneChannel
from core.terminal_agent import (
    OVERRIDE_TOKEN,
    CommandBlocked,
    OverrideRequired,
    TerminalAgent,
    TerminalExecutionError,
)
from core.terminal_guard import TerminalGuard


def _completed(args, *, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_safe_echo_executes_without_shell():
    result = TerminalAgent(timeout_seconds=2).execute("echo hello")

    assert result.return_code == 0
    assert "hello" in result.stdout
    assert result.stderr == ""


def test_dangerous_command_is_blocked_without_spawning_subprocess(tmp_path):
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return _completed(args[0])

    agent = TerminalAgent(database_path=tmp_path / "terminal.sqlite3", runner=runner)

    with pytest.raises(OverrideRequired, match="recursive forced deletion"):
        agent.execute("rm -rf /")

    assert calls == []


def test_invalid_shell_composition_cannot_be_overridden(tmp_path):
    calls = []
    agent = TerminalAgent(
        database_path=tmp_path / "terminal.sqlite3",
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(CommandBlocked, match="Shell operators"):
        agent.execute("echo safe && rm -rf /")
    with pytest.raises(CommandBlocked, match="Shell operators"):
        agent.execute_with_override(
            "echo safe && rm -rf /", OVERRIDE_TOKEN, user_id="user-1"
        )
    assert calls == []


def test_override_requires_exact_token_and_runs_one_mocked_command(tmp_path):
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return _completed(args, stdout="mocked output")

    agent = TerminalAgent(database_path=tmp_path / "terminal.sqlite3", runner=runner)
    with pytest.raises(PermissionError, match="valid explicit override token"):
        agent.execute_with_override("rm -rf /", "OVERRIDE", user_id="user-1")
    assert calls == []

    result = agent.execute_with_override(
        "rm -rf /", OVERRIDE_TOKEN, user_id="phone-user-42"
    )
    assert result.stdout == "mocked output"
    assert len(calls) == 1
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 10


def test_override_log_persists_reason_command_and_user_id(tmp_path):
    database = tmp_path / "terminal.sqlite3"
    agent = TerminalAgent(
        database_path=database,
        runner=lambda args, **kwargs: _completed(args, stdout="mocked"),
    )

    agent.execute_with_override(
        "format C:", OVERRIDE_TOKEN, user_id="phone-user-7"
    )

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT occurred_at, command, block_reason, user_id, status,
                return_code, duration_seconds
            FROM terminal_overrides
            """
        ).fetchone()
        policies = connection.execute(
            "SELECT policy_hash, policy_yaml FROM terminal_policies"
        ).fetchall()
    assert row[0]
    assert row[1] == "format C:"
    assert "disk format" in row[2]
    assert row[3] == "phone-user-7"
    assert row[4] == "completed"
    assert row[5] == 0
    assert row[6] >= 0
    assert len(policies) == 1
    assert "blocked_patterns" in policies[0][1]


def test_override_timeout_is_one_subprocess_invocation_and_logged_failure(tmp_path):
    calls = []

    def timeout_runner(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    database = tmp_path / "terminal.sqlite3"
    agent = TerminalAgent(
        database_path=database, runner=timeout_runner, timeout_seconds=0.1
    )
    with pytest.raises(TerminalExecutionError, match="execution limit"):
        agent.execute_with_override("format C:", OVERRIDE_TOKEN)
    assert len(calls) == 1
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT status, return_code FROM terminal_overrides"
        ).fetchone()
    assert row == ("failed", None)


def test_phone_message_router_integrates_terminal_override_with_user_id(tmp_path):
    calls = []
    agent = TerminalAgent(
        database_path=tmp_path / "terminal.sqlite3",
        runner=lambda args, **kwargs: calls.append((args, kwargs))
        or _completed(args, stdout="mocked phone result"),
    )
    channel = MockPhoneChannel()
    channel.enqueue_incoming(
        "AUTORIZZO OVERRIDE: format C:",
        sender_id="authorized-user",
    )
    router = MessageRouter(
        channel,
        jarvis_handler=lambda _message: "Jarvis",
        status_handler=lambda _message: "status",
        stop_handler=lambda _message: "stop",
        terminal_agent=agent,
        allowed_sender_ids={"authorized-user"},
    )

    responses = router.poll_once()

    assert len(calls) == 1
    assert "mocked phone result" in responses[0][1]
    assert channel.sent_messages == [responses[0][1]]
    with sqlite3.connect(agent.database_path) as connection:
        user_id, command = connection.execute(
            "SELECT user_id, command FROM terminal_overrides"
        ).fetchone()
    assert (user_id, command) == ("authorized-user", "format C:")


def test_phone_override_requires_exact_prefixed_format(tmp_path):
    agent = TerminalAgent(
        database_path=tmp_path / "terminal.sqlite3",
        runner=lambda *args, **kwargs: pytest.fail("No execution expected."),
    )
    channel = MockPhoneChannel()
    channel.enqueue_incoming("AUTORIZZO OVERRIDE rm -rf /")
    router = MessageRouter(
        channel,
        jarvis_handler=lambda _message: "",
        status_handler=lambda _message: "",
        stop_handler=lambda _message: "",
        terminal_agent=agent,
        allowed_sender_ids={"mock-sender"},
    )

    responses = router.poll_once()

    assert "Formato richiesto" in responses[0][1]
