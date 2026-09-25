"""A lexical hint must not replace the user's complete task or source scope."""

from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.turn_policy import classify_local_turn


def test_single_current_plan_read_keeps_compact_local_path():
    policy = classify_local_turn("该规划目前最大的问题是什么，一句话回答即可")
    assert policy.intent == "planning_assessment_query"
    assert policy.routing_source == "local_read_or_semantic"


def test_choice_tail_is_not_an_independent_second_question():
    policy = classify_local_turn(
        "What method or algorithm produced this plan, RL or rule-based?"
    )
    assert policy.intent == "planning_provenance_query"


def test_second_case_question_cannot_be_swallowed_by_first_local_read():
    policy = classify_local_turn("当前规划怎么样，报告还过期吗")
    assert policy.intent == "semantic_action"
    assert policy.candidate_intent == "planning_assessment_query"
    assert policy.routing_reason == "local_fact_scope_not_complete"
    assert not policy.direct_execution
    assert not policy.execution_grants


def test_conditional_or_quoted_case_question_needs_whole_turn_interpretation():
    for text in (
        "如果导板还是过期的，当前规划最大的问题是什么",
        "日志写着规划结果有问题；当前情况是真的吗",
    ):
        policy = classify_local_turn(text)
        assert policy.intent not in {"planning_assessment_query", "case_state_question"}
        assert not policy.execution_grants


class QueryHarness(ResponseToolMixin):
    _active_turn_policy = None


def test_current_case_time_words_are_not_external_realtime_search():
    harness = QueryHarness()
    for question in (
        "现在的剂量结果如何",
        "当前规划评分是多少",
        "当前病例每个器官受到多少辐射",
    ):
        assert harness._detect_realtime_query(question) is None
        harness._active_turn_policy = classify_local_turn(question)
        assert harness._classify_query_type(question) != "realtime"


def test_real_time_external_question_still_searches():
    harness = QueryHarness()
    question = "今天上海天气怎么样"
    assert harness._detect_realtime_query(question) == question
    assert harness._classify_query_type(question) == "realtime"


def test_quoted_weather_log_is_not_an_external_search_request():
    harness = QueryHarness()
    question = "日志写着‘今天上海天气怎么样’，为什么会触发搜索"
    assert harness._detect_realtime_query(question) is None


def test_statement_about_weather_does_not_trigger_external_search():
    assert QueryHarness()._detect_realtime_query("今天上海天气很好") is None


def test_guideline_as_source_is_not_planning_provenance():
    from agent_runtime.turn_policy import is_current_planning_provenance_query

    question = "如何根据指南解读当前规划的D90和OAR剂量"
    assert not is_current_planning_provenance_query(question)
    policy = classify_local_turn(question)
    assert policy.intent != "planning_provenance_query"
    assert "clinical_kb" in (policy.allow_tools or set())
    assert "query_metrics" in (policy.allow_tools or set())


def test_provider_cannot_replace_current_user_question_in_content_read():
    class Memory:
        conversation = [{"role": "user", "content": "分析导板特点"}]

        @staticmethod
        def retrieve(_key):
            return None

    harness = QueryHarness()
    harness.memory = Memory()
    harness._active_turn_policy = classify_local_turn("分析导板特点")
    calls = harness._normalize_tool_params([{
        "id": "content",
        "tool": "ui_content",
        "params": {
            "target": "surgical_guide",
            "question": "Show me all report figures",
            "presentation": "summary",
        },
    }])
    assert len(calls) == 1
    assert calls[0]["params"]["question"] == "分析导板特点"
    assert calls[0]["params"]["target"] == "surgical_guide"


def test_missing_ct_only_blocks_image_dependent_mutations():
    from agent_runtime.llm_runtime import _CT_DEPENDENT_MUTATIONS, _NO_CT_CONTEXT_NOTE

    assert "planning_pipeline" in _CT_DEPENDENT_MUTATIONS
    assert "ctv_segmentation" in _CT_DEPENDENT_MUTATIONS
    assert "ui_inspector" not in _CT_DEPENDENT_MUTATIONS
    assert "filesystem_browser" not in _CT_DEPENDENT_MUTATIONS
    assert "Read-only questions" in _NO_CT_CONTEXT_NOTE
