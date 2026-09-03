from memory.language import detect


def test_language_detection_uses_latest_script_and_ui_fallback_for_ambiguous_turns():
    assert detect("请检查 RL 状态", fallback="en")["code"] == "zh"
    assert detect("check the RL status", fallback="zh")["code"] == "en"
    assert detect("1", fallback="zh")["code"] == "zh"
    assert detect("1", fallback="en")["code"] == "en"


def test_mixed_script_tie_has_stable_english_fallback():
    # Two Latin and two CJK letters: the result must not depend on the
    # insertion order of the language table.
    assert detect("ab中文", fallback="zh")["code"] == "en"
