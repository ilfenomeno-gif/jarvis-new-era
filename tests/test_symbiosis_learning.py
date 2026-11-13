from core.bidirectional_learning import learn
from memory import memory_manager


def test_disable_battery_alert_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_manager, "USER_PROFILE_PATH", tmp_path / "profile.json")
    assert "disattivato" in learn("Jarvis, non avvisarmi della batteria")
    assert memory_manager.load_user_profile()["preferences"]["low_battery_alert"] == "disabled"
