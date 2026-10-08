"""Request-scope negative controls through actual authorization/provider loops.

Synthetic receipts only: this is engineering regression evidence, not a live
language-model accuracy result or clinical planning experiment.
"""
from copy import deepcopy
from types import SimpleNamespace
import time

import pytest

from AgenticSys import BrachyAgent
from agent_runtime.core import AgentMemory
from agent_runtime.execution_authorization import TurnExecutionAuthorization, PLANNING_WORKFLOW
from agent_runtime.execution_scope import ExecutionScope, check_call_scopes
from agent_runtime.request_parse import parse_request, mutating_execution_authorized
from agent_runtime.semantic_kernel import semantic_runtime_policy, admission_error_text
from agent_runtime.turn_policy import classify_local_turn
from test_decision_chain_execution import Harness


CASES = [
    ('仅作重新规划', 'planning_pipeline', {'step': 'full'}, {'planning'}, set()),
    ('只重新规划', 'planning_pipeline', {'step': 'full'}, {'planning'}, set()),
    ('这次仅重新执行治疗规划，报告和导板保持不动', 'planning_pipeline', {'step': 'full'}, {'planning'}, {'report', 'surgical_guide'}),
    ('只重新计算剂量和 DVH，不要重新规划', 'dose_recompute', {}, {'dose'}, {'planning'}),
    ('只更新报告，导板保持原样', 'report_auto_fill', {}, {'report'}, {'surgical_guide'}),
    ('仅分割 CTV，不用进行规划，也不要生成导板', 'ctv_segmentation', {}, {'ctv'}, {'planning', 'surgical_guide'}),
    ('只重新分割 OAR，CTV 保持不变', 'oar_segmentation', {}, {'oar'}, {'ctv'}),
    ('只生成导板，不用重算剂量', 'surgical_guide', {'action': 'generate'}, {'surgical_guide'}, {'dose'}),
    ('Only replan', 'planning_pipeline', {'step': 'full'}, {'planning'}, set()),
    ('Please just replan, keep the report and guide unchanged', 'planning_pipeline', {'step': 'full'}, {'planning'}, {'report', 'surgical_guide'}),
    ('Recompute dose only; do not replan', 'dose_recompute', {}, {'dose'}, {'planning'}),
    ('Only update the report, leave the guide untouched', 'report_auto_fill', {}, {'report'}, {'surgical_guide'}),
    ('Just segment the CTV without a new plan or guide', 'ctv_segmentation', {}, {'ctv'}, {'planning', 'surgical_guide'}),
    ('Only segment the OAR; retain the existing CTV unchanged', 'oar_segmentation', {}, {'oar'}, {'ctv'}),
    ('Generate the guide only, no need to recompute dose', 'surgical_guide', {'action': 'generate'}, {'surgical_guide'}, {'dose'}),
    ('只重新计算当前规划方案的剂量', 'dose_recompute', {}, {'dose'}, set()),
    ('仅重算当前规划的 DVH', 'dose_recompute', {}, {'dose'}, set()),
    ("Only recompute the current plan's dose", 'dose_recompute', {}, {'dose'}, set()),
    ('Only recalculate DVH for the current plan', 'dose_recompute', {}, {'dose'}, set()),
    ('只更新剂量', 'dose_recompute', {}, {'dose'}, set()),
    ('只刷新剂量和 DVH', 'dose_recompute', {}, {'dose'}, set()),
    ('Only update the dose', 'dose_recompute', {}, {'dose'}, set()),
]
WRITERS = [('planning_pipeline', {'step': 'full'}), ('dose_recompute', {}),
           ('report_auto_fill', {}), ('surgical_guide', {'action': 'generate'}),
           ('ctv_segmentation', {}), ('oar_segmentation', {})]


