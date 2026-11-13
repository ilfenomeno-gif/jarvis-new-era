"""Load local environment values without overriding the launching process."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: Path) -> int:
    """Load simple KEY=VALUE entries; never execute shell syntax or replace env vars."""
    path = Path(path)
    try:
        contents = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise RuntimeError(f"Unable to read environment file {path}: {exc}") from exc

    loaded = 0
    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not _NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid environment entry at {path}:{line_number}.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif value.startswith(("'", '"')):
            raise ValueError(f"Unclosed quote at {path}:{line_number}.")
        if name not in os.environ:
            os.environ[name] = value
            loaded += 1
    return loaded


def save_env_values(path: Path, values: dict[str, str]) -> None:
    """Atomically update local KEY=VALUE entries without exposing values in logs."""
    path = Path(path)
    if not values:
        return

    normalized: dict[str, str] = {}
    for name, value in values.items():
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {name!r}.")
        if not isinstance(value, str) or any(char in value for char in "\r\n\0"):
            raise ValueError(f"Invalid value for environment variable {name}.")
        normalized[name] = value.strip()

    try:
        contents = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        contents = ""
    except OSError as exc:
        raise RuntimeError(f"Unable to read environment file {path}: {exc}") from exc

    pending = dict(normalized)
    output: list[str] = []
    for line in contents.splitlines():
        candidate = line.strip()
        if candidate.startswith("export "):
            candidate = candidate[len("export "):].lstrip()
        name, separator, _ = candidate.partition("=")
        name = name.strip()
        if separator and name in normalized:
            if name in pending:
                output.append(f"{name}={pending.pop(name)}")
        else:
            output.append(line)
    output.extend(f"{name}={value}" for name, value in pending.items())
    serialized = "\n".join(output)
    if output:
        serialized += "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(serialized)
            temp_path = Path(temp_file.name)
        os.replace(temp_path, path)
    except OSError as exc:
        raise RuntimeError(f"Unable to save environment file {path}: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
