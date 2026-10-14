"""Owned timepoint routes use authentication, CSRF, leases and typed scope."""
import pytest
from flask import Flask

from web.auth import configure_auth, register_auth_routes
from web.routes.timepoint_routes import register_timepoint_routes
from web.workspace_store import WorkspaceStore


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    # Create synthetic fixture accounts only; public registration stays closed.
    monkeypatch.setenv("BRACHYBOT_ALLOW_SELF_REGISTRATION", "1")
    app = Flask(__name__)
    store = WorkspaceStore(tmp_path / "runtime")
    configure_auth(app, store, {"secret_key": "synthetic-test-secret"})
    register_auth_routes(app, store)
    register_timepoint_routes(app, store)
    first, second = app.test_client(), app.test_client()
    a = first.post("/api/auth/register", json={"username": "tp_owner", "password": "synthetic test passphrase"}).get_json()
    b = second.post("/api/auth/register", json={"username": "tp_other", "password": "synthetic test passphrase"}).get_json()
    return app, store, first, second, a, b


def test_metadata_routes_create_link_and_restore_without_agent_load(clients):
    app, store, client, other, account, _ = clients
    sid = account["active_session_id"]
    headers = {"X-CSRF-Token": account["csrf_token"]}
    base = f"/api/sessions/{sid}/timepoints"
    initial = client.get(base).get_json()
    assert initial["capabilities"]["execution_scope"] is True
    created = client.post(base, headers=headers, json={"title": "New scan", "expected_revision": initial['catalog_revision']})
    assert created.status_code == 201
    payload = created.get_json()
    identifier = payload["created_timepoint_id"]
    renamed = client.patch(f"{base}/{identifier}", headers=headers, json={"title": "Renamed", "expected_revision": payload['catalog_revision']})
    assert renamed.status_code == 200
    workspace = client.get(f"{base}/{identifier}/workspace").get_json()["workspace"]
    assert workspace["timepoint_id"] == identifier
    saved = client.patch(f"{base}/{identifier}/workspace", headers=headers,
                         json={"expected_state_revision": 0, "patch": {"ui": {"color": "#22D3EE"}}})
    assert saved.status_code == 200
    assert saved.get_json()["workspace"]["ui"]["color"] == "#22D3EE"
    assert other.get(base).status_code == 404


def test_csrf_and_stale_catalog_guards(clients):
    _, _, client, _, account, _ = clients
    base = f"/api/sessions/{account['active_session_id']}/timepoints"
    assert client.post(base, json={"expected_revision": 0}).status_code == 403
    headers = {"X-CSRF-Token": account["csrf_token"]}
    assert client.post(base, headers=headers, json={"expected_revision": 0}).status_code == 201
    assert client.post(base, headers=headers, json={"expected_revision": 0}).status_code == 409
    assert client.post(base, headers=headers, json={"expected_revision": True}).status_code == 400


def test_conflicting_header_and_url_targets_fail_closed(clients):
    _, _, client, _, account, _ = clients
    base = f"/api/sessions/{account['active_session_id']}/timepoints"
    headers = {"X-CSRF-Token": account["csrf_token"]}
    created = client.post(base, headers=headers, json={"expected_revision": 0}).get_json()
    identifier = created["created_timepoint_id"]
    response = client.get(f"{base}/{identifier}/workspace", headers={"X-BrachyBot-Timepoint": "f" * 32})
    assert response.status_code == 400
    assert "Conflicting" in response.get_json()["error"]


def test_browser_cannot_forge_job_or_clinical_results(clients):
    _, _, client, _, account, _ = clients
    base = f"/api/sessions/{account['active_session_id']}/timepoints"
    headers = {"X-CSRF-Token": account["csrf_token"]}
    identifier = client.post(base, headers=headers, json={"expected_revision": 0}).get_json()["created_timepoint_id"]
    for section in ("agent", "chat", "operation"):
        response = client.patch(f"{base}/{identifier}/workspace", headers=headers,
                                json={"expected_state_revision": 0, "patch": {section: {}}})
        assert response.status_code == 400


def test_compact_presentation_ack_retains_canonical_state_and_security(clients):
    _, store, client, other, account, other_account = clients
    owner, sid = account['user']['id'], account['active_session_id']
    base = f'/api/sessions/{sid}/timepoints'
    headers = {'X-CSRF-Token': account['csrf_token']}
    tid = client.post(base, headers=headers, json={'expected_revision': 0}).get_json()['created_timepoint_id']
    url = f'{base}/{tid}/workspace'
    before = client.get(url).get_json()['workspace']
    body = {'expected_state_revision': before['timepoint_state_revision'],
            'response_mode': 'presentation_receipt',
            'patch': {'ui': {'state': {'viewer': {'zoom': 1.2}}}}}
    assert client.patch(url, json=body).status_code == 403
    assert other.patch(url, headers={'X-CSRF-Token': other_account['csrf_token']}, json=body).status_code == 404
    saved = client.patch(url, headers=headers, json=body)
    assert saved.status_code == 200, saved.get_json()
    packet = saved.get_json()
    assert set(packet) == {'success', 'presentation_receipt', 'presentation'}
    receipt = packet['presentation_receipt']
    assert receipt['session_id'] == sid and receipt['timepoint_id'] == tid
    assert receipt['timepoint_state_revision'] == before['timepoint_state_revision'] + 1
    assert receipt['timepoint_clinical_revision'] == before['timepoint_clinical_revision']
    canonical = client.get(url).get_json()['workspace']
    assert packet['presentation']['ui'] == canonical['ui']
    assert 'agent' not in str(packet) and 'chat' not in str(packet)
    assert len(saved.data) < 4000
    # Compact mode changes transport only: stale CAS and clinical writes fail.
    assert client.patch(url, headers=headers, json=body).status_code == 409
    forged = {**body, 'expected_state_revision': receipt['timepoint_state_revision'], 'patch': {'agent': {}}}
    assert client.patch(url, headers=headers, json=forged).status_code == 400


def test_catalog_edit_fences_metadata_not_unrelated_presentation_commits(clients):
    _, store, client, _, account, _ = clients
    owner, sid = account['user']['id'], account['active_session_id']
    url = f'/api/sessions/{sid}/timepoints'
    catalog = client.get(url).get_json()
    tid = catalog['default_timepoint_id']
    state = store.load_timepoint_snapshot(owner,sid,tid)
    store.save_timepoint_patch(owner,sid,tid,{'ui':{'state':{'opacity':.5}}},
        expected_state_revision=state['timepoint_state_revision'])
    created = client.post(url, headers={'X-CSRF-Token':account['csrf_token']}, json={
        'title':'New target after display save', 'expected_revision':catalog['catalog_revision'],
        'expected_metadata_signature':catalog['metadata_signature']})
    assert created.status_code == 201, created.get_json()
    # An intervening human metadata edit cannot be rebased using that receipt.
    current = created.get_json()
    store.update_timepoint(owner,sid,tid,{'title':'Renamed source'},expected_revision=current['catalog_revision'])
    stale = client.post(url, headers={'X-CSRF-Token':account['csrf_token']}, json={
        'title':'Not created', 'expected_revision':current['catalog_revision'],
        'expected_metadata_signature':current['metadata_signature']})
    assert stale.status_code == 409
