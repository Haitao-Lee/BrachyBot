import numpy as np
import pytest
from web.resource_view import RequestResults
from web.timepoint_chat import _detached, _state_token


def test_unread_history_is_not_detached_or_fingerprinted_and_nested_edits_are_isolated():
    source = {'history': [{'huge': list(range(10000))}], 'current': {'positions': [1, 2]}}
    a, b = RequestResults(source), RequestResults(source)
    assert a['current'] == source['current']
    assert set(a.owned) == {'current'}
    assert set(a.baseline.tokens) == {'current'}
    before = a.baseline['current']
    a['current']['positions'][0] = 77
    assert _state_token(a['current']) != before
    assert source['current']['positions'] == [1, 2]
    assert b['current']['positions'] == [1, 2]
    assert 'history' not in a.owned


def test_replacement_deletion_addition_and_exact_checkpoint_changes():
    source = {'a': {'x': [1]}, 'drop': [2], 'untouched': {'v': 3}}
    results = RequestResults(source)
    baseline = results.baseline
    results['a'] = {'x': [9]}
    del results['drop']
    results['new'] = [7]
    updates = {k: v for k, v in results.items() if k not in baseline or _state_token(v) != baseline[k]}
    assert updates == {'a': {'x': [9]}, 'new': [7]}
    assert set(source) - set(results) == {'drop'}
    assert source == {'a': {'x': [1]}, 'drop': [2], 'untouched': {'v': 3}}


def test_array_views_are_read_only_and_mapping_export_has_owned_containers():
    source = {'array': np.arange(8), 'nested': {'list': [1]}}
    results = RequestResults(source)
    assert np.shares_memory(results['array'], source['array'])
    with pytest.raises(ValueError):
        results['array'][0] = 3
    exported = _detached(results)
    exported['nested']['list'].append(2)
    assert results['nested']['list'] == [1]
    assert source['nested']['list'] == [1]
    assert not exported['array'].flags.writeable


def test_delete_then_reinsert_and_baseline_rebase():
    results = RequestResults({'x': [1]})
    before = results.baseline['x']
    del results['x']
    results['x'] = [4]
    assert results.baseline['x'] == before
    results.baseline['x'] = _state_token(results['x'])
    assert results.baseline['x'] == _state_token(results['x'])
    results.baseline.pop('x')
    assert 'x' not in results.baseline


def test_pending_metadata_is_demand_decoded_and_never_exposes_array_placeholders():
    original = {'ct_data': {'$array': 'owned.npy'}, 'shape': {'$tuple': [1, 2, 3]},
                'history': [{'nested': list(range(10000))}]}
    results = RequestResults(original, metadata_only=True)
    assert results['ct_data'] is None
    assert results['shape'] == (1, 2, 3)
    assert set(results.owned) == {'ct_data', 'shape'}
    assert 'history' not in results.baseline.tokens


@pytest.mark.parametrize('endpoint', ['/api/viewer/volume', '/api/viewer/label_volume', '/api/viewer/3d_skin', '/api/planning/seeds_3d'])
def test_resource_read_retries_agent_construction_race(endpoint, monkeypatch):
    from flask import Flask
    from web.routes import viewer_routes
    monkeypatch.setattr(viewer_routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(viewer_routes, 'rate_limit', lambda f: f)
    app = Flask(__name__)
    viewer_routes.register_viewer_routes(app, lambda *args, **kwargs: None, None, None)
    response = (app.test_client().post(endpoint, json={}) if endpoint.endswith('3d_skin')
                else app.test_client().get(endpoint))
    assert response.status_code == 202
    assert response.get_json()['pending'] is True
    assert response.get_json()['code'] == 'workspace_agent_initializing'


def test_cached_resource_manifest_has_detached_presentation_and_demand_clinical_values():
    from web.timepoints import _resource_snapshot
    original = {'agent': {'planning_results': {'history': [{'seed': [1]}]}},
                'ui': {'tree': [1]}, 'report': {'text': ['saved']}}
    a, b = _resource_snapshot(original), _resource_snapshot(original)
    assert not a['agent']['planning_results'].owned
    a['ui']['tree'].append(2)
    a['agent']['planning_results']['history'][0]['seed'].append(2)
    assert original['ui']['tree'] == [1]
    assert b['ui']['tree'] == [1]
    assert b['agent']['planning_results']['history'][0]['seed'] == [1]


def test_resource_only_snapshot_omits_presentation_without_modifying_original():
    from web.timepoints import _resource_snapshot
    original = {'agent': {'planning_results': {'ct_shape': [3, 4, 5]},
                          'ui_state': {'tree': [1]}, 'patient_data': {'id': 2}},
                'ui': {'tree': [1]}, 'report': {'text': ['saved']},
                'image_presentations': {'a': [2]}, 'image_collection': {'images': []}}
    resource = _resource_snapshot(original, resource_only=True)
    assert not {'ui', 'report', 'image_presentations'} & resource.keys()
    assert 'ui_state' not in resource['agent']
    assert resource['agent']['planning_results']['ct_shape'] == [3, 4, 5]
    resource['agent']['patient_data']['id'] = 8
    assert original['agent']['patient_data']['id'] == 2
    assert original['report']['text'] == ['saved']


def test_manifest_projection_cache_preserves_checksum_replacement_and_writer_isolation(tmp_path, monkeypatch):
    import json, hashlib
    from web.workspace_store import WorkspaceStore
    from web.timepoints import TimepointIntegrityError
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path/'archive'))
    store = WorkspaceStore(tmp_path/'runtime')
    user = store.create_user('demand_cache_owner', 'synthetic-password-hash')['id']
    sid = store.create_session(user, 'Synthetic case').id
    catalog = store.list_timepoints(user, sid)
    tid = store.create_timepoint(user, sid, 'Source', expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    store.save_timepoint_results(user, sid, tid, {'history': [{'x': [1]}]}, expected_clinical_revision=0)
    catalog = store._timepoint_catalog(user, sid)
    item = catalog['items'][tid]
    state = store._read_timepoint_state(user, sid, item)
    state['image_collection'] = {'test_metadata': [1]}
    store._publish_timepoint_state(user, sid, catalog, item, state)
    item = store._timepoint_catalog(user, sid)['items'][tid]
    store._read_timepoint_state(user, sid, item, defer_results=True)
    projected = store._read_timepoint_state(user, sid, item, image_metadata=True)
    assert set(projected) == {'image_collection'}
    projected['image_collection']['test_metadata'].append(2)
    resource = store._read_timepoint_state(user, sid, item, defer_results=True)
    assert resource['image_collection']['test_metadata'] == [1]
    resource['agent']['planning_results']['history'][0]['x'].append(2)
    writer = store._read_timepoint_state(user, sid, item)
    assert writer['agent']['planning_results']['history'][0]['x'] == [1]
    writer['agent']['planning_results']['history'][0]['x'].append(3)
    assert store._read_timepoint_state(user, sid, item, defer_results=True)['agent']['planning_results']['history'][0]['x'] == [1]
    assert sum(entry[2] for entry in store._timepoint_manifest_cache.values()) <= 128*1024**2
    path = store.workspace_root(user, sid)/item['state_ref']['path']
    state = json.loads(path.read_bytes());state['image_collection']['test_metadata'] = [9]
    replacement = path.with_suffix('.replacement');replacement.write_text(json.dumps(state))
    replacement.replace(path)
    with pytest.raises(TimepointIntegrityError):
        store._read_timepoint_state(user, sid, item, image_metadata=True)
    item['state_ref']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert store._read_timepoint_state(user, sid, item, image_metadata=True)['image_collection']['test_metadata'] == [9]
