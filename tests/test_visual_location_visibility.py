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
        {"role": "user", "content": "[Tool result: 肿瘤在左侧]"},
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
            "target_ref": "surgical_guide:active",
            "label": "Puncture guide v2", "kind": "data-tree-row",
            "visible": True, "in_view": True, "annotatable": True,
            "scene_visible": False, "scene_visibility_known": True,
        }]},
    }]}, "zh")
    assert "截图已核验" in answer and "隐藏状态" in answer
    assert grounded_location_answer({"evidence": [{"visual_purpose": "explain"}]}, "zh") is None



def test_tree_only_evidence_retains_other_subanswers_without_claiming_viewer_location():
    answer = grounded_location_answer({
        "preliminary_response": (
            "Planning_2 is completed with 13 trajectories. "
            "Code help is available; no code was run."
        ),
        "evidence": [{
            "visual_purpose": "locate", "target": "data-tree",
            "grounding_manifest": {"targets": [{
                "target_ref": "surgical_guide:active",
                "label": "Puncture guide v2", "kind": "data-tree-row",
                "visible": True, "in_view": True, "annotatable": True,
                "scene_visible": False, "scene_visibility_known": True,
                "status": "ready",
            }]},
        }],
    }, "zh")
    assert "Planning_2" in answer and "Code help is available" in answer
    assert "Puncture guide v2" in answer
    assert "Viewer" in answer and "\u4e09\u7ef4\u622a\u56fe" in answer
    assert "\\n" not in answer
    assert "\u9888\u90e8" not in answer and "\u9752\u8272" not in answer


def test_spatial_preliminary_claims_are_not_reused_as_screenshot_evidence():
    answer = grounded_location_answer({
        "preliminary_response": (
            "\u5bfc\u677f\u4f4d\u4e8e\u60a3\u8005\u9888\u90e8\u5de6\u4fa7\u3002"
            "Planning_2 \u5df2\u5b8c\u6210 13 \u6761\u8f68\u8ff9\uff1b"
            "Code help is available."
        ),
        "evidence": [{
            "visual_purpose": "locate", "target": "data-tree",
            "grounding_manifest": {"targets": [{
                "target_ref": "surgical_guide:active",
                "label": "Puncture guide v2", "kind": "data-tree-row",
                "visible": True, "in_view": True, "annotatable": True,
                "scene_visible": False, "scene_visibility_known": True,
                "status": "ready",
            }]},
        }],
    }, "zh")
    assert "Planning_2" in answer and "Code help is available" in answer
    assert "\u9888\u90e8" not in answer and "\u5de6\u4fa7" not in answer
    assert "Puncture guide v2" in answer
    assert "截图已核验" in answer


def test_grounded_location_answer_does_not_repeat_stale_visual_placeholders():
    answer = grounded_location_answer({
        "preliminary_response": (
            "**对象截图/位置**\n"
            "没有建立与该目标对应的截图任务，因此不对位置作判断。\n"
            "**对象截图/位置**\n"
            "没有建立与该目标对应的截图任务，因此不对位置作判断。\n"
            "Planning_2 已完成。"
        ),
        "evidence": [{
            "attachment_id": "guide-viewer",
            "visual_purpose": "locate",
            "target": "viewer-3d",
            "annotation_target_refs": ["surgical_guide:active"],
            "appearance_preserved": True,
            "grounding_manifest": {"targets": [{
                "target_ref": "surgical_guide:active",
                "label": "Puncture guide v2",
                "kind": "scene-object",
                "visible": True,
                "scene_visible": True,
                "data_tree_visible": True,
                "in_view": True,
                "annotatable": True,
                "loaded": True,
                "status": "ready",
            }]},
        }],
    }, "zh")
    assert answer.count("### 对象截图/位置") == 1
    assert "没有建立与该目标对应的截图任务" not in answer
    assert "Planning_2 已完成" in answer
    assert "标出了“Puncture guide v2”的位置" in answer


def test_successful_capture_discards_earlier_image_unavailable_claim():
    answer = grounded_location_answer({
        "preliminary_response": (
            "我提交了截图计划，但浏览器端没有把图像回传给我。"
            "你可以重新截图。Planning_2 已完成。"
        ),
        "evidence": [{
            "visual_purpose": "locate", "target": "viewer-3d",
            "annotation_target_refs": ["surgical_guide:active"],
            "grounding_manifest": {"targets": [{
                "target_ref": "surgical_guide:active", "label": "Puncture guide v1",
                "kind": "scene-object", "visible": True, "scene_visible": True,
                "data_tree_visible": True, "in_view": True, "annotatable": True,
                "loaded": True,
            }]},
        }],
    }, "zh")
    assert "Planning_2 已完成" in answer
    assert "没有把图像回传" not in answer
    assert "重新截图" not in answer
    assert "标出了“Puncture guide v1”的位置" in answer


def test_tree_row_with_unknown_scene_visibility_is_not_called_hidden():
    answer = grounded_location_answer({"evidence": [{
        "visual_purpose": "locate", "target": "data-tree",
        "grounding_manifest": {"targets": [{
            "target_ref": "surgical_guide:active",
            "label": "Puncture guide v2", "kind": "data-tree-row",
            "visible": True, "in_view": True, "annotatable": True,
            "scene_visible": False, "scene_visibility_known": False,
        }]},
    }]}, "zh")
    assert "\u9690\u85cf\u72b6\u6001" not in answer
    assert "\u65e0\u6cd5\u6838\u9a8c" in answer


def test_ctv_capture_reports_temporary_guide_occlusion_change():
    answer = grounded_location_answer({"evidence": [{
        "visual_purpose": "locate", "target": "viewer-3d",
        "annotation_target_refs": ["structure:ctv:active"],
        "temporary_occluders": ["surgical_guide:active"],
        "grounding_manifest": {"targets": [{
            "target_ref": "structure:ctv:active", "label": "Label 2",
            "kind": "scene-object", "visible": True,
            "scene_visible": True, "data_tree_visible": True,
            "in_view": True, "annotatable": True, "loaded": True,
        }]},
    }]}, "zh")
    assert "**Label 2**" in answer
    assert "临时隐藏导板" in answer
    assert "已恢复" in answer
