"""Real standalone Agent QA on declared numerical component fields, no LLM/mock model."""
import copy
import numpy as np
import pytest

from AgenticSys import BrachyAgent
from agent_runtime.contracts import RunLedger, ToolCallGateway
from agent_runtime.core import ToolRegistry
from plans.dose_pre.evaluation_inputs import resolve_dose_evaluation_inputs
from tool_factory.dose_eval import DoseEvaluationTool
from web.planning_config import evaluation_inputs_current
from web.timepoint_resources import fingerprint
from test_owned_evaluation_config import existing_bundle


def agent_for(case):
    agent = object.__new__(BrachyAgent)
    agent.memory = case.memory
    agent.registry = ToolRegistry()
    agent.registry.register(DoseEvaluationTool())
    agent.run_ledger = RunLedger()
    agent.tool_gateway = ToolCallGateway(agent.run_ledger)
    return agent


def set_current_rx(case):
    case.memory.store('timepoint_planning_config', {
        'in_lowest_dose_gy':120., 'dose_value_unit':'gy', 'tumor_type':'prostate',
        'oar_constraints':{'bladder':{'max_dose':80.}}})
    case.memory.store('ct_spacing', list(case.image.GetSpacing()))
    # Old aliases deliberately contain only one component. Total must come
    # from the producer's source-separated bundle, not whichever alias exists.
    case.memory.store('dose_distribution_physical_gy', np.full((3,4,5),30.,np.float32))
    case.memory.store('report_data', {'old_rx':90.})


def test_real_agent_evaluates_total_with_current_rx_and_publishes_complete_quality(existing_bundle):
    case = existing_bundle
    set_current_rx(case)
    before = fingerprint(case.bundle)
    result = agent_for(case)._execute_tool_with_memory('dose_evaluation', {})
    assert result.success, result.error
    metrics = case.memory.retrieve('dose_metrics')
    assert metrics['source_set'] == 'total'
    assert metrics['prescription_gy'] == 120. and metrics['d90'] == 90.
    assert metrics['v100'] == 0. and metrics['volume_metric_units'] == 'fraction'
    assert case.memory.retrieve('metrics') == metrics
    assert case.memory.retrieve('dvh_data')['CTV']
    assert case.memory.retrieve('total_dose_evaluation')['total_dose_sha256'] == case.bundle['total']['dose_sha256']
    assert case.memory.retrieve('current_dose_evaluation_config')['in_lowest_dose_gy'] == 120.
    assert case.memory.retrieve('plan_config') == case.plan
    assert fingerprint(case.bundle) == before
    assert case.memory.retrieve('artifact_status')['quality_check'] == 'ready'
    assert case.memory.retrieve('report_status') == 'stale' and case.memory.retrieve('report_data') is None
    assert evaluation_inputs_current(case.memory.retrieve)
    assert any(row['constraint'] == 80. for row in result.metadata['oar_violations'])
    from web.planning_runs import current_planning_context
    assert current_planning_context(case.memory)['metrics']['prescription_gy'] == 120.


@pytest.mark.parametrize('change', ['manual_flag','structured_flag','component_stale','total_tamper','grid'])
def test_agent_refuses_invalidated_or_corrupted_dose_without_resurrecting_quality(existing_bundle, change):
    case = existing_bundle
    set_current_rx(case)
    if change == 'manual_flag':
        case.memory.store('manual_artifact_status', {'dose':'stale'})
    elif change == 'structured_flag':
        case.memory.store('artifact_status', {'dose':{'status':'stale'}})
    elif change == 'component_stale':
        case.bundle['planned']['status'] = 'stale'
    elif change == 'total_tamper':
        case.bundle['total']['dose_distribution_physical_gy'][0,0,0] += 1.
    else:
        case.image.SetOrigin((2.,0.,0.))
    before = copy.deepcopy(case.memory.retrieve('dose_metrics'))
    result = agent_for(case)._execute_tool_with_memory('dose_evaluation', {})
    assert not result.success and 'source dose is stale' in result.error
    assert case.memory.retrieve('dose_metrics') == before
    assert case.memory.retrieve('report_data') == {'old_rx':90.}
    from utils.user_errors import format_tool_error
    assert '重新计算' in format_tool_error('dose_evaluation', result.error, {}, 'zh')


