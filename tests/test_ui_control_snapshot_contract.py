from AgenticSys import _normalize_ui_controls


def test_normalize_durable_control_mapping():
    controls = _normalize_ui_controls({"ctvImageModality": {"value": "CT"}})
    assert controls["ctvImageModality"]["value"] == "CT"


def test_normalize_dom_control_list():
    controls = _normalize_ui_controls([
        {"id": None, "value": "ignored"},
        {"id": "ctvImageModality", "value": "CT"},
        {"id": "ctvVolumeIndex", "value": "0"},
    ])
    assert controls == {
        "ctvImageModality": {"id": "ctvImageModality", "value": "CT"},
        "ctvVolumeIndex": {"id": "ctvVolumeIndex", "value": "0"},
    }


def test_normalize_ignores_malformed_controls():
    assert _normalize_ui_controls([None, "bad", {"text": "anonymous"}]) == {}
