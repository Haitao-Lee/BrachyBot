"""Presentation ordering must not fence against unrelated storage publications."""
import pytest
from web.workspace_store import WorkspaceStore
from web.timepoints import TimepointConflict


def test_ui_merge_uses_clinical_readset_and_order_without_invalidating_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    owner = store.create_user('presentation_owner', 'synthetic-hash')['id']
    sid = store.create_session(owner, 'Synthetic presentation case').id
    tid = store.migrate_default_timepoint(owner, sid)['default_timepoint_id']
    saved = store.load_timepoint_snapshot(owner, sid, tid)
    context = store.capture_timepoint_context(owner, sid, tid)
    fields = dict(expected_state_revision=saved['timepoint_state_revision'],
        expected_clinical_revision=saved['timepoint_clinical_revision'],
        expected_lifecycle_revision=saved['timepoint']['lifecycle_revision'],
        presentation_source='browser-test', presentation_sequence=2)
    # A separate server bridge checkpoint advances storage only.
    store.save_timepoint_patch(owner,sid,tid,{'ui':{'bridge':{'state_seq':1}}},
        expected_state_revision=saved['timepoint_state_revision'])
    patch = {'ui':{'state':{'viewer':{'labelColor':'#22d3ee'}}}}
    current = store.save_timepoint_patch(owner,sid,tid,patch,**fields)
    assert current['ui']['bridge']['state_seq'] == 1
    assert current['ui']['state']['viewer']['labelColor'] == '#22d3ee'
    assert current['timepoint_clinical_revision'] == saved['timepoint_clinical_revision']
    context.assert_current(owner,sid,store._timepoint_catalog(owner,sid),legacy_revision=store.get_session(owner,sid).revision)
    duplicate = store.save_timepoint_patch(owner,sid,tid,patch,**fields)
    assert duplicate['timepoint_state_revision'] == current['timepoint_state_revision']
    with pytest.raises(TimepointConflict):
        store.save_timepoint_patch(owner,sid,tid,{'ui':{'state':{'viewer':{'labelColor':'#ffffff'}}}},
            **{**fields,'presentation_sequence':1})
    store.save_timepoint_results(owner,sid,tid,{'changed_clinical_input':True},
        expected_clinical_revision=current['timepoint_clinical_revision'])
    with pytest.raises(TimepointConflict):
        store.save_timepoint_patch(owner,sid,tid,patch,**{**fields,'presentation_sequence':3})


def test_identical_clinical_checkpoint_does_not_invalidate_captured_source(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    owner = store.create_user('noop_owner', 'synthetic-hash')['id']
    sid = store.create_session(owner, 'Synthetic no-op case').id
    tid = store.migrate_default_timepoint(owner, sid)['default_timepoint_id']
    state = store.load_timepoint_snapshot(owner,sid,tid)
    state = store.save_timepoint_results(owner,sid,tid,{'clinical_value':17},
        expected_clinical_revision=state['timepoint_clinical_revision'])
    context = store.capture_timepoint_context(owner,sid,tid)
    for updates,removals in [({},()), ({'clinical_value':17},()), ({},('already_absent_legacy_key',))]:
        saved = store.save_timepoint_results(owner,sid,tid,updates,removals=removals,
            expected_clinical_revision=state['timepoint_clinical_revision'],execution_context=context)
        assert saved['timepoint_state_revision'] == state['timepoint_state_revision']
        assert saved['timepoint_clinical_revision'] == state['timepoint_clinical_revision']
    store.save_timepoint_results(owner,sid,tid,{'clinical_value':18},
        expected_clinical_revision=state['timepoint_clinical_revision'])
    with pytest.raises(TimepointConflict):
        store.save_timepoint_results(owner,sid,tid,{},expected_clinical_revision=state['timepoint_clinical_revision'])


def test_restore_profile_does_not_duplicate_agent_capability_catalog():
    from web.timepoints import compact_restore_presentation
    catalog = [{'target':'viewer.angle','usage':'verified native measurement gestures'}]
    source = {'state':{'ui_operation_catalog':catalog,'viewer':{'window':630}},
        'bridge':{'state':{'ui_operation_catalog':catalog,'viewer':{'window':630}}}}
    compact = compact_restore_presentation(source)
    assert compact['state'] == {'viewer':{'window':630}}
    assert compact['bridge']['state']['ui_operation_catalog'] == catalog
    assert source['state']['ui_operation_catalog'] == catalog