def test_what_if_legacy_rx_is_returned_without_overwriting_current_quality(existing_bundle):
    case = existing_bundle
    set_current_rx(case)
    before = copy.deepcopy(case.memory.retrieve('dose_metrics'))
    result = agent_for(case)._execute_tool_with_memory('dose_evaluation', {'prescribed_dose':60.})
    assert result.success and result.metadata['prescribed_dose'] == 60.
    assert result.metadata['evaluation_is_current'] is False
    assert case.memory.retrieve('dose_metrics') == before
    assert case.memory.retrieve('report_data') == {'old_rx':90.}


def test_legacy_result_store_retains_same_complete_evaluation_contract(existing_bundle):
    case = existing_bundle
    set_current_rx(case)
    resolved = resolve_dose_evaluation_inputs(case.memory.retrieve)
    result = DoseEvaluationTool().execute(**resolved['params'])
    assert result.success
    agent_for(case)._store_tool_result('dose_evaluation', result)
    assert case.memory.retrieve('dose_metrics')['d90'] == 90.
    assert case.memory.retrieve('dose_metrics')['prescription_gy'] == 120.
    assert case.memory.retrieve('current_dose_evaluation_config')['in_lowest_dose_gy'] == 120.


def test_actual_owned_agent_publication_and_cold_restore_stay_on_original_timepoint(existing_bundle, tmp_path, monkeypatch):
    from agent_runtime.core import AgentMemory
    from web.workspace_store import WorkspaceStore
    from web.timepoint_chat import ScopedChatRuntime, capture_chat_scope
    import SimpleITK as sitk
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path/'archive'))
    if __import__('os').name == 'nt':
        monkeypatch.setattr(WorkspaceStore, '_fsync_directory', staticmethod(lambda path: None))
    case = existing_bundle
    set_current_rx(case)
    store = WorkspaceStore(tmp_path/'runtime')
    uid = store.create_user('owned_qa_fixture', 'synthetic-test-hash')['id']
    sid = store.create_session(uid, 'Declared numerical QA case').id
    catalog = store.migrate_default_timepoint(uid, sid)
    first = catalog['default_timepoint_id']
    second = store.create_timepoint(uid, sid, 'QA B', expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    values = dict(case.memory.planning_results)
    values.update(ct_data=sitk.GetArrayFromImage(case.image), ct_origin=list(case.image.GetOrigin()),
                  ct_direction=list(case.image.GetDirection()))
    state = store.load_timepoint_snapshot(uid, sid, second)
    store.save_timepoint_results(uid,sid,second,values, expected_clinical_revision=state['timepoint_clinical_revision'])
    control = agent_for(case)
    control.memory = AgentMemory(sid)
    control._workspace_store = store
    control.config = {'_workspace_owner_id':uid, '_workspace_session_id':sid,
                      '_workspace_root':str(store.workspace_root(uid,sid))}
    import web.timepoint_messages as messages
    original_error = messages.timepoint_error
    failures = []
    def record_error(exc, *args, **kwargs):
        failures.append(str(exc))
        return original_error(exc, *args, **kwargs)
    monkeypatch.setattr(messages, 'timepoint_error', record_error)
    runtime = ScopedChatRuntime(control, capture_chat_scope(store,uid,sid,second))
    runtime.view._active_turn_context = {'timepoint_scope':runtime.scope}
    result = runtime.view._execute_tool_with_memory('dose_evaluation', {})
    assert result.success, (result.error, failures)
    assert result.metadata['published_to_timepoint'] and result.metadata['timepoint_id'] == second
    assert control.memory.retrieve('dose_metrics') is None
    assert not store.load_timepoint_snapshot(uid,sid,first)['agent']['planning_results']
    runtime.close()
    # A new store and fresh runtime decode the actual persisted files/ledger.
    reopened = WorkspaceStore(tmp_path/'runtime')
    control._workspace_store = reopened
    cold = ScopedChatRuntime(control, capture_chat_scope(reopened,uid,sid,second))
    cold._waiter(True)
    assert cold.view.memory.retrieve('dose_metrics')['d90'] == 90.
    assert cold.view.memory.retrieve('dose_metrics')['prescription_gy'] == 120.
    assert cold.view.memory.retrieve('current_dose_evaluation_config')['in_lowest_dose_gy'] == 120.
    assert cold.view.memory.retrieve('dvh_data')['CTV']
    assert cold.view.memory.retrieve('plan_config') == case.plan
    assert cold.view.memory.retrieve('dose_components')['total']['dose_sha256'] == case.bundle['total']['dose_sha256']
    cold.close()