@pytest.mark.parametrize('message,tool,params,exclusive,excluded', CASES)
def test_scope_preserves_requested_write_and_excludes_other_effects(message, tool, params, exclusive, excluded):
    parsed = parse_request(message)
    assert parsed.exclusive_write_targets == frozenset(exclusive), parsed.to_dict()
    assert set(parsed.excluded_targets) == excluded, parsed.to_dict()
    assert mutating_execution_authorized(message, tool, params=params), parsed.to_dict()
    auth = TurnExecutionAuthorization(1)
    auth.bind_request(message)
    # Deliberately overbroad policy/provider grants cannot override the human.
    auth.grant_tools([name for name, _ in WRITERS], source='bad-shortcut')
    calls = [{'tool': name, 'params': p} for name, p in WRITERS]
    auth.grant_tool_calls(calls, source='bad-provider')
    assert auth.tool_allowed(tool, params)
    for name, p in WRITERS:
        effects = ExecutionScope.from_request(message).allows(name, p)
        assert auth.tool_allowed(name, p) == effects
    assert auth.tool_allowed('query_metrics', {'metric_type': 'all_metrics'})
    assert auth.tool_allowed('surgical_guide', {'action': 'status'})
    assert auth.tool_allowed('case_memory', {'action': 'list'})


@pytest.mark.parametrize('message', [
    'Replan without regenerating the guide', 'Replan without a new guide',
    '重新规划不用生成导板', '重新规划，导板保持原样',
    '重新规划并保留导板不变', 'Update the report without recomputing dose',
])
def test_postposed_restriction_does_not_cancel_the_positive_antecedent(message):
    tool = 'report_auto_fill' if message.startswith('Update') else 'planning_pipeline'
    assert mutating_execution_authorized(message, tool)
    prohibited = 'dose_recompute' if tool == 'report_auto_fill' else 'surgical_guide'
    assert not mutating_execution_authorized(message, prohibited, params={'action': 'generate'})


@pytest.mark.parametrize('message', [
    'Update the report without abbreviations',
    'Generate the report without personal identifiers',
])
def test_non_object_output_modifier_does_not_prohibit_the_requested_artifact(message):
    assert mutating_execution_authorized(message, 'report_auto_fill')
    assert not parse_request(message).excluded_targets


def test_preserve_masks_without_an_adjective_is_still_a_no_replace_constraint():
    message = '重新规划，保留 CTV 和 OAR'
    assert mutating_execution_authorized(message, 'planning_pipeline')
    assert set(parse_request(message).excluded_targets) == {'ctv', 'oar'}
    scope = ExecutionScope.from_request(message)
    assert not scope.allows('ctv_segmentation', {})
    assert not scope.allows('oar_segmentation', {})


@pytest.mark.parametrize('message', ['重新规划', '请重新执行手术规划', '我是让你重新规划'])
def test_legacy_replan_dependency_plan_contains_no_optional_guide(message):
    policy = classify_local_turn(message)
    assert policy.action_plan.tool_names == ('ctv_segmentation', 'oar_segmentation', 'planning_pipeline')
    assert 'surgical_guide' not in policy.execution_grants


def test_explicit_sibling_generation_is_not_lost_to_exclusivity():
    message = '只重新规划，然后生成报告；导板保持原样'
    auth = TurnExecutionAuthorization(1)
    auth.bind_request(message)
    assert auth.effect_scope.exclusive == {'planning', 'report'}
    assert auth.effect_allowed('planning_pipeline', {'step': 'full'})
    assert auth.effect_allowed('report_auto_fill', {})
    assert not auth.effect_allowed('surgical_guide', {'action': 'generate'})
    assert mutating_execution_authorized(message, 'report_auto_fill')


def test_language_modifier_is_not_an_operation_or_clinical_effect_scope():
    parsed = parse_request('请重新规划，用中文回答即可')
    assert parsed.exclusive_write_targets is None
    parsed = parse_request('只用中文解释为什么要重新规划，不要执行')
    assert not parsed.unconditional_command
    assert not mutating_execution_authorized(parsed.raw, 'planning_pipeline')


def test_read_only_constraints_remain_read_only_and_do_not_modify_display():
    message = '截图告诉我肿瘤的位置，但不要改变显示状态'
    for name, params in WRITERS:
        assert not mutating_execution_authorized(message, name, params=params)
    message = '只看报告有没有包含器官剂量，不要回填报告'
    assert not mutating_execution_authorized(message, 'report_auto_fill')


