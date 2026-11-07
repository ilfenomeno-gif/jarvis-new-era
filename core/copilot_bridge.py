"""Guarded, persistent handoff packaging for the user's immutable Copilot prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence

from core.internal_workflow import default_database_path


class CopilotPromptNotFound(Exception):
    """No configured Copilot prompt file exists."""


class CopilotPromptEmpty(Exception):
    """The configured Copilot prompt exists but has no meaningful content."""


class CopilotPromptModified(Exception):
    """The Copilot prompt changed after it was loaded for a handoff."""


class CopilotHandoffInvalid(Exception):
    """The handoff request or one of its attachments is invalid."""


@dataclass(frozen=True)
class HandoffFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class HandoffPackage:
    prompt: str
    prompt_hash: str
    prompt_state: str
    files: tuple[HandoffFile, ...]
    task: str
    instructions: str
    checklist: tuple[str, ...]
    created_at: str
    prompt_path: Path
    extra: dict[str, object] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompt_state(content: str) -> str:
    if content.strip() == "":
        return "empty"
    if content.lstrip().startswith("# BOZZA"):
        return "draft"
    return "approved"


class CopilotBridge:
    """Build and persist confirmed handoffs without ever writing the source prompt."""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )

    def _configured_prompt_path(self) -> Path | None:
        config_path = self.repo_root / "config" / "copilot.yaml"
        if not config_path.is_file():
            return None
        try:
            config_text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CopilotHandoffInvalid(
                f"Impossibile leggere la configurazione Copilot {config_path}: {exc}"
            ) from exc

        match = re.search(r"^\s*prompt_path\s*:\s*(.*?)\s*$", config_text, re.MULTILINE)
        if not match:
            return None
        value = match.group(1).split(" #", 1)[0].strip()
        if not value:
            return None
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise CopilotHandoffInvalid(
                    f"Valore prompt_path non valido in {config_path}."
                ) from exc
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1].replace("''", "'")
        configured = Path(value).expanduser()
        return configured if configured.is_absolute() else self.repo_root / configured

    @staticmethod
    def _read_prompt(path: Path) -> tuple[str, bytes]:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise CopilotHandoffInvalid(
                f"Impossibile leggere il prompt Copilot {path}: {exc}"
            ) from exc
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CopilotHandoffInvalid(
                f"Il prompt Copilot {path} non è UTF-8 valido."
            ) from exc
        if prompt_state(content) == "empty":
            raise CopilotPromptEmpty(
                f"Prompt Copilot vuoto: {path} (size={len(raw)} byte). "
                "Compilare il file originale; non verrà creato alcun sostituto."
            )
        return content, raw

    def _load_prompt_source(
        self, path: str | Path | None = None
    ) -> tuple[str, bytes, Path]:
        if path is not None:
            explicit = Path(path).expanduser()
            if not explicit.is_absolute():
                explicit = self.repo_root / explicit
            try:
                content, raw = self._read_prompt(explicit)
            except FileNotFoundError as exc:
                raise CopilotPromptNotFound(
                    f"Prompt Copilot non trovato: {explicit} (stato=not_found)."
                ) from exc
            return content, raw, explicit.resolve()

        default_path = self.repo_root / "prompts" / "copilot_prompt.md"
        searched = [default_path]
        if default_path.is_file():
            content, raw = self._read_prompt(default_path)
            return content, raw, default_path.resolve()

        configured_path = self._configured_prompt_path()
        if configured_path is not None:
            searched.append(configured_path)
            if configured_path.is_file():
                content, raw = self._read_prompt(configured_path)
                return content, raw, configured_path.resolve()

        environment_value = os.environ.get("JARVIS_COPILOT_PROMPT")
        if environment_value:
            environment_path = Path(environment_value).expanduser()
            if not environment_path.is_absolute():
                environment_path = self.repo_root / environment_path
            searched.append(environment_path)
            if environment_path.is_file():
                content, raw = self._read_prompt(environment_path)
                return content, raw, environment_path.resolve()

        searched_paths = "\n".join(f"- {candidate}" for candidate in searched)
        raise CopilotPromptNotFound(
            "Prompt Copilot non trovato (stato=not_found). Percorsi cercati:\n"
            f"{searched_paths}"
        )

    def load_prompt(self, path: str | Path | None = None) -> str:
        """Return the UTF-8 text without newline or whitespace normalization."""
        content, _, _ = self._load_prompt_source(path)
        return content

    def package_handoff(
        self,
        files: Sequence[str | Path],
        task: str,
        extra: dict[str, object] | None = None,
    ) -> HandoffPackage:
        prompt, prompt_bytes, prompt_path = self._load_prompt_source()
        if not isinstance(task, str) or not task.strip():
            raise CopilotHandoffInvalid("Il task dell'handoff non può essere vuoto.")
        if not isinstance(files, Sequence) or isinstance(files, (str, bytes)) or not files:
            raise CopilotHandoffInvalid("Specificare almeno un file da allegare.")
        if extra is not None and not isinstance(extra, dict):
            raise CopilotHandoffInvalid("extra deve essere un dizionario.")
        if extra is not None:
            try:
                json.dumps(extra, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise CopilotHandoffInvalid(
                    "extra deve contenere soltanto valori serializzabili in JSON."
                ) from exc

        attachments: list[HandoffFile] = []
        root = self.repo_root.resolve()
        for supplied_path in files:
            candidate = Path(supplied_path).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = candidate.resolve()
            try:
                relative_path = resolved.relative_to(root)
            except ValueError as exc:
                raise CopilotHandoffInvalid(
                    f"Il file allegato è fuori dal repository: {supplied_path}"
                ) from exc
            if not resolved.is_file():
                raise CopilotHandoffInvalid(
                    f"Il file allegato non esiste o non è un file: {supplied_path}"
                )
            try:
                raw = resolved.read_bytes()
            except OSError as exc:
                raise CopilotHandoffInvalid(
                    f"Impossibile leggere il file allegato {relative_path}: {exc}"
                ) from exc
            attachments.append(
                HandoffFile(
                    path=relative_path.as_posix(),
                    sha256=_sha256(raw),
                    size=len(raw),
                )
            )

        instructions = (
            "Implementare esclusivamente il task indicato, usando il prompt Copilot "
            "originale allegato senza modificarlo. Verificare le modifiche con test "
            "e riportare risultati e limiti."
        )
        checklist = (
            "Leggere il prompt Copilot originale senza modificarlo.",
            "Esaminare tutti i file allegati e i vincoli del task.",
            "Implementare solo il task richiesto.",
            "Eseguire test e controlli pertinenti.",
            "Riportare risultati verificati, limiti e file modificati.",
        )
        return HandoffPackage(
            prompt=prompt,
            prompt_hash=_sha256(prompt_bytes),
            prompt_state=prompt_state(prompt),
            files=tuple(attachments),
            task=task.strip(),
            instructions=instructions,
            checklist=checklist,
            created_at=_utc_now(),
            prompt_path=prompt_path,
            extra=extra,
        )

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_handoffs (
                handoff_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                task TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                files_hash_set TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                prompt_state TEXT NOT NULL DEFAULT ''
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(copilot_handoffs)")
        }
        if "prompt_state" not in columns:
            connection.execute(
                "ALTER TABLE copilot_handoffs "
                "ADD COLUMN prompt_state TEXT NOT NULL DEFAULT ''"
            )
        return connection

    @staticmethod
    def _package_payload(package: HandoffPackage) -> dict[str, object]:
        return {
            "prompt": package.prompt,
            "prompt_hash": package.prompt_hash,
            "prompt_state": package.prompt_state,
            "prompt_path": str(package.prompt_path),
            "files": [
                {"path": item.path, "sha256": item.sha256, "size": item.size}
                for item in package.files
            ],
            "task": package.task,
            "instructions": package.instructions,
            "checklist": list(package.checklist),
            "created_at": package.created_at,
            "extra": package.extra,
        }

    def verify_prompt_intact(self, prompt_text: str, path: str | Path) -> bool:
        prompt_path = Path(path)
        if not prompt_path.is_absolute():
            prompt_path = self.repo_root / prompt_path
        try:
            current_bytes = prompt_path.read_bytes()
            expected_bytes = prompt_text.encode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise CopilotPromptModified(
                f"Impossibile verificare il prompt Copilot {prompt_path}: {exc}"
            ) from exc
        if current_bytes != expected_bytes:
            raise CopilotPromptModified(
                f"Il prompt Copilot è stato modificato durante l'handoff: {prompt_path}"
            )
        return True

    def record_handoff(self, package: HandoffPackage) -> str:
        if not isinstance(package, HandoffPackage):
            raise CopilotHandoffInvalid("È richiesto un HandoffPackage valido.")
        self.verify_prompt_intact(package.prompt, package.prompt_path)
        if _sha256(package.prompt.encode("utf-8")) != package.prompt_hash:
            raise CopilotHandoffInvalid("L'hash del prompt nel pacchetto non corrisponde.")
        if not package.task.strip() or not package.files:
            raise CopilotHandoffInvalid("Il pacchetto richiede task e almeno un allegato.")
        root = self.repo_root.resolve()
        for item in package.files:
            candidate = (root / item.path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise CopilotHandoffInvalid(
                    f"Il file allegato è fuori dal repository: {item.path}"
                ) from exc
            if not candidate.is_file():
                raise CopilotHandoffInvalid(
                    f"Il file allegato non esiste più: {item.path}"
                )
            try:
                current_bytes = candidate.read_bytes()
            except OSError as exc:
                raise CopilotHandoffInvalid(
                    f"Impossibile rileggere il file allegato {item.path}: {exc}"
                ) from exc
            if len(current_bytes) != item.size or _sha256(current_bytes) != item.sha256:
                raise CopilotHandoffInvalid(
                    f"Il file allegato è cambiato durante l'handoff: {item.path}"
                )
        file_hashes = sorted({item.sha256 for item in package.files})
        files_hash_set = json.dumps(file_hashes, separators=(",", ":"))
        fingerprint_value = json.dumps(
            [package.task, package.prompt_hash, file_hashes],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        fingerprint = _sha256(fingerprint_value.encode("utf-8"))
        handoff_id = f"copilot_{fingerprint[:24]}"
        payload = json.dumps(
            self._package_payload(package),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO copilot_handoffs (
                    handoff_id, fingerprint, task, prompt_hash, files_hash_set,
                    payload_json, status, created_at, prompt_state
                ) VALUES (?, ?, ?, ?, ?, ?, 'recorded', ?, ?)
                """,
                (
                    handoff_id,
                    fingerprint,
                    package.task,
                    package.prompt_hash,
                    files_hash_set,
                    payload,
                    package.created_at,
                    package.prompt_state,
                ),
            )
            row = connection.execute(
                "SELECT handoff_id FROM copilot_handoffs WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            raise RuntimeError("SQLite non ha restituito il record dell'handoff.")
        return str(row[0])

    def write_handoff_file(self, package: HandoffPackage) -> Path:
        """Write a temporary, self-contained brief while leaving source files untouched."""
        if not isinstance(package, HandoffPackage):
            raise CopilotHandoffInvalid("È richiesto un HandoffPackage valido.")
        sections = [
            "# Copilot Handoff",
            "",
            "## Task",
            package.task,
            "",
            "## Istruzioni",
            package.instructions,
            "",
            "## Prompt Copilot originale",
            package.prompt,
            "",
            "## File allegati",
        ]
        total_embedded = 0
        for item in package.files:
            path = (self.repo_root / item.path).resolve()
            sections.extend(
                [
                    "",
                    f"### `{item.path}`",
                    f"SHA-256: `{item.sha256}`; dimensione: {item.size} byte.",
                    f"Percorso locale: `{path}`",
                ]
            )
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                sections.append("Contenuto non incorporato; aprire il file al percorso locale.")
                continue
            if item.size > 128_000 or total_embedded + item.size > 512_000:
                sections.append("File testuale non incorporato per il limite di dimensione.")
                continue
            total_embedded += item.size
            longest_fence = max(
                (len(match.group(0)) for match in re.finditer(r"`+", text)),
                default=0,
            )
            fence = "`" * max(3, longest_fence + 1)
            sections.extend(["", f"{fence}text", text, fence])

        sections.extend(
            [
                "",
                "## Checklist",
                *[f"- [ ] {item}" for item in package.checklist],
                "",
                "---",
                "Questo brief è stato aperto in VS Code. La CLI di VS Code non può "
                "inviare automaticamente il testo alla chat Copilot.",
                "",
            ]
        )
        directory = Path(tempfile.mkdtemp(prefix="jarvis-copilot-"))
        handoff_path = directory / "copilot_task.md"
        handoff_path.write_text("\n".join(sections), encoding="utf-8", newline="\n")
        return handoff_path

    def resume_handoff(self, handoff_id: str) -> dict[str, object] | None:
        """Load the persisted handoff checkpoint after an application restart."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM copilot_handoffs WHERE handoff_id = ?",
                (handoff_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None


def is_copilot_handoff_intent(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:passa|invia|handoff|prepara|consegna)\s+(?:a\s+)?copilot\b|"
            r"\bcopilot\s+handoff\b",
            text,
            re.IGNORECASE,
        )
    )


def handle_copilot_chat_handoff(
    text: str,
    bridge: CopilotBridge,
    confirm_request: Callable[[str, str, Callable[[], str]], str],
    *,
    open_handoff: Callable[[Path], bool] | None = None,
) -> str | None:
    """Validate a chat handoff request and defer persistence to the HUD confirmation."""
    if not is_copilot_handoff_intent(text):
        return None
    try:
        bridge.load_prompt()
    except (CopilotPromptNotFound, CopilotPromptEmpty, CopilotHandoffInvalid) as exc:
        return str(exc)

    match = re.search(
        r"\btask\s*:\s*(.*?)\s*(?:\|\s*|;\s*)files\s*:\s*(.+)$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return (
            "Prompt Copilot presente. Per preparare l'handoff indichi task e file "
            "nel formato: `passa a Copilot task: ... | files: percorso1, percorso2`."
        )
    task = match.group(1).strip()
    file_values = [value.strip().strip('"') for value in match.group(2).split(",")]
    try:
        package = bridge.package_handoff(file_values, task)
    except (
        CopilotPromptNotFound,
        CopilotPromptEmpty,
        CopilotHandoffInvalid,
        CopilotPromptModified,
    ) as exc:
        return str(exc)

    summary = (
        f"Task: {package.task}\n"
        f"File allegati: {len(package.files)}\n"
        f"Stato prompt: {package.prompt_state}\n"
        + (
            "ATTENZIONE: Il prompt Copilot è attualmente in BOZZA.\n"
            if package.prompt_state == "draft"
            else ""
        )
        +
        f"Hash prompt: {package.prompt_hash}\n"
        "Nessun invio a Copilot avverrà in questa fase."
    )

    def record_after_confirmation() -> str:
        handoff_id = bridge.record_handoff(package)
        handoff_path = bridge.write_handoff_file(package)
        opened = open_handoff(handoff_path) if open_handoff else open_handoff_in_vscode(handoff_path)
        status = "aperto in VS Code" if opened else "creato ma non aperto (comando `code` non disponibile)"
        return (
            f"Handoff registrato: {handoff_id}. Brief {status}: {handoff_path}. "
            "La CLI non invia automaticamente il contenuto alla chat Copilot."
        )

    return confirm_request(
        "Conferma handoff Copilot",
        summary,
        record_after_confirmation,
    )


def open_handoff_in_vscode(path: str | Path) -> bool:
    """Open a prepared handoff in VS Code; this does not submit it to Copilot Chat."""
    try:
        subprocess.Popen(["code", "--reuse-window", str(path)], shell=False)
    except (OSError, PermissionError):
        return False
    return True


def handle_copilot_handoff_cli(
    argv: Sequence[str],
    *,
    repo_root: str | Path | None = None,
    bridge: CopilotBridge | None = None,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], object] = print,
    open_handoff: Callable[[Path], bool] | None = None,
) -> int | None:
    """Handle the standalone CLI flow; return None when it was not requested."""
    if "--copilot-handoff" not in argv:
        return None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--copilot-handoff", action="store_true")
    parser.add_argument("--task", required=True)
    parser.add_argument("--files", nargs="+", required=True)
    try:
        args, _ = parser.parse_known_args(list(argv))
    except SystemExit:
        output(
            "Handoff non eseguito: specificare --task e almeno un percorso con --files."
        )
        return 2

    active_bridge = bridge or CopilotBridge(repo_root=repo_root)
    try:
        package = active_bridge.package_handoff(args.files, args.task)
    except CopilotPromptEmpty as exc:
        output(f"Errore prompt (stato=empty): {exc}")
        return 2
    except CopilotPromptNotFound as exc:
        output(f"Errore prompt (stato=not_found): {exc}")
        return 2
    except (CopilotHandoffInvalid, CopilotPromptModified) as exc:
        output(f"Handoff non valido: {exc}")
        return 2

    output(
        "Pacchetto Copilot pronto per revisione (nessun invio automatico a Copilot):\n"
        f"Task: {package.task}\n"
        f"File allegati: {len(package.files)}\n"
        f"Stato prompt: {package.prompt_state}\n"
        + (
            "ATTENZIONE: Il prompt Copilot è attualmente in BOZZA.\n"
            if package.prompt_state == "draft"
            else ""
        )
        +
        f"Hash prompt: {package.prompt_hash}\n"
        f"Hash file: {', '.join(item.sha256 for item in package.files)}"
    )
    try:
        answer = input_fn("Registrare l'handoff? Digitare SI per confermare: ").strip()
    except (EOFError, OSError):
        output("Handoff non registrato: conferma non disponibile.")
        return 2
    if answer.casefold() not in {"si", "sì", "yes"}:
        output("Handoff annullato; nessun record è stato salvato.")
        return 2

    try:
        active_bridge.verify_prompt_intact(package.prompt, package.prompt_path)
        handoff_id = active_bridge.record_handoff(package)
        handoff_path = active_bridge.write_handoff_file(package)
    except (CopilotPromptModified, CopilotHandoffInvalid) as exc:
        output(f"Handoff non registrato: {exc}")
        return 2
    output(f"Handoff registrato in SQLite: {handoff_id}")
    opened = open_handoff(handoff_path) if open_handoff else open_handoff_in_vscode(handoff_path)
    output(
        f"Brief {'aperto in VS Code' if opened else 'creato ma non aperto'}: {handoff_path}"
    )
    output("La CLI di VS Code non invia automaticamente il contenuto alla chat Copilot.")
    return 0
