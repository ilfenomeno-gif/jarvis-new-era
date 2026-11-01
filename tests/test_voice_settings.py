import json

import pytest

import memory.config_manager as config_manager


def _use_temp_voice_settings(monkeypatch, tmp_path):
    settings_file = tmp_path / "voice_settings.json"
    monkeypatch.setattr(config_manager, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_manager, "VOICE_SETTINGS_FILE", settings_file)
    return settings_file


def test_page_reader_engine_defaults_to_system(monkeypatch, tmp_path):
    _use_temp_voice_settings(monkeypatch, tmp_path)

    assert config_manager.get_page_reader_engine() == "system"


@pytest.mark.parametrize("engine", ["system", "kokoro"])
def test_page_reader_engine_round_trips_without_api_key_file(
    monkeypatch,
    tmp_path,
    engine,
):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    config_manager.save_page_reader_engine(engine)

    assert config_manager.get_page_reader_engine() == engine
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "page_reader_engine": engine
    }
    assert not (tmp_path / "api_keys.json").exists()


def test_page_reader_engine_refuses_unknown_values(monkeypatch, tmp_path):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="Unsupported"):
        config_manager.save_page_reader_engine("cloud")

    assert not settings_file.exists()


def test_page_reader_engine_does_not_overwrite_corrupt_settings(
    monkeypatch,
    tmp_path,
):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)
    settings_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot update voice settings"):
        config_manager.save_page_reader_engine("kokoro")

    assert settings_file.read_text(encoding="utf-8") == "{broken"


def test_wake_word_is_opt_in_and_persisted_separately(monkeypatch, tmp_path):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    assert config_manager.get_wake_word_enabled() is False
    config_manager.save_page_reader_engine("kokoro")
    config_manager.save_wake_word_enabled(True)

    assert config_manager.get_wake_word_enabled() is True
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "page_reader_engine": "kokoro",
        "wake_word_enabled": True,
    }


def test_wake_word_setting_requires_a_boolean(monkeypatch, tmp_path):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="boolean"):
        config_manager.save_wake_word_enabled("true")

    assert not settings_file.exists()


def test_full_duplex_is_opt_in_and_persisted_separately(monkeypatch, tmp_path):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    assert config_manager.get_full_duplex_enabled() is False
    config_manager.save_full_duplex_enabled(True)

    assert config_manager.get_full_duplex_enabled() is True
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "full_duplex_enabled": True
    }
    assert not (tmp_path / "api_keys.json").exists()


def test_full_duplex_setting_requires_a_boolean(monkeypatch, tmp_path):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="boolean"):
        config_manager.save_full_duplex_enabled("true")

    assert not settings_file.exists()


def test_page_reader_speed_defaults_and_round_trips(monkeypatch, tmp_path):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    assert config_manager.get_page_reader_speed() == 1.0
    config_manager.save_page_reader_speed(1.25)

    assert config_manager.get_page_reader_speed() == 1.25
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "page_reader_speed": 1.25
    }


@pytest.mark.parametrize("speed", [0, 3, "fast", float("nan"), True])
def test_page_reader_speed_rejects_unsupported_values(
    monkeypatch,
    tmp_path,
    speed,
):
    settings_file = _use_temp_voice_settings(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        config_manager.save_page_reader_speed(speed)

    assert not settings_file.exists()