def test_scope_is_current_turn_immutable_and_not_an_authorization_grant():
    auth = TurnExecutionAuthorization(9)
    assert auth.bind_request('只更新报告')
    assert not auth.bind_request('更新报告并生成导板')
    assert auth.bind_request('只更新报告')
    assert not auth.tool_allowed('report_auto_fill', {})
    auth.grant_tool_calls([{'tool': 'report_auto_fill', 'params': {}}], source='provider')
    assert auth.tool_allowed('report_auto_fill', {})
    assert not auth.tool_allowed('surgical_guide', {'action': 'generate'})
    other = TurnExecutionAuthorization(10)
    other.bind_request('请生成导板')
    other.grant_tool_calls([{'tool': 'surgical_guide', 'params': {'action': 'generate'}}], source='provider')
    assert other.tool_allowed('surgical_guide', {'action': 'generate'})


def test_mixed_ui_wrapper_cannot_bypass_report_only_scope():
    auth = TurnExecutionAuthorization(1)
    auth.bind_request('只更新报告')
    report = {'actions': [{'target': 'report.autofill', 'command': 'run'}]}
    auth.grant_tool_calls([{'tool': 'ui_controller', 'params': report}], source='provider')
    assert auth.tool_allowed('ui_controller', report)
    assert not auth.tool_allowed('ui_controller', {'actions': [{'target': 'manual.plan.replan', 'command': 'run'}]})
    assert not auth.effect_allowed('ui_controller', {'actions': report['actions'] + [{'target': 'viewer.reset', 'command': 'run'}]})


@pytest.mark.parametrize('message', [
    '仅更新报告中的剂量表，其他内容不动',
    "Only update the report's dose table",  # owning-field intent is semantically explicit
    "Only update the report's title",
])
def test_partial_report_write_cannot_be_replaced_by_full_autofill(message):
    # "dose table" includes a clinical noun before the generic table head.
    auth = TurnExecutionAuthorization(1)
    auth.bind_request(message)
    assert auth.effect_scope.partial == {'report'}
    assert not auth.effect_allowed('report_auto_fill', {})
    assert not auth.effect_allowed('report_generator', {})
    assert not auth.effect_allowed('ui_controller', {'actions': [{'target': 'report.autofill', 'command': 'run'}]})
    assert auth.effect_allowed('ui_controller', {'actions': [{'target': 'report.field.set', 'command': 'set', 'value': '{"key":"interpretation","value":"synthetic"}'}]})


def test_excluded_prerequisite_is_not_authorized_by_a_workflow_grant():
    auth = TurnExecutionAuthorization(1)
    auth.bind_request('仅重新规划，不要重新分割 CTV 和 OAR')
    auth.grant_tool_calls([{'tool': 'planning_pipeline', 'params': {'step': 'full'}}], source='provider')
    assert auth.workflow_allowed(PLANNING_WORKFLOW)
    assert not auth.tool_allowed('ctv_segmentation', {})
    assert not auth.tool_allowed('oar_segmentation', {})
    assert auth.tool_allowed('planning_pipeline', {'step': 'full'})


def test_denial_is_a_receipt_not_silent_disappearance_or_confirmation():
    auth = TurnExecutionAuthorization(1)
    auth.bind_request('只重算剂量')
    proposals = [{'id': 'dose', 'tool': 'dose_recompute', 'params': {}},
                 {'id': 'guide', 'tool': 'surgical_guide', 'params': {'action': 'generate'}}]
    before = deepcopy(proposals)
    checked = check_call_scopes(proposals, auth)
    assert proposals == before
    assert not checked[0].get('_argument_error')
    assert checked[1]['_admission_code'] == 'request_scope'
    assert '不会要求你确认' in admission_error_text(checked[1], 'zh')


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('message,tool,params,exclusive,excluded', CASES)
def test_actual_provider_loops_block_overbroad_model_proposals(stream, message, tool, params, exclusive, excluded):
    # Harness intentionally bypasses the lexical normalizer: this tests the
    # independent shared effect guard rather than repeating parser assertions.
    actual_params = dict(params)
    if tool == 'ctv_segmentation':
        actual_params['tumor_type'] = 'nnunet_pancreatic'  # required real schema input
    proposals = [{'name': tool, 'input': actual_params},
                 {'name': 'ui_controller', 'input': {'actions': [{'target': 'viewer.reset', 'command': 'run'}]}}]
    if tool != 'surgical_guide':
        proposals.append({'name': 'surgical_guide', 'input': {'action': 'generate'}})
    if tool != 'report_auto_fill':
        proposals.append({'name': 'report_auto_fill', 'input': {}})
    harness = Harness([proposals], {})
    harness.memory.store('tumor_type_used', 'nnunet_pancreatic')
    harness.memory.store('tumor_type_used_ct_path', '/test/ct.nii.gz')
    harness.memory.add_message('user', message)
    harness._turn_execution_authorization.bind_request(message)
    steps = []
    if stream:
        list(harness._run_llm_function_calling_stream(message, steps, [0], lambda kind, data: {'type': kind, 'data': data}))
    else:
        harness._run_llm_function_calling(message, steps, [0])
    assert harness.executed == [tool], (message, harness.executed, steps)
    assert any(s.get('_admission_code') == 'request_scope' or 'scope' in str(s).lower() for s in steps)
    assert len(harness.provider_messages) <= 2  # no classifier/confirmation round


