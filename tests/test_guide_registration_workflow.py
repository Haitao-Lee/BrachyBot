"""Owned persisted jobs, explicit human review and restart/source fences."""
from dataclasses import asdict
from types import SimpleNamespace
import time
from uuid import uuid4

import numpy as np
import pytest
import SimpleITK as sitk
from flask import Flask

from test_guide_bore_manifest import tube_guide
from test_guide_tool_manifest import create_timepoint
from test_guide_registration_cpu import phantom
from utils.guide_registration_cpu import RegistrationLimits
from web.auth import configure_auth, register_auth_routes
from web.guide_placement import GuidePlacementError
from web.guide_service import GuidePlacementService
from web.guide_registration import GuideRegistrationJobs, owned_service, guide_overlay
from web.routes.guide_registration_routes import register_guide_registration_routes
from web.workspace_store import WorkspaceStore


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    owner = store.create_user('guide_job_owner', 'synthetic_hash')['id']
    sid = store.create_session(owner, 'Synthetic registration').id
    source = create_timepoint(store, owner, sid, 'Preop')
    target = create_timepoint(store, owner, sid, 'Current', stage='intraoperative', preoperative_timepoint_id=source)
    guide = tube_guide(); guide.update(version=1, status='ready', parameters={})
    image = phantom()
    values = {'ct_data': sitk.GetArrayFromImage(image), 'ct_spacing': image.GetSpacing(),
              'ct_origin': image.GetOrigin(), 'ct_direction': image.GetDirection()}
    store.save_timepoint_results(owner, sid, source, {**values, 'surgical_guide': guide}, expected_state_revision=0)
    store.save_timepoint_results(owner, sid, target, values, expected_state_revision=0)
    return store, owner, sid, source, target


def job_request(source, **updates):
    return {'request_id': str(uuid4()), 'source_timepoint_id': source, 'guide_version': 1,
            'manufactured_guide_id': 'physical-guide-phantom', 'expected_state_revision': 1,
            'method': 'image_rigid', 'max_residual_mm': 2., 'ambiguity_margin_mm': .1, **updates}


def wait_job(jobs, owner, sid, target, rid):
    deadline = time.monotonic() + 30.
    while time.monotonic() < deadline:
        result = jobs.get(owner, sid, target, rid)
        if result['status'] not in {'queued', 'running'}:
            return result
        time.sleep(.05)
    raise AssertionError('Synthetic registration job did not finish within its bounded test timeout')


def saved_manual(workspace):
    store, owner, sid, source, target = workspace
    service = owned_service(store, owner, sid)
    result = service.estimate(source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
         manufactured_guide_id='physical-guide-phantom', expected_state_revision=1, method='manual_rigid',
         matrix=np.eye(4).tolist(), evidence_source='synthetic direct guide marker observation')
    return service, result['placement']


def test_real_child_job_publishes_once_and_restart_reads_same_result(workspace):
    store, owner, sid, source, target = workspace
    jobs = GuideRegistrationJobs(store, limits=RegistrationLimits(max_seconds=20, iterations=30))
    request = job_request(source)
    initial = jobs.start(owner, sid, target, request)
    assert initial['input_readset']['context']['dependencies']
    assert initial['input_readset']['source_image']
    completed = wait_job(jobs, owner, sid, target, request['request_id'])
    assert completed['status'] == 'completed', completed
    revision = store.load_timepoint_snapshot(owner, sid, target)['timepoint_state_revision']
    cold = GuideRegistrationJobs(WorkspaceStore(store.runtime_dir))
    assert cold.get(owner, sid, target, request['request_id'])['placement_id'] == completed['placement_id']
    assert cold.start(owner, sid, target, request)['placement_id'] == completed['placement_id']
    assert store.load_timepoint_snapshot(owner, sid, target)['timepoint_state_revision'] == revision
    with pytest.raises(GuidePlacementError, match='reused'):
        cold.start(owner, sid, target, {**request, 'max_residual_mm': 3.})


