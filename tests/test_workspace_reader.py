from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions.workspace_reader import workspace_reader
from core.action_loader import discover_actions
from core.tool_router import ToolRouter


def test_folder_map_lists_files_types_and_python_module_structure(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text(
        "from helper import helper\n\nclass App:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=not-to-read", encoding="utf-8")

    result = workspace_reader({"action": "map", "path": str(tmp_path)})

    assert "README.md" in result
    assert "src/main.py" in result
    assert "Defines: App" in result
    assert "Imports: helper" in result
    assert "hidden.py" not in result
    assert "not-to-read" not in result


def test_read_extracts_visible_html_and_skips_script_content(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        "<h1>Overview</h1><p>Visible <b>content</b>.</p>"
        "<script>private_script_value()</script><style>.secret {}</style>",
        encoding="utf-8",
    )

    result = workspace_reader({"action": "read", "path": str(page)})

    assert "Overview" in result
    assert "Visible content." in result
    assert "private_script_value" not in result
    assert ".secret" not in result


def test_read_extracts_spreadsheet_values(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Name", "Value"])
    sheet.append(["JARVIS", 7])
    path = tmp_path / "report.xlsx"
    workbook.save(path)

    result = workspace_reader({"action": "read", "path": str(path)})

    assert "[Summary]" in result
    assert "Name | Value" in result
    assert "JARVIS | 7" in result


def test_search_reports_matching_file_and_line_and_skips_secrets(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "notes.md").write_text("first line\nJarvis reads folders\n", encoding="utf-8")
    (folder / ".env").write_text("Jarvis API_KEY=private", encoding="utf-8")

    result = workspace_reader({
        "action": "search",
        "path": str(folder),
        "query": "reads folders",
    })

    assert "notes.md:2: Jarvis reads folders" in result
    assert "private" not in result


def test_direct_reads_reject_hidden_or_secret_files(tmp_path):
    secret = tmp_path / "api_keys.json"
    secret.write_text('{"api_key":"do-not-read"}', encoding="utf-8")

    with pytest.raises(PermissionError, match="excluded"):
        workspace_reader({"action": "read", "path": str(secret)})


def test_direct_reads_reject_junction_paths(tmp_path, monkeypatch):
    junction = tmp_path / "junction"
    requested = junction / "nested.txt"
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda candidate: candidate == junction,
        raising=False,
    )

    with pytest.raises(PermissionError, match="junction"):
        workspace_reader({"action": "read", "path": str(requested)})


def test_read_redacts_secrets_from_regular_configuration_files(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"api_key": "sensitive-value-123", "public": "visible"}',
        encoding="utf-8",
    )

    result = workspace_reader({"action": "read", "path": str(settings)})

    assert "sensitive-value-123" not in result
    assert "[REDACTED]" in result
    assert "visible" in result


def test_reorganization_plan_is_advisory_and_does_not_move_files(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF")
    (tmp_path / "notes.txt").write_text("notes", encoding="utf-8")

    result = workspace_reader({"action": "plan_reorganization", "path": str(tmp_path)})

    assert "Documents/: 2 file(s)" in result
    assert "no files were moved or changed" in result
    assert (tmp_path / "report.pdf").is_file()
    assert (tmp_path / "notes.txt").is_file()


def test_folder_map_marks_truncated_only_when_files_exceed_limit(tmp_path):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text(str(index), encoding="utf-8")

    exact = workspace_reader({
        "action": "map",
        "path": str(tmp_path),
        "max_files": 3,
    })
    over = workspace_reader({
        "action": "map",
        "path": str(tmp_path),
        "max_files": 2,
    })

    assert "Files: 3 |" in exact
    assert "Truncated: no" in exact
    assert "Files: 2 |" in over
    assert "Truncated: yes" in over


def test_folder_map_marks_depth_limited_subfolders(tmp_path):
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("deep", encoding="utf-8")

    result = workspace_reader({
        "action": "map",
        "path": str(tmp_path),
        "max_depth": 0,
    })

    assert "Truncated: yes" in result
    assert "deep.txt" not in result


def test_folder_read_includes_scan_limit_and_exclusion_notices(tmp_path):
    (tmp_path / "a-visible.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "b-second.txt").write_text("second", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=private", encoding="utf-8")

    result = workspace_reader({
        "action": "read",
        "path": str(tmp_path),
        "max_files": 1,
    })

    assert "File list limited to 1 items." in result
    assert "Hidden/secret entries skipped: 1." in result
    assert "a-visible.txt" in result
    assert "private" not in result


@pytest.mark.parametrize(
    ("action", "path", "extra", "message"),
    [
        ("map", "relative/path", {}, "absolute"),
        ("map", "relative/path", {"max_depth": 99}, "absolute"),
        ("search", ".", {"query": ""}, "absolute"),
    ],
)
def test_invalid_workspace_requests_are_rejected(action, path, extra, message):
    with pytest.raises((ValueError, PermissionError), match=message):
        workspace_reader({"action": action, "path": path, **extra})


def test_workspace_action_is_discovered_and_selected_for_folder_requests():
    root = Path(__file__).resolve().parents[1]
    registry = discover_actions(root / "actions", logger=lambda _message: None)

    assert "workspace_reader" in registry.names()
    assert registry.risk_class("workspace_reader") == "read"
    declarations = [{"name": "workspace_reader"}, {"name": "hud_control"}]
    selected = ToolRouter().select_for_request(
        "Crea una mappa dei moduli e cerca nella cartella del progetto",
        declarations,
    )
    assert [item["name"] for item in selected] == ["workspace_reader"]


def test_existing_desktop_browser_web_and_script_tools_route_for_requests():
    declarations = [
        {"name": name}
        for name in (
            "computer_input",
            "computer_perception",
            "workspace_reader",
            "file_processor",
            "browser_control",
            "web_search",
        )
    ]
    router = ToolRouter()

    keyboard = router.select_for_request("Premi il tasto F24 nel computer", declarations)
    screen = router.select_for_request("Leggi etichette con OCR sullo schermo", declarations)
    script = router.select_for_request("Spiega questo script Python", declarations)
    browser = router.select_for_request("Leggi questa pagina HTML e clicca il link", declarations)
    web = router.select_for_request("Fai una ricerca web sulle novità", declarations)

    assert "computer_input" in {item["name"] for item in keyboard}
    assert "computer_perception" in {item["name"] for item in screen}
    assert "file_processor" in {item["name"] for item in script}
    assert "browser_control" in {item["name"] for item in browser}
    assert "web_search" in {item["name"] for item in web}
    selected = ToolRouter().select_for_request(
        "Mappa la cartella e mostra i moduli",
        declarations + [{"name": "hud_control"}, {"name": "ui_layout"}],
    )
    selected_names = {item["name"] for item in selected}
    assert {"workspace_reader", "file_processor"} <= selected_names
    assert not {"hud_control", "ui_layout"} & selected_names