def test_live_mask_reuse_materializes_only_the_planning_operation():
    agent = object.__new__(BrachyAgent)
    agent.memory = AgentMemory('synthetic-only-plan')
    for key, value in [('ctv_array', object()), ('oar_array', object()), ('oar_is_full', True), ('ct_path', '/synthetic/ct.nii.gz')]:
        agent.memory.store(key, value)
    agent.config = {}
    agent._has_completed_planning = lambda: True
    agent._active_turn_policy = semantic_runtime_policy(classify_local_turn('仅作重新规划'), message='仅作重新规划')
    auth = TurnExecutionAuthorization(0)
    auth.bind_request('仅作重新规划')
    auth.grant_tool_calls([{'tool': 'planning_pipeline', 'params': {'step': 'full'}}], source='provider')
    agent._turn_execution_authorization = auth
    calls = agent._normalize_clinical_tool_calls([{'tool': 'planning_pipeline', 'params': {'step': 'full'}}], '仅作重新规划')
    assert [c['tool'] for c in calls] == ['planning_pipeline']
    assert calls[0]['params']['step'] == 'full'


def test_final_execution_boundary_refuses_before_resources_or_registry_access():
    agent = object.__new__(BrachyAgent)
    auth = TurnExecutionAuthorization(0)
    auth.bind_request('只更新报告')
    agent._turn_execution_authorization = auth
    result = agent._execute_tool_with_memory('surgical_guide', {'action': 'generate'})
    assert not result.success and 'scope' in result.error


@pytest.mark.parametrize('message', [
    '先只重算剂量，报告等我确认后再更新',
    'Only recompute dose; update the report after I approve',
    '只重新规划，得到我同意再生成导板',
    'Just replan; generate the guide once I confirm',
])
def test_wait_for_consent_is_not_a_current_sibling_write_grant(message):
    deferred = 'report_auto_fill' if 'report' in message or '报告' in message else 'surgical_guide'
    assert not mutating_execution_authorized(message, deferred, params={'action': 'generate'})
    assert len(parse_request(message).exclusive_write_targets) == 1


def test_excluded_operation_never_becomes_a_pending_confirmation():
    agent = object.__new__(BrachyAgent)
    auth = TurnExecutionAuthorization(0)
    auth.bind_request('只重新规划，不要生成导板')
    agent._turn_execution_authorization = auth
    agent._blocked_mutating_proposals = [{'tool': 'surgical_guide', 'params': {'action': 'generate'}}]
    agent._blocked_mutating_tool_names = ['surgical_guide']
    result = agent._confirmation_fallback('zh', ['surgical_guide'])
    assert '不会转成待确认' in result
    assert getattr(agent, '_pending_execution_confirmation', None) is None


def test_scope_projection_has_no_io_or_provider_latency():
    start = time.perf_counter()
    for _ in range(30):
        for message, *_ in CASES:
            ExecutionScope.from_request(message)
    assert (time.perf_counter() - start) < 5  # generous CI ceiling, not a speed claim
