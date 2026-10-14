"""Owned acquisitions and immutable Planning fixtures; no clinical fit claims."""
from copy import deepcopy
import os
import time
from uuid import uuid4

import numpy as np
import pytest
import SimpleITK as sitk

from test_guide_bore_manifest import tube_guide
from test_guide_tool_manifest import create_timepoint
from web.guide_registration import GuideRegistrationJobs, guide_overlay, owned_service
from web.guide_placement import GuidePlacementError
from web.timepoint_images import TimepointImageService
from web.timepoint_resources import capture_resources, fingerprint, resource_state
from tool_factory.seed_plan.continuation_support import image_signature
from web.workspace_store import WorkspaceStore
from utils.guide_registration_cpu import RegistrationLimits


@pytest.fixture(autouse=True)
def windows_store_primitives(monkeypatch):
    if os.name == 'nt':
        # POSIX directory fsync is unsupported. Also os.kill(pid, 0) means
        # CTRL_C_EVENT on Windows, not the Linux process-existence probe.
        # Every test job owner is this process (or a deliberate dead PID).
        monkeypatch.setattr(WorkspaceStore, '_fsync_directory', staticmethod(lambda path: None))
        monkeypatch.setattr('web.guide_registration._process_alive', lambda pid: pid == os.getpid())


def upload(images, owner, sid, tid, path):
    with path.open('rb') as stream:
        return images.register_upload(owner, sid, tid, stream, path.name, modality='CT',
            expected_collection_revision=images.list_images(owner, sid, tid)['collection_revision'],
            editor_token='', select_first_reference=True)['created_image_id']


