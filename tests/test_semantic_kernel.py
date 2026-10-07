"""Semantic-first contract regressions, not a model-accuracy benchmark.

Both production provider loops are exercised with deterministic replay. No
provider/network/GPU/patient mutation is performed by this suite.
"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent_runtime.semantic_kernel import (
    PLAN_TOOL, SemanticDecisionState, admission_error_text, admitted_proposals, identify_proposals, is_semantic_first,
    partial_batch_notice,
    project_provider_schemas, request_plan_schema, semantic_runtime_policy,
)
from agent_runtime.turn_policy import LocalTurnPolicy, classify_local_turn, SEMANTIC_TOOLS
from agent_runtime.execution_authorization import TurnExecutionAuthorization
from agent_runtime.step_execution import StepExecutionState, is_state_changing
from agent_runtime.llm_runtime import LLMRuntimeMixin, _model_round_budget


def semantic_policy():
    return semantic_runtime_policy(LocalTurnPolicy('knowledge_query', 'low', False, False, False))


@pytest.mark.parametrize('message', [
    '具体的剂量分布如何，这些都写在报告里了吗',
    '那从每个器官受到的辐射来看呢',
    '为什么你问我确认，刚才我已经让你全部更新了',
    '如果我重新生成导板会影响报告吗',
    '我不是问导板在哪里，是问为什么没显示',
    '我不是让你截图，是问报告里有没有这些数值',
    '不要规划，解释当前报告和剂量为何不一致',
    '那个青色的挡住肿瘤了，先告诉我它是什么',
    'Show the dose and explain what changed, without moving anything',
    'What changed after the edit, and is the report still current?',
    'Can you explain why stopping monitor starts it again?',
    'The log says “generate the guide”; why did that execute?',
    '这次微调是覆盖改善，还是仅仅评分变高了',
    '剂量有了，但文档呢，里面有没有遗漏受影响的器官',
    'Explain the actual case state, not your software capabilities',
    'If I keep the edit, what will still need recomputation?',
])
def test_general_requests_do_not_preselect_a_topic_fact_packet(message):
    policy = semantic_runtime_policy(classify_local_turn(message), message=message)
    assert is_semantic_first(policy), (message, policy)
    assert policy.allow_tools == SEMANTIC_TOOLS
    assert not policy.direct_execution and not policy.execution_grants
    assert policy.action_plan is None and not policy.parsed_goals


@pytest.mark.parametrize('intent', ['small_talk', 'visual_analysis', 'external_project_query'])
def test_transport_and_isolated_routes_keep_their_contract(intent):
    candidate = LocalTurnPolicy(intent, 'low', False, False, False)
    assert semantic_runtime_policy(candidate) is candidate


def test_content_classification_without_a_proved_command_remains_a_semantic_hint():
    # Unlike native attachment transport, a report/content topic can contain
    # factual questions and restrictions; it is not an execution contract.
    candidate = LocalTurnPolicy('session_content_query', 'low', False, False, False)
    policy = semantic_runtime_policy(candidate)
    assert is_semantic_first(policy)
    assert policy.candidate_intent == 'session_content_query'
    assert not policy.direct_execution and not policy.execution_grants


def test_verified_fast_path_and_rollback_are_preserved():
    candidate = classify_local_turn('手术导板生成了吗')
    assert candidate.direct_execution and not candidate.execution_grants
    assert semantic_runtime_policy(candidate) is candidate
    candidate = classify_local_turn('请重新生成手术导板')
    assert candidate.direct_execution
    assert semantic_runtime_policy(candidate) is candidate
    assert semantic_runtime_policy(candidate, enabled=False) is candidate


def test_partial_multi_read_must_return_to_whole_request_interpretation():
    candidate = LocalTurnPolicy('multi_intent_query', 'medium', False, False, False,
        direct_execution=True, parsed_subtasks=(('case_dose_query', 'dose'), ('session_content_query', 'report')))
    result = semantic_runtime_policy(candidate)
    assert is_semantic_first(result) and not result.direct_execution


def test_semantic_routing_cannot_remove_existing_review_requirements():
    candidate = LocalTurnPolicy('semantic_action', 'high', True, True, True)
    result = semantic_runtime_policy(candidate)
    assert result.requires_review and result.use_completeness
    assert not result.use_router  # not a second classifier model round
    assert not result.execution_grants


def test_runtime_entry_defaults_to_semantic_without_an_extra_classifier_call():
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    runtime = object.__new__(ChatWorkflowMixin)
    runtime.config = {}
    runtime.memory = SimpleNamespace(conversation=[])
    runtime._pending_tumor_site_clarification = lambda: False
    runtime._ui_state_snapshot = lambda: {}
    assert is_semantic_first(runtime._resolve_turn_policy('当前各器官实际剂量是多少'))
    runtime.config = {'agent_runtime': {'intent_mode': 'legacy'}}
    assert not is_semantic_first(runtime._resolve_turn_policy('当前各器官实际剂量是多少'))


def test_semantic_round_budget_does_not_add_a_classifier_or_unbounded_repair():
    policy = semantic_policy()
    assert _model_round_budget(policy) == 3
    assert _model_round_budget(replace(policy, complexity='medium')) == 5
    assert _model_round_budget(replace(policy, complexity='high')) == 5


def schema(name, actions=None):
    properties = {'action': {'enum': actions, 'default': actions[-1]}} if actions else {}
    return {'type': 'function', 'function': {'name': name,
        'parameters': {'type': 'object', 'properties': properties, 'required': []}}}


def test_capability_projection_is_server_owned_and_does_not_mutate_registry_cache():
    original = [schema('query_metrics'), schema('new_case_reader'), schema('unknown_writer'),
                schema('code_executor'), schema('shell_executor')]
    before = deepcopy(original)
    result = project_provider_schemas(original, semantic_policy(), {
        'new_case_reader': {'conversation_access': 'read'},
        'code_executor': {'conversation_access': 'read'},
        'shell_executor': {'conversation_access': 'read'},
    })
    assert {s['function']['name'] for s in result} == {'query_metrics', 'new_case_reader'}
    assert original == before
    result[0]['function']['parameters']['required'].append('test')
    assert original == before


def test_mixed_effect_schemas_do_not_advertise_implicit_mutations():
    original = [schema('clinical_kb', ['search', 'add']), schema('case_memory', ['list', 'save']),
                schema('surgical_guide', ['analyze', 'generate'])]
    result = project_provider_schemas(original, semantic_policy())
    assert result[0]['function']['parameters']['properties']['action']['enum'] == ['search']
    assert result[1]['function']['parameters']['properties']['action']['enum'] == ['list', 'save']
    assert result[2]['function']['parameters']['properties']['action']['enum'] == ['analyze', 'generate']
    assert all('default' not in s['function']['parameters']['properties']['action'] for s in result)
    assert all('action' in s['function']['parameters']['required'] for s in result)
    assert original[0]['function']['parameters']['properties']['action']['default'] == 'add'


def test_dropped_proposals_are_receipts_not_execution_grants():
    original = [{'id': 'd', 'tool': 'surgical_guide', 'params': {'action': 'generate'}},
                {'id': 'r', 'tool': 'query_metrics', 'params': {}}]
    calls = admitted_proposals(original, [original[1]], {'surgical_guide', 'query_metrics'})
    denied = next(c for c in calls if c['id'] == 'd')
    assert denied['_argument_error'] and denied['_admission_denied']
    assert not original[0].get('_argument_error')
    auth = TurnExecutionAuthorization(1)
    auth.grant_tool_calls(calls, source='test')
    assert not auth.granted_tools
    state = StepExecutionState()
    calls = state.prepare(calls)
    denied = next(c for c in calls if c['id'] == 'd')
    assert state.blocked_reason(denied)
    state.record(denied, success=False, attempted=False)
    assert state.epoch == 0
    assert 'other admitted operations' in denied['_argument_error']


@pytest.mark.parametrize('tool', ['ctv_segmentation', 'code_executor', 'new_writer'])
def test_out_of_palette_and_no_ct_proposals_never_execute(tool):
    call = {'id': 'x', 'tool': tool, 'params': {}}
    result = admitted_proposals([call], [call], {'ctv_segmentation'}, no_ct_tools={'ctv_segmentation'})
    assert len(result) == 1 and result[0]['_argument_error']


def test_alias_normalization_with_native_identity_does_not_add_a_false_denial():
    result = admitted_proposals([{'id': 'same', 'tool': 'alias', 'params': {}}],
        [{'id': 'same', 'tool': 'query_metrics', 'params': {}}], {'query_metrics'})
    assert len(result) == 1 and not result[0].get('_argument_error')


@pytest.mark.parametrize('code', ['unavailable', 'rejected'])
def test_runtime_denials_follow_response_language_without_rewriting_backend_errors(code):
    call = {'_argument_error': 'specific backend error', '_admission_code': code}
    assert '未执行' in admission_error_text(call, 'zh') or '没有执行' in admission_error_text(call, 'zh')
    assert admission_error_text(call, 'en') == 'specific backend error'
    assert admission_error_text({'_argument_error': 'specific backend error'}, 'zh') == 'specific backend error'


def test_text_format_variants_of_one_tool_keep_independent_admission_identity():
    calls = identify_proposals([
        {'tool': 'query_metrics', 'params': {'metric_type': 'dose_metrics'}},
        {'tool': 'query_metrics', 'params': {'metric_type': 'unsupported'}},
    ], 1)
    result = admitted_proposals(calls, [calls[0]], {'query_metrics'})
    assert len(result) == 2
    assert len({c['id'] for c in result}) == 2
    assert result[1]['_argument_error']


def test_duplicate_native_call_identities_are_denied_with_unique_failure_receipts():
    calls = identify_proposals([{'id': 'same', 'tool': 'query_metrics', 'params': {}},
                               {'id': 'same', 'tool': 'ui_controller', 'params': {}}], 1)
    assert len({c['id'] for c in calls}) == 2
    assert all(c['_argument_error'] for c in calls)
    auth = TurnExecutionAuthorization(1)
    auth.grant_tool_calls(calls, source='test')
    assert not auth.granted_tools


def test_reduced_ui_batch_notice_survives_all_admission_stages_without_trusting_model_notice():
    original = {'id': 'u', 'tool': 'ui_controller', 'params': {'actions': [
        {'target': 'tree.opacity', 'command': 'set', 'value': 0.3},
        {'target': 'tree.color', 'command': 'set', 'value': '#ffffff'}]}}
    normalized = {**original, 'params': {'actions': original['params']['actions'][:1]}}
    first = admitted_proposals([original], [normalized], {'ui_controller'})
    second = admitted_proposals(first, first, {'ui_controller'}, preserve_notices=True)
    final = admitted_proposals(second, second, {'ui_controller'}, preserve_notices=True)
    assert final[0]['_partial_ui_batch'] == {'proposed': 2, 'admitted': 1}
    assert not final[0].get('_argument_error')
    assert 'admitted batch has 1' in partial_batch_notice(final[0], 'en')
    assert '包含 1 项' in partial_batch_notice(final[0], 'zh')
    forged = {**normalized, '_partial_ui_batch': {'proposed': 999, 'admitted': 0}}
    assert not admitted_proposals([forged], [forged], {'ui_controller'})[0].get('_partial_ui_batch')


def goal(state, *, identity='dose', mode='read', evidence='session', tools=None, refs=None):
    return {'id': identity, 'clauses': refs or [c['id'] for c in state.frame['clauses']],
            'mode': mode, 'outcome': 'Answer the requested outcome', 'evidence': evidence,
            'tools': ['query_metrics'] if tools is None else tools}


def test_plan_is_bounded_non_authoritative_and_requires_complete_clause_accounting():
    state = SemanticDecisionState('What is the dose; is it in the report; do not regenerate anything')
    assert len(state.frame['clauses']) == 3
    partial = goal(state, refs=[state.frame['clauses'][0]['id']])
    with pytest.raises(ValueError, match='omits'):
        state.accept({'goals': [partial]}, {'query_metrics', 'ui_content'})
    assert not state.goals
    goals = [goal(state, refs=[state.frame['clauses'][0]['id']]),
             goal(state, identity='report', evidence='report', tools=['ui_content'], refs=[state.frame['clauses'][1]['id']]),
             goal(state, identity='restriction', mode='constraint', evidence='none', tools=[], refs=[state.frame['clauses'][2]['id']])]
    accepted = state.accept({'goals': goals}, {'query_metrics', 'ui_content'})
    assert accepted['grants_execution'] is False
    assert len(state.goals) == 3
    assert 'not authority' in state.context()
    assert not state.audit()['semantic_accuracy_verified']


@pytest.mark.parametrize('change', [
    {'tools': ['invented_tool']}, {'tools': [PLAN_TOOL]}, {'mode': 'constraint'},
    {'clauses': ['invented_clause']}, {'id': ''}, {'evidence': 'invented_source'},
    {'outcome': 'x' * 301}, {'tools': ['query_metrics'] * 13},
    {'clauses': ['c1'] * 13}, {'mode': 'read', 'tools': []},
])
def test_invalid_plan_does_not_install_partially_valid_outcomes(change):
    state = SemanticDecisionState('Read the dose')
    invalid = {**goal(state), **change}
    with pytest.raises(ValueError):
        state.accept({'goals': [invalid]}, {'query_metrics', PLAN_TOOL})
    assert not state.goals


def test_truncated_frame_cannot_be_promoted_to_complete_coverage():
    state = SemanticDecisionState(';'.join(['long clause ' * 100] * 20))
    with pytest.raises(ValueError, match='truncated'):
        state.accept({'goals': [goal(state)]}, {'query_metrics'})


@pytest.mark.parametrize('metadata', [
    {'pending': True}, {'completed': False}, {'status': 'dispatched'},
    {'status': 'queued'}, {'status': 'running'}, {'execution_claim': 'accepted_pending_browser'},
])
def test_pending_executor_receipt_cannot_certify_an_outcome(metadata):
    decision = SemanticDecisionState('Read the report')
    decision.accept({'goals': [goal(decision, tools=['ui_content'], evidence='report')]}, {'ui_content'})
    state = StepExecutionState()
    call = state.prepare([{'tool': 'ui_content', 'params': {}}])[0]
    state.record(call, success=True, metadata=metadata)
    assert decision.missing_evidence(state.receipts, epoch=state.epoch) == ['dose']
    assert decision.missing_evidence([{'type': 'tool', 'tool': 'ui_content', 'status': 'done'}]) == ['dose']


def test_repair_is_bounded_and_cannot_count_pre_write_reads_or_tool_success_as_field_proof():
    decision = SemanticDecisionState('Read the dose')
    decision.accept({'goals': [goal(decision)]}, {'query_metrics'})
    state = StepExecutionState()
    calls = state.prepare([{'tool': 'query_metrics', 'params': {}}, {'tool': 'ui_controller', 'params': {}}])
    state.record(calls[0], success=True)
    assert not decision.missing_evidence(state.receipts, epoch=state.epoch)
    state.record(calls[1], success=True)
    assert decision.missing_evidence(state.receipts, epoch=state.epoch) == ['dose']
    assert LLMRuntimeMixin._outcome_evidence_repair(decision, state.receipts, epoch=state.epoch)
    assert not LLMRuntimeMixin._outcome_evidence_repair(decision, state.receipts, epoch=state.epoch)
    assert 'actual returned fields' in decision.context()
    assert 'successful tool is not proof' in decision.context()


@pytest.mark.parametrize('tool,action,mutating', [
    ('case_memory', 'list', False), ('case_memory', 'save', True),
    ('clinical_kb', 'search', False), ('clinical_kb', 'add', True),
    ('surgical_guide', 'status', False), ('surgical_guide', 'generate', True),
])
def test_mixed_effect_cache_invalidation_uses_the_validated_action(tool, action, mutating):
    assert is_state_changing(tool, {'action': action}) is mutating


def test_bookkeeping_plan_tool_is_not_a_business_action_or_an_authorization():
    runtime = object.__new__(LLMRuntimeMixin)
    auth = TurnExecutionAuthorization(1)
    runtime._current_execution_authorization = lambda: auth
    state = SemanticDecisionState('Read the dose')
    params = {'goals': [goal(state)]}
    result = runtime._execute_request_plan(state, params, {'query_metrics'})
    assert result.success and result.metadata['grants_execution'] is False
    runtime._record_ordered_action_plan([{'tool': PLAN_TOOL, 'params': params}])
    assert not auth.action_plan.steps and not auth.granted_tools
    assert request_plan_schema()['function']['name'] == PLAN_TOOL


@pytest.mark.parametrize('stream', [False, True])
def test_real_provider_loops_feed_filtered_proposal_back_and_recover(stream):
    from test_decision_chain_execution import Harness, run

    class FilteredHarness(Harness):
        def _normalize_tool_params(self, calls):
            return [c for c in calls if c['tool'] != 'surgical_guide']

    harness = FilteredHarness([
        [{'id': 'denied', 'name': 'surgical_guide', 'input': {'action': 'generate'}}],
        [{'id': 'read', 'name': 'query_metrics', 'input': {}}],
    ], {})
    harness._active_turn_policy = semantic_policy()
    steps, response = run(harness, stream)
    assert harness.executed == ['query_metrics']
    assert len(harness.provider_messages) == 3
    second = str(harness.provider_messages[1])
    assert 'This operation was not executed' in second and 'denied' in second
    assert '120.2' in response
    assert not harness._turn_execution_authorization.granted_tools
    assert any(s.get('tool') == 'surgical_guide' and s.get('status') == 'error' for s in steps)


@pytest.mark.parametrize('stream', [False, True])
def test_real_provider_loops_can_record_plan_and_fetch_evidence_in_one_round(stream):
    from test_decision_chain_execution import Harness, run
    message = 'Please check the current workspace and explain each result'
    state = SemanticDecisionState(message)
    params = {'goals': [goal(state)]}
    harness = Harness([[
        {'id': 'plan', 'name': PLAN_TOOL, 'input': params},
        {'id': 'read', 'name': 'query_metrics', 'input': {}},
    ]], {})
    harness._active_turn_policy = semantic_policy()
    steps, response = run(harness, stream)
    assert harness.executed == ['query_metrics']
    assert len(harness.provider_messages) == 2  # not a separate planning round
    assert '120.2' in response
    assert 'Validated outcome proposal' in str(harness.provider_messages[-1])
    assert PLAN_TOOL not in harness._turn_execution_authorization.action_plan.tool_names


@pytest.mark.parametrize('stream', [False, True])
def test_real_loops_repair_missing_read_after_a_plan_once(stream):
    from test_decision_chain_execution import Harness, run
    message = 'Please check the current workspace and explain each result'
    state = SemanticDecisionState(message)
    harness = Harness([
        [{'name': PLAN_TOOL, 'input': {'goals': [goal(state)]}}],
        [],  # an early answer without the promised read
        [{'name': 'query_metrics', 'input': {}}],
    ], {})
    harness._active_turn_policy = semantic_policy()
    _, response = run(harness, stream)
    assert harness.executed == ['query_metrics']
    assert len(harness.provider_messages) == 4
    assert 'still have no successful same-turn evidence receipt' in str(harness.provider_messages[2])
    assert '120.2' in response


@pytest.mark.parametrize('stream', [False, True])
def test_real_normalizer_retains_bookkeeping_and_rejects_unrequested_ui_write(stream):
    from AgenticSys import BrachyAgent
    from test_decision_chain_execution import Harness, run
    state = SemanticDecisionState('Please check the current workspace and explain each result')

    class RealNormalizationHarness(Harness):
        def _normalize_tool_params(self, calls):
            return BrachyAgent._normalize_tool_params(self, calls)

    harness = RealNormalizationHarness([[
        {'id': 'plan', 'name': PLAN_TOOL, 'input': {'goals': [goal(state)]}},
        {'id': 'write', 'name': 'ui_controller', 'input': {'actions': [
            {'target': 'tree.opacity', 'command': 'set', 'value': 0.1}]}},
        {'id': 'read', 'name': 'query_metrics', 'input': {'metric_type': 'dose_metrics'}},
    ]], {})
    harness._active_turn_policy = semantic_policy()
    steps, response = run(harness, stream)
    assert harness.executed == ['query_metrics']
    assert not harness._turn_execution_authorization.granted_tools
    assert '120.2' in response
    denied = [s for s in steps if s.get('tool') == 'ui_controller']
    assert len(denied) == 1 and denied[0]['admission_denied']
    assert denied[0]['attempted'] is False and not denied[0]['dependency_blocked']
    assert 'Validated outcome proposal' in str(harness.provider_messages[-1])


def test_registry_extension_contract_reads_only_server_tool_metadata():
    from agent_runtime.core import ToolRegistry
    registry = ToolRegistry()
    registry.register(SimpleNamespace(name='case_read_extension', description='read',
        category='test', conversation_access='read', input_schema={'type': 'object', 'properties': {}}))
    registry.register(SimpleNamespace(name='default_extension', description='default',
        category='test', input_schema={'type': 'object', 'properties': {}, 'conversation_access': 'read'}))
    metadata = registry.conversation_capability_metadata()
    assert metadata['case_read_extension']['conversation_access'] == 'read'
    assert metadata['default_extension']['conversation_access'] is None
    result = project_provider_schemas(registry.to_openai_tools(), semantic_policy(), metadata)
    assert {s['function']['name'] for s in result} == {'case_read_extension'}


@pytest.mark.parametrize('stream', [False, True])
def test_real_loops_do_not_certify_the_whole_original_ui_batch_after_normalization(stream):
    from test_decision_chain_execution import Harness, run

    class ReducedHarness(Harness):
        def _normalize_tool_params(self, calls):
            return [{**c, 'params': {'actions': c['params']['actions'][:1]}}
                    if c['tool'] == 'ui_controller' else c for c in calls]

    harness = ReducedHarness([[
        {'id': 'u', 'name': 'ui_controller', 'input': {'actions': [
            {'target': 'tree.opacity', 'command': 'set', 'value': 0.2},
            {'target': 'tree.color', 'command': 'set', 'value': '#ffffff'}]}},
    ]], {})
    harness._active_turn_policy = semantic_policy()
    run(harness, stream)
    assert harness.executed == ['ui_controller']  # synthetic executor, no browser mutation
    assert 'admitted batch has 1' in str(harness.provider_messages[-1])
