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


def test_complete_semantic_instructions_are_shared_and_do_not_mutate_input():
    from agent_runtime.llm_runtime import LLMRuntimeMixin
    messages = [{'role': 'system', 'content': 'Trusted system'},
                {'role': 'user', 'content': 'Do not clear the report'}]
    output = LLMRuntimeMixin()._pack_context_for_provider(messages, messages[-1]['content'])
    assert '[Whole-request interpretation]' in output[0]['content']
    assert messages[0]['content'] == 'Trusted system'
    assert output[-1] == messages[-1]
