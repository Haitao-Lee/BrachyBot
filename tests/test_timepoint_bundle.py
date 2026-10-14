"""Complete real store exchange and negative archive controls."""
import json
import os
import zipfile

import numpy as np
import pytest
from web.timepoint_bundle import export_bundle, import_bundle
from web.timepoints import TimepointIntegrityError
from web.workspace_store import WorkspaceStore


@pytest.fixture(autouse=True)
def platform_directory_durability(monkeypatch):
    # Windows has no directory fsync. File/SQLite writes remain real; POSIX
    # directory durability is intentionally outside this portable test claim.
    if os.name == "nt":
        monkeypatch.setattr(WorkspaceStore, "_fsync_directory", staticmethod(lambda path: None))


def test_actual_multitimepoint_graph_and_numerical_sidecars_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    uid = store.create_user("bundle_owner", "synthetic-hash")["id"]
    sid = store.create_session(uid, "Patient graph").id
    first = store.migrate_default_timepoint(uid, sid)["default_timepoint_id"]
    second = store.create_timepoint(uid, sid, "Intraoperative", stage="intraoperative",
        preoperative_timepoint_id=first, expected_revision=store.list_timepoints(uid, sid)["catalog_revision"])["created_timepoint_id"]
    for tid, value in ((first, 2), (second, 7)):
        before = store.load_timepoint_snapshot(uid, sid, tid)
        store.save_timepoint_results(uid, sid, tid, {"ct_data": np.full((12, 15, 18), value, np.int16),
            "ct_spacing": (1., 1., 1.), "ct_origin": (0., 0., 0.), "ct_direction": (1.,0.,0.,0.,1.,0.,0.,0.,1.)},
            expected_clinical_revision=before["timepoint_clinical_revision"])
    store.save_snapshot_patch(uid, sid, {"chat": {"messages": [{"id": "shared", "content": "Conversation", "type": "user"}]}})
    source = tmp_path / "full.zip"
    export_bundle(store, uid, sid, source)
    entry = import_bundle(store, uid, source)
    assert entry.id != sid
    catalog = store.list_timepoints(uid, entry.id)
    assert catalog["items"][second]["preoperative_timepoint_id"] == first
    for tid, value in ((first, 2), (second, 7)):
        restored = store.load_timepoint_snapshot(uid, entry.id, tid, decode_arrays=True)
        assert np.all(restored["agent"]["planning_results"]["ct_data"] == value)
        assert restored["chat"]["messages"][0]["content"] == "Conversation"
    assert store.load_timepoint_snapshot(uid, sid, first, decode_arrays=True)["agent"]["planning_results"]["ct_data"].min() == 2


