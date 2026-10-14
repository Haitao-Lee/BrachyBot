"""Persistent archive identity, real archive/cold restore and mount safeguards."""
import json
import os

import numpy as np
import pytest

from web.workspace_store import WorkspaceStore, WorkspaceError, _archive_storage_config


@pytest.fixture(autouse=True)
def clean_archive_environment(monkeypatch):
    monkeypatch.delenv('BRACHYBOT_ARCHIVE_ROOT', raising=False)
    monkeypatch.delenv('BRACHYBOT_ARCHIVE_MOUNTPOINT', raising=False)
    if os.name == 'nt':
        monkeypatch.setattr(WorkspaceStore, '_fsync_directory', staticmethod(lambda path: None))


def config(runtime, archive, **extra):
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'storage-config.json').write_text(json.dumps({
        'schema_version': 1, 'archive_root': str(archive), **extra}), encoding='utf-8')


def test_real_archive_restores_after_environment_removed_and_restart(tmp_path, monkeypatch):
    runtime, archive = tmp_path / 'runtime', tmp_path / 'nas-archive'
    config(runtime, archive)
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(archive))
    store = WorkspaceStore(runtime)
    owner = store.create_user('archive_restart_owner', 'synthetic_hash')['id']
    sid = store.create_session(owner, 'Synthetic archive restart').id
    values = np.arange(240, dtype=np.float32).reshape(4, 6, 10)
    catalog = store.list_timepoints(owner, sid)
    tid = store.create_timepoint(owner, sid, 'Synthetic follow-up',
        expected_revision=catalog['catalog_revision'])['created_timepoint_id']
    store.save_timepoint_results(owner, sid, tid, {'ct_data': values}, expected_state_revision=0)
    store.save_snapshot_patch(owner, sid, {'ui': {'state': {'activePanel': 'viewers'}}})
    record = store.archive_session(owner, sid)
    assert record.storage_status == 'archived'
    assert not store.workspace_root(owner, sid).exists()
    assert (store.archived_workspace_root(owner, sid) / 'snapshot.json').is_file()
    monkeypatch.delenv('BRACHYBOT_ARCHIVE_ROOT')
    cold = WorkspaceStore(runtime)
    assert cold.archive_root == archive.resolve()
    restored = cold.restore_archived_session(owner, sid)
    assert restored.storage_status == 'active' and restored.id == sid
    loaded = cold.load_snapshot(owner, sid)
    assert np.array_equal(cold.load_timepoint_snapshot(owner, sid, tid, decode_arrays=True)['agent']['planning_results']['ct_data'], values)
    assert loaded['ui']['state']['activePanel'] == 'viewers'


def test_runtime_configs_do_not_share_archive_between_deployments(tmp_path):
    lan, public = tmp_path / 'lan', tmp_path / 'public'
    config(lan, tmp_path / 'lan-archive')
    config(public, tmp_path / 'public-archive')
    assert WorkspaceStore(lan).archive_root != WorkspaceStore(public).archive_root


def test_explicit_test_override_wins_without_inheriting_other_mount(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    config(runtime, tmp_path / 'nas' / 'archive', archive_mountpoint=str(tmp_path / 'nas'))
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'test-archive'))
    store = WorkspaceStore(runtime)
    assert store.archive_root == (tmp_path / 'test-archive').resolve()
    assert store.archive_required_mountpoint is None and store.archive_available


@pytest.mark.parametrize('data', [
    {'schema_version': 99, 'archive_root': '/missing'},
    {'schema_version': 1, 'archive_root': ''},
    {'schema_version': 1, 'archive_root': 'relative-archive'},
    {'schema_version': 1, 'archive_root': 123},
    {'schema_version': 1, 'archive_root': '/archive', 'unknown': True},
    {'schema_version': 1, 'archive_root': '/archive', 'archive_mountpoint': '/other'},
    [],
])
def test_bad_persistent_config_never_silently_falls_back(tmp_path, data):
    (tmp_path / 'storage-config.json').write_text(json.dumps(data))
    with pytest.raises(WorkspaceError, match='no fallback'):
        _archive_storage_config(tmp_path)


def test_empty_environment_is_not_an_archive_location(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', '')
    with pytest.raises(WorkspaceError, match='empty'):
        _archive_storage_config(tmp_path)


def test_unmounted_nas_does_not_create_archive_in_mount_stub(tmp_path, monkeypatch):
    runtime, mount = tmp_path / 'runtime', tmp_path / 'unmounted-nas'
    config(runtime, mount / 'archive', archive_mountpoint=str(mount))
    store = WorkspaceStore(runtime)
    assert not store.archive_available
    assert not (mount / 'archive').exists()


def test_mount_lost_after_start_is_rechecked_before_restore_path(tmp_path, monkeypatch):
    runtime, mount = tmp_path / 'runtime', tmp_path / 'test-nas'
    config(runtime, mount / 'archive', archive_mountpoint=str(mount))
    monkeypatch.setattr(os.path, 'ismount', lambda path: True)
    store = WorkspaceStore(runtime)
    owner = store.create_user('mount_check_owner', 'synthetic_hash')['id']
    sid = store.create_session(owner, 'Synthetic mount probe').id
    monkeypatch.setattr(os.path, 'ismount', lambda path: False)
    with pytest.raises(WorkspaceError, match='unavailable'):
        store.archived_workspace_root(owner, sid)


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_real_activation_route_reports_mount_unavailable_without_data_loss(tmp_path, monkeypatch, language):
    from web.server import create_app
    runtime, mount = tmp_path / 'runtime', tmp_path / 'test-nas'
    config(runtime, mount / 'archive', archive_mountpoint=str(mount))
    monkeypatch.setattr(os.path, 'ismount', lambda path: True)
    app = create_app({'runtime_dir': str(runtime), 'secret_key': 'synthetic-storage-secret',
                      'workspace_maintenance': False})
    client = app.test_client()
    auth = client.post('/api/auth/register', json={
        'username': 'storage_route_owner', 'password': 'synthetic test passphrase'}).get_json()
    store = getattr(app.extensions['brachybot_workspace_store'], 'raw', app.extensions['brachybot_workspace_store'])
    owner = auth['user']['id']
    sid = store.create_session(owner, 'Synthetic archived route').id
    store.archive_session(owner, sid)
    snapshot = store.archived_workspace_root(owner, sid) / 'snapshot.json'
    before = snapshot.read_bytes()
    monkeypatch.setattr(os.path, 'ismount', lambda path: False)
    result = client.post(f'/api/sessions/{sid}/activate', headers={
        'X-CSRF-Token': auth['csrf_token'], 'X-BrachyBot-Language': language})
    assert result.status_code == 503
    packet = result.get_json()
    assert packet['code'] == 'archive_storage_unavailable' and packet['language'] == language
    assert str(mount) not in packet['error']
    assert ('暂时不可用' if language == 'zh' else 'temporarily unavailable') in packet['error']
    assert snapshot.read_bytes() == before
    assert store.get_session(owner, sid).storage_status == 'archived'
    assert not store.workspace_root(owner, sid).exists()
