"""Tests for the extended secret redaction (P4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.guardrails import redact_sensitive


def test_redacts_api_key_assignment():
    out = redact_sensitive("api_key: abcdef1234567890")
    assert "abcdef1234567890" not in out
    assert "[REDACTED]" in out


def test_redacts_openai_and_github_tokens():
    assert "sk-" + "a" * 20 not in redact_sensitive("key is sk-" + "a" * 20)
    assert "ghp_" + "b" * 20 not in redact_sensitive("tok ghp_" + "b" * 20)


def test_redacts_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIs." + "x" * 12 + "." + "y" * 8
    assert jwt not in redact_sensitive(f"token {jwt}")


def test_redacts_aws_access_key():
    assert "AKIA" + "1" * 16 not in redact_sensitive("aws AKIA" + "1" * 16)


def test_redacts_bearer():
    assert "Bearer " + "z" * 30 not in redact_sensitive("Authorization: Bearer " + "z" * 30)


def test_redacts_github_fine_grained_pat():
    pat = "github_pat_" + "A" * 30
    assert pat not in redact_sensitive("pat " + pat)


def test_redacts_nested_structures():
    # redact_sensitive redacts PATTERNS inside string values, not dict keys.
    data = {"outer": [{"note": "password: hunter2"}, "safe"], "n": 5}
    out = redact_sensitive(data)
    assert "hunter2" not in str(out)
    assert "safe" in str(out)
    assert out["n"] == 5


def test_non_string_passthrough():
    assert redact_sensitive(42) == 42
    assert redact_sensitive(None) is None
