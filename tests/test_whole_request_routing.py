"""Adversarial utterances: a lexical noun/verb hit cannot grant execution."""
import pytest
from agent_runtime.turn_policy import classify_local_turn
from agent_runtime.response_tools import ResponseToolMixin


@pytest.mark.parametrize('message', [
    '不要重新执行规划', '为什么要重新执行规划',
    '如果重新执行规划会怎样', '他让我重新执行规划，这是什么意思',
    '日志中写着重新执行规划', '不要在viewer中显示规划结果',
    '为什么viewer显示规划结果很慢', '我昨天生成了手术导板',
    '导板生成失败了', '请解释如何生成手术导板',
    '请不要重新计算当前剂量', '如果隐藏所有OAR会怎样',
    '请把所有OAR隐藏这个功能解释一下',
    '请把OAR设为半透明但是保留CTV不变',
    'Do not rerun planning', 'Why should I replan?',
    'The log says regenerate the surgical guide',
    'Why does the viewer display planning results slowly?',
    'Do not hide all OAR', 'Please explain how to segment CTV',
])
def test_candidate_is_not_permission(message):
    policy = classify_local_turn(message)
    assert not policy.direct_execution, (message, policy)
    assert not policy.execution_grants
    assert not policy.workflow_grants
    assert policy.action_plan is None
    assert ResponseToolMixin()._detect_tool_request(message) is None


def test_rejected_plan_is_not_reintroduced_as_overwrite():
    assert not ResponseToolMixin._force_reexecution_requested('不要重新执行规划')
    assert not ResponseToolMixin._force_reexecution_requested('why rerun planning?')
    assert ResponseToolMixin._force_reexecution_requested(params={'force_reexecution': True})


@pytest.mark.parametrize('message', [
    '请执行放射性粒子植入规划', '请执行CTV分割', '请重新生成手术导板',
    '将结果在viewer中显示出来啊', '帮我将所有OAR在调到半透明',
    '请截图告诉我手术导板在哪里',
])
def test_complete_commands_retain_shortcuts(message):
    policy = classify_local_turn(message)
    assert policy.direct_execution
    assert policy.routing_source == 'whole_request_contract'


def test_abstention_is_auditable_and_does_not_add_router_call():
    policy = classify_local_turn('不要在viewer中显示规划结果')
    assert policy.routing_source == 'primary_semantic'
    assert policy.candidate_intent == 'viewer_display'
    assert policy.routing_reason == 'whole_request_contract_not_satisfied'
    assert not policy.use_router


def test_normalizer_cannot_invent_dose_call_or_replace_unrelated_tool():
    from AgenticSys import BrachyAgent
    message = '可以重新计算DVH相关指标，验证和当前的结果是否一致'
    assert BrachyAgent._normalize_clinical_tool_calls(object(), [], message) == []
    calls = [{'tool': 'query_metrics', 'params': {}}]
    assert BrachyAgent._normalize_clinical_tool_calls(object(), calls, message) == calls


@pytest.mark.parametrize('message', [
    '请重新生成手术报告', '重新生成报告', '生成手术报告',
    '重新生成剂量报告', '生成计划报告', 'regenerate the surgical report',
])
def test_report_object_wins_over_guide_and_dose(message):
    from agent_runtime.turn_policy import (
        is_report_generation_request, is_surgical_guide_generation_request,
    )
    policy = classify_local_turn(message)
    assert is_report_generation_request(message)
    assert not is_surgical_guide_generation_request(message)
    assert policy.intent == 'report_generation'
    assert policy.direct_execution
    assert policy.execution_grants == {'ui_controller'}
    assert 'surgical_guide' not in (policy.allow_tools or set())


@pytest.mark.parametrize('message', [
    '生成手术导板', '请重新生成导板', '请重新生成手术导板',
    'regenerate the surgical guide',
])
def test_guide_object_still_wins_when_guide_noun_present(message):
    policy = classify_local_turn(message)
    assert policy.intent == 'surgical_guide_generation'
    assert policy.direct_execution
    assert policy.execution_grants == {'surgical_guide'}


