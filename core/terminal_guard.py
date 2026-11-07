"""Fail-closed command policy loading and analysis."""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "config" / "terminal_policy.yaml"
_SHELL_OPERATORS = {";", "&&", "||", "|", ">", ">>", "<", "<<", "&"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class TerminalPolicyError(ValueError):
    """The terminal policy is missing or invalid."""


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    blocked: bool
    requires_override: bool
    reason: str
    command: str
    argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class TerminalPolicy:
    version: int
    allowed_executables: frozenset[str]
    blocked_patterns: tuple[tuple[re.Pattern[str], str], ...]
    source: Path
    content: str
    sha256: str


def load_policy(path: str | Path | None = None) -> TerminalPolicy:
    policy_path = Path(path) if path is not None else _DEFAULT_POLICY
    try:
        content = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TerminalPolicyError(
            f"Cannot read terminal policy {policy_path}: {type(exc).__name__}."
        ) from None
    try:
        raw: Any = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise TerminalPolicyError(
            f"Invalid terminal policy YAML ({type(exc).__name__})."
        ) from None
    if not isinstance(raw, dict):
        raise TerminalPolicyError("Terminal policy must be a YAML object.")

    version = raw.get("version")
    executables = raw.get("allowed_executables")
    patterns = raw.get("blocked_patterns")
    if isinstance(version, bool) or version != 1:
        raise TerminalPolicyError("Terminal policy version must be 1.")
    if (
        not isinstance(executables, list)
        or not executables
        or any(not isinstance(item, str) or not item.strip() for item in executables)
    ):
        raise TerminalPolicyError("allowed_executables must be a non-empty string list.")
    if not isinstance(patterns, list):
        raise TerminalPolicyError("blocked_patterns must be a list.")
    compiled: list[tuple[re.Pattern[str], str]] = []
    for item in patterns:
        if not isinstance(item, dict):
            raise TerminalPolicyError("Each blocked pattern must be a YAML object.")
        expression, reason = item.get("pattern"), item.get("reason")
        if not isinstance(expression, str) or not isinstance(reason, str) or not reason.strip():
            raise TerminalPolicyError("Each blocked pattern needs a pattern and reason.")
        try:
            compiled.append((re.compile(expression), reason.strip()))
        except re.error as exc:
            raise TerminalPolicyError(
                f"Invalid blocked command regex ({exc.__class__.__name__})."
            ) from None
    return TerminalPolicy(
        version=version,
        allowed_executables=frozenset(item.strip().casefold() for item in executables),
        blocked_patterns=tuple(compiled),
        source=policy_path.resolve(),
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


class TerminalGuard:
    def __init__(self, policy_path: str | Path | None = None) -> None:
        self.policy = load_policy(policy_path)

    @staticmethod
    def _parse(command: str) -> tuple[str, ...]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Command must be non-empty text.")
        if len(command) > 10_000 or _CONTROL_CHARS.search(command):
            raise ValueError("Command contains invalid control characters or exceeds 10 KB.")
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            lexer.commenters = ""
            argv = tuple(lexer)
        except ValueError as exc:
            raise ValueError("Command quoting is invalid.") from exc
        if not argv:
            raise ValueError("Command must be non-empty text.")
        if any(token in _SHELL_OPERATORS for token in argv):
            raise ValueError("Shell operators are not supported; commands run without a shell.")
        return argv

    def inspect(self, command: str) -> PolicyResult:
        try:
            argv = self._parse(command)
        except ValueError as exc:
            return PolicyResult(
                allowed=False,
                blocked=True,
                requires_override=False,
                reason=str(exc),
                command=command if isinstance(command, str) else "",
            )
        normalized = " ".join(argv)
        for pattern, reason in self.policy.blocked_patterns:
            if pattern.search(normalized):
                return PolicyResult(
                    allowed=False,
                    blocked=True,
                    requires_override=True,
                    reason=reason,
                    command=command,
                    argv=argv,
                )
        executable = Path(argv[0]).name.casefold()
        if executable not in self.policy.allowed_executables:
            return PolicyResult(
                allowed=False,
                blocked=True,
                requires_override=True,
                reason=f"Executable '{executable}' is not in the allowed command policy.",
                command=command,
                argv=argv,
            )
        return PolicyResult(
            allowed=True,
            blocked=False,
            requires_override=False,
            reason="Command matches the allowlist and no blocked pattern.",
            command=command,
            argv=argv,
        )