def test_queued_job_is_cancellable_without_publication(workspace):
    store, owner, sid, source, target = workspace
    jobs = GuideRegistrationJobs(store)
    jobs.slots.acquire(); jobs.slots.acquire()
    request = job_request(source)
    try:
        jobs.start(owner, sid, target, request)
        jobs.cancel(owner, sid, target, request['request_id'])
        assert wait_job(jobs, owner, sid, target, request['request_id'])['status'] == 'cancelled'
        assert store.load_timepoint_snapshot(owner, sid, target)['timepoint_state_revision'] == 1
    finally:
        jobs.slots.release(); jobs.slots.release()


def test_source_drift_fences_registration_publication(workspace):
    store, owner, sid, source, target = workspace
    service = owned_service(store, owner, sid)
    context, _, _, _, _, binding = service.capture_registration(source_timepoint_id=source, target_timepoint_id=target,
        guide_version=1, expected_state_revision=1, manufactured_guide_id='physical-guide-phantom')
    store.save_timepoint_results(owner, sid, source, {'source_geometry_revision': 2}, expected_state_revision=1)
    from web.timepoints import TimepointConflict
    with pytest.raises(TimepointConflict, match='changed'):
        service.publish_registration({'matrix': np.eye(4).tolist(), 'method': 'test', 'qc': {}, 'evidence': {'source': 'test'}},
                                     binding, context, job_id=str(uuid4()))
    assert not service._results(service._snapshot(target)).get('guide_placement_candidates')


def test_printed_guide_from_an_older_planning_run_is_not_silently_omitted(workspace):
    store,owner,sid,source,target=workspace
    original=store.load_timepoint_snapshot(owner,sid,source)['agent']['planning_results']['surgical_guide']
    current=store.load_timepoint_snapshot(owner,sid,source)
    store.save_timepoint_results(owner,sid,source,{'surgical_guide':None,'surgical_guide_versions':[],
        'active_planning_id':'new-plan-without-new-print','planning_run:older-printed-plan':{'surgical_guide':original}},
        expected_clinical_revision=current['timepoint_clinical_revision'])
    service=owned_service(store,owner,sid)
    restored=service._guide(service._snapshot(source),1)
    assert restored['bore_manifest']['geometry_id']==original['bore_manifest']['geometry_id']
    assert service.guide_records(service._snapshot(source))


def test_presentation_publications_do_not_abort_captured_guide_registration(workspace):
    store,owner,sid,source,target=workspace
    service=owned_service(store,owner,sid)
    initial=store.load_timepoint_snapshot(owner,sid,target)
    store.save_timepoint_patch(owner,sid,target,{'ui':{'state':{'viewer':{'level':51}}}},expected_state_revision=1)
    context,_,_,_,_,binding=service.capture_registration(source_timepoint_id=source,target_timepoint_id=target,
        guide_version=1,expected_state_revision=1,expected_clinical_revision=initial['timepoint_clinical_revision'],
        manufactured_guide_id='physical-guide-phantom')
    current=store.load_timepoint_snapshot(owner,sid,target)
    store.save_timepoint_patch(owner,sid,target,{'ui':{'state':{'viewer':{'level':52}}}},
        expected_state_revision=current['timepoint_state_revision'])
    candidate,_=service.publish_registration({'matrix':np.eye(4).tolist(),'method':'manual_rigid','qc':{},
        'evidence':{'source':'explicit synthetic marker transform'}},binding,context,job_id=str(uuid4()))
    assert candidate['review_state']=='pending'
    with pytest.raises(GuidePlacementError,match='Clinical inputs changed'):
        service.capture_registration(source_timepoint_id=source,target_timepoint_id=target,guide_version=1,
            expected_state_revision=1,expected_clinical_revision=initial['timepoint_clinical_revision'],
            manufactured_guide_id='physical-guide-phantom')


