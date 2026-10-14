"""The server captures current dependencies; an LLM cannot invent the CAS head."""
from types import SimpleNamespace
import os
import pytest
from test_agent_timepoint_boundary import owned, activate
from agent_runtime.timepoint_tools import owned_tool_arguments
from web.timepoint_chat import project_timepoint_schemas
from web.timepoints import TimepointError
from tool_factory.dose_recompute import CurrentPlanDoseRecomputeTool


@pytest.fixture(autouse=True)
def portable_temporary_store(monkeypatch):
    if os.name=='nt':
        monkeypatch.setattr('web.workspace_store.WorkspaceStore._fsync_directory',staticmethod(lambda path:None))


def bound(owned):
    runtime=activate(owned,message='Recompute current implanted dose')
    runtime._waiter(True)
    scope=runtime.scope
    runtime.view.memory.store('implanted_seed_reconstruction',{'schema_version':1,'by_timepoint':{
        scope.timepoint_id:{'scope':{'owner_id':scope.owner_id,'session_id':scope.session_id,
            'timepoint_id':scope.timepoint_id},'current':{'reconstruction':{'revision_id':'b'*32}}}}})
    return runtime


def test_provider_cannot_reuse_old_observation_head_after_edit(owned):
    runtime=bound(owned)
    args=owned_tool_arguments(runtime.view,'dose_recompute',{'source_set':'implanted',
        'expected_observation_revision_id':'a'*32})
    assert args['expected_observation_revision_id']=='b'*32
    assert args['source_set']=='implanted'
    assert args['_agent'] is runtime.view
    runtime.close()


def test_explicit_human_observation_precondition_is_not_silently_replaced(owned):
    runtime=bound(owned)
    runtime.view._turn_local=SimpleNamespace(human_message='Recompute using observation revision '+ 'a'*32)
    args=owned_tool_arguments(runtime.view,'dose_recompute',{'source_set':'implanted',
        'expected_observation_revision_id':'a'*32})
    assert args['expected_observation_revision_id']=='a'*32
    runtime.close()


def test_other_target_or_owner_cannot_supply_current_head(owned):
    runtime=bound(owned)
    entry=runtime.view.memory.retrieve('implanted_seed_reconstruction')['by_timepoint'][runtime.scope.timepoint_id]
    entry['scope']['owner_id']='another-owner'
    with pytest.raises(TimepointError,match='does not belong'):
        owned_tool_arguments(runtime.view,'dose_recompute',{'source_set':'both'})
    runtime.close()


def test_planned_only_dose_does_not_borrow_observation_head(owned):
    runtime=bound(owned)
    args=owned_tool_arguments(runtime.view,'dose_recompute',{'source_set':'planned',
        'expected_observation_revision_id':'a'*32})
    assert 'expected_observation_revision_id' not in args
    runtime.close()


def test_only_scoped_provider_schema_hides_runtime_dependency_control(owned):
    runtime=bound(owned)
    original=CurrentPlanDoseRecomputeTool().input_schema
    schema={'type':'function','function':{'name':'dose_recompute','parameters':original}}
    projected=project_timepoint_schemas([schema],runtime.scope)[0]['function']['parameters']
    assert 'expected_observation_revision_id' not in projected['properties']
    assert 'expected_observation_revision_id' in original['properties']
    assert 'source_set' in projected['properties']
    runtime.close()
