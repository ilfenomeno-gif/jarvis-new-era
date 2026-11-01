"""Writes a JSON summary for each standalone or pytest-driven live run."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
E2E_ROOT = Path(__file__).resolve().parent


def _version() -> str:
    workspace_root = PROJECT_ROOT.parent
    tracked_source = f"{PROJECT_ROOT.name}/main.py"
    try:
        outer_tree_tracks_source = subprocess.run(
            [
                "git",
                "-C",
                str(workspace_root),
                "ls-files",
                "--error-unmatch",
                "--",
                tracked_source,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        outer_tree_tracks_source = False
    git_root = workspace_root if outer_tree_tracks_source else PROJECT_ROOT
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable: {exc}"
    return result.stdout.strip()


def write_report(
    results: list[dict[str, Any]],
    started_at: datetime,
    duration: float,
) -> Path:
    summary = {
        "passed": sum(result["status"] == "PASS" for result in results),
        "failed": sum(result["status"] == "FAIL" for result in results),
        "skipped": sum(result["status"] == "SKIP" for result in results),
    }
    report = {
        "date": started_at.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 3),
        "jarvis_version": _version(),
        "tests": results,
        "summary": summary,
    }
    E2E_ROOT.mkdir(parents=True, exist_ok=True)
    path = E2E_ROOT / f"report-{started_at.strftime('%Y%m%d-%H%M%S-%f')}.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


class E2EReportPlugin:
    def __init__(self) -> None:
        self.started_at = datetime.now()
        self.started_clock = time.monotonic()
        self.results: dict[str, dict[str, Any]] = {}
        self.path: Path | None = None

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        result = outcome.get_result()
        if result.when not in ("call", "setup"):
            return

        status = (
            "SKIP" if result.skipped
            else "FAIL" if result.failed
            else "PASS"
        )
        details: dict[str, Any] = {}
        for key, value in item.user_properties:
            if key == "e2e_result":
                details = json.loads(value)
            elif key == "e2e_screenshot_error":
                details["screenshot_error"] = value

        entry = {
            "name": item.name,
            "status": status,
            "duration_seconds": round(result.duration, 3),
            "screenshots": details.get("screenshots", []),
            "log_excerpt": details.get("log_excerpt", ""),
            "pid_new": details.get("pid_new", []),
        }
        if result.failed:
            entry["error"] = str(result.longrepr)[-4000:]
        if result.skipped:
            entry["skip_reason"] = str(result.longrepr)[-1000:]
        if details.get("log_path"):
            entry["log_path"] = details["log_path"]
        if details.get("screenshot_error"):
            entry["screenshot_error"] = details["screenshot_error"]
        if details.get("report_data_error"):
            entry["report_data_error"] = details["report_data_error"]
        self.results[item.nodeid] = entry

    def pytest_sessionfinish(self, session, exitstatus):
        self.path = write_report(
            list(self.results.values()),
            self.started_at,
            time.monotonic() - self.started_clock,
        )
        print(f"\nE2E report: {self.path}")