def test_overlay_and_explicit_accept_reject_publish_authoritative_placement(workspace):
    store, owner, sid, source, target = workspace
    service, candidate = saved_manual(workspace)
    packet = guide_overlay(service, source_timepoint_id=source, target_timepoint_id=target, guide_version=1, placement_id=candidate['placement_id'])
    assert len(packet['slices']) == 3 and packet['vertices_lps_mm']
    assert any(len(row['ct_hu']) for row in packet['slices'])
    receipt = {**{key: packet[key] for key in ('candidate_sha256', 'target_image', 'state_revision')}, 'dimensions': ['2d', '3d']}
    kwargs = dict(source_timepoint_id=source, target_timepoint_id=target, guide_version=1, placement_id=candidate['placement_id'],
                  expected_state_revision=packet['state_revision'], candidate_sha256=candidate['candidate_sha256'],
                  profile_id='phantom-fit-review', note='Current CT and guide fit checked', manufacturing_confirmed=True)
    with pytest.raises(GuidePlacementError, match='2D and 3D'):
        service.review(**kwargs, decision='accepted')
    result = service.review(**kwargs, decision='accepted', overlay_receipt=receipt)
    assert service._results(service._snapshot(target))['guide_placement']['review_state'] == 'accepted'
    rejected = service.review(**{**kwargs, 'expected_state_revision': result['state_revision']}, decision='rejected')
    assert rejected['placement']['review_state'] == 'rejected'
    assert service._results(service._snapshot(target))['guide_placement'] is None


def test_current_overlay_review_tolerates_only_presentation_publication(workspace):
    store,owner,sid,source,target=workspace
    service,candidate=saved_manual(workspace)
    packet=guide_overlay(service,source_timepoint_id=source,target_timepoint_id=target,
        guide_version=1,placement_id=candidate['placement_id'])
    receipt={**{key:packet[key] for key in ('candidate_sha256','target_image','state_revision','clinical_revision')},
        'dimensions':['2d','3d']}
    store.save_timepoint_patch(owner,sid,target,{'ui':{'state':{'viewer':{'window':570}}}},
        expected_state_revision=packet['state_revision'])
    kwargs=dict(source_timepoint_id=source,target_timepoint_id=target,guide_version=1,placement_id=candidate['placement_id'],
        expected_state_revision=packet['state_revision'],expected_clinical_revision=packet['clinical_revision'],
        candidate_sha256=candidate['candidate_sha256'],profile_id='software-fit-review',note='Explicit software overlay review',
        decision='accepted',overlay_receipt=receipt,manufacturing_confirmed=True)
    reviewed=service.review(**kwargs)
    assert reviewed['placement']['review_state']=='accepted'
    with pytest.raises(GuidePlacementError,match='Clinical inputs changed'):
        service.review(**kwargs)


def test_restart_marks_dead_worker_interrupted_without_optimizer_resume(workspace):
    store, owner, sid, source, target = workspace
    jobs = GuideRegistrationJobs(store); request = job_request(source); rid = request['request_id']
    import json
    record = {'job_id': rid, 'status': 'running', 'cancel_requested': False}
    with jobs.database(owner, sid, target) as connection:
        connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', (rid, 'old', 'running', json.dumps(record), -1)); connection.commit()
    recovered = jobs.get(owner, sid, target, rid)
    assert recovered['status'] == 'interrupted' and recovered['auto_resumed'] is False


def test_actual_registration_child_crash_preserves_inputs_and_explicit_retry_recovers(workspace):
    """Kill only this fixture's newly spawned CPU child, never a service PID."""
    import multiprocessing
    store, owner, sid, source, target = workspace
    jobs = GuideRegistrationJobs(store, limits=RegistrationLimits(max_seconds=20, iterations=30))
    request = job_request(source)
    before = {row.pid for row in multiprocessing.active_children()}
    jobs.start(owner, sid, target, request)
    deadline = time.monotonic() + 10.
    child = None
    while time.monotonic() < deadline:
        new = [row for row in multiprocessing.active_children() if row.pid not in before]
        if len(new) == 1:
            child = new[0]
            break
        time.sleep(.01)
    assert child is not None, 'The real registration child did not start'
    child.terminate()
    child.join(timeout=2.)
    failed = wait_job(jobs, owner, sid, target, request['request_id'])
    assert failed['status'] == 'failed' and failed['auto_resumed'] is False
    assert 'child exited without a result' in failed['error']
    current = store.load_timepoint_snapshot(owner, sid, target)
    assert current['timepoint_state_revision'] == 1
    assert not current['agent']['planning_results'].get('guide_placement_candidates')
    cold = GuideRegistrationJobs(WorkspaceStore(store.runtime_dir),
        limits=RegistrationLimits(max_seconds=20, iterations=30))
    assert cold.get(owner,sid,target,request['request_id'])['status'] == 'failed'
    # Repeating an idempotency ID does not secretly retry a crashed operation.
    assert cold.start(owner,sid,target,request)['status'] == 'failed'
    retry = {**request, 'request_id':str(uuid4())}
    cold.start(owner,sid,target,retry)
    recovered = wait_job(cold,owner,sid,target,retry['request_id'])
    assert recovered['status'] == 'completed', recovered
    assert recovered['placement_id']


