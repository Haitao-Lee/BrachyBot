"""Adversarial discourse and actual execution-receipt regression matrix."""
import pytest

from agent_runtime.request_parse import (
    parse_request, mutating_execution_authorized, _quoted_spans, is_conditional,
)
from agent_runtime.action_plan import ActionPlan
from agent_runtime.step_execution import StepExecutionState, append_tool_receipt, decode_provider_call
from agent_runtime.turn_policy import classify_local_turn


@pytest.mark.parametrize("message", [
    '日志写着“查看导板，生成报告”，请解释原因',
    '他说："show guide, generate report"，不要执行',
    'Please explain "view guide; generate report".',
    'Explain this log: ```\nshow guide\ngenerate report\n```',
    '日志：“先看导板，然后生成报告',
    '如果剂量合格，生成导板，再生成报告',
    'If dose is acceptable, generate guide, then generate report',
])
def test_reference_and_conditional_content_cannot_release_mutations(message):
    assert not mutating_execution_authorized(message, "report_generator")
    assert not classify_local_turn(message).direct_execution


def test_quoted_commands_do_not_block_independent_explicit_command():
    assert mutating_execution_authorized('日志写着“生成导板，生成报告”。现在请生成报告', "report_generator")
    assert not mutating_execution_authorized('日志写着“生成导板，生成报告”。现在请生成报告', "surgical_guide")


def test_multiple_quotes_keep_correct_source_offsets():
    text = '解释 "show guide" 和 "generate report, update dose"'
    assert [text[a:b] for a, b in _quoted_spans(text)] == ['show guide', 'generate report, update dose']


def test_apostrophes_are_not_quote_delimiters():
    assert not _quoted_spans("don't generate report; it's already there")
    assert not mutating_execution_authorized("don't generate report; it's already there", "report_generator")


def test_decimal_is_part_of_the_original_parameter():
    tasks = parse_request("请将CTV透明度设置为0.5，然后生成报告").subtasks
    assert len(tasks) == 2
    assert "0.5" in tasks[0].raw


def test_condition_ends_at_chinese_sentence_boundary():
    tasks = parse_request("如果剂量合格，生成导板，再生成报告。请重新计算剂量").subtasks
    assert [task.conditional for task in tasks] == [True, True, True, False]


@pytest.mark.parametrize("message", [
    'Could you generate the report?', 'Can you please update the report?',
    '可以帮我生成报告吗？', '能不能生成报告？',
])
def test_polite_requests_are_commands_without_extra_model_round(message):
    assert mutating_execution_authorized(message, "report_generator")
    assert not mutating_execution_authorized(message, "planning_pipeline")


@pytest.mark.parametrize("message", [
    'Could you explain how to generate a report?',
    'Can you generate a report or a guide?',
    '可以告诉我如何生成报告吗？', '你可以生成报告吗，还是只能查看？',
    'If needed, could you generate the report?',
])
def test_capability_choice_and_conditional_questions_remain_read_only(message):
    assert not mutating_execution_authorized(message, "report_generator")


def test_conditional_markers_have_english_word_boundaries():
    assert not is_conditional('Generate a report for the diff result')
    assert is_conditional('Generate report if the dose is current')


def test_failure_blocks_only_dependents_and_keeps_tool_protocol():
    state = StepExecutionState()
    calls = state.prepare([
        {"key": "dose", "tool": "dose_recompute", "params": {}},
        {"key": "report", "tool": "report_generator", "depends_on": ["dose"]},
        {"key": "read", "tool": "query_metrics", "params": {}},
    ])
    state.record(calls[0], success=False)
    assert state.blocked_reason(calls[1])
    assert not state.blocked_reason(calls[2])
    messages = []
    append_tool_receipt(messages, calls[0], "Dose calculation failed")
    assert messages[1]["tool_call_id"] == messages[0]["tool_calls"][0]["id"]
    assert "failed" in messages[1]["content"]


@pytest.mark.parametrize("metadata", [
    {"completed": False}, {"status": "dispatched"}, {"pending": True},
    {"execution_claim": "accepted_pending_browser", "accepted": 1, "executed": 0},
])
def test_browser_dispatch_is_not_completion(metadata):
    state = StepExecutionState()
    calls = state.prepare([
        {"key": "show", "tool": "ui_controller", "params": {}},
        {"key": "image", "tool": "ui_screenshot", "depends_on": "show"},
    ])
    state.record(calls[0], success=True, metadata=metadata)
    assert state.blocked_reason(calls[1])
    repeated = state.prepare([{"key": "show-again", "tool": "ui_controller", "params": {}}])[0]
    assert state.reuse(repeated)
    assert state.outcomes[repeated["key"]] == "pending"


