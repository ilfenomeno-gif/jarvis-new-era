"""Interpreter selection and early dependency checks for the app entry point."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

DEPENDENCY_INSTALL_MESSAGE = (
    "Esegui pip install -r requirements.txt per installare le dipendenze."
)


def venv_python(project_dir: Path, *, windows: bool | None = None) -> Path:
    if windows is None:
        windows = os.name == "nt"
    executable = "python.exe" if windows else "python"
    scripts_dir = "Scripts" if windows else "bin"
    return Path(project_dir) / ".venv" / scripts_dir / executable


def ensure_venv_interpreter(project_dir: Path) -> None:
    if getattr(sys, "frozen", False):
        return

    executable = venv_python(project_dir)
    if not executable.is_file():
        raise SystemExit(
            "Ambiente virtuale .venv non trovato. Crealo con "
            "`python -m venv .venv`, poi installa le dipendenze con "
            f"`{DEPENDENCY_INSTALL_MESSAGE}`"
        )

    try:
        already_using_venv = os.path.samefile(sys.executable, executable)
    except OSError:
        already_using_venv = (
            str(Path(sys.executable).resolve()).casefold()
            == str(executable.resolve()).casefold()
        )
    if already_using_venv:
        return

    os.execv(
        str(executable),
        [str(executable), str(Path(project_dir) / "main.py"), *sys.argv[1:]],
    )
    raise AssertionError("os.execv unexpectedly returned.")


def check_startup_dependencies() -> bool:
    missing = [
        module
        for module in ("public_apis_mcp",)
        if importlib.util.find_spec(module) is None
    ]
    if not missing:
        return True

    print(
        "Dipendenze mancanti nell'interprete "
        f"{sys.executable}: {', '.join(missing)}.\n"
        f"{DEPENDENCY_INSTALL_MESSAGE}",
        file=sys.stderr,
        flush=True,
    )
    return False
