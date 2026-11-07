"""Run the Phase A terminal benchmark against the ComputerLoop in local fixtures."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.audit_log import AuditLog  # noqa: E402
from core.computer_loop import ComputerLoop  # noqa: E402
from core.memory_store import MemoryStore  # noqa: E402
from core.terminal_agent import TerminalAgent  # noqa: E402


def _step(
    description: str,
    operation: str,
    *,
    verify: dict[str, Any] | None = None,
    **action: Any,
) -> dict[str, Any]:
    return {
        "description": description,
        "action": {"type": "terminal", "operation": operation, **action},
        "verify": verify or {"exit_code": 0},
    }


def _run_task(
    loop: ComputerLoop,
    name: str,
    goal: str,
    step: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    loop.planner = lambda *_args, planned=step: [planned]
    started = time.perf_counter()
    result = loop.run(goal, workspace=workspace)
    elapsed = (time.perf_counter() - started) * 1000
    step_result = result.steps[-1] if result.steps else None
    return {
        "task": name,
        "status": result.status,
        "success": result.status == "completed",
        "steps": len(result.steps),
        "retries": result.retry_count,
        "elapsed_ms": round(elapsed, 2),
        "stdout_bytes": len(step_result.stdout.encode("utf-8")) if step_result else 0,
        "stdout_lines": len(step_result.stdout.splitlines()) if step_result else 0,
        "stdout_preview": step_result.stdout[:1000] if step_result else "",
        "attempt_details": [
            {
                "attempt": item.attempt,
                "success": item.success,
                "verification": item.verification,
                "stdout": item.stdout[:300],
                "stderr": item.stderr[:300],
            }
            for item in result.steps
        ],
        "returncode": step_result.returncode if step_result else None,
        "summary": result.summary,
        "stdout": step_result.stdout if step_result else "",
        "stderr": step_result.stderr if step_result else "",
    }


def _relative(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


def run_benchmark() -> dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory(prefix="jarvis-computer-loop-") as directory:
        fixture = Path(directory).resolve()
        project = fixture / "fixture-project"
        project.mkdir()
        (project / "sample.py").write_text(
            "def benchmark_marker():\n    return 'computer-loop-marker'\n",
            encoding="utf-8",
        )
        (project / "notes.log").write_text("log data\n", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_sample.py").write_text(
            "def test_sample():\n    assert 2 + 2 == 4\n",
            encoding="utf-8",
        )
        jpeg = fixture / "photos"
        jpeg.mkdir()
        (jpeg / "one.jpeg").write_bytes(b"jpeg-one")
        (jpeg / "two.jpeg").write_bytes(b"jpeg-two")

        loop = ComputerLoop(
            terminal_agent=TerminalAgent(database_path=fixture / "terminal.sqlite3"),
            memory_store=MemoryStore(fixture / "memory.sqlite3"),
            audit_log=AuditLog(fixture / "audit.jsonl"),
            max_retries=3,
            timeout_seconds=30,
            confirmation_requester=lambda *_args, **_kwargs: (
                "Confirmation unavailable; nothing was run."
            ),
        )
        try:
            results.append(_run_task(
                loop,
                "1_list_python_files",
                "List Python files in the current project.",
                _step(
                    "List Python files",
                    "list_python_files",
                    path=".",
                    verify={"stdout_contains": "core/computer_loop.py"},
                ),
                ROOT,
            ))
            results.append(_run_task(
                loop,
                "2_sum_log_sizes",
                "Find project log files and report their total byte size.",
                _step(
                    "Sum project log sizes",
                    "sum_log_sizes",
                    path=".",
                    verify={"stdout_contains": "total_bytes="},
                ),
                ROOT,
            ))
            results.append(_run_task(
                loop,
                "3_copy_file_and_verify",
                "Create a destination directory, copy a Python file, and verify it.",
                _step(
                    "Copy file into a new directory",
                    "copy_file",
                    source=_relative(fixture, project / "sample.py"),
                    destination="copies/sample.py",
                    verify={"path_exists": "copies/sample.py"},
                ),
                fixture,
            ))
            results.append(_run_task(
                loop,
                "4_run_pytest",
                "Run pytest on the fixture project and report its result.",
                _step(
                    "Run the project's computer-loop tests",
                    "run_pytest",
                    path="tests/test_computer_loop.py",
                    config="pytest.ini",
                    verify={"exit_code": 0},
                ),
                ROOT,
            ))
            results.append(_run_task(
                loop,
                "5_search_python_files",
                "Search the project Python sources for the opt-in flag.",
                _step(
                    "Search Python files",
                    "search_text",
                    path=".",
                    term="JARVIS_COMPUTER_LOOP",
                    verify={"stdout_contains": "computer_loop.py"},
                ),
                ROOT,
            ))
            results.append(_run_task(
                loop,
                "6_rename_jpeg_files",
                "Rename all JPEG fixture files to the JPG extension.",
                _step(
                    "Rename JPEG files",
                    "rename_extension",
                    path=_relative(fixture, jpeg),
                    verify={"stdout_contains": "one.jpg"},
                ),
                fixture,
            ))
            results.append(_run_task(
                loop,
                "7_create_zip_backup",
                "Create and verify a zip backup of the fixture project.",
                _step(
                    "Create fixture ZIP backup",
                    "zip_backup",
                    path=_relative(fixture, project),
                    archive="backup.zip",
                    verify={"path_exists": "backup.zip"},
                ),
                fixture,
            ))
            results.append(_run_task(
                loop,
                "8_find_port_8080_owner",
                "Find the process currently listening on port 8080, if any.",
                _step(
                    "Inspect port owner",
                    "find_port",
                    port=8080,
                    verify={"exit_code": 0},
                ),
                fixture,
            ))
            results.append(_run_task(
                loop,
                "9_count_project_lines",
                "Count Python source lines in the fixture project.",
                _step(
                    "Count project Python source lines",
                    "count_lines",
                    path=".",
                    verify={"stdout_contains": "files="},
                ),
                ROOT,
            ))
            results.append({
                "task": "10_git_branch_and_commit",
                "status": "blocked",
                "success": False,
                "steps": 0,
                "retries": 0,
                "elapsed_ms": 0,
                "returncode": None,
                "summary": (
                    "Not executed: the current task explicitly forbids commits; "
                    "the feature branch is the only branch created."
                ),
                "stdout": "",
                "stderr": "Commit prohibited by user instruction.",
            })
        finally:
            loop.close()

    return {
        "schema_version": 1,
        "tasks": results,
        "passed": sum(result["success"] for result in results),
        "total": len(results),
        "checkpoint_passed": sum(result["success"] for result in results) >= 8,
        "note": (
            "Tasks 1, 2, 4, 5, and 9 ran read-only against the current project; "
            "write tasks used isolated fixture files. Task 10 was not attempted "
            "because commit "
            "creation is explicitly prohibited."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2))
