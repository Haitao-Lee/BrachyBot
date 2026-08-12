"""Regression contracts for semantic routing and per-turn execution grants."""

from agent_runtime.execution_authorization import (
    PLANNING_WORKFLOW,
    TurnExecutionAuthorization,
)
from agent_runtime.turn_policy import classify_local_turn
from agent_runtime.chat_workflows import ChatWorkflowMixin


def test_negated_planning_never_receives_a_local_execution_grant():
    policy = classify_local_turn(
        "我上传了一名肝脏肿瘤患者CT，请不要执行规划"
    )

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False
    assert not policy.execution_grants
    assert not policy.workflow_grants


def test_mixed_scope_request_is_decided_by_the_llm_not_the_fast_path():
    policy = classify_local_turn("只分割CTV，不要进行规划，也不要生成导板")

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False
    assert "ctv_segmentation" in policy.allow_tools
    assert "planning_pipeline" in policy.allow_tools
    assert "surgical_guide" in policy.allow_tools


def test_unambiguous_full_plan_keeps_the_low_latency_legacy_route():
    policy = classify_local_turn("请执行放射性粒子植入规划")

    assert policy.intent == "clinical_planning"
    assert policy.direct_execution is True
    assert PLANNING_WORKFLOW in policy.workflow_grants
    assert {
        "ctv_segmentation",
        "oar_segmentation",
        "planning_pipeline",
        "surgical_guide",
    }.issubset(policy.execution_grants)


def test_compound_replan_and_guide_request_preserves_an_ordered_action_plan():
    message = (
        "\u6211\u6539\u4e86\u7c92\u5b50\u690d\u5165\u53c2\u6570\uff0c"
        "\u8bf7\u91cd\u65b0\u6267\u884c\u89c4\u5212\uff0c\u5e76\u751f\u6210\u65b0\u7684\u5bfc\u677f"
    )
    policy = classify_local_turn(message)

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False
    assert policy.action_plan is not None
    assert policy.action_plan.tool_names == (
        "ctv_segmentation",
        "oar_segmentation",
        "planning_pipeline",
        "surgical_guide",
    )
    assert [step.tool for step in policy.action_plan.ordered_steps()] == [
        "ctv_segmentation",
        "oar_segmentation",
        "planning_pipeline",
        "surgical_guide",
    ]
    assert policy.action_plan.ordered_steps()[2].depends_on == (
        "ctv_segmentation",
        "oar_segmentation",
    )
    assert policy.action_plan.ordered_steps()[3].depends_on == ("planning_pipeline",)
    assert "planning_pipeline" in policy.execution_grants
    assert "surgical_guide" in policy.execution_grants


def test_action_plan_preserves_repeated_provider_steps_and_order_after_merge():
    from agent_runtime.action_plan import ActionPlan

    provider_plan = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 1}},
        {"tool": "report_generator", "params": {"version": 2}},
        {"tool": "ui_content", "params": {"target": "report"}},
    ])
    merged = ActionPlan.from_tools(
        ("planning_pipeline", "surgical_guide"),
        dependencies={"surgical_guide": ("planning_pipeline",)},
    ).merge(provider_plan)

    assert [step.key for step in provider_plan.steps] == [
        "report_generator",
        "report_generator#2",
        "ui_content",
    ]
    ordered = merged.order_tool_calls([
        {"tool": "ui_content"},
        {"tool": "surgical_guide"},
        {"tool": "planning_pipeline"},
    ])
    assert [call["tool"] for call in ordered] == [
        "planning_pipeline",
        "surgical_guide",
        "ui_content",
    ]


def test_compound_report_and_attachment_request_cannot_use_report_fast_path():
    policy = classify_local_turn(
        "\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a\u5e76\u628a\u62a5\u544a\u56fe\u7247\u663e\u793a\u5728\u5bf9\u8bdd\u4e2d"
    )

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False
    assert policy.action_plan is None


def test_compound_guide_request_keeps_the_planning_dependency_plan():
    policy = classify_local_turn(
        "\u8bf7\u91cd\u65b0\u6267\u884c\u89c4\u5212\u540e\u518d\u751f\u6210\u5bfc\u677f"
    )

    assert policy.intent == "semantic_action"
    assert policy.action_plan is not None
    assert policy.action_plan.tool_names[-2:] == (
        "planning_pipeline",
        "surgical_guide",
    )


def test_punctuation_separated_actions_also_use_the_primary_planner():
    policy = classify_local_turn(
        "\u8bf7\u91cd\u65b0\u89c4\u5212, \u751f\u6210\u65b0\u7684\u5bfc\u677f"
    )

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False


