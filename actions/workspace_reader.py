"""Read-only folder mapping, search, extraction, and organization suggestions."""
from __future__ import annotations

import ast
import csv
import html
import io
import json
import os
import re
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from core.computer_use import configure_tesseract
from core.guardrails import redact_sensitive


MAX_FILES = 300
MAX_FILE_BYTES = 1_000_000
MAX_RESULT_CHARS = 50_000
MAX_SEARCH_MATCHES = 100
MAX_TREE_DEPTH = 8

_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "dist", "build",
})
_SECRET_DIRS = frozenset({"api_keys", "credentials", "keys", "private", "secrets", "tokens"})
_SECRET_FILE = re.compile(
    r"(?i)(?:^\.env(?:\.|$)|api.?keys?|passwords?|credentials?|secrets?|tokens?|private.?keys?|"
    r"id_rsa|id_ed25519|\.pem$|\.p12$|\.pfx$|\.key$)"
)
_TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".xml",
    ".html", ".htm", ".xhtml", ".svg", ".css", ".js", ".jsx", ".ts",
    ".tsx", ".mjs", ".cjs", ".py", ".pyi", ".java", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sh",
    ".bash", ".ps1", ".bat", ".cmd", ".lua", ".r", ".sql", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".properties", ".env.example",
    ".gitignore", ".dockerfile",
})
_CODE_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb",
    ".php", ".swift", ".kt", ".sh", ".bash", ".ps1", ".lua", ".r",
})
_JS_IMPORT = re.compile(
    r"""(?m)^\s*(?:import\s+(?:[^'"]+?\s+from\s+)?|"""
    r"""export\s+[^'"]+?\s+from\s+|require\s*\()\s*['"]([^'"]+)['"]"""
)
_SECRET_ASSIGNMENT = re.compile(
    r"""(?i)(["']?[\w.-]*(?:api[_-]?key|password|passwd|secret|token|"""
    r"""authorization|access[_-]?token|refresh[_-]?token|private[_-]?key)"""
    r"""[\w.-]*["']?\s*[:=]\s*["']?)([^"'\s,;}]+)"""
)


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._ignored += 1
        elif tag.casefold() in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._ignored = max(0, self._ignored - 1)
        elif tag.casefold() in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip())


