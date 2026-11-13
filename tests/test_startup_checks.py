from __future__ import annotations

import pytest

from core import startup_checks


def test_venv_python_path_is_platform_specific(tmp_path):
    assert startup_checks.venv_python(tmp_path, windows=True) == (
        tmp_path / ".venv" / "Scripts" / "python.exe"
    )
    assert startup_checks.venv_python(tmp_path, windows=False) == (
        tmp_path / ".venv" / "bin" / "python"
    )


def test_missing_venv_stops_startup_with_creation_instructions(tmp_path):
    with pytest.raises(SystemExit, match="Ambiente virtuale .venv non trovato"):
        startup_checks.ensure_venv_interpreter(tmp_path)


def test_global_interpreter_is_replaced_with_project_venv(tmp_path, monkeypatch):
    executable = tmp_path / ".venv" / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    entry_point = tmp_path / "main.py"
    arguments = [str(entry_point), "--check-startup"]
    calls = []

    monkeypatch.setattr(startup_checks.sys, "executable", r"C:\Python313\python.exe")
    monkeypatch.setattr(startup_checks.sys, "argv", arguments)
    monkeypatch.setattr(
        startup_checks.os,
        "execv",
        lambda path, args: calls.append((path, args)),
    )

    with pytest.raises(AssertionError, match="os.execv unexpectedly returned"):
        startup_checks.ensure_venv_interpreter(tmp_path)

    assert calls == [
        (
            str(executable),
            [str(executable), str(entry_point), "--check-startup"],
        )
    ]


def test_missing_required_package_prints_install_instructions(monkeypatch, capsys):
    monkeypatch.setattr(startup_checks.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(startup_checks.sys, "executable", r"C:\project\.venv\Scripts\python.exe")

    assert startup_checks.check_startup_dependencies() is False
    captured = capsys.readouterr()
    assert "public_apis_mcp" in captured.err
    assert "Esegui pip install -r requirements.txt per installare le dipendenze" in captured.err
    assert "C:\\project\\.venv\\Scripts\\python.exe" in captured.err


def test_installed_required_package_passes_startup(monkeypatch):
    monkeypatch.setattr(
        startup_checks.importlib.util,
        "find_spec",
        lambda _name: object(),
    )

    assert startup_checks.check_startup_dependencies() is True
