"""Cross-topic routing contracts for the one-call semantic decision path.

The lexical candidate may help select an inexpensive tool palette, but it
cannot choose the answer or grant a clinical mutation.
"""

from agent_runtime.llm_runtime import (
    _model_round_budget,
    _planning_followup_instruction,
    _planning_workflow_hint_allowed,
)
from agent_runtime.turn_policy import classify_local_turn


def test_unfamiliar_question_uses_semantics_with_read_evidence_tools():
    policy = classify_local_turn("为什么 BrachyBot 会这样回答？")
    assert policy.intent == "semantic_action"
    assert policy.routing_source == "primary_semantic"
    assert {"case_memory", "ui_inspector", "clinical_kb", "web_search"} <= policy.allow_tools
    assert "planning_pipeline" not in policy.allow_tools
    assert not policy.execution_grants
    assert not policy.use_router
    assert _model_round_budget(policy) == 3


def test_topic_words_do_not_force_a_single_source_or_execution():
    policy = classify_local_turn("剂量和临床指南之间有什么区别？")
    assert policy.intent == "semantic_action"
    assert {"query_metrics", "clinical_kb"} <= policy.allow_tools
    assert "dose_recompute" not in policy.allow_tools


def test_unknown_positive_request_retains_semantic_capabilities_without_grants():
    policy = classify_local_turn("请整理当前状态，然后指出还缺少哪些证据")
    assert policy.intent == "semantic_action"
    assert "query_metrics" in policy.allow_tools
    assert not policy.execution_grants
    assert _model_round_budget(policy) == 5


def test_external_project_does_not_inherit_patient_tools():
    policy = classify_local_turn("请查询 DeepRare 的开源代码")
    assert policy.intent == "external_project_query"
    assert "web_search" in policy.allow_tools
    assert "case_memory" not in policy.allow_tools


def test_historical_skill_cannot_turn_discussion_into_planning():
    question = classify_local_turn("为什么上次规划没有成功？")
    assert not _planning_workflow_hint_allowed(question)
    explicit = classify_local_turn("请执行放射性粒子植入规划")
    assert _planning_workflow_hint_allowed(explicit)


def test_trivial_turn_keeps_the_low_latency_path():
    greeting = classify_local_turn("你好")
    assert greeting.intent == "small_talk"
    assert greeting.allow_tools == frozenset()


def test_planning_followup_does_not_claim_unverified_downstream_work():
    pending = _planning_followup_instruction(False)
    completed = _planning_followup_instruction(True)
    assert "never invent a CT path" in pending
    assert "All workflow tools completed" not in pending
    assert "guide, report, UI refresh" in completed
    assert "unless its own" in completed
    assert "exact format" not in completed
