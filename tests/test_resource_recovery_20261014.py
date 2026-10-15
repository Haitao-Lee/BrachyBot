"""Real persistence/array recovery regressions; no clinical model substitutes."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from web import timepoint_hydration as hydration
from web.workspace_store import WorkspaceStore, _decode_artifacts, _restore_json
from web.timepoints import TimepointIntegrityError


def case(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path/'archive'))
    store=WorkspaceStore(tmp_path/'runtime')
    uid=store.create_user('recovery_test_owner','synthetic-hash')['id']
    sid=store.create_session(uid,'Synthetic persisted case').id
    tid=store.migrate_default_timepoint(uid,sid)['default_timepoint_id']
    return store,uid,sid,tid


def test_mapped_history_does_not_charge_virtual_bytes_or_restart_polling(tmp_path,monkeypatch):
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    array=np.ones((1024,1024),dtype=np.float32)
    store.save_timepoint_results(uid,sid,tid,{'history_array':array},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    context=store.capture_timepoint_context(uid,sid,tid)
    monkeypatch.setattr(hydration,'_MAX_BYTES',1024*1024)
    first=hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context)
    assert first.ready.wait(10)
    assert first.error is None
    assert first.size<1024*1024
    assert isinstance(first.values['history_array'],np.memmap)
    assert not first.values['history_array'].flags.writeable
    second=hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context)
    assert second is first and second.ready.is_set()
    assert float(second.values['history_array'].sum())==array.size
    # A clinical publication has a different identity and cannot reuse history.
    store.save_timepoint_results(uid,sid,tid,{'marker':2},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    current=store.load_timepoint_snapshot(uid,sid,tid)
    newer=hydration.clinical_hydration(store,SimpleNamespace(),current,
        store.capture_timepoint_context(uid,sid,tid))
    assert newer is not first and newer.ready.wait(10) and newer.error is None


def test_native_image_buffers_are_not_miscounted_as_small_python_wrappers():
    import SimpleITK as sitk
    image=sitk.Image([64,64,64],sitk.sitkUInt16)
    assert hydration._weight(image)>=64**3*2


def test_large_heap_handoff_stays_available_to_next_poll(tmp_path,monkeypatch):
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    store.save_timepoint_results(uid,sid,tid,{'heap_array':np.ones(10000,dtype=np.float64)},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    context=store.capture_timepoint_context(uid,sid,tid)
    monkeypatch.setattr(hydration,'_MAX_BYTES',1024)
    first=hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context)
    assert first.ready.wait(10) and first.error is None
    assert first.values['heap_array'].shape == (10000,)
    assert first.size>1024
    assert hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context) is first


def test_missing_sidecar_reports_a_stable_error_and_retries_after_repair(tmp_path,monkeypatch):
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    store.save_timepoint_results(uid,sid,tid,{'source':np.ones((64,64),dtype=np.float32)},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    reference=snapshot['agent']['planning_results']['source']['$array']
    path=store.workspace_root(uid,sid)/reference
    moved=path.with_suffix('.test-missing');path.rename(moved)
    context=store.capture_timepoint_context(uid,sid,tid)
    first=hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context)
    assert first.ready.wait(10) and first.error is None
    with pytest.raises(FileNotFoundError) as failure:
        first.values['source']
    assert hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context) is first
    with pytest.raises(FileNotFoundError) as repeated:
        first.values['source']
    assert repeated.value is failure.value
    moved.rename(path)
    from web import resource_view
    now = resource_view.time.monotonic()
    monkeypatch.setattr(resource_view.time,'monotonic',lambda:now+6)
    retry=hydration.clinical_hydration(store,SimpleNamespace(),snapshot,context)
    assert retry is first and retry.ready.is_set() and retry.error is None
    assert retry.values['source'].shape == (64,64)


def test_manifest_cache_is_detached_and_tampering_invalidates_it(tmp_path,monkeypatch):
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    store.save_timepoint_results(uid,sid,tid,{'history':{'bins':[1,2,3]}},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    first=store.load_timepoint_snapshot(uid,sid,tid)
    first['agent']['planning_results']['history']['bins'][0]=999
    second=store.load_timepoint_snapshot(uid,sid,tid)
    assert second['agent']['planning_results']['history']['bins']==[1,2,3]
    item=store._timepoint_catalog(uid,sid)['items'][tid]
    path=store.workspace_root(uid,sid)/item['state_ref']['path']
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(TimepointIntegrityError,match='checksum'):
        store.load_timepoint_snapshot(uid,sid,tid)


def test_single_pass_decode_preserves_nested_label_keys_tuple_and_arrays(tmp_path):
    encoded={'2':{'bins':[1.,2.,3.],'points':{'$tuple':[{'-7':42},[3,4]]}},
        'unsupported':{'$unsupported':'Object'}}
    assert _decode_artifacts(encoded,tmp_path)==_restore_json(encoded)
    assert _decode_artifacts(encoded,tmp_path)[2]['bins'] is not encoded['2']['bins']


def test_resource_projection_keeps_clinical_ownership_without_reloading_chat(tmp_path,monkeypatch):
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    snapshot=store.load_timepoint_snapshot(uid,sid,tid)
    store.save_timepoint_results(uid,sid,tid,{'marker':{'value':7}},
        expected_clinical_revision=snapshot['timepoint_clinical_revision'])
    def unexpected(*args,**kwargs):
        raise AssertionError('Resource projection reread shared attachment history')
    monkeypatch.setattr(store,'load_snapshot',unexpected)
    projected=store.load_timepoint_snapshot(uid,sid,tid,include_shared=False)
    assert projected['agent']['planning_results']['marker']['value']==7
    assert projected['timepoint_id']==tid and projected['session_id']==sid
    assert 'chat' not in projected


def test_storage_default_migration_preserves_custom_accounts(tmp_path,monkeypatch):
    monkeypatch.delenv('BRACHYBOT_USER_STORAGE_QUOTA_BYTES',raising=False)
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    custom=store.create_user('custom_recovery_owner','synthetic-hash')['id']
    with store._connection() as connection,connection:
        connection.execute('update users set storage_quota_bytes=? where id=?',(40*1024**3,uid))
        connection.execute('update users set storage_quota_bytes=? where id=?',(15*1024**3,custom))
    restarted=WorkspaceStore(store.runtime_dir)
    assert restarted.get_user_by_id(uid)['storage_quota_bytes']==160*1024**3
    assert restarted.get_user_by_id(custom)['storage_quota_bytes']==15*1024**3
    assert restarted.get_session(uid,sid).id==sid


def test_storage_environment_policy_is_not_overridden(tmp_path,monkeypatch):
    store,uid,sid,tid=case(tmp_path,monkeypatch)
    with store._connection() as connection,connection:
        connection.execute('update users set storage_quota_bytes=? where id=?',(40*1024**3,uid))
    monkeypatch.setenv('BRACHYBOT_USER_STORAGE_QUOTA_BYTES',str(40*1024**3))
    restarted=WorkspaceStore(store.runtime_dir)
    assert restarted.get_user_by_id(uid)['storage_quota_bytes']==40*1024**3


def test_bundle_unicode_preserves_truncated_browser_code_units_and_canonical_bytes():
    import json
    from web.timepoint_bundle import _encoded, _json
    value = {'text': '中文 🧠', 'truncated': 'label\ud83d'}
    assert _json(_encoded(value)) == value
    valid = {'text': '中文 🧠'}
    assert _encoded(valid) == json.dumps(valid, ensure_ascii=False, sort_keys=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')


def test_frontend_resource_transaction_boundaries():
    import os, shutil, subprocess
    from pathlib import Path
    node=os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    result=subprocess.run([node,str(Path(__file__).with_name('resource-recovery.test.cjs'))],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0, result.stdout+result.stderr
