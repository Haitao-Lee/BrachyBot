"""Routing contracts for artifact-analysis requests ("分析导板特点").

An analysis request is a read-only discourse act over an already-produced
artifact. It must never restart a workflow, never ask the user to "confirm"
a regeneration, and it must reach a grounded characteristics answer instead
of a presentation-only tool call.
"""
import pytest

from agent_runtime.turn_policy import (
    ANALYSIS_READ_TOOLS,
    classify_local_turn,
    is_artifact_analysis_request,
    resolve_artifact_analysis_target,
)
from agent_runtime.response_tools import ResponseToolMixin


GUIDE_TURN = [
    {"role": "user", "content": "请你将该患者的导板特点分析一遍"},
    {"role": "assistant", "content": "手术导板 v1已生成，包含 24 条计划针道。"},
]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('message, expected', [
    ("请你将该患者的导板特点分析一遍", "surgical_guide"),
    ("分析一下导板的特点和质量", "surgical_guide"),
    ("analyze the surgical guide characteristics", "surgical_guide"),
    ("分析一下该患者的肿瘤情况", "tumor"),
    ("评估一下当前规划", "planning"),
    ("解读一下剂量分布的特点", "dose"),
    ("分析分割结果", "segmentation"),
    ("分析粒子分布特点", "seeds_needles"),
])
def test_analysis_requests_resolve_their_artifact(message, expected):
    resolved = is_artifact_analysis_request(message)
    assert resolved is not None, message
    assert resolved["artifact"] == expected, message


@pytest.mark.parametrize('message', [
    "重新生成导板",
    "请重新生成手术导板",
    "生成分析报告",
    "分析一下导板然后重新生成",
    "请解释如何生成手术导板",
    "请把OAR设为半透明这个功能解释一下",
    "explain how to generate the surgical guide",
    "他让我重新生成报告，这是什么意思",
])
def test_commands_and_howto_questions_are_not_analysis_requests(message):
    assert is_artifact_analysis_request(message) is None, message


def test_bare_analysis_followup_inherits_the_conversation_target():
    assert is_artifact_analysis_request("分析啊") is None
    resolved = is_artifact_analysis_request("分析啊", conversation=GUIDE_TURN)
    assert resolved is not None
    assert resolved["artifact"] == "surgical_guide"


def test_multi_artifact_or_matching_analysis_is_delegated_to_the_llm():
    resolved = is_artifact_analysis_request("分析导板和肿瘤的匹配情况")
    assert resolved is not None
    assert resolved["complex"] is True


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_guide_characteristics_analysis_is_a_read_only_grounded_turn():
    policy = classify_local_turn("请你将该患者的导板特点分析一遍")
    assert policy.intent == "artifact_analysis_query"
    assert policy.analysis_target == "surgical_guide"
    assert not policy.direct_execution
    assert not policy.execution_grants
    assert not policy.workflow_grants
    assert policy.action_plan is None
    assert not (policy.allow_tools & {
        "surgical_guide", "planning_pipeline", "ctv_segmentation",
        "oar_segmentation", "ui_controller",
    })


def test_tumor_analysis_routes_to_the_same_grounded_family():
    policy = classify_local_turn("分析一下该患者的肿瘤情况")
    assert policy.intent == "artifact_analysis_query"
    assert policy.analysis_target == "tumor"


def test_followup_analysis_uses_the_inherited_target():
    policy = classify_local_turn("分析啊", conversation=GUIDE_TURN)
    assert policy.intent == "artifact_analysis_query"
    assert policy.analysis_target == "surgical_guide"


def test_generation_commands_keep_their_mutation_routes():
    guide = classify_local_turn("重新生成导板")
    assert guide.intent == "surgical_guide_generation"
    assert guide.execution_grants == {"surgical_guide"}

    report = classify_local_turn("生成分析报告")
    assert report.intent == "report_generation"
    assert report.execution_grants == {"ui_controller"}


def test_analysis_plus_regeneration_stays_semantic_and_grants_nothing():
    policy = classify_local_turn("分析一下导板然后重新生成")
    assert policy.intent != "artifact_analysis_query"
    assert not policy.direct_execution
    assert not policy.execution_grants


