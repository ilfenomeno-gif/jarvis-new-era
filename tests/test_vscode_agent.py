"""Tests for the GitHub Copilot CLI action."""

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import vscode_agent


def test_run_sends_prompt_as_single_argument_without_shell(monkeypatch, tmp_path):
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: "gh")
    run = Mock(
        return_value=CompletedProcess(
            args=["gh", "copilot", "suggest", "Explain this code"],
            returncode=0,
            stdout="Suggestion text\n",
            stderr="",
        )
    )
    monkeypatch.setattr(vscode_agent.subprocess, "run", run)

    result = vscode_agent.run(
        {
            "prompt": "  Explain this code  ",
            "working_dir": str(tmp_path),
        }
    )

    run.assert_called_once_with(
        ["gh", "copilot", "suggest", "Explain this code"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
        check=False,
    )
    assert result == "Suggestion text"


def test_run_uses_configured_timeout(monkeypatch):
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: "gh")
    run = Mock(
        return_value=CompletedProcess(
            args=["gh", "copilot", "suggest", "Help me"],
            returncode=0,
            stdout="Here is a suggestion",
            stderr="",
        )
    )
    monkeypatch.setattr(vscode_agent.subprocess, "run", run)

    result = vscode_agent.run({"prompt": "Help me", "timeout": 45})

    assert run.call_args.kwargs["timeout"] == 45
    assert result == "Here is a suggestion"


def test_run_reports_missing_gh_with_install_instructions(monkeypatch):
    run = Mock()
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: None)
    monkeypatch.setattr(vscode_agent.subprocess, "run", run)

    result = vscode_agent.run({"prompt": "Suggest a test"})

    assert "non trovato nel PATH" in result
    assert "cli.github.com" in result
    assert "gh extension install" in result
    run.assert_not_called()


def test_run_reports_nonzero_cli_exit_and_stderr(monkeypatch):
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(
        vscode_agent.subprocess,
        "run",
        Mock(
            return_value=CompletedProcess(
                args=["gh", "copilot", "suggest", "Help"],
                returncode=1,
                stdout="",
                stderr="extension unavailable",
            )
        ),
    )

    result = vscode_agent.run({"prompt": "Help"})

    assert "codice 1" in result
    assert "extension unavailable" in result


def test_run_reports_timeout_and_partial_output(monkeypatch):
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: "gh")
    run = Mock(
        side_effect=TimeoutExpired(
            ["gh", "copilot", "suggest", "Help"],
            5,
            output="working",
            stderr="",
        )
    )
    monkeypatch.setattr(vscode_agent.subprocess, "run", run)

    result = vscode_agent.run({"prompt": "Help", "timeout": 5})

    assert "dopo 5 secondi" in result
    assert "working" in result


def test_run_reports_security_policy_rejection(monkeypatch):
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: "gh")
    run = Mock(side_effect=PermissionError("executable not whitelisted"))
    monkeypatch.setattr(vscode_agent.subprocess, "run", run)

    result = vscode_agent.run({"prompt": "Help"})

    assert "policy di sicurezza" in result
    assert "executable not whitelisted" in result


def test_tool_contract_is_discoverable_and_uses_run_handler():
    assert vscode_agent.TOOL["name"] == vscode_agent.PLUGIN["name"]
    assert vscode_agent.TOOL["handler"] is vscode_agent.run


@pytest.mark.parametrize(
    ("parameters", "expected_text"),
    [
        ({}, "prompt"),
        ({"prompt": "  "}, "prompt"),
        ({"prompt": "Help", "timeout": 0}, "timeout"),
        ({"prompt": "Help", "timeout": True}, "timeout"),
        ({"prompt": "Help", "working_dir": "  "}, "working_dir"),
    ],
)
def test_run_rejects_invalid_parameters(parameters, expected_text):
    assert expected_text in vscode_agent.run(parameters).lower()


def test_run_reports_file_not_found_after_path_check(monkeypatch):
    monkeypatch.setattr(vscode_agent.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(
        vscode_agent.subprocess,
        "run",
        Mock(side_effect=FileNotFoundError),
    )

    result = vscode_agent.run({"prompt": "Help"})

    assert "non trovato" in result
    assert "PATH" in result