@pytest.fixture
def acquisitions(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    owner = store.create_user('original_guide_owner', 'synthetic_hash')['id']
    sid = store.create_session(owner, 'Synthetic guide provenance').id
    source = create_timepoint(store, owner, sid, 'Preop A/C')
    target = create_timepoint(store, owner, sid, 'Intraop B', stage='intraoperative',
                              preoperative_timepoint_id=source)
    images = TimepointImageService(store)
    ids = []
    for name, offset, tid in [('A', 0, source), ('C', 1000, source), ('B', 0, target)]:
        image = sitk.GetImageFromArray(np.arange(512, dtype=np.int16).reshape(8, 8, 8) + offset)
        path = tmp_path / (name + '.nii.gz')
        sitk.WriteImage(image, str(path))
        ids.append(upload(images, owner, sid, tid, path))
    bridge = images.planning_reference_bridge(owner, sid, source)
    receipt = bridge['planning_reference_receipt']
    image_leaf = fingerprint({'content': image_signature(bridge['ct_image']),
        'reference_image_id': receipt['image_id'], 'reference': {k: receipt[k] for k in
        ('image_id', 'source_sha256', 'volume_sha256', 'voxel_sha256', 'geometry_signature', 'frame_index', 'modality')}})
    guide = tube_guide()
    guide.update(version=1, status='ready', planning_id='planning-A', source_plan_signature='fixture-A')
    parent = {'surgical_guide': guide, 'timepoint_resource_state': resource_state(None, {'image': image_leaf})}
    state = store.load_timepoint_snapshot(owner, sid, source)
    store.save_timepoint_results(owner, sid, source, {'surgical_guide': guide,
        'active_planning_id': 'planning-A', 'planning_run:planning-A': parent},
        expected_state_revision=state['timepoint_state_revision'])
    images.update_image(owner, sid, source, ids[1], {'planning_reference': True}, editor_token='',
        expected_collection_revision=images.list_images(owner, sid, source)['collection_revision'])
    return store, owner, sid, source, target, images, ids, guide


def test_reference_switch_keeps_exact_old_print_discoverable(acquisitions):
    store, owner, sid, source, target, images, ids, guide = acquisitions
    service = owned_service(store, owner, sid)
    frozen, _, selected = service._source_target(source, target, 1)
    assert selected['bore_manifest'] == guide['bore_manifest']
    assert frozen['image_collection']['planning_reference_image_id'] == ids[1]
    # This is the pre-repair hazardous helper: it returns C, not original A.
    assert sitk.GetArrayFromImage(service._target_ct_image(frozen)).min() == 1000


def test_original_image_resolves_from_saved_parent_after_switch(acquisitions):
    store, owner, sid, source, target, images, ids, _ = acquisitions
    service = owned_service(store, owner, sid)
    frozen, _, guide = service._source_target(source, target, 1)
    original, provenance = service._guide_source_image(frozen, guide)
    assert provenance['image']['image_id'] == ids[0]
    assert provenance['policy'] == 'saved_parent_image_fingerprint'
    assert sitk.GetArrayFromImage(original).min() == 0
    assert images.list_images(owner, sid, source)['planning_reference_image_id'] == ids[1]


def test_retained_old_parent_job_captures_A_not_current_C(acquisitions, monkeypatch):
    store, owner, sid, source, target, images, ids, _ = acquisitions
    snapshot = store.load_timepoint_snapshot(owner, sid, source)
    # Retain the immutable older Planning in current history without changing
    # the collection/reference. This is a real owned store write, not a fake CT.
    old = snapshot['image_resources'][ids[0]]['agent']['planning_results']
    store.save_timepoint_results(owner, sid, source,
        {'planning_run:planning-A': old['planning_run:planning-A']},
        expected_state_revision=snapshot['timepoint_state_revision'])
    jobs = GuideRegistrationJobs(store)
    captured = {}
    monkeypatch.setattr(jobs, '_run', lambda *args: captured.update(payload=args[-1]))
    state = store.load_timepoint_snapshot(owner, sid, target)
    record = jobs.start(owner, sid, target, {'request_id': str(uuid4()),
        'source_timepoint_id': source, 'guide_version': 1, 'manufactured_guide_id': 'printed-A',
        'expected_state_revision': state['timepoint_state_revision'], 'method': 'image_rigid',
        'max_residual_mm': 2., 'ambiguity_margin_mm': .1})
    jobs.threads[(owner, sid, target, record['job_id'])].join(timeout=2)
    assert record['input_readset']['source_image']['image_id'] == ids[0]
    assert np.asarray(captured['payload']['source']['array']).min() == 0


def capture(acquisitions):
    store, owner, sid, source, target, _, _, _ = acquisitions
    service = owned_service(store, owner, sid)
    target_state = service._snapshot(target)
    context, frozen, _, guide, _, binding = service.capture_registration(
        source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
        expected_state_revision=target_state['timepoint_state_revision'], manufactured_guide_id='printed-A')
    _, provenance = service._guide_source_image(frozen, guide)
    binding.update(source_image=provenance['image'], source_provenance=provenance)
    # Controlled rigid transform exercises storage/fences only, not fit accuracy.
    result = {'matrix': guide['bore_manifest']['guide_local_to_source_lps'],
        'source_to_target_matrix': np.eye(4).tolist(), 'method': 'provenance_fence_fixture',
        'qc': {}, 'evidence': {'source': 'synthetic fence test'}}
    return service, context, binding, result


def test_publication_overlay_review_restart_all_bind_original_A(acquisitions):
    store, owner, sid, source, target, images, ids, guide = acquisitions
    service, context, binding, result = capture(acquisitions)
    candidate, _ = service.publish_registration(result, binding, context, job_id=str(uuid4()))
    cold = owned_service(WorkspaceStore(store.runtime_dir), owner, sid)
    packet = guide_overlay(cold, source_timepoint_id=source, target_timepoint_id=target,
        guide_version=1, placement_id=candidate['placement_id'])
    assert packet['source_provenance'] == binding['source_provenance']
    for row in packet['slices']:
        np.testing.assert_allclose(row['registered_source_hu'], row['ct_hu'], atol=1e-5)
    receipt = {**{k: packet[k] for k in ('candidate_sha256', 'target_image', 'state_revision')},
               'dimensions': ['2d', '3d']}
    reviewed = cold.review(source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
        placement_id=candidate['placement_id'], expected_state_revision=packet['state_revision'],
        candidate_sha256=candidate['candidate_sha256'], decision='accepted', profile_id='synthetic-review',
        note='Provenance contract only, not clinical validation', overlay_receipt=receipt,
        manufacturing_confirmed=True)
    assert reviewed['placement']['evidence']['input_readset']['source_provenance'] == binding['source_provenance']
    assert reviewed['placement']['review_state'] == 'accepted'
    assert not reviewed['clinical_use_approved']
    assert images.list_images(owner, sid, source)['planning_reference_image_id'] == ids[1]
    recovered = cold._decode(cold._guide(cold._snapshot(source), 1))
    np.testing.assert_array_equal(recovered['vertices'], guide['vertices'])
    np.testing.assert_array_equal(recovered['faces'], guide['faces'])


@pytest.mark.parametrize('damage', ['delete', 'missing', 'alter_pixels', 'parent_conflict'])
def test_source_damage_fences_publication_and_candidate_review(acquisitions, damage):
    store, owner, sid, source, target, images, ids, _ = acquisitions
    service, context, binding, result = capture(acquisitions)
    candidate, _ = service.publish_registration(result, binding, context, job_id=str(uuid4()))
    if damage == 'delete':
        images.delete_image(owner, sid, source, ids[0], editor_token='',
            expected_collection_revision=images.list_images(owner, sid, source)['collection_revision'])
    elif damage in {'missing', 'alter_pixels'}:
        path, _ = images.source_file(owner, sid, source, ids[0])
        if damage == 'missing':
            path.unlink()  # only this test's explicitly resolved owned fixture
        else:
            volume = sitk.ReadImage(str(path))
            sitk.WriteImage(volume + 1, str(path))
    else:
        state = service._snapshot(source)
        parent = deepcopy(state['image_resources'][ids[0]]['agent']['planning_results']['planning_run:planning-A'])
        parent['timepoint_resource_state']['fingerprints']['image'] = 'f' * 64
        store.save_timepoint_results(owner, sid, source, {'planning_run:planning-A': parent},
            expected_state_revision=state['timepoint_state_revision'])
    with pytest.raises(GuidePlacementError):
        service.publish_registration(result, binding, context, job_id=str(uuid4()))
    with pytest.raises(GuidePlacementError):
        service.validate(source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
                         placement_id=candidate['placement_id'])
    with pytest.raises(GuidePlacementError):
        guide_overlay(service, source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
                      placement_id=candidate['placement_id'])


@pytest.mark.parametrize('method', ['visible_guide', 'auto'])
def test_direct_visible_guide_job_needs_no_source_acquisition(acquisitions, monkeypatch, method):
    store, owner, sid, source, target, images, ids, _ = acquisitions
    images.delete_image(owner, sid, source, ids[0], editor_token='',
        expected_collection_revision=images.list_images(owner, sid, source)['collection_revision'])
    jobs = GuideRegistrationJobs(store)
    captured = {}
    monkeypatch.setattr(jobs, '_run', lambda *args: captured.update(payload=args[-1]))
    state = store.load_timepoint_snapshot(owner, sid, target)
    record = jobs.start(owner, sid, target, {'request_id': str(uuid4()),
        'source_timepoint_id': source, 'guide_version': 1, 'manufactured_guide_id': 'printed-A',
        'expected_state_revision': state['timepoint_state_revision'], 'method': method,
        'guide_roi_index_xyz': [1, 1, 1, 7, 7, 7], 'guide_threshold_hu': 200.,
        'max_residual_mm': 2., 'ambiguity_margin_mm': .1})
    jobs.threads[(owner, sid, target, record['job_id'])].join(timeout=2)
    assert 'source' not in captured['payload']
    assert 'source_image' not in record['input_readset']


def test_multi_image_missing_parent_fails_closed(acquisitions):
    store, owner, sid, source, target, _, _, guide = acquisitions
    service = owned_service(store, owner, sid)
    snapshot = service._snapshot(source)
    snapshot['image_resources'] = {}
    snapshot['agent']['planning_results'] = {'surgical_guide': guide}
    with pytest.raises(GuidePlacementError, match='provenance.*multi-image'):
        service._guide_source_image(snapshot, guide)


@pytest.mark.parametrize('parent_kind', ['missing', 'matching', 'mismatched'])
def test_native_first_upload_archive_requires_exact_saved_parent(tmp_path, monkeypatch, parent_kind):
    from io import BytesIO
    from test_guide_registration_cpu import phantom
    from web.server import create_app

    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    for key in ('BRACHYBOT_API_KEY', 'BRACHYBOT_REQUIRE_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    app = create_app({'runtime_dir': str(tmp_path / 'runtime'),
        'secret_key': 'synthetic-native-source-parent', 'workspace_maintenance': False})
    client = app.test_client()
    auth = client.post('/api/auth/register', json={'username': 'native_guide_owner',
        'password': 'synthetic-browser-password-123'}).get_json()
    owner, sid = auth['user']['id'], auth['active_session_id']
    source = client.get(f'/api/sessions/{sid}/timepoints').get_json()['default_timepoint_id']
    store = getattr(app.extensions['brachybot_workspace_store'], 'raw', app.extensions['brachybot_workspace_store'])
    path = tmp_path / 'native-phantom.nii.gz'
    sitk.WriteImage(phantom(), str(path))
    headers = {'X-CSRF-Token': auth['csrf_token'], 'X-BrachyBot-Session': sid, 'X-BrachyBot-Timepoint': source}
    uploaded = client.post('/api/upload', headers=headers,
        data={'file': (BytesIO(path.read_bytes()), path.name)}, content_type='multipart/form-data')
    assert uploaded.status_code == 200, uploaded.get_data(as_text=True)
    loaded = client.post('/api/viewer/load', headers=headers, json={'ct_path': uploaded.get_json()['path']})
    assert loaded.status_code == 200, loaded.get_data(as_text=True)
    service = owned_service(store, owner, sid)
    state = service._snapshot(source)
    assert len(state['image_collection']['images']) == 1
    archive = state['image_resources']['unassigned']
    assert archive['reference_image_id'] is None
    assert archive['source_receipt'] is None
    assert not service._results(archive)
    guide = tube_guide()
    guide.update(version=1, status='ready', planning_id='native-parent')
    values = {'surgical_guide': guide}
    bridge = TimepointImageService(store).planning_reference_bridge(owner, sid, source)
    resources = capture_resources(bridge.get, bridge['ct_image'])
    if parent_kind != 'missing':
        if parent_kind == 'mismatched':
            # Equal physical grid but different pixels cannot prove identity.
            resources = capture_resources(bridge.get, bridge['ct_image'] + 1)
        values['planning_run:native-parent'] = {'surgical_guide': guide,
            'timepoint_resource_state': resource_state(None, resources)}
    store.save_timepoint_results(owner, sid, source, values,
        expected_state_revision=state['timepoint_state_revision'])
    saved = service._snapshot(source)
    if parent_kind == 'matching':
        original, provenance = service._guide_source_image(saved, guide)
        assert provenance['policy'] == 'saved_parent_image_fingerprint'
        assert provenance['original_acquisition_verified'] is True
        assert provenance['parent_image_fingerprint'] == resources['image']
        assert provenance['image']['image_id'] == bridge['planning_reference_image_id']
        np.testing.assert_array_equal(sitk.GetArrayFromImage(original), sitk.GetArrayFromImage(bridge['ct_image']))
    else:
        with pytest.raises(GuidePlacementError) as error:
            service._guide_source_image(saved, guide)
        assert error.value.error_code == 'guide_source_image_unverified'
    assert 'unassigned' in saved['image_resources']


