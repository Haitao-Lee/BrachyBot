"""Independent durable products must not wait for unrelated artifact I/O."""
from concurrent.futures import ThreadPoolExecutor
import threading
import numpy as np
import pytest
from web.resource_view import HydratedResults, RequestResults


def test_slow_history_does_not_block_current_masks_or_geometry(tmp_path, monkeypatch):
    from web import workspace_store
    np.save(tmp_path/'current.npy', np.arange(8))
    real = workspace_store._decode_artifacts
    started, release = threading.Event(), threading.Event()
    def decode(value, root):
        if value == 'slow historical plan':
            started.set()
            assert release.wait(5)
        return real(value, root)
    monkeypatch.setattr(workspace_store, '_decode_artifacts', decode)
    source = HydratedResults({'planning_run:old': 'slow historical plan',
        'ctv_array': {'$array':'current.npy'}, 'needles': {'points': [1,2,3]}}, tmp_path)
    first, second = RequestResults(source), RequestResults(source)
    assert source.loaded == {}  # Constructing a request cannot decode history.
    with ThreadPoolExecutor(2) as pool:
        history = pool.submit(lambda: first['planning_run:old'])
        assert started.wait(2)
        try:
            assert pool.submit(lambda: int(second['ctv_array'].sum())).result(1) == 28
            assert second['needles']['points'] == [1,2,3]
            assert not history.done()
        finally:
            release.set()
        assert history.result(1) == 'slow historical plan'


def test_artifact_failure_is_local_stable_and_recovers_without_clearing_others(tmp_path, monkeypatch):
    from web import resource_view
    now = [100.]
    monkeypatch.setattr(resource_view.time, 'monotonic', lambda: now[0])
    np.save(tmp_path/'mask.npy', np.ones(8))
    source = HydratedResults({'ctv': {'$array':'mask.npy'},
        'guide': {'$array':'missing.npy'}}, tmp_path)
    mask = source['ctv']
    with pytest.raises(FileNotFoundError) as first:
        source['guide']
    np.save(tmp_path/'missing.npy', np.arange(3))
    with pytest.raises(FileNotFoundError) as second:
        source['guide']
    assert first.value is second.value
    assert source['ctv'] is mask
    now[0] += 6
    assert source['guide'].tolist() == [0,1,2]
    assert source['ctv'] is mask


def test_lazy_handoff_keeps_request_containers_and_mutation_baselines_independent(tmp_path):
    np.save(tmp_path/'mask.npy', np.ones(8))
    source = HydratedResults({'mask': {'$array':'mask.npy'},
        'geometry': {'points':[1,2]}, 'unread': {'nested':[8]}}, tmp_path)
    a, b = RequestResults(source), RequestResults(source)
    token = a.baseline['geometry']
    a['geometry']['points'].append(3)
    assert a.baseline['geometry'] == token
    assert b['geometry'] == {'points':[1,2]}
    assert 'unread' not in source.loaded
    with pytest.raises(ValueError):
        a['mask'][0] = 0
    del a['geometry']
    assert 'geometry' not in a and 'geometry' in b


def test_guide_projection_does_not_decode_the_same_plans_unrelated_dose(tmp_path):
    np.save(tmp_path/'mesh.npy', np.arange(9).reshape(3,3))
    source = HydratedResults({'planning_run:p13': {
        'surgical_guide':{'mesh':{'$array':'mesh.npy'},'version':1},
        'dose':{'$array':'unrelated-missing-dose.npy'}}}, tmp_path)
    results = RequestResults(source)
    first = results.project('planning_run:p13', ('surgical_guide','surgical_guide_versions'))
    assert first['surgical_guide']['version'] == 1
    assert first['surgical_guide']['mesh'].shape == (3,3)
    assert 'planning_run:p13' not in source.loaded
    assert not results.owned
    first['surgical_guide']['version'] = 2
    assert results.project('planning_run:p13',('surgical_guide',))['surgical_guide']['version'] == 1


def test_large_verified_manifest_is_not_reparsed_or_reweighed_on_each_resource_poll(tmp_path, monkeypatch):
    from web.workspace_store import WorkspaceStore
    from web import timepoint_hydration
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path/'archive'))
    store = WorkspaceStore(tmp_path/'runtime')
    uid = store.create_user('progressive_test', 'synthetic-hash')['id']
    sid = store.create_session(uid, 'Synthetic case').id
    catalog = store.list_timepoints(uid,sid)
    tid = store.create_timepoint(uid,sid,'Case',expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    store.save_timepoint_results(uid,sid,tid,{'marker':1},expected_clinical_revision=0)
    item = store._timepoint_catalog(uid,sid)['items'][tid]
    calls = []
    monkeypatch.setattr(timepoint_hydration, '_weight', lambda value: calls.append(1) or 256*1024**2)
    from collections import OrderedDict
    store._timepoint_manifest_cache = OrderedDict()
    for _ in range(3):
        store._read_timepoint_state(uid,sid,item,image_metadata=True)
    assert len(calls) == 1
    assert len(store._timepoint_manifest_cache) == 1


def test_browser_shell_preserves_identity_visibility_and_inputs_without_historical_payloads():
    from web.timepoints import browser_resource_snapshot
    results = {'ct_path':'owned/input.nii', 'ctv_array':{'$array':'owned/ctv.npy'},
        'active_planning_id':'p13', 'planning_runs':[{'planning_id':'p13','status':'completed'}],
        'planning_run:p12':{'dose':list(range(10000))}, 'manual_artifact_status':{'dose':'ready'}}
    source = {'session_id':'case', 'timepoint_id':'preop', 'timepoint_clinical_revision':4,
        'agent':{'planning_results':RequestResults(results), 'ui_state':{'data_tree':{'seeds':{'visible':False}}}},
        'ui':{'state':{'viewer':{'labelImage':{'3d':{'visible':False}}}}, 'bridge':{'huge':[1]}},
        'report':{'form':{'saved':'report'}}}
    shell = browser_resource_snapshot(source)
    assert shell['timepoint_clinical_revision'] == 4
    assert shell['agent']['planning_results']['active_planning_id'] == 'p13'
    assert shell['agent']['planning_results']['ct_path'] == 'owned/input.nii'
    assert shell['agent']['planning_results']['planning_runs'] == results['planning_runs']
    assert shell['agent']['planning_results']['planning_run:p12'] == {'$available':True}
    assert not source['agent']['planning_results'].owned
    assert shell['agent']['ui_state']['data_tree']['seeds']['visible'] is False
    assert shell['ui']['state']['viewer']['labelImage']['3d']['visible'] is False
    assert 'bridge' not in shell['ui']
    assert shell['report'] == source['report']