def _absolute_path(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Provide the absolute path of the file or folder to inspect.")
    candidate = Path(os.path.expandvars(raw.strip().strip('"').strip("'"))).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Workspace paths must be absolute; JARVIS will not guess a folder.")
    if any(_is_reparse_point(ancestor) for ancestor in (candidate, *candidate.parents)):
        raise PermissionError(
            "Symbolic-link and junction paths are not read by the workspace reader."
        )
    try:
        target = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Path not found: {candidate}") from exc
    if not target.is_file() and not target.is_dir():
        raise ValueError("The selected path is not a regular file or folder.")
    if any(
        ancestor.name.startswith(".")
        or ancestor.name.casefold() in _SKIP_DIRS
        or ancestor.name.casefold() in _SECRET_DIRS
        for ancestor in target.parents
    ):
        raise PermissionError("Hidden, secret, and dependency paths are excluded.")
    if (
        (target.is_file() and _is_private_file(target))
        or (target.is_dir() and _is_private_directory(target))
    ):
        raise PermissionError("Hidden, secret, and dependency paths are excluded.")
    return target


def _is_hidden_path(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        return bool(os.stat(path, follow_symlinks=False).st_file_attributes & 0x2)
    except (AttributeError, OSError):
        return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _is_private_file(path: Path) -> bool:
    return _is_hidden_path(path) or bool(_SECRET_FILE.search(path.name))


def _is_private_directory(path: Path) -> bool:
    return (
        _is_hidden_path(path)
        or path.name.casefold() in _SKIP_DIRS
        or path.name.casefold() in _SECRET_DIRS
    )


def _walk_files(
    root: Path,
    max_depth: int,
    max_files: int,
) -> tuple[list[Path], list[str], bool, int]:
    files: list[Path] = []
    errors: list[str] = []
    skipped_private = 0
    truncated = False
    file_limit_reached = False
    pending = [(root, 0)]

    while pending and not file_limit_reached:
        folder, depth = pending.pop()
        try:
            children = sorted(folder.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            errors.append(f"{folder}: {exc}")
            continue
        directories: list[Path] = []
        for item in children:
            if _is_reparse_point(item):
                continue
            if item.is_dir():
                if _is_private_directory(item):
                    skipped_private += 1
                elif depth < max_depth:
                    directories.append(item)
                else:
                    truncated = True
                continue
            if not item.is_file():
                continue
            if _is_private_file(item):
                skipped_private += 1
                continue
            if len(files) >= max_files:
                truncated = True
                file_limit_reached = True
                break
            files.append(item)
        if file_limit_reached:
            break
        pending.extend((directory, depth + 1) for directory in reversed(directories))
    return files, errors, truncated, skipped_private


def _file_metadata(path: Path, root: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise OSError(f"Could not inspect {path}: {exc}") from exc
    return {
        "path": path.relative_to(root).as_posix() if path != root else path.name,
        "extension": path.suffix.casefold() or "(none)",
        "bytes": stat.st_size,
    }


def _redact_text(content: str) -> str:
    sanitized = redact_sensitive(content)
    return _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", sanitized)


def _python_module(path: Path, root: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ][:80]
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append("." * node.level + (node.module or ""))
    return {
        "file": path.relative_to(root).as_posix(),
        "definitions": definitions,
        "imports": sorted(set(imports))[:100],
    }


def _module_map(files: list[Path], root: Path) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for path in files:
        if path.suffix.casefold() not in _CODE_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                modules.append({
                    "file": path.relative_to(root).as_posix(),
                    "note": f"Skipped module analysis: file exceeds {MAX_FILE_BYTES} bytes.",
                })
                continue
            if path.suffix.casefold() in {".py", ".pyi"}:
                modules.append(_python_module(path, root))
                continue
            source = path.read_text(encoding="utf-8-sig")
            imports = sorted(set(_JS_IMPORT.findall(source)))[:100]
            modules.append({
                "file": path.relative_to(root).as_posix(),
                "imports": imports,
            })
        except (OSError, UnicodeError, SyntaxError) as exc:
            modules.append({
                "file": path.relative_to(root).as_posix(),
                "error": f"Module analysis failed: {exc}",
            })
    return modules


def _map_folder(root: Path, max_depth: int, max_files: int) -> str:
    files, errors, truncated, skipped_private = _walk_files(root, max_depth, max_files)
    extensions = Counter(item.suffix.casefold() or "(none)" for item in files)
    modules = _module_map(files, root)
    lines = [
        f"Folder map: {root}",
        f"Files: {len(files)} | Max depth: {max_depth} | "
        f"Truncated: {'yes' if truncated else 'no'}",
        "Excluded hidden/secret folders or files: " + str(skipped_private),
        "",
        "Files:",
    ]
    for item in files:
        try:
            metadata = _file_metadata(item, root)
            lines.append(f"- {metadata['path']} ({metadata['extension']}, {metadata['bytes']} B)")
        except OSError as exc:
            lines.append(f"- {item.relative_to(root).as_posix()} [error: {exc}]")
    lines.extend(["", "File types:"])
    lines.extend(f"- {ext}: {count}" for ext, count in sorted(extensions.items()))
    lines.extend(["", "Code modules:"])
    for module in modules:
        lines.append(f"- {module['file']}")
        if "definitions" in module and module["definitions"]:
            lines.append("  Defines: " + ", ".join(module["definitions"]))
        if module.get("imports"):
            lines.append("  Imports: " + ", ".join(module["imports"]))
        if module.get("error") or module.get("note"):
            lines.append("  " + str(module.get("error") or module.get("note")))
    if errors:
        lines.extend(["", "Read errors:"])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)[:MAX_RESULT_CHARS]


def _extract(path: Path) -> str:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(
            f"File exceeds the {MAX_FILE_BYTES}-byte read limit; use the large-file reader."
        )
    extension = path.suffix.casefold()
    if extension in _TEXT_EXTENSIONS:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        if extension in {".html", ".htm", ".xhtml", ".svg"}:
            parser = _VisibleHTML()
            parser.feed(content)
            content = re.sub(
                r"\s+([,.;:!?])",
                r"\1",
                html.unescape(" ".join(parser.parts)),
            )
        elif extension in {".csv", ".tsv"}:
            dialect = "excel-tab" if extension == ".tsv" else "excel"
            rows = csv.reader(io.StringIO(content), dialect=dialect)
            content = "\n".join(" | ".join(row) for row in rows)
        return content
    if extension == ".pdf":
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("PDF text extraction requires the installed pdfplumber package.") from exc
        with pdfplumber.open(path) as document:
            return "\n\n".join(page.extract_text() or "" for page in document.pages)
    if extension == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX extraction requires the installed python-docx package.") from exc
        document = Document(path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if extension == ".pptx":
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise RuntimeError("PPTX extraction requires the installed python-pptx package.") from exc
        presentation = Presentation(path)
        return "\n".join(
            shape.text
            for slide in presentation.slides
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
        )
    if extension in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("XLSX extraction requires the installed openpyxl package.") from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            return "\n".join(
                f"[{sheet.title}]\n" + "\n".join(
                    " | ".join("" if value is None else str(value) for value in row)
                    for row in sheet.iter_rows(values_only=True)
                )
                for sheet in workbook.worksheets
            )
        finally:
            workbook.close()
    if extension in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        try:
            from PIL import Image
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("Image OCR requires the installed Pillow and pytesseract packages.") from exc
        configure_tesseract(pytesseract)
        try:
            with Image.open(path) as image:
                return pytesseract.image_to_string(image)
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError("Image OCR requires the local Tesseract executable.") from exc
    if extension == ".zip":
        with zipfile.ZipFile(path) as archive:
            return "\n".join(info.filename for info in archive.infolist()[:300])
    return (
        f"No local text extractor is configured for {extension or 'this file type'}. "
        "Use the existing file processor for supported media operations."
    )


def _read_path(target: Path, max_files: int, max_chars: int) -> str:
    if target.is_file():
        files = [target]
        root = target.parent
    else:
        root = target
        files, errors, truncated, skipped_private = _walk_files(root, MAX_TREE_DEPTH, max_files)
        if errors:
            prefix = "Folder scan warnings:\n" + "\n".join(f"- {error}" for error in errors)
        else:
            prefix = ""
        if truncated:
            prefix += f"\nFile list limited to {max_files} items."
        if skipped_private:
            prefix += f"\nHidden/secret entries skipped: {skipped_private}."
    sections: list[str] = [prefix.strip()] if target.is_dir() and prefix.strip() else []
    remaining = max_chars
    for path in files:
        try:
            content = _extract(path)
            content = _redact_text(content)
        except (OSError, UnicodeError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
            content = f"[Read error: {exc}]"
        relative = path.relative_to(root).as_posix() if path != root else path.name
        section = f"### {relative}\n{content.strip() or '[No extractable text]'}"
        if len(section) > remaining:
            sections.append(section[:remaining] + "\n[Output truncated at the configured character limit.]")
            break
        sections.append(section)
        remaining -= len(section) + 2
        if remaining <= 0:
            break
    return "\n\n".join(sections)[:max_chars]


def _search_folder(root: Path, query: str, max_depth: int, max_files: int) -> str:
    needle = query.casefold().strip()
    if not needle:
        raise ValueError("Search requires non-empty query text.")
    files, errors, truncated, skipped_private = _walk_files(root, max_depth, max_files)
    matches: list[str] = []
    for path in files:
        if path.suffix.casefold() not in _TEXT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1
            ):
                safe_line = _redact_text(line)
                if needle in safe_line.casefold():
                    relative = path.relative_to(root).as_posix()
                    matches.append(f"{relative}:{line_number}: {safe_line.strip()[:300]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        break
        except OSError as exc:
            errors.append(f"{path}: {exc}")
        if len(matches) >= MAX_SEARCH_MATCHES:
            break
    lines = [f"Search results for {query!r} in {root}:", *(f"- {line}" for line in matches)]
    if not matches:
        lines.append("- No matching text found in supported text files.")
    if truncated:
        lines.append(f"Scan limited to the first {max_files} files.")
    if skipped_private:
        lines.append(f"Hidden/secret entries skipped: {skipped_private}.")
    if errors:
        lines.extend(["Read errors:", *(f"- {error}" for error in errors)])
    return "\n".join(lines)[:MAX_RESULT_CHARS]


def _reorganization_plan(root: Path, max_depth: int, max_files: int) -> str:
    files, errors, truncated, skipped_private = _walk_files(root, max_depth, max_files)
    categories = {
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
        "Spreadsheets": {".csv", ".tsv", ".xls", ".xlsx", ".ods"},
        "Presentations": {".ppt", ".pptx", ".odp"},
        "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff"},
        "Audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
        "Video": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
        "Code": _CODE_EXTENSIONS,
        "Archives": {".zip", ".7z", ".rar", ".tar", ".gz"},
    }
    lines = [
        f"Suggested organization for {root} (no files were moved or changed):",
    ]
    assigned: set[Path] = set()
    for label, extensions in categories.items():
        group = [path for path in files if path.suffix.casefold() in extensions]
        if group:
            assigned.update(group)
            lines.append(f"- {label}/: {len(group)} file(s)")
    other_count = len(files) - len(assigned)
    if other_count:
        lines.append(f"- Other/: {other_count} file(s) with uncommon or no extension")
    if truncated:
        lines.append(f"Plan covers only the first {max_files} files; scan was capped.")
    if skipped_private:
        lines.append(f"Hidden/secret entries excluded: {skipped_private}.")
    if errors:
        lines.extend(["Scan errors:", *(f"- {error}" for error in errors)])
    lines.append("Confirm the plan explicitly before using file-management actions.")
    return "\n".join(lines)


def workspace_reader(parameters: dict[str, Any] | None = None, **_context: Any) -> str:
    values = parameters or {}
    action = str(values.get("action", "")).strip().casefold()
    if action not in {"map", "read", "search", "plan_reorganization"}:
        raise ValueError("action must be map, read, search, or plan_reorganization.")

    target = _absolute_path(values.get("path"))
    if action == "map" and not target.is_dir():
        raise ValueError("map requires a folder path.")
    if action in {"search", "plan_reorganization"} and not target.is_dir():
        raise ValueError(f"{action} requires a folder path.")
    if action == "search" and not isinstance(values.get("query"), str):
        raise ValueError("search requires a text query.")

    max_depth = values.get("max_depth", 4)
    max_files = values.get("max_files", 100)
    max_chars = values.get("max_chars", 20_000)
    for name, value, minimum, maximum in (
        ("max_depth", max_depth, 0, MAX_TREE_DEPTH),
        ("max_files", max_files, 1, MAX_FILES),
        ("max_chars", max_chars, 1, MAX_RESULT_CHARS),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer from {minimum} to {maximum}.")

    if action == "map":
        return _map_folder(target, max_depth, max_files)
    if action == "read":
        return _read_path(target, max_files, max_chars)
    if action == "search":
        return _search_folder(target, values["query"], max_depth, max_files)
    return _reorganization_plan(target, max_depth, max_files)


TOOL = {
    "name": "workspace_reader",
    "description": (
        "Read-only local workspace assistant. Map a named folder recursively, "
        "inspect code module definitions/imports, search supported text files, "
        "extract text from HTML, PDF, DOCX, PPTX, XLSX, images (local OCR), and "
        "common text/code formats, or suggest an organization plan. Requires an "
        "explicit absolute path; caps traversal/output; skips hidden, secret, and "
        "dependency folders and symbolic links. Never writes, moves, deletes, or "
        "executes files. Unknown/media types are reported and can be handled with "
        "the existing file processor when appropriate."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["map", "read", "search", "plan_reorganization"],
            },
            "path": {"type": "STRING", "description": "Absolute file or folder path explicitly named by the user."},
            "query": {"type": "STRING", "description": "Search text, required for action=search."},
            "max_depth": {"type": "INTEGER", "default": 4},
            "max_files": {"type": "INTEGER", "default": 100},
            "max_chars": {"type": "INTEGER", "default": 20000},
        },
        "required": ["action", "path"],
    },
    "risk_class": "read",
    "handler": workspace_reader,
}
