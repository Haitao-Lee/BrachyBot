from types import SimpleNamespace

from web.export_service import ExportService
from web.resource_view import HydratedResults, RequestResults
from web.planning_runs import current_planning_context
from web.timepoints import _project_snapshot
from test_data_tree_export_system import _case


def test_artifact_catalog_matches_full_catalog_without_reading_clinical_results(tmp_path):
    store, user, session, agent = _case(tmp_path)
    service = ExportService(store)
    wanted = {'report_data', 'report', 'report_figure', 'screenshot'}
    full = service.public_catalog(user['id'], session.id, agent)
    expected = [row for row in full['objects'] if row['data_type'] in wanted]
    original = agent.memory.retrieve
    allowed = {'planning_id', 'manual_planning_id', 'planning_version', 'manual_plan_version'}
    def guarded(key):
        assert key in allowed, 'Artifact listing touched clinical product ' + key
        return original(key)
    agent.memory.retrieve = guarded
    actual = service.public_catalog(user['id'], session.id, agent, artifacts_only=True)
    assert actual['objects'] == expected


def test_projected_snapshot_is_detached_before_any_caller_mutation(tmp_path):
    store, user, session, _ = _case(tmp_path)
    uid, sid = user['id'], session.id
    full = store.load_snapshot(uid, sid)
    shell = store.load_snapshot(uid, sid, projection='resource_shell')
    assert shell['resource_shell']
    assert 'bridge' not in shell['ui']
    shell['agent']['planning_results']['active_planning_id'] = 'foreign'
    shell['chat']['messages'].append({'role': 'user', 'content': 'private mutation'})
    assert store.load_snapshot(uid, sid) == full
    artifacts = store.load_snapshot(uid, sid, projection='artifacts')
    assert set(artifacts['chat']) == {'attachments', 'messages'}
    assert all(set(row) == {'attachments'} for row in artifacts['chat']['messages'])


def test_compact_planning_read_keeps_active_owner_without_loading_dose(tmp_path):
    source = HydratedResults({
        'active_planning_id': 'new', 'planning_id': 'old',
        'planning_runs': [{'planning_id': 'new', 'status': 'completed'}],
        'dose_metrics': {'d90': 999},
        'planning_run:new': {'dose_distribution_gy': {'$array': 'unavailable.npy'},
            'dose_metrics': {'d90': 123}, 'total_seeds': 10, 'num_trajectories': 2},
    }, tmp_path)
    memory = SimpleNamespace(planning_results=RequestResults(source))
    memory.retrieve = lambda key: memory.planning_results.get(key)
    result = current_planning_context(memory)
    assert result['planning_id'] == 'new'
    assert result['metrics']['d90'] == 123
    assert result['total_seeds'] == 10 and result['num_trajectories'] == 2
    assert 'planning_run:new' not in source.loaded
    assert 'dose_distribution_gy' not in source.fragments['planning_run:new'].loaded


def test_artifact_projection_retains_attachment_registry_and_legacy_message_fallback():
    from web.artifact_catalog import screenshot_attachment_index
    capture = {'id': 'c', 'session_id': 'case', 'planning_id': 'p1',
               'url': '/api/sessions/case/screenshots/c.png'}
    snapshot = {'agent': {'planning_results': {'planning_run:p1': {'huge': [1, 2]}}},
                'chat': {'execution_trace': [1, 2], 'messages': [
                    {'content': 'not needed', 'attachments': [capture]}]}}
    projected = _project_snapshot(snapshot, 'artifacts')
    assert screenshot_attachment_index(projected, 'case') == screenshot_attachment_index(snapshot, 'case')
    assert projected['agent']['planning_results']['planning_run:p1'] == {}
    assert 'execution_trace' not in projected['chat']


