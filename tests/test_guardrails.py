"""Tests for the command execution security policy."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.guardrails import validate_command


@pytest.mark.parametrize(
    "command",
    [
        ["git", "status"],
        ["gh", "copilot", "suggest", "Explain this code"],
        ["python", "-V"],
        ["python3", "-V"],
        ["pytest", "tests", "-q"],
        ["pip", "--version"],
        ["code", "--version"],
        ["node", "--version"],
        ["npm", "--version"],
    ],
)
def test_development_commands_are_allowed(command):
    validate_command(command)


@pytest.mark.parametrize(
    "command",
    [
        ["rm", "-rf", "folder"],
        ["del", "/f", "file.txt"],
        ["format", "C:"],
        ["shutdown", "/s"],
        ["taskkill", "/f", "/im", "app.exe"],
        ["reg", "delete", "HKCU\\Software\\Example"],
        ["sudo", "python", "script.py"],
        ["powershell", "-Command", "Remove-Item file.txt"],
    ],
)
def test_destructive_commands_are_rejected(command):
    with pytest.raises(PermissionError, match="dangerous command"):
        validate_command(command)


@pytest.mark.parametrize(
    "command",
    [
        ["git", "status", "|", "more"],
        ["python", "-m", "pytest", ">", "test.log"],
        ["git", "status", "&&", "git", "log"],
        ["python", "-c", "print('one'); print('two')"],
        ["python", "-c", "`whoami`"],
        ["python", "-c", "$(whoami)"],
        ["git", "status", "<", "input.txt"],
    ],
)
def test_shell_metacharacters_are_rejected(command):
    with pytest.raises(PermissionError, match="shell metacharacters"):
        validate_command(command)


def test_unlisted_executables_remain_rejected():
    with pytest.raises(PermissionError, match="not whitelisted"):
        validate_command(["unknown_tool", "--version"])


def test_shell_execution_remains_rejected_even_for_allowed_executable():
    with pytest.raises(PermissionError, match="shell execution is disabled"):
        validate_command(["git", "status"], shell=True)


@pytest.mark.parametrize(
    "command",
    [
        ["cmd", "/c", "dir"],
        ["powershell", "-Command", "Get-Process"],
        ["sh", "-c", "ls"],
    ],
)
def test_shell_executables_are_not_allowed_for_user_commands(command):
    with pytest.raises(PermissionError, match="not whitelisted"):
        validate_command(command)


@pytest.mark.parametrize(
    "command",
    [
        ["cmd", "/c", "dir"],
        ["powershell", "-Command", "Get-Process"],
    ],
)
def test_shell_executables_remain_available_to_internal_actions(command):
    validate_command(command, internal=True)


def test_internal_shell_commands_can_contain_sequencing_syntax():
    validate_command(
        ["powershell", "-Command", "first-command; second-command"],
        internal=True,
    )


def test_chrome_is_allowed_only_for_internal_browser_startup(tmp_path):
    chrome = tmp_path / "chrome.exe"
    chrome.touch()

    validate_command([str(chrome), "https://example.org"], internal=True)

    with pytest.raises(PermissionError, match="not whitelisted"):
        validate_command([str(chrome), "https://example.org"])


def test_magnifier_is_allowed_only_for_internal_startup():
    validate_command(["magnify.exe"], internal=True)

    with pytest.raises(PermissionError, match="not whitelisted"):
        validate_command(["magnify.exe"])


def test_guarded_popen_starts_internal_chrome(monkeypatch, tmp_path):
    import subprocess

    from core import guardrails

    chrome = tmp_path / "chrome.exe"
    chrome.touch()
    calls = []

    monkeypatch.setattr(
        subprocess,
        "_original_popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or "started",
        raising=False,
    )

    result = guardrails.guarded_popen(
        [str(chrome), "https://example.org"],
        stdout=subprocess.DEVNULL,
    )

    assert result == "started"
    assert calls == [
        ([str(chrome), "https://example.org"], {"stdout": subprocess.DEVNULL})
    ]
