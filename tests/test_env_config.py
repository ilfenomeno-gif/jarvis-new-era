from __future__ import annotations

import os

import pytest

from core.env_config import load_env_file, save_env_values


def test_load_env_file_reads_values_without_overriding_process_environment(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\ufeff# local secrets\n"
        "JARVIS_TEST_ENV=from-file\n"
        "export JARVIS_TEST_QUOTED=\"quoted value\"\n"
        "JARVIS_TEST_PRECEDENCE=file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_TEST_PRECEDENCE", "from-process")

    assert load_env_file(env_file) == 2
    assert os.environ["JARVIS_TEST_ENV"] == "from-file"
    assert os.environ["JARVIS_TEST_QUOTED"] == "quoted value"
    assert os.environ["JARVIS_TEST_PRECEDENCE"] == "from-process"


def test_load_env_file_rejects_malformed_entries(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("not-an-assignment\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid environment entry"):
        load_env_file(env_file)


def test_load_env_file_ignores_missing_optional_file(tmp_path):
    assert load_env_file(tmp_path / ".env") == 0


def test_save_env_values_updates_entries_without_duplicate_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# local settings\n"
        "JARVIS_TEST_ID=old\n"
        "KEEP_ME=unchanged\n"
        "export JARVIS_TEST_ID=duplicate\n",
        encoding="utf-8",
    )

    save_env_values(
        env_file,
        {
            "JARVIS_TEST_ID": "new-client-id",
            "JARVIS_TEST_SECRET": "secret=with=equals",
        },
    )

    assert env_file.read_text(encoding="utf-8") == (
        "# local settings\n"
        "JARVIS_TEST_ID=new-client-id\n"
        "KEEP_ME=unchanged\n"
        "JARVIS_TEST_SECRET=secret=with=equals\n"
    )
    monkeypatch.delenv("JARVIS_TEST_ID", raising=False)
    monkeypatch.delenv("JARVIS_TEST_SECRET", raising=False)
    monkeypatch.delenv("KEEP_ME", raising=False)
    assert load_env_file(env_file) == 3
    assert os.environ["JARVIS_TEST_ID"] == "new-client-id"
    assert os.environ["JARVIS_TEST_SECRET"] == "secret=with=equals"


def test_save_env_values_rejects_line_injection_without_writing(tmp_path):
    env_file = tmp_path / ".env"
    with pytest.raises(ValueError, match="Invalid value"):
        save_env_values(env_file, {"JARVIS_TEST_SECRET": "secret\nOTHER=value"})
    assert not env_file.exists()