def test_first_manifest_reader_cannot_mutate_the_cached_resource_handoff(tmp_path):
    store, user, session, _ = _case(tmp_path)
    uid, sid = user['id'], session.id
    catalog = store.list_timepoints(uid, sid)
    tid = store.create_timepoint(uid, sid, 'Owned', expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    store.save_timepoint_results(uid, sid, tid, {'nested': {'points': [1, 2]}}, expected_clinical_revision=0)
    store._timepoint_manifest_cache.clear()
    first = store.load_timepoint_snapshot(uid, sid, tid, include_shared=False)
    first['agent']['planning_results']['nested']['points'].append(999)
    resource = store.load_timepoint_snapshot(uid, sid, tid, include_shared=False, defer_results=True)
    assert resource['agent']['planning_results']['nested']['points'] == [1, 2]


def test_session_selection_shell_keeps_owner_csrf_and_full_snapshot_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path/'archive'))
    monkeypatch.setenv('BRACHYBOT_ALLOW_SELF_REGISTRATION', '1')
    monkeypatch.delenv('BRACHYBOT_API_KEY', raising=False)
    monkeypatch.delenv('BRACHYBOT_REQUIRE_API_KEY', raising=False)
    from web.server import create_app
    app = create_app({'runtime_dir': str(tmp_path/'runtime'), 'secret_key': 'synthetic-shell',
                      'workspace_maintenance': False})
    client, other = app.test_client(), app.test_client()
    auth = client.post('/api/auth/register', json={'username': 'shell_owner', 'password': 'synthetic-password-123'}).get_json()
    foreign = other.post('/api/auth/register', json={'username': 'shell_other', 'password': 'synthetic-password-123'}).get_json()
    uid, sid = auth['user']['id'], auth['active_session_id']
    raw = getattr(app.extensions['brachybot_workspace_store'], 'raw', app.extensions['brachybot_workspace_store'])
    raw.save_agent_results_patch(uid, sid, {
        'planning_run:p1': {'dose': list(range(100))}, 'active_planning_id': 'p1'})
    raw.save_snapshot_patch(uid, sid, {
        'ui': {'state': {'viewer': {'labelImage': {'3d': {'visible': False}}}}}})
    url = '/api/sessions/'+sid+'/select'
    assert client.post(url+'?response_mode=resource_shell').status_code == 403
    assert other.post(url+'?response_mode=resource_shell', headers={'X-CSRF-Token': foreign['csrf_token']}).status_code == 404
    headers = {'X-CSRF-Token': auth['csrf_token']}
    shell = client.post(url+'?response_mode=resource_shell', headers=headers).get_json()['workspace']
    assert shell['resource_shell']
    assert shell['agent']['planning_results']['planning_run:p1'] == {'$available': True}
    assert shell['ui']['state']['viewer']['labelImage']['3d']['visible'] is False
    full = client.post(url, headers=headers).get_json()['workspace']
    assert full['agent']['planning_results']['planning_run:p1']['dose'] == list(range(100))
    catalog = raw.list_timepoints(uid, sid)
    tid = raw.create_timepoint(uid, sid, 'Explicit target', expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    raw.save_timepoint_results(uid, sid, tid, {'ct_path': 'owned.nii',
        'planning_run:history': {'dose': list(range(1000))}}, expected_clinical_revision=0)
    target = f'/api/sessions/{sid}/timepoints/{tid}/workspace'
    projected = client.get(target+'?response_mode=resource_shell').get_json()['workspace']
    assert projected['timepoint_id'] == tid and projected['resource_shell']
    assert projected['agent']['planning_results']['planning_run:history'] == {'$available': True}
    assert projected['agent']['planning_results']['ct_path'] == 'owned.nii'
    assert 'chat' not in projected and 'bridge' not in projected['ui']


def test_browser_projection_does_not_materialize_a_nested_lazy_handoff(tmp_path):
    lazy = HydratedResults({'planning_id': 'p', 'planning_run:p': {
        'dose': {'$array': 'unavailable-history.npy'}}}, tmp_path)
    snapshot = {'agent': {'planning_results': RequestResults(lazy)}}
    shell = _project_snapshot(snapshot, 'resource_shell')
    assert shell['agent']['planning_results']['planning_id'] == 'p'
    assert shell['agent']['planning_results']['planning_run:p'] == {'$available': True}
    assert _project_snapshot(snapshot, 'artifacts')['agent']['planning_results']['planning_run:p'] == {}
    assert not lazy.loaded


def test_artifact_projection_preserves_legacy_and_current_report_identity():
    from web.workspace_store import _snapshot_planning_identity
    for active in ({'planning_run_id': 'legacy'}, {'active_planning_id': 'current'}):
        snapshot = {'agent': {'planning_results': {**active, 'planning_run:history': {'dose': [1, 2]}}}}
        assert _snapshot_planning_identity(_project_snapshot(snapshot, 'artifacts')) == _snapshot_planning_identity(snapshot)
