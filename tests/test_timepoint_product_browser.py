"""Full product assets + actual HTTP/store/image decoding; no mocked API."""
from pathlib import Path
import os
import subprocess
import shutil
import threading

import numpy as np
import SimpleITK as sitk
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_actual_product_two_timepoints_upload_switch_and_cold_restore(tmp_path, monkeypatch):
    from werkzeug.serving import make_server
    from web.server import create_app
    node = os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    module = os.environ.get('PLAYWRIGHT_MODULE', 'playwright')
    if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
        pytest.skip('Full-product browser acceptance requires installed Playwright and Node')
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    for name in ('BRACHYBOT_API_KEY', 'BRACHYBOT_REQUIRE_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    paths = []
    for name, shape, value in [('preoperative.nii.gz', (12, 18, 20), 100), ('intraoperative.nii.gz', (14, 16, 22), 400)]:
        pixels = np.full(shape, -1000, dtype=np.int16)
        pixels[2:-2, 2:-2, 2:-2] = value
        image = sitk.GetImageFromArray(pixels)
        image.SetSpacing((.8, 1.1, 1.6))
        path = tmp_path / name
        sitk.WriteImage(image, str(path))
        paths.append(path)
    app = create_app({'runtime_dir': str(tmp_path / 'runtime'), 'secret_key': 'synthetic-product-browser-secret',
                      'workspace_maintenance': False})
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run([node, str(ROOT / 'tests/timepoint-product-browser.test.cjs'),
            f'http://127.0.0.1:{server.server_port}', *(str(path) for path in paths)],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Full-product two-timepoint upload, switch and cold restoration passed.' in result.stdout
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_actual_supplied_model_full_page_implant_edit_and_dose(tmp_path,monkeypatch):
    source=os.environ.get('BRACHYBOT_MODEL_BROWSER_INPUT')
    if not source or not Path(source).is_file():
        pytest.skip('Supplied-model product acceptance requires the explicit isolated demo acquisition')
    from werkzeug.serving import make_server
    from web.server import create_app
    node=os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    assert node
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    for key in ('BRACHYBOT_API_KEY','BRACHYBOT_REQUIRE_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key,raising=False)
    app=create_app({'runtime_dir':str(tmp_path/'runtime'),'secret_key':'synthetic-real-model-browser',
        'workspace_maintenance':False})
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([node,str(ROOT/'tests/implanted-product-browser.test.cjs'),
            f'http://127.0.0.1:{server.server_port}',source],cwd=ROOT,capture_output=True,text=True,timeout=480)
        assert result.returncode==0,result.stdout+result.stderr
        assert 'Actual model + 2D/3D/tree presentation' in result.stdout
    finally:
        server.shutdown();thread.join(timeout=5)


@pytest.mark.parametrize('complete_reviewed_baseline', [False, True])
def test_actual_native_intraoperative_entry_detects_then_pauses_for_review(tmp_path,monkeypatch,complete_reviewed_baseline):
    """Actual model/route/page; source-plan and masks are declared synthetic inputs."""
    source=os.environ.get('BRACHYBOT_MODEL_BROWSER_INPUT')
    if not source or not Path(source).is_file():
        pytest.skip('Native intraoperative model acceptance requires the explicit isolated demo')
    from io import BytesIO
    from werkzeug.serving import make_server
    from web.server import create_app
    from web.timepoint_images import TimepointImageService
    node=os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    assert node
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    for key in ('BRACHYBOT_API_KEY','BRACHYBOT_REQUIRE_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key,raising=False)
    app=create_app({'runtime_dir':str(tmp_path/'runtime'),'secret_key':'synthetic-native-intraoperative','workspace_maintenance':False})
    client=app.test_client()
    auth=client.post('/api/auth/register',json={'username':'native_intraoperative_owner','password':'synthetic-browser-password-123'}).get_json()
    sid,uid=auth['active_session_id'],auth['user']['id']
    preop=client.get(f'/api/sessions/{sid}/timepoints').get_json()['default_timepoint_id']
    raw=getattr(app.extensions['brachybot_workspace_store'],'raw',app.extensions['brachybot_workspace_store'])
    target=raw.create_timepoint(uid,sid,'Current software acquisition',stage='intraoperative',preoperative_timepoint_id=preop,
        expected_revision=raw.list_timepoints(uid,sid)['catalog_revision'])['created_timepoint_id']
    for tid in (preop,target):
        headers={'X-CSRF-Token':auth['csrf_token'],'X-BrachyBot-Session':sid,'X-BrachyBot-Timepoint':tid}
        uploaded=client.post('/api/upload',headers=headers,data={'file':(BytesIO(Path(source).read_bytes()),Path(source).name)},content_type='multipart/form-data')
        assert uploaded.status_code==200
        loaded=client.post('/api/viewer/load',headers=headers,json={'ct_path':uploaded.get_json()['path']})
        assert loaded.status_code==200,loaded.get_data(as_text=True)
    reference=TimepointImageService(raw).planning_reference_bridge(uid,sid,target)
    shape=tuple(reference['ct_data'].shape)
    mask=np.zeros(shape,np.uint8)
    mid=tuple(n//2 for n in shape);mask[mid]=1
    current=raw.load_timepoint_snapshot(uid,sid,target)
    raw.save_timepoint_results(uid,sid,target,{'ctv_array':mask,'ctv_binary_array':mask,'oar_array':np.zeros(shape,np.uint8),
        'ctv_label_map':{1:'Synthetic software target'},'ctv_source':'uploaded_mask','oar_source':'uploaded_mask'},
        expected_clinical_revision=current['timepoint_clinical_revision'])
    original=raw.load_timepoint_snapshot(uid,sid,preop)
    center=reference['ct_image'].TransformIndexToPhysicalPoint(tuple(int(i) for i in mid[::-1]))
    raw.save_timepoint_results(uid,sid,preop,{'manual_seeds':[{'id':'synthetic-source-plan-input','position':list(center),'direction':[1.,0.,0.]}],
        'software_fixture_provenance':'Synthetic nonempty source-plan input; not an optimized clinical plan'},
        expected_clinical_revision=original['timepoint_clinical_revision'])
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([node,str(ROOT/'tests/native-intraoperative-product-browser.test.cjs'),
            f'http://127.0.0.1:{server.server_port}',target, 'complete' if complete_reviewed_baseline else 'pause'],
            cwd=ROOT,capture_output=True,text=True,timeout=420)
        assert result.returncode==0,result.stdout+result.stderr
        assert 'Actual native intraoperative pipeline' in result.stdout
    finally:
        server.shutdown();thread.join(timeout=5)


def test_actual_product_guide_registration_and_review_on_synthetic_phantom(tmp_path,monkeypatch):
    from io import BytesIO
    from werkzeug.serving import make_server
    from web.server import create_app
    from test_guide_bore_manifest import tube_guide
    from test_guide_registration_cpu import phantom
    from web.guide_registration import owned_service
    from web.timepoint_images import TimepointImageService
    from web.timepoint_resources import capture_resources, resource_state
    from web.workspace_store import WorkspaceStore
    node=os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    if not node or subprocess.run([node,'-e','require(process.argv[1])',os.environ.get('PLAYWRIGHT_MODULE','playwright')],capture_output=True).returncode:
        pytest.skip('Actual guide product acceptance requires Node and Playwright')
    if os.name == 'nt':
        # Test-only POSIX accommodations; these do not validate Windows
        # directory durability or Linux-style worker liveness probes.
        monkeypatch.setattr(WorkspaceStore,'_fsync_directory',staticmethod(lambda path: None))
        monkeypatch.setattr('web.guide_registration._process_alive',lambda pid: pid == os.getpid())
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    for key in ('BRACHYBOT_API_KEY','BRACHYBOT_REQUIRE_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key,raising=False)
    app=create_app({'runtime_dir':str(tmp_path/'runtime'),'secret_key':'synthetic-guide-product-secret','workspace_maintenance':False})
    client=app.test_client()
    auth=client.post('/api/auth/register',json={'username':'guide_product_owner','password':'synthetic-browser-password-123'}).get_json()
    sid,owner=auth['active_session_id'],auth['user']['id']
    source=client.get(f'/api/sessions/{sid}/timepoints').get_json()['default_timepoint_id']
    store=getattr(app.extensions['brachybot_workspace_store'],'raw',app.extensions['brachybot_workspace_store'])
    target=store.create_timepoint(owner,sid,'Synthetic current image',stage='intraoperative',
        preoperative_timepoint_id=source,expected_revision=store.list_timepoints(owner,sid)['catalog_revision'])['created_timepoint_id']
    path=tmp_path/'synthetic-phantom.nii.gz';sitk.WriteImage(phantom(),str(path))
    for tid in (source,target):
        headers={'X-CSRF-Token':auth['csrf_token'],'X-BrachyBot-Session':sid,'X-BrachyBot-Timepoint':tid}
        uploaded=client.post('/api/upload',headers=headers,data={'file':(BytesIO(path.read_bytes()),path.name)},content_type='multipart/form-data')
        assert uploaded.status_code==200,uploaded.get_data(as_text=True)
        loaded=client.post('/api/viewer/load',headers=headers,json={'ct_path':uploaded.get_json()['path']})
        assert loaded.status_code==200,loaded.get_data(as_text=True)
    current=store.load_timepoint_snapshot(owner,sid,source)
    collection=current['image_collection']
    assert len(collection['images']) == 1
    source_image_id=collection['planning_reference_image_id']
    # First native selection archives the pre-upload state too. Preserve it:
    # the legacy no-parent fallback must not be used for this fixture.
    assert 'unassigned' in current['image_resources']
    assert current['image_resources']['unassigned']['reference_image_id'] is None
    bridge=TimepointImageService(store).planning_reference_bridge(owner,sid,source)
    resources=capture_resources(bridge.get,bridge['ct_image'])
    planning_id='synthetic-guide-parent'
    guide=tube_guide();guide.update(version=1,status='ready',parameters={},planning_id=planning_id,
        source_plan_signature='synthetic-phantom-plan')
    # The mesh/Planning remain declared software fixtures. Capture the actual
    # owned upload's image leaf using the same function as normal Planning.
    parent={'planning_id':planning_id,'surgical_guide':guide,
        'timepoint_resource_state':resource_state(None,resources)}
    store.save_timepoint_results(owner,sid,source,{'surgical_guide':guide,
        'active_planning_id':planning_id,'planning_run:'+planning_id:parent},
        expected_clinical_revision=current['timepoint_clinical_revision'])
    service=owned_service(store,owner,sid)
    _,provenance=service._guide_source_image(service._snapshot(source),guide)
    assert provenance['policy'] == 'saved_parent_image_fingerprint'
    assert provenance['original_acquisition_verified'] is True
    assert provenance['parent_image_fingerprint'] == resources['image']
    assert provenance['image']['image_id'] == source_image_id
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([node,str(ROOT/'tests/guide-product-browser.test.cjs'),f'http://127.0.0.1:{server.server_port}',target],
            cwd=ROOT,capture_output=True,text=True,timeout=240)
        assert result.returncode==0,result.stdout+result.stderr
        assert 'Actual product guide CPU registration' in result.stdout
        candidates=store.load_timepoint_snapshot(owner,sid,target)['agent']['planning_results']['guide_placement_candidates']
        assert len(candidates) == 1
        candidate=next(iter(candidates.values()))
        assert candidate['review_state'] == 'rejected'
        assert candidate['evidence']['input_readset']['source_provenance'] == provenance
        assert store.load_timepoint_snapshot(owner,sid,source)['image_collection']['planning_reference_image_id'] == source_image_id
    finally:
        server.shutdown();thread.join(timeout=5)

