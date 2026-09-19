from test_workspace_auth import _app, _register


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