def test_deleted_second_acquisition_still_blocks_no_parent_fallback(acquisitions):
    store, owner, sid, source, _, images, ids, guide = acquisitions
    images.delete_image(owner, sid, source, ids[1], editor_token='',
        expected_collection_revision=images.list_images(owner, sid, source)['collection_revision'])
    service = owned_service(store, owner, sid)
    snapshot = service._snapshot(source)
    # Even without an archive hint, historical collection records count. An
    # active-only filter must not turn A/C history into single-image evidence.
    snapshot['image_resources'] = {}
    snapshot['agent']['planning_results'] = {'surgical_guide': guide}
    assert len(snapshot['image_collection']['images']) == 2
    assert sum(row['status'] == 'active' for row in snapshot['image_collection']['images'].values()) == 1
    with pytest.raises(GuidePlacementError, match='provenance.*multi-image'):
        service._guide_source_image(snapshot, guide)


def test_fingerprint_only_parent_searches_all_bounded_images(acquisitions):
    store, owner, sid, source, _, _, ids, guide = acquisitions
    service = owned_service(store, owner, sid)
    snapshot = service._snapshot(source)
    parent = snapshot['image_resources'][ids[0]]['agent']['planning_results']['planning_run:planning-A']
    snapshot['image_resources'] = {}
    snapshot['agent']['planning_results']['planning_run:planning-A'] = parent
    _, provenance = service._guide_source_image(snapshot, guide)
    assert provenance['image']['image_id'] == ids[0]


