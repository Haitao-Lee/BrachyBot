"""Multi-target parameter binding (audit defect F05).

A request to "set CTV and OAR to 30% and 70% opacity respectively" used to
produce `ctv,30` and `oar,30`: the first number in the sentence was broadcast
to every target. A "respectively" request aligns values with targets
positionally, and a length mismatch must be clarified rather than guessed at
high confidence.
"""

from __future__ import annotations

from agent_runtime.ui_operations import (
    aligned_group_values,
    resolve_ui_operation_request,
    values_from_text,
)


def _actions(message):
    contract = resolve_ui_operation_request(message, {"ui_operation_catalog": []})
    assert contract is not None, message
    return contract


def _pairs(message):
    contract = _actions(message)
    assert contract.get("ambiguous") is False, (message, contract)
    return [
        action["value"] for action in contract["actions"]
        if action.get("target") == "tree.group.opacity"
    ]


# ---------------------------------------------------------------------------
# "respectively" aligns values with targets positionally
# ---------------------------------------------------------------------------


def test_respectively_binds_each_value_to_its_own_target():
    assert _pairs("请把CTV和OAR分别设为30%和70%的透明度") == ["ctv,30", "oar,70"]


def test_english_respectively_binds_positionally():
    assert _pairs("set CTV and OAR to 30% and 70% opacity respectively") == [
        "ctv,30",
        "oar,70",
    ]


def test_in_order_binds_positionally():
    assert _pairs("请把CTV和OAR依次设为30%和70%的透明度") == ["ctv,30", "oar,70"]


def test_three_targets_bind_positionally():
    assert _pairs("请把CTV、OAR和粒子分别设为30%、70%和90%的透明度") == [
        "ctv,30",
        "oar,70",
        "planning_seeds,90",
    ]


def test_reverse_order_follows_the_word_order_not_the_alias_order():
    """"OAR and CTV respectively 30 and 70" means OAR=30, CTV=70."""
    assert _pairs("请把OAR和CTV分别设为30%和70%的透明度") == ["oar,30", "ctv,70"]


# ---------------------------------------------------------------------------
# A single shared value is legitimately broadcast
# ---------------------------------------------------------------------------


def test_one_value_over_several_targets_is_still_shared():
    assert _pairs("请把CTV和OAR设为30%的透明度") == ["ctv,30", "oar,30"]


def test_shared_word_value_still_broadcasts():
    assert _pairs("请把CTV和OAR都设为半透明") == ["ctv,50", "oar,50"]


# ---------------------------------------------------------------------------
# A length or meaning mismatch is clarified, never guessed
# ---------------------------------------------------------------------------


def test_respectively_with_too_few_values_is_ambiguous():
    contract = _actions("请把CTV和OAR分别设为30%的透明度")
    assert contract["ambiguous"] is True
    assert contract["actions"] == []
    assert contract["source"] == "typed_multi_group_ambiguous"


def test_respectively_with_too_many_values_is_ambiguous():
    contract = _actions("请把CTV和OAR分别设为30%、70%和90%的透明度")
    assert contract["ambiguous"] is True
    assert contract["actions"] == []


def test_several_values_without_a_binding_marker_is_ambiguous():
    """"CTV and OAR to 30% and 70%" does not say which is which."""
    contract = _actions("请把CTV和OAR设为30%和70%的透明度")
    assert contract["ambiguous"] is True
    assert contract["actions"] == []


def test_several_values_without_respectively_in_english_is_ambiguous():
    contract = _actions("set CTV and OAR to 30% and 70% opacity")
    assert contract["ambiguous"] is True


# ---------------------------------------------------------------------------
# The value list itself is extracted in source order
# ---------------------------------------------------------------------------


def test_values_from_text_keeps_source_order():
    assert values_from_text("请把CTV和OAR分别设为30%和70%的透明度", "opacity") == [30, 70]


def test_values_from_text_reads_a_single_percent():
    assert values_from_text("请把CTV和OAR设为30%的透明度", "opacity") == [30]


def test_values_from_text_maps_word_values():
    assert values_from_text("请把CTV和OAR都设为半透明", "opacity") == [50]
    assert values_from_text("完全透明", "opacity") == [0]
    assert values_from_text("不透明", "opacity") == [100]


def test_aligned_group_values_requires_equal_lengths():
    assert aligned_group_values(
        "请把CTV和OAR分别设为30%和70%的透明度", "opacity", ["ctv", "oar"],
    ) == {"ctv": 30, "oar": 70}
    assert aligned_group_values(
        "请把CTV和OAR分别设为30%的透明度", "opacity", ["ctv", "oar"],
    ) is None