def test_complex_analysis_delegates_to_the_llm_with_read_only_tools():
    policy = classify_local_turn("分析导板和肿瘤的匹配情况")
    assert policy.allow_tools <= ANALYSIS_READ_TOOLS
    assert "surgical_guide" in policy.allow_tools
    assert "planning_pipeline" not in policy.allow_tools
    assert not policy.direct_execution


# ---------------------------------------------------------------------------
# Tool-call coercion (second-line boundary for the semantic path)
# ---------------------------------------------------------------------------

class _Memory:
    def __init__(self, content):
        self.conversation = [{"role": "user", "content": content}]

    @staticmethod
    def retrieve(_key, default=None):
        return default


def _normalizer(content):
    normalizer = ResponseToolMixin()
    normalizer.memory = _Memory(content)
    return normalizer


def test_analysis_turn_coerces_bare_surgical_guide_to_analyze():
    calls = _normalizer("请你将该患者的导板特点分析一遍")._normalize_tool_params([
        {"id": "g", "tool": "surgical_guide", "params": {}},
    ])
    assert calls == [{"id": "g", "tool": "surgical_guide", "params": {"action": "analyze"}}]


def test_analysis_turn_coerces_explicit_generate_back_to_analyze():
    calls = _normalizer("分析啊")._normalize_tool_params([
        {"id": "g", "tool": "surgical_guide", "params": {"action": "generate"}},
    ])
    assert calls[0]["params"]["action"] == "analyze"


def test_analysis_turn_drops_unrelated_mutations_without_confirmation_text():
    normalizer = _normalizer("分析一下该患者的肿瘤情况")
    calls = normalizer._normalize_tool_params([
        {"id": "p", "tool": "planning_pipeline", "params": {"step": "full"}},
        {"id": "m", "tool": "query_metrics", "params": {"metric_type": "all_metrics"}},
    ])
    assert [call["tool"] for call in calls] == ["query_metrics"]
    assert normalizer._blocked_mutating_tool_names == []


def test_analysis_turn_injects_the_question_into_ui_content():
    calls = _normalizer("分析导板特点")._normalize_tool_params([
        {"id": "u", "tool": "ui_content",
         "params": {"target": "surgical_guide", "presentation": "summary"}},
    ])
    assert calls[0]["params"]["question"]
    assert "分析" in calls[0]["params"]["question"]


def test_generation_command_still_coerces_to_generate():
    calls = _normalizer("重新生成导板")._normalize_tool_params([
        {"id": "g", "tool": "surgical_guide", "params": {}},
    ])
    assert calls[0]["params"]["action"] == "generate"


# ---------------------------------------------------------------------------
# Guide characteristics facts
# ---------------------------------------------------------------------------

def test_guide_characteristics_packet_exposes_design_and_validation_facts():
    from agent_runtime.artifact_analysis import build_guide_characteristics_facts

    guide_state = {
        "version": 3,
        "status": "ready",
        "planning_id": "planning-abc",
        "parameters": {
            "channel_radius_mm": 0.9,
            "plate_thickness_mm": 2.5,
            "skin_clearance_mm": 1.0,
            "sleeve_outer_radius_mm": 1.8,
            "auxiliary_holes_enabled": True,
            "auxiliary_hole_ring_count": 2,
            "auxiliary_holes_per_ring": 12,
        },
        "selected_needle_ids": ["n1", "n2", "n3"],
        "needle_paths": [{"needle_id": "n1"}, {"needle_id": "n2"}],
        "auxiliary_holes": {"holes": list(range(50)), "ring_count": 2},
        "validation": {
            "source_needle_count": 3,
            "max_centerline_deviation_mm": 0.0,
            "skin_fit": "physical",
            "bore_quality": {"ok": True},
            "needle_spacing": {"bore_conflicts": [], "sleeve_overlaps": 1},
            "plate_connectivity": {"single_piece": True},
            "finite_fov": {"truncated_superior": False},
        },
    }
    facts = build_guide_characteristics_facts(guide_state)
    assert facts["version"] == 3
    assert facts["needle_count"] == 3
    assert facts["parameters"]["channel_radius_mm"] == 0.9
    assert facts["parameters"]["auxiliary_holes_enabled"] is True
    assert facts["validation"]["max_centerline_deviation_mm"] == 0.0
    assert facts["validation"]["plate_connectivity_single_piece"] is True
    assert "holes" not in facts.get("auxiliary_holes", {})
