"""Real owned acquisitions and route errors; no registration/model substitution."""
from uuid import uuid4

import pytest
import SimpleITK as sitk
from flask import Flask

from test_guide_bore_manifest import tube_guide
from test_guide_tool_manifest import create_timepoint
from test_guide_registration_cpu import phantom
from test_guide_original_source_image import upload
from web.auth import configure_auth, register_auth_routes
from web.routes.guide_registration_routes import register_guide_registration_routes
from web.timepoint_images import TimepointImageService
from web.workspace_store import WorkspaceStore


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_missing_original_multimage_provenance_has_localized_recovery(tmp_path, monkeypatch, language):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    app = Flask(__name__)
    configure_auth(app, store, {'secret_key': 'synthetic-provenance-secret'})
    register_auth_routes(app, store)
    register_guide_registration_routes(app, store)
    client = app.test_client()
    account = client.post('/api/auth/register', json={
        'username': 'provenance_route_owner', 'password': 'synthetic test passphrase'}).get_json()
    owner, sid = account['user']['id'], account['active_session_id']
    source = create_timepoint(store, owner, sid, 'source A/C')
    target = create_timepoint(store, owner, sid, 'target B', stage='intraoperative',
                             preoperative_timepoint_id=source)
    image = phantom()
    images = TimepointImageService(store)
    for name in ('A', 'C'):
        path = tmp_path / (name + '.nii.gz')
        sitk.WriteImage(image, str(path))
        upload(images, owner, sid, source, path)
    guide = tube_guide()
    guide.update(version=1, status='ready', parameters={})
    source_state = store.load_timepoint_snapshot(owner, sid, source)
    store.save_timepoint_results(owner, sid, source, {'surgical_guide': guide},
        expected_state_revision=source_state['timepoint_state_revision'])
    store.save_timepoint_results(owner, sid, target, {'ct_data': sitk.GetArrayFromImage(image),
        'ct_spacing': image.GetSpacing(), 'ct_origin': image.GetOrigin(), 'ct_direction': image.GetDirection()},
        expected_state_revision=0)
    before = store.load_timepoint_snapshot(owner, sid, target)
    result = client.post(f'/api/sessions/{sid}/timepoints/{target}/guide-registration/jobs',
        headers={'X-CSRF-Token': account['csrf_token'], 'X-BrachyBot-Language': language},
        json={'request_id': str(uuid4()), 'source_timepoint_id': source, 'guide_version': 1,
              'manufactured_guide_id': 'physical-test-guide', 'expected_state_revision': 1,
              'method': 'image_rigid', 'max_residual_mm': 2., 'ambiguity_margin_mm': .1})
    assert result.status_code == 400
    packet = result.get_json()
    assert packet['code'] == 'guide_source_image_unverified'
    assert packet['language'] == language
    assert ('原始术前影像' if language == 'zh' else 'original preoperative acquisition') in packet['error']
    assert ('区域' if language == 'zh' else 'ROI') in packet['error']
    assert 'multi-image history' not in packet['error']
    assert sid not in packet['error'] and str(tmp_path) not in packet['error']
    assert store.load_timepoint_snapshot(owner, sid, target)['timepoint_state_revision'] == before['timepoint_state_revision']
    assert not store.load_timepoint_snapshot(owner, sid, target)['agent']['planning_results'].get('guide_placement_candidates')
