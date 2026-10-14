"""Actual Flask factory and actual decoding/Viewer APIs on owned test volumes."""
from io import BytesIO

import numpy as np
import SimpleITK as sitk


def test_real_product_upload_switch_and_restore_never_clear_other_scan_or_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_REQUIRE_API_KEY", raising=False)
    from web.server import create_app
    app = create_app({"runtime_dir": str(tmp_path / "runtime"), "secret_key": "synthetic-http-secret",
        "workspace_maintenance": False})
    client = app.test_client()
    auth = client.post("/api/auth/register", json={"username": "real_http_owner", "password": "synthetic-password-123"}).get_json()
    sid, uid = auth["active_session_id"], auth["user"]["id"]
    catalog = client.get(f"/api/sessions/{sid}/timepoints").get_json()
    assert catalog["capabilities"]["execution_scope"] is True
    tid = catalog["default_timepoint_id"]
    headers = {"X-CSRF-Token": auth["csrf_token"], "X-BrachyBot-Session": sid, "X-BrachyBot-Timepoint": tid}
    def upload(name, offset):
        array = np.arange(240, dtype=np.int16).reshape(4, 6, 10) + offset
        image = sitk.GetImageFromArray(array)
        path = tmp_path / name
        sitk.WriteImage(image, str(path))
        response = client.post("/api/upload", headers=headers, data={"file": (BytesIO(path.read_bytes()), name)}, content_type="multipart/form-data")
        assert response.status_code == 200, response.get_data(as_text=True)
        loaded = client.post("/api/viewer/load", headers=headers, json={"ct_path": response.get_json()["path"]})
        assert loaded.status_code == 200, loaded.get_data(as_text=True)
        return loaded.get_json()["image_id"]
    first = upload("first.nii.gz", 0)
    raw = getattr(app.extensions["brachybot_workspace_store"], "raw", app.extensions["brachybot_workspace_store"])
    before_projection = raw.load_timepoint_snapshot(uid,sid,tid)
    repeated = client.post('/api/viewer/load',headers=headers,json={'image_id':first,'display_only':True})
    assert repeated.status_code == 200
    after_projection = raw.load_timepoint_snapshot(uid,sid,tid)
    assert after_projection['image_collection']['collection_revision'] == before_projection['image_collection']['collection_revision']
    assert after_projection['timepoint_clinical_revision'] == before_projection['timepoint_clinical_revision']
    state = raw.load_timepoint_snapshot(uid, sid, tid)
    raw.save_timepoint_results(uid, sid, tid, {"ctv_binary_array": np.ones((4, 6, 10), np.uint8),
        "dose_metrics": {"v100": .91}}, expected_clinical_revision=state["timepoint_clinical_revision"])
    second = upload("second.nii.gz", 1000)
    assert first != second
    state = raw.load_timepoint_snapshot(uid, sid, tid)
    assert state["agent"]["planning_results"]["dose_metrics"]["v100"] == .91
    assert state["image_collection"]["planning_reference_image_id"] == first
    assert state["image_collection"]["display_image_id"] == second
    response = client.get("/api/viewer/volume", headers=headers)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    meta = client.post("/api/viewer/load", headers=headers, json={"image_id": first, "display_only": True}).get_json()
    assert meta["image_id"] == first and meta["clinical_visible"] is True
    assert raw.load_timepoint_snapshot(uid, sid, tid)["agent"]["planning_results"]["dose_metrics"]["v100"] == .91
    images_url = f'/api/sessions/{sid}/timepoints/{tid}/images'
    collection = client.get(images_url,headers=headers).get_json()
    hidden = client.patch(images_url+'/'+first,headers=headers,json={'display':False,
        'expected_collection_revision':collection['collection_revision']})
    assert hidden.status_code == 200
    geometry = client.post('/api/viewer/load',headers=headers,json={'image_id':first,'geometry_only':True})
    assert geometry.status_code == 200 and geometry.get_json()['geometry_only']
    assert geometry.get_json()['display_image_id'] is None
    assert client.get(images_url,headers=headers).get_json()['display_image_id'] is None
    assert raw.load_timepoint_snapshot(uid,sid,tid)['agent']['planning_results']['dose_metrics']['v100'] == .91
    created = client.post(f"/api/sessions/{sid}/timepoints", headers={"X-CSRF-Token": auth["csrf_token"]},
        json={"title": "Other timepoint", "expected_revision": raw.list_timepoints(uid, sid)["catalog_revision"]})
    assert created.status_code == 201
    other = created.get_json()["created_timepoint_id"]
    other_headers = {**headers, "X-BrachyBot-Timepoint": other}
    empty = client.get("/api/workspace/snapshot", headers=other_headers).get_json()["workspace"]
    assert empty["timepoint_id"] == other and not empty["agent"]["planning_results"]
    assert client.get("/api/planning/results", headers=headers).status_code == 200
    settings_url=f'/api/sessions/{sid}/timepoints/{tid}/implants/dose-source'
    profile_response=client.get(settings_url,headers=headers)
    assert profile_response.status_code==200,profile_response.get_data(as_text=True)
    source_settings=profile_response.get_json()
    state=raw.load_timepoint_snapshot(uid,sid,tid)
    raw.save_timepoint_patch(uid,sid,tid,{'ui':{'state':{'viewer':{'window':570,'level':51}}}},
        expected_state_revision=state['timepoint_state_revision'])
    confirm={'length_mm':4.5,'radius_mm':.4,'expected_clinical_revision':source_settings['clinical_revision']}
    confirmed=client.post(settings_url,headers=headers,json=confirm)
    assert confirmed.status_code==200,confirmed.get_data(as_text=True)
    assert confirmed.get_json()['profile']['seed_info']['length']==4.5
    assert client.post(settings_url,headers=headers,json=confirm).status_code==409
    current=raw.load_timepoint_snapshot(uid,sid,tid)
    assert current['agent']['planning_results']['dose_metrics'] is None
    owned_source = current['agent']['planning_results']['timepoint_planning_config']['seed_info']
    assert owned_source['length'] == 4.5 and owned_source['radius'] == .4
    accepted_config = client.get('/api/config', headers=headers).get_json()['config']
    assert accepted_config['seed_info']['length'] == 4.5
    assert current['agent']['planning_results']['report_status'] == 'stale'
    same=client.post(settings_url,headers=headers,json={**confirm,
        'expected_clinical_revision':current['timepoint_clinical_revision']})
    assert same.status_code == 200 and same.get_json()['reused'] is True
    assert same.get_json()['profile']['confirmation_id'] == confirmed.get_json()['profile']['confirmation_id']
    assert raw.load_timepoint_snapshot(uid,sid,tid)['timepoint_clinical_revision'] == current['timepoint_clinical_revision']
    # No model execution or clinical mutation can happen before the actual
    # source set/revision contract is supplied. This is not a dose mock.
    missing=client.post('/api/dose/recompute',headers=headers,json={'source_set':'implanted',
        'expected_clinical_revision':current['timepoint_clinical_revision']})
    assert missing.status_code==400
    assert raw.load_timepoint_snapshot(uid,sid,tid)['timepoint_clinical_revision']==current['timepoint_clinical_revision']
    for invalid in ({'source_set':[],'expected_clinical_revision':current['timepoint_clinical_revision']},
                    {'source_set':'planned','expected_clinical_revision':True},
                    {'source_set':'planned','expected_clinical_revision':-1},
                    {'source_set':'implanted','expected_clinical_revision':current['timepoint_clinical_revision'],
                     'expected_observation_revision_id':[]}):
        rejected=client.post('/api/dose/recompute',headers=headers,json=invalid)
        assert rejected.status_code==400,rejected.get_data(as_text=True)
    assert raw.load_timepoint_snapshot(uid,sid,tid)['timepoint_clinical_revision']==current['timepoint_clinical_revision']
    # A previous scan's body cannot be silently redirected using another header.
    mismatch = client.post("/api/viewer/load", headers=other_headers,
        json={"timepoint_id": tid, "image_id": first, "display_only": True})
    assert mismatch.status_code == 400

    # Transport-only fixture: clinical detector/optimizer behavior is not
    # claimed here. The actual route must preserve a producer's review pause.
    from tool_factory import ToolResult
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    monkeypatch.setattr(PlanningPipelineTool,'_execute',lambda self,**kwargs:ToolResult(False,
        error='Operator review required',metadata={'phase':'awaiting_observation_review',
            'code':'implant_review_required','requires_human_review':True,'planning_completed':False}))
    reference=raw.load_timepoint_snapshot(uid,sid,tid)['agent']['planning_results']['ct_path']
    paused=client.post('/api/planning/run_step',headers=headers,json={'ct_image_path':reference,'step':'full'})
    assert paused.status_code==202,paused.get_data(as_text=True)
    assert paused.get_json()['pending_review'] and paused.get_json()['planning_completed'] is False
    assert paused.get_json()['metadata']['code']=='implant_review_required'
    collection=client.get(images_url,headers=headers).get_json()
    selected=next(image for image in collection['images'] if image['id']==first)
    relative=client.post('/api/planning/run_step',headers=headers,json={'ct_image_path':selected['path'],'step':'full',
        'planning_reference_image_id':first})
    assert relative.status_code==202,relative.get_data(as_text=True)
    foreign=client.post('/api/planning/run_step',headers={**headers,'X-BrachyBot-Language':'zh'},
        json={'ct_image_path':selected['path'],'planning_reference_image_id':second,'step':'full'})
    assert foreign.status_code==400
    assert foreign.get_json()['code']=='planning_reference_input_mismatch'
    assert '规划参考' in foreign.get_json()['error']
    empty_foreign=client.post('/api/planning/run_step',headers=other_headers,
        json={'ct_image_path':reference,'step':'full'})
    assert empty_foreign.status_code==400
    assert empty_foreign.get_json()['code']=='planning_reference_input_mismatch'

    # Transport-only unsuccessful producer: a failed/clarification response
    # must not create a completed clinical-operation checkpoint.
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    monkeypatch.setattr(ChatWorkflowMixin, 'run_preoperative_plan',
        lambda self, **kwargs: {'success': False, 'clarification_required': True,
                               'error': 'Explicit software fixture: tumor type required'})
    failed_preop = client.post('/api/plan/preoperative', headers=headers,
        json={'ct_path': selected['path'], 'planning_reference_image_id': first})
    assert failed_preop.status_code == 200, failed_preop.get_data(as_text=True)
    assert failed_preop.get_json()['success'] is False
    latest = raw.latest_timepoint_operation(uid, sid, tid)
    assert latest['state'] == 'interrupted'
    assert latest['checkpoint']['completed'] is False
