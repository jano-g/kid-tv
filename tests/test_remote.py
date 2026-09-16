from kidtv.remote import KeyMapper, LongPressTracker, DEFAULT_MAP, ACTIONS
from kidtv.cec import _KEY_RE, CEC_KEY_ACTIONS


def test_default_map_only_uses_known_actions():
    assert set(DEFAULT_MAP.values()) <= set(ACTIONS)
    assert set(CEC_KEY_ACTIONS.values()) <= set(ACTIONS)


def test_mapper_learn_overrides_and_replaces():
    m = KeyMapper()
    assert m.action_for("KEY_VOLUMEUP") == "VOL_UP"
    assert m.action_for("BTN_LEFT") == "OK"  # air-mouse OK button
    m.learn("KEY_F5", "CH_UP")
    assert m.action_for("KEY_F5") == "CH_UP"
    m.learn("KEY_F5", "CH_DOWN")
    assert m.action_for("KEY_F5") == "CH_DOWN"
    assert "KEY_F5" in m.mapping_for_action("CH_DOWN")
    assert "KEY_F5" not in m.mapping_for_action("CH_UP")
    m.learn("KEY_VOLUMEUP", "MUTE")
    assert m.action_for("KEY_VOLUMEUP") == "MUTE"
    assert m.action_for("KEY_UNKNOWN_XYZ") is None


def test_long_press_tracker():
    t = LongPressTracker(hold_ms=1000)
    t.down("KEY_MENU", now=100.0)
    assert t.check_long(now=100.5) == []
    assert t.check_long(now=101.1) == ["KEY_MENU"]
    assert t.check_long(now=102.0) == []  # fires once
    assert t.up("KEY_MENU") is False  # release after long press is not a short press
    t.down("KEY_OK", now=200.0)
    assert t.up("KEY_OK") is True


def test_cec_regex():
    m = _KEY_RE.search("DEBUG:   [  1234]\tkey pressed: volume up (41) current(ff) duration(0)")
    assert m and m.group(1) == "pressed" and m.group(2) == "volume up"
    assert CEC_KEY_ACTIONS[m.group(2)] == "VOL_UP"