def test_manual_pose_is_invalid_after_source_clinical_edit(workspace):
    store, owner, sid, source, target = workspace
    service, candidate = saved_manual(workspace)
    store.save_timepoint_results(owner, sid, source, {'source_geometry_revision': 2}, expected_state_revision=1)
    with pytest.raises(GuidePlacementError, match='Source dependency changed'):
        service.validate(source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
                         placement_id=candidate['placement_id'])


def test_accept_uses_saved_confirmed_profile_and_invalidates_baseline(workspace):
    store, owner, sid, source, target = workspace
    service, candidate = saved_manual(workspace)
    store.save_timepoint_results(owner, sid, target, {'continuation_review_profile': {
        'profile_id': 'confirmed-profile', 'confirmed_by': owner, 'needle_radius_mm': .5,
        'minimum_guiding_length_mm': 1., 'obstacle_clearance_mm': 0., 'maximum_depth_mm': 80.},
        'continuation_baseline_record': {'old': True}}, expected_state_revision=2)
    packet = guide_overlay(service, source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
                           placement_id=candidate['placement_id'])
    kwargs = dict(source_timepoint_id=source, target_timepoint_id=target, guide_version=1,
        placement_id=candidate['placement_id'], expected_state_revision=3,
        candidate_sha256=candidate['candidate_sha256'], decision='accepted', profile_id='wrong-profile',
        note='Current guide fit reviewed', manufacturing_confirmed=True,
        overlay_receipt={'candidate_sha256': candidate['candidate_sha256'], 'target_image': packet['target_image'],
                         'state_revision': 3, 'dimensions': ['2d', '3d']})
    with pytest.raises(GuidePlacementError, match='confirmed current needle'):
        service.review(**kwargs)
    service.review(**{**kwargs, 'profile_id': 'confirmed-profile'})
    values = service._results(service._snapshot(target))
    assert values['continuation_baseline_record'] is None
    assert values['guide_current_feasibility']['status'] == 'pending_inputs'
    assert 'explicit_current_in_situ_needle_observations' in values['guide_current_feasibility']['missing']


def test_routes_reject_cross_owner_csrf_conflicting_scope_and_forged_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    app = Flask(__name__); store = WorkspaceStore(tmp_path / 'runtime')
    configure_auth(app, store, {'secret_key': 'synthetic-secret'}); register_auth_routes(app, store)
    register_guide_registration_routes(app, store)
    client, other = app.test_client(), app.test_client()
    account = client.post('/api/auth/register', json={'username': 'guide_route_owner', 'password': 'synthetic test passphrase'}).get_json()
    other.post('/api/auth/register', json={'username': 'guide_route_other', 'password': 'synthetic test passphrase'})
    owner, sid = account['user']['id'], account['active_session_id']
    source = create_timepoint(store, owner, sid, 'source'); target = create_timepoint(store, owner, sid, 'target', stage='intraoperative', preoperative_timepoint_id=source)
    base = f'/api/sessions/{sid}/timepoints/{target}/guide-registration'
    assert other.get(base).status_code == 404
    assert client.post(base + '/jobs', json=job_request(source)).status_code == 403
    assert client.get(base, headers={'X-BrachyBot-Timepoint': 'f' * 32}).status_code == 400
    headers = {'X-CSRF-Token': account['csrf_token']}
    forged = client.post(base + '/placements/fake/review', headers=headers, json={'decision': 'accepted', 'overlay_receipt': {}})
    assert forged.status_code == 400
    localized=client.post(base+'/placements/fake/review',headers={**headers,'X-BrachyBot-Language':'zh'},
        json={'decision':'accepted','overlay_receipt':{}})
    assert localized.status_code==400
    assert localized.get_json()['language']=='zh'
    assert '导板定位' in localized.get_json()['message']
    assert 'Fetch and display' not in localized.get_json()['error']
