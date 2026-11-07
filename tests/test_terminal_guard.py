import pytest

from core.terminal_guard import TerminalGuard, TerminalPolicyError


@pytest.mark.parametrize("command", ["echo hello", "ls", "pwd", "whoami"])
def test_allowlisted_commands_are_allowed(command):
    result = TerminalGuard().inspect(command)

    assert result.allowed
    assert not result.blocked
    assert not result.requires_override


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("rm -rf /", "recursive forced deletion"),
        ("format C:", "disk format"),
        ("del /f /s /q C:\\temp\\*", "Windows deletion"),
        ("rmdir /s C:\\temp", "recursive Windows"),
        ("Remove-Item C:\\temp -Recurse -Force", "PowerShell deletion"),
        ("diskpart", "system or disk"),
        ("git clean -fdx", "repository files"),
    ],
)
def test_destructive_commands_are_blocked_and_require_override(command, reason):
    result = TerminalGuard().inspect(command)

    assert not result.allowed
    assert result.blocked
    assert result.requires_override
    assert reason in result.reason


def test_unknown_executable_requires_explicit_override():
    result = TerminalGuard().inspect("python -c print(1)")

    assert result.blocked
    assert result.requires_override
    assert "not in the allowed command policy" in result.reason


@pytest.mark.parametrize(
    "command",
    ["", "echo hello && whoami", "echo hello; del file", "echo hello\nwhoami"],
)
def test_empty_or_shell_composed_commands_fail_closed(command):
    result = TerminalGuard().inspect(command)

    assert result.blocked
    assert not result.allowed
    assert not result.requires_override


def test_policy_is_loaded_from_yaml_and_invalid_policy_is_rejected(tmp_path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "version: 1\n"
        "allowed_executables:\n  - echo\n"
        "blocked_patterns:\n"
        "  - pattern: '(?i)^echo\\s+blocked$'\n"
        "    reason: explicit test policy\n",
        encoding="utf-8",
    )
    guard = TerminalGuard(policy_path)

    assert guard.inspect("echo hello").allowed
    assert guard.inspect("echo blocked").requires_override

    policy_path.write_text("version: 1\nblocked_patterns: [", encoding="utf-8")
    with pytest.raises(TerminalPolicyError, match="Invalid terminal policy YAML"):
        TerminalGuard(policy_path)