def test_report_object_never_reaches_surgical_guide_in_normalization():
    class Memory:
        conversation = [{'role': 'user', 'content': '请重新生成手术报告'}]

        @staticmethod
        def retrieve(_key):
            return None

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    calls = normalizer._normalize_tool_params([{
        'id': 'mis_selected_guide',
        'tool': 'surgical_guide',
        'params': {'action': 'generate'},
    }])
    assert calls == [{
        'id': 'mis_selected_guide',
        'tool': 'ui_controller',
        'params': {'actions': [{'target': 'report.autofill', 'command': 'run'}]},
    }]


def test_rejected_or_compound_report_turn_does_not_force_report_autofill():
    class Memory:
        def __init__(self, content):
            self.conversation = [{'role': 'user', 'content': content}]

        @staticmethod
        def retrieve(_key):
            return None

    for content in ('不要生成报告', '重新生成手术报告并显示截图'):
        normalizer = ResponseToolMixin()
        normalizer.memory = Memory(content)
        calls = [{'id': 'guide', 'tool': 'surgical_guide', 'params': {'action': 'generate'}}]
        assert normalizer._normalize_tool_params(calls) == calls, content


def test_complete_semantic_instructions_are_shared_and_do_not_mutate_input():
    from agent_runtime.llm_runtime import LLMRuntimeMixin
    messages = [{'role': 'system', 'content': 'Trusted system'},
                {'role': 'user', 'content': 'Do not clear the report'}]
    output = LLMRuntimeMixin()._pack_context_for_provider(messages, messages[-1]['content'])
    assert '[Whole-request interpretation]' in output[0]['content']
    assert messages[0]['content'] == 'Trusted system'
    assert output[-1] == messages[-1]


# ---------------------------------------------------------------------------
# Whole-request regression table (negation / question / condition / state)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('message', [
    '报告生成好了吗？', '报告生成好了吗',
    '不要生成报告', '如果报告空了就重新生成',
    '重新生成的报告解读一下', '他让我重新生成报告，这是什么意思',
])
def test_report_semantic_classes_never_take_the_report_fast_path(message):
    from agent_runtime.turn_policy import unambiguous_report_generation_request
    policy = classify_local_turn(message)
    assert not unambiguous_report_generation_request(message), message
    assert not policy.direct_execution, message
    assert not policy.execution_grants, message


@pytest.mark.parametrize('message', [
    '请重新生成手术报告', '生成分析报告', '重新生成剂量报告',
    'regenerate the surgical report', '写一份术后报告',
])
def test_positive_report_commands_keep_the_report_fast_path(message):
    from agent_runtime.turn_policy import unambiguous_report_generation_request
    policy = classify_local_turn(message)
    assert unambiguous_report_generation_request(message), message
    assert policy.intent == 'report_generation', message
    assert policy.execution_grants == {'ui_controller'}, message


def test_compound_guide_and_report_is_ordered_and_stays_semantic():
    message = '重新生成手术导板和报告'
    policy = classify_local_turn(message)
    assert policy.intent == 'semantic_action'
    assert policy.parsed_goals == (
        ('surgical_guide', 'generate'),
        ('report', 'generate'),
    )
    assert policy.action_plan is None


def test_conditional_guide_generation_is_not_an_unconditional_run():
    from agent_runtime.request_parse import mutating_execution_authorized
    message = '如果还没有导板就生成一个'
    policy = classify_local_turn(message)
    assert not policy.direct_execution
    assert not mutating_execution_authorized(message, 'surgical_guide')


def test_generated_guide_location_question_is_not_a_new_generation():
    from agent_runtime.turn_policy import is_surgical_guide_generation_request
    assert not is_surgical_guide_generation_request('生成的手术导板在哪里')
    assert is_surgical_guide_generation_request('请生成手术导板')

