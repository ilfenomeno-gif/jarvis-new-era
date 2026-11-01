from types import SimpleNamespace

from actions import ui_layout


class _Ui:
    def __init__(self):
        self.focus_mode = False
        self.calls = []

    def set_focus_mode(self, active):
        self.calls.append(active)
        self.focus_mode = active


def test_ui_layout_modes_drive_focus_mode():
    ui = _Ui()
    assert "on" in ui_layout.ui_layout({"mode": "focus_on"}, player=ui)
    assert ui.calls == [True]
    ui_layout.ui_layout({"mode": "focus_toggle"}, player=ui)
    assert ui.calls == [True, False]
    ui_layout.ui_layout({"mode": "focus_off"}, player=ui)
    assert ui.calls == [True, False, False]


def test_ui_layout_rejects_unknown_mode_and_missing_ui():
    ui = _Ui()
    assert "Unknown mode" in ui_layout.ui_layout({"mode": "dock"}, player=ui)
    assert not ui.calls
    assert "not available" in ui_layout.ui_layout({"mode": "focus_on"}, player=None)


def test_ui_layout_is_a_valid_read_tool():
    assert ui_layout.TOOL["risk_class"] == "read"
    assert ui_layout.TOOL["parameters"]["type"] == "OBJECT"