def test_archive_extra_path_is_rejected_before_creating_patient(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    uid = store.create_user("safe_bundle_owner", "synthetic-hash")["id"]
    sid = store.create_session(uid, "Before").id
    store.migrate_default_timepoint(uid, sid)
    source = tmp_path / "unsafe.zip"
    export_bundle(store, uid, sid, source)
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr("workspace/../../outside.json", "{}")
    before = len(store.list_sessions(uid))
    with pytest.raises(TimepointIntegrityError):
        import_bundle(store, uid, source)
    assert len(store.list_sessions(uid)) == before


def test_actual_implant_immutable_head_operation_and_reviews_cold_load_after_exchange(tmp_path, monkeypatch):
    from uuid import uuid4
    import SimpleITK as sitk
    from agent_runtime.core import AgentMemory
    from utils.implant_reconstruction import ImageReference, ImageGeometry, OrientationProfile, SeedAxisReconstruction
    from web.implant_service import ImplantScope, ImplantService
    from tool_factory.seed_seg.seedfinder_adapter import sha256_file
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    uid = store.create_user('deep_bundle_owner', 'synthetic-hash')['id']
    sid = store.create_session(uid, 'Immutable implanted graph').id
    tid = store.migrate_default_timepoint(uid, sid)['default_timepoint_id']
    root = store.workspace_root(uid, sid)
    image = sitk.GetImageFromArray(np.full((4,5,6), -500, np.int16))
    source = root / 'inputs' / 'phantom.nii.gz'
    source.parent.mkdir(exist_ok=True)
    sitk.WriteImage(image, str(source))
    ref = ImageReference(sid, tid, uuid4().hex, 1, sha256_file(source), ImageGeometry.from_image(image))
    reconstruction = SeedAxisReconstruction(observation_set_id=str(uuid4()), revision_id=str(uuid4()), revision=1, parent_revision_id=None,
        image_ref=ref, observations=(), deposition_lines=(), profile=OrientationProfile(),
        provider_id='manual-observation-review', provider_version='1',
        coverage_status='complete', set_reviewer_id=uid, set_review_evidence='Reviewed synthetic empty phantom')
    service = ImplantService(ImplantScope(uid, sid, tid, str(root)), AgentMemory(sid))
    # Use the actual immutable publication and typed cold reader, with a human
    # authored empty set. No detector/model replacement is part of this test.
    record = service._envelope(reconstruction, [], None, uuid4().hex)
    with service._journal() as index:
        service._publish(index, record, None)
    assert service.get()['record']['reconstruction']['dose_input_ready'] is True
    store.save_timepoint_results(uid, sid, tid, {'implanted_seed_reconstruction': {
        'schema_version':1, 'by_timepoint': {tid:{'current': record}}}},
        expected_clinical_revision=store.load_timepoint_snapshot(uid,sid,tid)['timepoint_clinical_revision'])
    oid = uuid4().hex
    store.save_timepoint_operation(uid,sid,tid,oid,{'state':'running','kind':'synthetic-recovery-test'})
    archive = tmp_path / 'actual-head.zip'
    export_bundle(store, uid, sid, archive)
    imported = import_bundle(store, uid, archive)
    restarted = WorkspaceStore(store.runtime_dir)
    imported_root = restarted.workspace_root(uid, imported.id)
    cold = ImplantService(ImplantScope(uid, imported.id, tid, str(imported_root)), AgentMemory(imported.id)).get()
    assert cold['record']['scope']['session_id'] == imported.id
    assert cold['record']['reconstruction']['review_status'] == 'review_needed'
    assert cold['record']['reconstruction']['dose_input_ready'] is False
    recovered = restarted.load_timepoint_snapshot(uid, imported.id, tid)
    assert recovered['operation']['state'] == 'interrupted'
    assert recovered['operation']['auto_resumed'] is False
    assert service.get()['record']['reconstruction']['dose_input_ready'] is True


def test_real_ui_state_dictionaries_are_not_interpreted_as_job_enums(tmp_path,monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    store=WorkspaceStore(tmp_path/'runtime')
    uid=store.create_user('ui_bundle','synthetic-hash')['id']
    sid=store.create_session(uid,'UI graph case').id
    tid=store.migrate_default_timepoint(uid,sid)['default_timepoint_id']
    state=store.load_timepoint_snapshot(uid,sid,tid)
    ui={'state':{'viewer':{'settings':{'window':570,'level':51}},'status':{'available':True}},
        'bridge':{'state':{'ui_operation_catalog':[{'target':'viewer.angle','source_set':{'choices':['total']}}]}}}
    store.save_timepoint_patch(uid,sid,tid,{'ui':ui},expected_state_revision=state['timepoint_state_revision'])
    archive=tmp_path/'real-ui.zip';export_bundle(store,uid,sid,archive)
    restored=import_bundle(store,uid,archive)
    saved=store.load_timepoint_snapshot(uid,restored.id,tid)
    assert saved['ui']['state']['viewer']['settings'] == {'window':570,'level':51}
    assert saved['ui']['state']['status'] == {'available':True}
    assert saved['ui']['bridge']['state']['ui_operation_catalog'][0]['source_set'] == {'choices':['total']}
