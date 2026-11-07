import json

from memory import config_manager


def test_default_voice_is_jarvis_voice_and_iris_uses_female_voice(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_file = config_dir / "api_keys.json"
    config_dir.mkdir()
    config_file.write_text(
        json.dumps({"gemini_api_key": "test-key", "voice_name": "Charon"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_manager, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_manager, "CONFIG_FILE", config_file)

    assert config_manager.get_voice() == "Charon"
    assert config_manager.get_jarvis_voice() == "Charon"
    assert config_manager.get_iris_voice() == "Kore"

    config_manager.save_voice("Puck")
    assert config_manager.get_voice() == "Puck"
    assert config_manager.get_jarvis_voice() == "Puck"
    assert config_manager.get_iris_voice() == "Kore"
    assert json.loads(config_file.read_text(encoding="utf-8")) == {
        "gemini_api_key": "test-key",
        "voice_name": "Puck",
    }

    config_file.write_text(
        json.dumps({"gemini_api_key": "test-key"}), encoding="utf-8"
    )
    assert config_manager.get_voice() == "Charon"


def test_jarvis_uses_a_masculine_voice_if_saved_voice_is_feminine(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_file = config_dir / "api_keys.json"
    config_dir.mkdir()
    config_file.write_text(
        json.dumps({"voice_name": "Aoede"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_manager, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_manager, "CONFIG_FILE", config_file)

    assert config_manager.get_voice() == "Aoede"
    assert config_manager.get_jarvis_voice() == "Charon"
    assert config_manager.get_iris_voice() == "Kore"
    assert json.loads(config_file.read_text(encoding="utf-8")) == {
        "voice_name": "Aoede",
    }