def test_legacy_policies_are_explicit_and_content_fenced(acquisitions):
    store, owner, sid, source, _, images, ids, guide = acquisitions
    service = owned_service(store, owner, sid)
    snapshot = service._snapshot(source)
    snapshot['image_resources'] = {}
    snapshot['agent']['planning_results'] = {'surgical_guide': guide}
    snapshot['image_collection']['images'] = {ids[0]: snapshot['image_collection']['images'][ids[0]]}
    _, provenance = service._guide_source_image(snapshot, guide)
    assert provenance['policy'] == 'legacy_single_owned_acquisition'
    assert provenance['original_acquisition_verified'] is False
    bridge = images.planning_reference_bridge(owner, sid, source)
    snapshot.pop('image_collection')
    snapshot['agent']['planning_results'] = {k: v for k, v in bridge.items() if k == 'ct_data'}
    image = bridge['ct_image']
    snapshot['agent']['planning_results'].update(ct_spacing=image.GetSpacing(), ct_origin=image.GetOrigin(),
                                                ct_direction=image.GetDirection())
    _, provenance = service._guide_source_image(snapshot, guide)
    assert provenance['policy'] == 'legacy_single_ct_content_fenced'
    assert provenance['image']['image_revision']
    results = snapshot['agent']['planning_results']
    raw_leaf = fingerprint({'content': image_signature(image), 'reference_image_id': None,
        'reference': {k: None for k in ('image_id', 'source_sha256', 'volume_sha256', 'voxel_sha256',
            'geometry_signature', 'frame_index', 'modality')}})
    results['planning_run:planning-A'] = {'timepoint_resource_state': resource_state(None, {'image': raw_leaf})}
    _, provenance = service._guide_source_image(snapshot, guide)
    assert provenance['policy'] == 'saved_parent_single_ct_fingerprint'
    assert provenance['original_acquisition_verified']
    results['ct_data'] = results['ct_data'] + 1
    with pytest.raises(GuidePlacementError, match='differs.*saved parent fingerprint'):
        service._guide_source_image(snapshot, guide)