def test_action_plan_merge_keeps_repeated_actions_from_later_model_rounds():
    from agent_runtime.action_plan import ActionPlan

    first = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 1}},
    ])
    second = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 2}},
        {"tool": "ui_content", "params": {"target": "report"}},
    ])
    merged = first.merge(second)

    assert [step.key for step in merged.steps] == [
        "report_generator",
        "report_generator#2",
        "ui_content",
    ]
    assert [step.params.get("version") for step in merged.steps[:2]] == [1, 2]


def test_action_plan_merges_provider_call_into_dependency_placeholder():
    from agent_runtime.action_plan import ActionPlan

    guarded = ActionPlan.from_tools(
        ("planning_pipeline", "surgical_guide"),
        source="semantic_dependency_guard",
        dependencies={"surgical_guide": ("planning_pipeline",)},
    )
    concrete = ActionPlan.from_tool_calls([
        {"tool": "planning_pipeline", "params": {"step": "full"}},
        {"tool": "surgical_guide", "params": {"action": "generate"}},
    ])
    merged = guarded.merge(concrete)

    assert [step.key for step in merged.steps] == [
        "planning_pipeline",
        "surgical_guide",
    ]
    assert merged.steps[0].params["step"] == "full"
    assert merged.steps[1].params["action"] == "generate"


def test_compound_nonclinical_request_uses_primary_semantic_path():
    policy = classify_local_turn("请先查看当前报告，然后把截图显示在对话中")

    assert policy.intent == "semantic_action"
    assert policy.direct_execution is False


def test_planning_and_segmentation_mentions_are_not_execution_permission():
    planning = classify_local_turn("请介绍放射性粒子植入规划的原理")
    segmentation = classify_local_turn("CTV分割方法有哪些")

    assert planning.intent == "semantic_action"
    assert planning.direct_execution is False
    assert segmentation.intent == "semantic_action"
    assert segmentation.direct_execution is False


def test_report_correction_uses_semantic_selection_but_exact_command_stays_fast():
    correction = classify_local_turn(
        "我是要你重新生成报告，不是给我截图，报告正文还没填充"
    )
    exact = classify_local_turn("请重新生成报告")

    assert correction.intent == "semantic_action"
    assert correction.direct_execution is False
    assert exact.intent == "report_generation"
    assert exact.direct_execution is True
    assert "ui_controller" in exact.execution_grants


def test_unknown_action_wording_keeps_the_registered_capability_set_available():
    policy = classify_local_turn("把这个病例当前能呈现的结果整理给我")

    assert policy.intent == "semantic_action"
    assert "ui_content" in policy.allow_tools
    assert "query_metrics" in policy.allow_tools
    assert "case_memory" in policy.allow_tools


def test_planning_grant_supplies_only_required_prerequisites():
    authorization = TurnExecutionAuthorization(token=7)
    authorization.grant_tool_calls(
        [{"tool": "planning_pipeline"}],
        source="test_llm",
    )

    assert authorization.workflow_allowed(PLANNING_WORKFLOW)
    assert authorization.tool_allowed("ctv_segmentation")
    assert authorization.tool_allowed("oar_segmentation")
    assert authorization.tool_allowed("planning_pipeline")
    assert not authorization.tool_allowed("surgical_guide")
    assert authorization.tool_allowed("ui_content")


def test_guide_requires_an_explicit_grant_even_after_planning():
    authorization = TurnExecutionAuthorization(token=8)
    authorization.grant_tool_calls(
        [{"tool": "planning_pipeline"}],
        source="test_llm",
    )
    assert not authorization.tool_allowed("surgical_guide")

    authorization.grant_tool_calls(
        [{"tool": "surgical_guide"}],
        source="test_llm",
    )
    assert authorization.tool_allowed("surgical_guide")


def test_planning_enforcer_ignores_raw_keywords_without_a_grant():
    from AgenticSys import BrachyAgent

    agent = object.__new__(BrachyAgent)
    agent._active_turn_token = 1
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)

    assert agent._planning_requested("请执行规划") is False
    assert agent._planning_requested("请不要执行规划") is False
    assert agent._planning_requested(
        "status only",
        [{"tool": "planning_pipeline", "params": {"step": "full"}}],
    ) is True


def test_provider_failures_are_localized_and_do_not_expose_raw_diagnostics():
    assert ChatWorkflowMixin._is_llm_provider_error(
        "Error: Error code: 401 - Invalid API Key"
    )
    assert ChatWorkflowMixin._is_llm_provider_error(
        "LLM error: All providers failed"
    )

    zh = ChatWorkflowMixin._llm_unavailable_message("zh")
    en = ChatWorkflowMixin._llm_unavailable_message("en")

    assert "暂时不可用" in zh
    assert "没有启动任何临床操作" in zh
    assert "temporarily unavailable" in en
    assert "no clinical action was started" in en.lower()
    assert "API_KEY" not in zh
    assert "401" not in zh
