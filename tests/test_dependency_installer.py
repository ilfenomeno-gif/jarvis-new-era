from __future__ import annotations

import subprocess

import pytest

from core import dependency_installer as installer


def test_resolve_requirement_only_returns_project_packages(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "beautifulsoup4\n"
        "PyYAML>=6.0\n"
        "requests\n",
        encoding="utf-8",
    )

    assert installer.resolve_requirement("bs4", requirements) == "beautifulsoup4"
    assert installer.resolve_requirement("yaml", requirements) == "PyYAML>=6.0"
    assert installer.resolve_requirement("unlisted_package", requirements) is None
    assert installer.resolve_requirement("../../bad", requirements) is None


def test_install_requirement_uses_python_module_pip_and_allowlist(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests>=2\n", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    installer.install_requirement(
        "requests>=2",
        requirements,
        python_executable="C:\\project\\.venv\\Scripts\\python.exe",
        runner=runner,
    )

    assert calls[0][0] == [
        "C:\\project\\.venv\\Scripts\\python.exe",
        "-m",
        "pip",
        "install",
        "requests>=2",
        "--disable-pip-version-check",
    ]
    assert calls[0][1]["timeout"] == 300

    with pytest.raises(installer.DependencyInstallError, match="not an allowed"):
        installer.install_requirement(
            "untrusted-package",
            requirements,
            runner=runner,
        )


def test_install_never_falls_back_to_global_python(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n", encoding="utf-8")
    monkeypatch.setattr(installer, "sys", type("FakeSys", (), {
        "executable": "C:\\Python\\python.exe",
    })())
    with pytest.raises(installer.DependencyInstallError, match="global Python"):
        installer.install_requirement(
            "requests",
            requirements,
            runner=lambda *_args, **_kwargs: pytest.fail("pip must not run"),
        )


def test_missing_dependency_prompts_installs_and_retries_once(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("beautifulsoup4\n", encoding="utf-8")
    calls = []
    installed = []

    def action():
        calls.append("run")
        if len(calls) == 1:
            raise ModuleNotFoundError("No module named 'bs4'", name="bs4")
        return "success"

    monkeypatch.setattr(
        installer,
        "install_requirement",
        lambda requirement, path: installed.append((requirement, path)),
    )

    assert installer.run_with_missing_dependency_retry(
        action,
        lambda package: package == "beautifulsoup4",
        requirements,
    ) == "success"
    assert calls == ["run", "run"]
    assert installed == [("beautifulsoup4", requirements)]


def test_declined_or_unknown_dependencies_are_not_installed(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n", encoding="utf-8")
    installs = []
    monkeypatch.setattr(
        installer,
        "install_requirement",
        lambda *args: installs.append(args),
    )

    def missing(module_name):
        def action():
            raise ModuleNotFoundError(f"No module named {module_name}", name=module_name)

        return action

    with pytest.raises(installer.DependencyInstallError, match="declined"):
        installer.run_with_missing_dependency_retry(
            missing("requests"), lambda _package: False, requirements
        )
    with pytest.raises(installer.DependencyInstallError, match="not mapped"):
        installer.run_with_missing_dependency_retry(
            missing("not_in_requirements"), lambda _package: True, requirements
        )

    assert installs == []


def test_retry_is_limited_to_once(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n", encoding="utf-8")
    monkeypatch.setattr(installer, "install_requirement", lambda *_args: None)
    calls = []

    def action():
        calls.append(None)
        raise ModuleNotFoundError("No module named 'requests'", name="requests")

    with pytest.raises(installer.DependencyInstallError, match="still unavailable"):
        installer.run_with_missing_dependency_retry(
            action, lambda _package: True, requirements
        )
    assert len(calls) == 2