def test_reads_refresh_after_mutation_but_unchanged_duplicate_is_reused():
    state = StepExecutionState()
    calls = state.prepare([
        {"key": "before", "tool": "query_metrics", "params": {}},
        {"key": "move", "tool": "ui_controller", "params": {}},
        {"key": "after", "tool": "query_metrics", "params": {}},
    ])
    state.record(calls[0], success=True)
    assert state.reuse(calls[2])
    state.record(calls[1], success=True)
    assert not state.reuse(calls[2])
    assert state.reuse(calls[1])


def test_unknown_and_cyclic_dependencies_never_execute():
    state = StepExecutionState()
    calls = state.prepare([
        {"key": "a", "tool": "ui_controller", "depends_on": ["b"]},
        {"key": "b", "tool": "ui_controller", "depends_on": ["a"]},
        {"key": "c", "tool": "query_metrics", "depends_on": ["missing"]},
    ])
    assert all(state.blocked_reason(call) for call in calls)


def test_generated_receipt_keys_do_not_collide_with_explicit_keys():
    state = StepExecutionState()
    calls = state.prepare([
        {"tool": "query_metrics", "key": None},
        {"tool": "query_metrics", "key": "query_metrics"},
        {"tool": "query_metrics", "key": "query_metrics#2"},
    ])
    assert len({call["_receipt_key"] for call in calls}) == 3
    assert all(not state.blocked_reason(call) for call in calls)


def test_explicit_and_implicit_tool_slots_do_not_alias():
    plan = ActionPlan.from_tool_calls([
        {"key": "first", "tool": "query_metrics"},
        {"key": "middle", "tool": "ui_controller"},
        {"key": "last", "tool": "query_metrics"},
    ])
    calls = [
        {"key": "first", "tool": "query_metrics"},
        {"tool": "query_metrics"},
        {"key": "middle", "tool": "ui_controller"},
    ]
    assert [c["tool"] for c in plan.order_tool_calls(calls)] == ["query_metrics", "ui_controller", "query_metrics"]


def test_mixed_read_and_write_keeps_both_capabilities():
    policy = classify_local_turn("当前规划怎么样，然后重新生成报告")
    assert "query_metrics" in policy.allow_tools
    assert "report_auto_fill" in policy.allow_tools or "ui_controller" in policy.allow_tools


@pytest.mark.parametrize("payload", [
    {"function": {"name": "query_metrics", "arguments": '{"metric_type":"oar_dose"}'}},
    {"name": "query_metrics", "input": {"metric_type": "oar_dose"}},
])
def test_provider_formats_preserve_arguments_and_dependencies(payload):
    payload.update(key="read", depends_on=["recompute"])
    call = decode_provider_call(payload)
    assert call["params"] == {"metric_type": "oar_dose"}
    assert call["key"] == "read"
    assert call["depends_on"] == ["recompute"]


@pytest.mark.parametrize("arguments", ['{"action":', '[]', 'null', 3, None, ''])
def test_malformed_arguments_never_become_default_mutations(arguments):
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    state = StepExecutionState()
    call = decode_provider_call({"function": {"name": "planning_pipeline", "arguments": arguments}})
    auth = TurnExecutionAuthorization(1)
    auth.grant_tool_calls([call], source="llm")
    assert not auth.tool_allowed("planning_pipeline")
    assert state.blocked_reason(state.prepare([call])[0])


def test_compacted_same_turn_evidence_survives_another_model_round():
    from agent_runtime.llm_runtime import _bound_followup_messages
    base = [{"role": "system", "content": "test"}]
    messages = list(base)
    for index in range(4):
        append_tool_receipt(messages, {"id": str(index), "tool": "query_metrics", "params": {"target": f"object-{index}"}}, f"evidence-{index}")
    bounded = _bound_followup_messages(messages, 1)
    append_tool_receipt(bounded, {"id": "5", "tool": "query_metrics", "params": {}}, "evidence-5")
    again = _bound_followup_messages(bounded, 1)
    assert all(f"evidence-{index}" in str(again) for index in range(4))
    assert all(f"object-{index}" in str(again) for index in range(4))
    assert "evidence-5" in str(again)
    assert len([m for m in again if m.get("role") == "tool"]) == 2
