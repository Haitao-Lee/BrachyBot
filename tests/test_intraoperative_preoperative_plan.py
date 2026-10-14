"""Owned preoperative-plan prerequisite, not a phrase/count-match rule."""
from types import SimpleNamespace

from agent_runtime.core import AgentMemory
from web.workspace_store import WorkspaceStore
from web.intraoperative_workflow import associated_preoperative_plan_exists,ensure_intraoperative_baseline


def test_empty_linked_workspace_is_not_a_preoperative_plan(tmp_path,monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    store=WorkspaceStore(tmp_path/'runtime')
    owner=store.create_user('preoperative_plan_owner','synthetic-hash')['id']
    sid=store.create_session(owner,'Synthetic source-prerequisite case').id
    source=store.migrate_default_timepoint(owner,sid)['default_timepoint_id']
    target=store.create_timepoint(owner,sid,'Synthetic intraoperative',stage='intraoperative',
        preoperative_timepoint_id=source,expected_revision=store.list_timepoints(owner,sid)['catalog_revision'])['created_timepoint_id']
    captured=store.capture_timepoint_context(owner,sid,target)
    agent=SimpleNamespace(_workspace_store=store,_workspace_timepoint_context=captured,memory=AgentMemory(sid))
    agent.memory.user_lang='zh'
    assert associated_preoperative_plan_exists(agent,captured) is False
    blocked=ensure_intraoperative_baseline(agent)
    assert not blocked.success and blocked.metadata['code']=='continuation_preoperative_plan_required'
    assert '关联的术前时间点' in blocked.message
    assert blocked.metadata['downstream_actions_executed']==[]
    state=store.load_timepoint_snapshot(owner,sid,source)
    store.save_timepoint_results(owner,sid,source,{'total_seeds':12},expected_clinical_revision=state['timepoint_clinical_revision'])
    assert associated_preoperative_plan_exists(agent,captured) is False
    state=store.load_timepoint_snapshot(owner,sid,source)
    # Explicitly declared software fixture geometry, not a mock algorithm result.
    store.save_timepoint_results(owner,sid,source,{'seed_plan_serialized':{'seeds':[
        {'id':'synthetic_preoperative_source','position':[1.,2.,3.],'direction':[0.,0.,1.]}]}},
        expected_clinical_revision=state['timepoint_clinical_revision'])
    assert associated_preoperative_plan_exists(agent,captured) is True
    assert not store.load_timepoint_snapshot(owner,sid,target)['agent']['planning_results']