def test_existing_image_candidate_without_original_provenance_requires_reestimate(acquisitions):
    service, context, binding, result = capture(acquisitions)
    binding.pop('source_provenance')
    with pytest.raises(GuidePlacementError, match='lacks verified original source provenance'):
        service.publish_registration(result, binding, context, job_id=str(uuid4()))


def test_same_version_with_conflicting_guide_provenance_fails_closed(acquisitions):
    store, owner, sid, source, _, _, _, guide = acquisitions
    service = owned_service(store, owner, sid)
    state = service._snapshot(source)
    different = deepcopy(guide)
    different['planning_id'] = 'planning-C'
    state['agent']['planning_results']['surgical_guide'] = different
    with pytest.raises(GuidePlacementError, match='conflicting Planning provenance'):
        service._guide(state, 1)


def test_real_visible_guide_child_works_when_original_source_is_deleted(acquisitions, tmp_path):
    store, owner, sid, source, target, images, ids, _ = acquisitions
    images.delete_image(owner, sid, source, ids[0], editor_token='',
        expected_collection_revision=images.list_images(owner, sid, source)['collection_revision'])
    pixels = np.full((16, 16, 16), -1000., np.float32)
    pixels[5:10, 5:10, 5:10] = 500.
    path = tmp_path / 'visible-guide-B.nii.gz'
    sitk.WriteImage(sitk.GetImageFromArray(pixels), str(path))
    identifier = upload(images, owner, sid, target, path)
    images.update_image(owner, sid, target, identifier, {'planning_reference': True}, editor_token='',
        expected_collection_revision=images.list_images(owner, sid, target)['collection_revision'])
    jobs = GuideRegistrationJobs(store, limits=RegistrationLimits(max_seconds=20, iterations=10))
    state = store.load_timepoint_snapshot(owner, sid, target)
    record = jobs.start(owner, sid, target, {'request_id': str(uuid4()),
        'source_timepoint_id': source, 'guide_version': 1, 'manufactured_guide_id': 'printed-A',
        'expected_state_revision': state['timepoint_state_revision'], 'method': 'visible_guide',
        'guide_roi_index_xyz': [2, 2, 2, 14, 14, 14], 'guide_threshold_hu': 200.,
        'max_residual_mm': 2., 'ambiguity_margin_mm': .1})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        finished = jobs.get(owner, sid, target, record['job_id'])
        if finished['status'] not in {'queued', 'running'}:
            break
        time.sleep(.05)
    assert finished['status'] == 'completed', finished
    service = owned_service(store, owner, sid)
    candidate = service._results(service._snapshot(target))['guide_placement_candidates'][finished['placement_id']]
    assert candidate['review_state'] == 'pending'
    assert candidate['qc']['proper_rigid']
    assert 'source_image' not in candidate['evidence']['input_readset']
    assert not candidate.get('source_to_target_matrix')


def test_real_child_registration_uses_A_after_C_selection(acquisitions):
    store, owner, sid, source, target, _, ids, _ = acquisitions
    jobs = GuideRegistrationJobs(store, limits=RegistrationLimits(max_seconds=20, iterations=10))
    state = store.load_timepoint_snapshot(owner, sid, target)
    record = jobs.start(owner, sid, target, {'request_id': str(uuid4()),
        'source_timepoint_id': source, 'guide_version': 1, 'manufactured_guide_id': 'printed-A',
        'expected_state_revision': state['timepoint_state_revision'], 'method': 'image_rigid',
        'max_residual_mm': 2., 'ambiguity_margin_mm': .1})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        finished = jobs.get(owner, sid, target, record['job_id'])
        if finished['status'] not in {'queued', 'running'}:
            break
        time.sleep(.05)
    assert finished['status'] == 'completed', finished
    service = owned_service(store, owner, sid)
    candidate = service._results(service._snapshot(target))['guide_placement_candidates'][finished['placement_id']]
    assert candidate['evidence']['input_readset']['source_image']['image_id'] == ids[0]
    assert candidate['review_state'] == 'pending'
    assert candidate['qc']['proper_rigid']
    assert candidate['qc']['anatomy_to_guide_pose_is_estimate']
