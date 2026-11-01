"""Tests for the VS Code launcher action."""

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import vscode_control


@pytest.mark.parametrize(
    ("parameters", "expected_command", "expected_message"),
    [
        (
            {"action": "open_app"},
            ["code"],
            "Visual Studio Code avviato.",
        ),
        (
            {"action": "open_folder", "path": r"C:\Projects\Jarvis"},
            ["code", r"C:\Projects\Jarvis"],
            "Richiesta apertura in Visual Studio Code: C:\\Projects\\Jarvis",
        ),
        (
            {"action": "open_file", "path": r"C:\Projects\Jarvis\main.py"},
            ["code", r"C:\Projects\Jarvis\main.py"],
            "Richiesta apertura in Visual Studio Code: C:\\Projects\\Jarvis\\main.py",
        ),
    ],
)
def test_run_launches_requested_target(
    monkeypatch, parameters, expected_command, expected_message
):
    popen = Mock()
    monkeypatch.setattr(vscode_control.subprocess, "Popen", popen)

    result = vscode_control.run(parameters)

    popen.assert_called_once_with(
        expected_command, shell=(vscode_control.os.name == "nt")
    )
    assert result == expected_message


def test_windows_launch_uses_shell_true(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(vscode_control.subprocess, "Popen", popen)
    monkeypatch.setattr(vscode_control.os, "name", "nt")

    vscode_control.run({"action": "open_app"})

    popen.assert_called_once_with(["code"], shell=True)


def test_run_reports_missing_vscode(monkeypatch):
    def missing_executable(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(vscode_control.subprocess, "Popen", missing_executable)

    result = vscode_control.run({"action": "open_app"})

    assert "non trovato" in result
    assert "'code'" in result


@pytest.mark.parametrize(
    "parameters",
    [
        {"action": "open_folder"},
        {"action": "open_file", "path": "   "},
    ],
)
def test_run_requires_a_path_for_files_and_folders(parameters):
    assert "Specificare il percorso" in vscode_control.run(parameters)


def test_run_rejects_unknown_action_without_launching(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(vscode_control.subprocess, "Popen", popen)

    result = vscode_control.run({"action": "delete_everything"})

    assert "non valida" in result
    popen.assert_not_called()


def test_action_loader_contract_points_to_run_handler():
    assert vscode_control.TOOL["name"] == vscode_control.PLUGIN["name"]
    assert vscode_control.TOOL["handler"] is vscode_control.run


def test_open_terminal_starts_new_powershell_window(monkeypatch, tmp_path):
    popen = Mock()
    monkeypatch.setattr(vscode_control.subprocess, "Popen", popen)
    monkeypatch.setattr(vscode_control.os, "name", "nt")

    result = vscode_control.run(
        {"action": "open_terminal", "working_dir": str(tmp_path)}
    )

    popen.assert_called_once_with(
        ["powershell.exe", "-NoExit"],
        cwd=str(tmp_path),
        creationflags=vscode_control.subprocess.CREATE_NEW_CONSOLE,
    )
    assert result == "Nuova finestra PowerShell aperta."


def test_open_terminal_reports_missing_powershell_or_directory(monkeypatch):
    def missing_executable(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(vscode_control.subprocess, "Popen", missing_executable)
    monkeypatch.setattr(vscode_control.os, "name", "nt")

    result = vscode_control.run({"action": "open_terminal"})

    assert "PowerShell" in result


def test_run_task_captures_output_and_uses_timeout_without_shell(
    monkeypatch, tmp_path
):
    completed = CompletedProcess(
        args=["python", "-c", "print('ok')"],
        returncode=0,
        stdout="ok\n",
        stderr="",
    )
    run = Mock(return_value=completed)
    monkeypatch.setattr(vscode_control.subprocess, "run", run)

    result = vscode_control.run(
        {
            "action": "run_task",
            "command": ["python", "-c", "print('ok')"],
            "working_dir": str(tmp_path),
        }
    )

    run.assert_called_once_with(
        ["python", "-c", "print('ok')"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
        check=False,
    )
    assert "completato (codice 0)" in result
    assert "ok" in result


def test_run_task_returns_stderr_and_nonzero_exit_code(monkeypatch):
    monkeypatch.setattr(
        vscode_control.subprocess,
        "run",
        Mock(
            return_value=CompletedProcess(
                args=["python", "--invalid"], returncode=2, stdout="", stderr="bad arg"
            )
        ),
    )

    result = vscode_control.run(
        {"action": "run_task", "command": ["python", "--invalid"]}
    )

    assert "terminato con errore (codice 2)" in result
    assert "bad arg" in result


def test_run_task_accepts_configured_timeout(monkeypatch):
    run = Mock(
        return_value=CompletedProcess(
            args=["python", "-V"], returncode=0, stdout="Python 3", stderr=""
        )
    )
    monkeypatch.setattr(vscode_control.subprocess, "run", run)

    vscode_control.run(
        {"action": "run_task", "command": ["python", "-V"], "timeout": 12}
    )

    assert run.call_args.kwargs["timeout"] == 12


def test_run_task_reports_timeout_and_partial_output(monkeypatch):
    run = Mock(
        side_effect=TimeoutExpired(
            ["python", "-c", "print('waiting')"],
            3,
            output="waiting\n",
            stderr="still running",
        )
    )
    monkeypatch.setattr(vscode_control.subprocess, "run", run)

    result = vscode_control.run(
        {
            "action": "run_task",
            "command": ["python", "-c", "print('waiting')"],
            "timeout": 3,
        }
    )

    assert "timeout dopo 3 secondi" in result
    assert "waiting" in result
    assert "still running" in result


def test_run_task_rejects_commands_blocked_by_project_policy(monkeypatch):
    run = Mock()
    monkeypatch.setattr(vscode_control.subprocess, "run", run)

    result = vscode_control.run(
        {"action": "run_task", "command": ["rm", "-rf", "/"]}
    )

    assert "policy di sicurezza" in result
    run.assert_not_called()


@pytest.mark.parametrize(
    ("parameters", "expected_text"),
    [
        ({"action": "run_task"}, "Specificare"),
        ({"action": "run_task", "command": "python -V"}, "Specificare"),
        ({"action": "run_task", "command": [""]}, "Specificare"),
        ({"action": "run_task", "command": ["python"], "timeout": 0}, "timeout"),
        ({"action": "run_task", "command": ["python"], "timeout": True}, "timeout"),
    ],
)
def test_run_task_rejects_invalid_parameters(parameters, expected_text):
    assert expected_text.lower() in vscode_control.run(parameters).lower()
