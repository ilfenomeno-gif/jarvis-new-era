"""Explicitly confirmed installation and one-time retry for missing action imports."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(\[[A-Za-z0-9,._-]+\])?"
    r"((?:\s*(?:===|==|~=|!=|<=|>=|<|>)[A-Za-z0-9.*+!-]+"
    r"(?:\s*,\s*(?:===|==|~=|!=|<=|>=|<|>)[A-Za-z0-9.*+!-]+)*)?)"
)
_MODULE_ALIASES = {
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "pptx": "python-pptx",
    "docx": "python-docx",
    "google.genai": "google-genai",
    "google.generativeai": "google-generativeai",
}


class DependencyInstallError(RuntimeError):
    pass


def _requirements(requirements_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line or line.startswith(("-", "http://", "https://")):
            continue
        match = _REQUIREMENT.match(line)
        if not match:
            continue
        package, extras, specifier = match.groups()
        normalized = re.sub(r"[-_.]+", "-", package).casefold()
        result[normalized] = f"{package}{extras or ''}{specifier or ''}"
    return result


def resolve_requirement(
    module_name: str | None,
    requirements_path: Path,
) -> str | None:
    if not module_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module_name):
        return None
    available = _requirements(Path(requirements_path))
    distribution = _MODULE_ALIASES.get(module_name)
    if distribution is None:
        distribution = _MODULE_ALIASES.get(module_name.split(".", 1)[0])
    if distribution is None:
        distribution = module_name.split(".", 1)[0]
    normalized = re.sub(r"[-_.]+", "-", distribution).casefold()
    return available.get(normalized)


def install_requirement(
    requirement: str,
    requirements_path: Path,
    *,
    python_executable: str | None = None,
    runner: Callable = subprocess.run,
) -> None:
    allowed = set(_requirements(Path(requirements_path)).values())
    if requirement not in allowed:
        raise DependencyInstallError(
            "The requested package is not an allowed project requirement."
        )
    requirements_path = Path(requirements_path).resolve()
    project_root = requirements_path.parent
    venv_root = project_root / ".venv"
    venv_python = (
        venv_root / "Scripts" / "python.exe"
        if os.name == "nt"
        else venv_root / "bin" / "python"
    )
    if python_executable:
        executable = python_executable
    elif venv_python.is_file():
        executable = str(venv_python)
    else:
        try:
            Path(sys.executable).resolve().relative_to(venv_root.resolve())
        except ValueError as exc:
            raise DependencyInstallError(
                f"Project virtual environment not found at {venv_root}; "
                "install was not attempted with a global Python."
            ) from exc
        executable = sys.executable
    try:
        completed = runner(
            [
                executable,
                "-m",
                "pip",
                "install",
                requirement,
                "--disable-pip-version-check",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DependencyInstallError(
            f"Installation of {requirement} failed ({type(exc).__name__})."
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:500]
        raise DependencyInstallError(
            f"Installation of {requirement} failed: {detail or 'pip returned an error.'}"
        )


def install_missing_module(
    module_name: str | None,
    confirm: Callable[[str], bool],
    requirements_path: Path,
) -> bool:
    requirement = resolve_requirement(module_name, requirements_path)
    if requirement is None or not confirm(requirement):
        return False
    install_requirement(requirement, requirements_path)
    return True


def run_with_missing_dependency_retry(
    action: Callable[[], str],
    confirm: Callable[[str], bool],
    requirements_path: Path,
) -> str:
    try:
        return action()
    except ModuleNotFoundError as exc:
        requirement = resolve_requirement(exc.name, requirements_path)
        if requirement is None:
            raise DependencyInstallError(
                f"Missing Python module {exc.name!r} is not mapped to an "
                "approved project requirement; nothing was installed."
            ) from exc
        if not confirm(requirement):
            raise DependencyInstallError(
                f"Installation of {requirement} was declined; the action was not retried."
            ) from exc
        install_requirement(requirement, requirements_path)
        try:
            return action()
        except ModuleNotFoundError as retry_error:
            raise DependencyInstallError(
                f"Module {retry_error.name!r} is still unavailable after "
                f"installing {requirement}; restart Jarvis and retry."
            ) from retry_error
