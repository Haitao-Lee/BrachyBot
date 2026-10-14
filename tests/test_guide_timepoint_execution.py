"""Actual native guide tool on a nondefault owned phantom acquisition."""
from types import SimpleNamespace
import numpy as np
import SimpleITK as sitk
import pytest
from agent_runtime.core import AgentMemory
from tool_factory.surgical_guide import SurgicalGuideTool
from web.timepoint_chat import ScopedChatRuntime, capture_chat_scope
from web.timepoints import TimepointConflict
from web.workspace_store import WorkspaceStore


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    store=WorkspaceStore(tmp_path/'runtime')
    owner=store.create_user('guide_scope_fixture','synthetic-test-hash')['id']
    sid=store.create_session(owner,'Declared phantom, not a patient').id
    catalog=store.migrate_default_timepoint(owner,sid)
    first=catalog['default_timepoint_id']
    second=store.create_timepoint(owner,sid,'Owned guide acquisition',expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    root=SimpleNamespace(memory=AgentMemory(sid),_workspace_store=store,
        config={'_workspace_owner_id':owner,'_workspace_session_id':sid,
            '_workspace_root':str(store.workspace_root(owner,sid))})
    root.memory.store('surgical_guide',{'must_not_read':'shared_control_placeholder'})
    return store,owner,sid,first,second,root


def view(owned):
    store,owner,sid,_,second,root=owned
    return ScopedChatRuntime(root,capture_chat_scope(store,owner,sid,second))


def test_owned_nondefault_status_uses_captured_owner_when_target_is_omitted(owned):
    runtime=view(owned)
    runtime._waiter(True)
    result=SurgicalGuideTool(runtime.view).execute(action='status')
    assert result.success,result.error
    assert result.metadata['execution_scope']['timepoint_id'] == owned[4]
    assert result.metadata['execution_scope']['execution_scope'] == 'captured_timepoint'
    assert result.metadata['guide_status']['state'] == 'not_generated'
    assert owned[-1].memory.retrieve('surgical_guide') == {'must_not_read':'shared_control_placeholder'}
    runtime.close()


def test_guide_scope_refuses_an_explicit_sibling_and_changed_source_context(owned):
    store,owner,sid,first,second,_=owned
    runtime=view(owned)
    rejected=SurgicalGuideTool(runtime.view).execute(action='status',timepoint_id=first)
    assert not rejected.success
    current=store.load_timepoint_snapshot(owner,sid,second)
    store.save_timepoint_results(owner,sid,second,{'changed_input':True},
        expected_clinical_revision=current['timepoint_clinical_revision'])
    with pytest.raises(TimepointConflict):
        SurgicalGuideTool._execution_scope(runtime.view,{},mutating=True)
    runtime.close()


def test_real_generation_publication_and_cold_status_do_not_write_the_default(owned):
    store,owner,sid,first,second,root=owned
    zz,yy,xx=np.indices((64,64,64))
    ct=np.where((xx-32)**2+(yy-32)**2+(zz-32)**2<=22**2,40,-1000).astype(np.int16)
    image=sitk.GetImageFromArray(ct)
    snapshot=store.load_timepoint_snapshot(owner,sid,second)
    store.save_timepoint_results(owner,sid,second,{'ct_image':image,'ct_data':ct,
        'ct_spacing':image.GetSpacing(),'ct_origin':image.GetOrigin(),'ct_direction':image.GetDirection(),
        'algorithm_plan_snapshot':{'needles':[{'id':'phantom-needle','trajectory_id':'phantom-path',
            'points':[[32.,32.,32.],[-10.,32.,32.]]}],
            'seeds':[{'id':'phantom-seed','trajectory_id':'phantom-path','position':[28.,32.,32.]}]}},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    before=store.load_timepoint_snapshot(owner,sid,first)
    runtime=view(owned);runtime._waiter(True);runtime.before_tool()
    result=SurgicalGuideTool(runtime.view).execute(action='generate',parameters={'geometry_resolution_mm':1.})
    assert result.success,result.error
    saved_result=runtime.commit_tool(result)
    assert saved_result.success
    saved=store.load_timepoint_snapshot(owner,sid,second,decode_arrays=True)['agent']['planning_results']
    assert len(saved['surgical_guide']['vertices'])>0 and len(saved['surgical_guide']['faces'])>0
    assert saved['surgical_guide']['auxiliary_holes']['density_profile'] == 'continuation_dense_v1'
    assert saved['surgical_guide']['auxiliary_holes']['ring_count'] == 4
    assert store.load_timepoint_snapshot(owner,sid,first)['timepoint_clinical_revision'] == before['timepoint_clinical_revision']
    assert store.load_timepoint_snapshot(owner,sid,first)['agent']['planning_results'] == before['agent']['planning_results']
    assert root.memory.retrieve('surgical_guide') == {'must_not_read':'shared_control_placeholder'}
    runtime.close()
    cold=view(owned);cold._waiter(True)
    status=SurgicalGuideTool(cold.view).execute(action='status')
    assert status.success and status.metadata['guide_status']['persisted'] is True
    assert status.metadata['guide_status']['version'] == saved['surgical_guide']['version']
    cold.close()
