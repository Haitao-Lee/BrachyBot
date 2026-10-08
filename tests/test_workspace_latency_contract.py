from test_workspace_auth import _app, _register
import pytest


def test_ack_save_is_durable_and_legacy_full_response_remains(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, 'latency_user')
    headers = {'X-CSRF-Token': auth['csrf_token']}
    for mode in ('ack', 'full'):
        response = client.post('/api/workspace/state', json={
            'session_id': auth['active_session_id'], 'response_mode': mode,
            'ui': {'marker': mode},
        }, headers=headers)
        assert response.status_code == 200
        result = response.get_json()
        assert result['success']
        assert ('workspace' in result) == (mode == 'full')
        saved = client.get('/api/workspace/snapshot').get_json()['workspace']
        assert saved['ui']['marker'] == mode
        assert saved['session']['revision'] == result['revision']
    stale = client.post('/api/workspace/state', json={
        'response_mode': 'ack', 'revision': -1,
        'chat': {'messages': []},
    }, headers=headers)
    assert stale.status_code == 409


def test_patch_response_matches_fresh_load_and_cannot_mutate_cache(tmp_path):
    from web.workspace_store import WorkspaceStore
    store = WorkspaceStore(tmp_path / 'state')
    user = store.create_user('latency_owner', 'hash')
    case = store.create_session(user['id'], 'case')
    result = store.save_snapshot_patch(user['id'], case.id, {
        'ui': {'nested': {'value': [1, 2, 3]}},
        'chat': {'messages': [{'role': 'user', 'content': '中文 test'}]},
    })
    assert result == store.load_snapshot(user['id'], case.id)
    result['ui']['nested']['value'].append(4)
    assert store.load_snapshot(user['id'], case.id)['ui']['nested']['value'] == [1, 2, 3]


def test_scoped_annotation_save_preserves_every_other_section_and_empty_arrays(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, 'annotation_scope')
    headers = {'X-CSRF-Token': auth['csrf_token']}
    initial = {'session_id': auth['active_session_id'], 'ui_state': {
        'viewer': {'annotations': [{'id': 'line'}], 'masks': {'labels': {'mask': {'voxels': [[1, 2, 3]]}}}, 'settings': {'opacity': 0.4}},
        'data_tree': {'annotations': [{'id': 'line'}], 'organs': [{'id': 'cord'}]},
        'controls': {'prescription': 120},
    }, 'report': {'notes': 'keep report'}, 'chat': {'messages': [{'role': 'user', 'content': 'keep chat'}]}}
    assert client.post('/api/workspace/state', json=initial, headers=headers).status_code == 200
    before = client.get('/api/workspace/snapshot').get_json()['workspace']
    result = client.post('/api/workspace/state', json={
        'session_id': auth['active_session_id'], 'response_mode': 'ack',
        'viewer_annotations': {'annotations': [], 'data_tree_annotations': []},
    }, headers=headers)
    assert result.status_code == 200 and result.get_json()['saved_scope'] == 'viewer_annotations'
    after = client.get('/api/workspace/snapshot').get_json()['workspace']
    expected = before['ui']['state']
    expected['viewer']['annotations'] = []
    expected['data_tree']['annotations'] = []
    assert after['ui']['state'] == expected
    assert after['report'] == before['report'] and after['chat'] == before['chat']
    assert not app.extensions['test_agent_calls'], 'Saving UI must not cold-load a GPU agent'


def test_scoped_annotation_save_rejects_invalid_records_and_mixed_writes(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    auth = _register(client, 'annotation_invalid')
    headers = {'X-CSRF-Token': auth['csrf_token']}
    for annotations, tree in ((None, []), ([1], [1]), ([{}], [{}]), ([{'id': 'x'}, {'id': 'x'}], []), ([{'id': 'x'}], [{'id': 'y'}])):
        result = client.post('/api/workspace/state', json={'viewer_annotations': {
            'annotations': annotations, 'data_tree_annotations': tree,
        }}, headers=headers)
        assert result.status_code == 400
    result = client.post('/api/workspace/state', json={
        'viewer_annotations': {'annotations': [], 'data_tree_annotations': []},
        'ui_state': {'viewer': {'masks': {}}},
    }, headers=headers)
    assert result.status_code == 400


def test_scoped_save_updates_cached_memory_leaves_without_erasing_scene_state(tmp_path):
    from flask import Flask
    from types import SimpleNamespace
    from web.auth import configure_auth, register_auth_routes
    from web.routes.session_routes import register_session_routes
    from web.workspace_store import WorkspaceStore
    class Memory:
        def __init__(self):
            self.ui = {'viewer': {'annotations': [{'id': 'old'}], 'settings': {'opacity': 0.6}},
                       'data_tree': {'annotations': [{'id': 'old'}], 'organs': [{'id': 'cord'}]}, 'unrelated': True}
        def get_ui_state(self):
            return self.ui.copy()
        def set_ui_state(self, patch):
            self.ui.update(patch)
    store = WorkspaceStore(tmp_path / 'state')
    app = Flask(__name__)
    configure_auth(app, store, {'secret_key': 'test-secret'})
    register_auth_routes(app, store)
    memory = Memory()
    register_session_routes(app, store, lambda sid: pytest.fail('No cold agent hydration'),
                            lambda sid: None, get_cached_agent=lambda sid: SimpleNamespace(memory=memory))
    client = app.test_client()
    auth = _register(client, 'cached_annotations')
    result = client.post('/api/workspace/state', json={'viewer_annotations': {
        'annotations': [], 'data_tree_annotations': [],
    }}, headers={'X-CSRF-Token': auth['csrf_token']})
    assert result.status_code == 200
    assert memory.ui['viewer'] == {'annotations': [], 'settings': {'opacity': 0.6}}
    assert memory.ui['data_tree'] == {'annotations': [], 'organs': [{'id': 'cord'}]}
    assert memory.ui['unrelated'] is True
