"""Regressions for hidden-object evidence and mixed-language follow-ups."""
from types import SimpleNamespace

import pytest

from memory.language import detect
from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.turn_policy import resolve_session_visual_location_request
from agent_runtime.visual_evidence import grounded_location_answer


@pytest.mark.parametrize("text", [
    "在data tree的哪里呢", "在 data tree 的哪里呢",
    "截图给我看看当前导板在哪里", "请显示 Puncture guide v2",
    "请看看 surgical guide 的状态", "3D viewer里能看见吗",
])
def test_chinese_sentence_with_english_ui_labels(text):
    assert detect(text, fallback="en")["code"] == "zh"


@pytest.mark.parametrize("text", [
    "Where is the surgical guide?", "Please show the data tree",
    "Where can I find the object labelled 导板?",
])
def test_english_sentence_does_not_inherit_chinese(text):
    assert detect(text, fallback="zh")["code"] == "en"


class Agent(ResponseToolMixin):
    @staticmethod
    def _message_text(value):
        return str(value)


def test_provider_screenshot_inherits_actual_followup_subject_and_question():
    agent = Agent()
    agent.memory = SimpleNamespace(conversation=[
        {"role": "user", "content": "截图给我看看当前导板在哪里"},
        {"role": "assistant", "content": "导板已生成。Trajectories (22), Needles (22)"},
        {"role": "user", "content": "在data tree的哪里呢"},
    ], get_ui_state=lambda: {})
    result = agent._normalize_tool_params([{
        "tool": "ui_screenshot",
        "params": {"mode": "chat", "views": ["data-tree"], "question": "Where is it?"},
    }])
    plan = result[0]["params"]
    assert plan["question"] == "在data tree的哪里呢"
    assert plan["semantic_target"] == "surgical_guide"
    assert plan["views"] == ["data-tree"]
    assert plan["visual_purpose"] == "locate"
    assert plan["annotation_policy"] == "required"
    assert "surgical_guide:active" in plan["target_refs"]


def test_plain_provider_capture_is_enriched_without_clinical_actions():
    agent = Agent()
    result = agent._normalize_tool_params([{
        "tool": "ui_screenshot",
        "params": {"views": ["viewer-3d"], "question": "截图给我看看当前导板在哪里"},
    }])
    assert [call["tool"] for call in result] == ["ui_screenshot"]
    assert result[0]["params"]["semantic_target"] == "surgical_guide"
    assert "data-tree" in result[0]["params"]["views"]


def test_new_target_supersedes_old_guide_reference():
    request = resolve_session_visual_location_request("请标注CTV在哪里", conversation=[
        {"role": "user", "content": "导板在哪里"},
    ])
    assert request["semantic_targets"] == ["ctv"]


def test_hidden_scene_cannot_be_described_as_a_visible_mesh_in_durable_reply():
    answer = grounded_location_answer({"evidence": [{
        "visual_purpose": "locate", "target": "viewer-3d",
        "grounding_manifest": {"targets": [{
            "target_ref": "surgical_guide:active", "label": "Puncture guide v2",
            "kind": "scene-object", "visible": False, "annotatable": False,
            "status": "stale",
        }]},
    }]}, "zh")
    assert "未能在截图中核验" in answer
    assert "过期" in answer
    assert "青色" not in answer and "颈部" not in answer


def test_tree_row_visibility_is_distinct_from_mesh_visibility():
    answer = grounded_location_answer({"evidence": [{
        "visual_purpose": "locate", "target": "data-tree",
        "grounding_manifest": {"targets": [{
            "label": "Puncture guide v2", "kind": "data-tree-row",
            "visible": True, "in_view": True, "annotatable": True,
            "scene_visible": False,
        }]},
    }]}, "zh")
    assert "截图已核验" in answer and "隐藏状态" in answer
    assert grounded_location_answer({"evidence": [{"visual_purpose": "explain"}]}, "zh") is None
