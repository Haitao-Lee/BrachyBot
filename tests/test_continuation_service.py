"""Compose actual review DTOs, source binding and durable scoped baseline state."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import hashlib
import numpy as np
import pytest
import SimpleITK as sitk

from agent_runtime.core import AgentMemory
from utils.implant_reconstruction import (ImageReference, ImageGeometry, SeedDetection, SeedDimensions,
    PhysicalPCAOrientationProvider, ObservationReview, review_observations)
from web.continuation_service import ContinuationPreparationService, ContinuationSourceContract, candidate_on_planning_grid
from web.guide_placement import BoreValidationProfile
from web.workspace_store import WorkspaceStore
from web.timepoints import TimepointConflict


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    owner = store.create_user("continuation_owner", "synthetic-hash")["id"]
    sid = store.create_session(owner, "Synthetic continuation").id
    def create(name, **kwargs):
        return store.create_timepoint(owner, sid, name,
            expected_revision=store.list_timepoints(owner, sid)["catalog_revision"], **kwargs)["created_timepoint_id"]
    source = create("Source")
    target = create("Current", stage="intraoperative", preoperative_timepoint_id=source)
    image = sitk.DICOMOrient(sitk.GetImageFromArray(np.zeros((8,8,8), np.float32)), "LPI")
    root = store.workspace_root(owner, sid, create=True)
    path = root / "inputs" / "current-image.nii.gz"
    sitk.WriteImage(image, str(path))
    image = sitk.ReadImage(str(path))
    ref = ImageReference(sid, target, uuid4().hex, 1, hashlib.sha256(path.read_bytes()).hexdigest(), ImageGeometry.from_image(image))
    observed = PhysicalPCAOrientationProvider().estimate_seed_axes(ref, image,
        [SeedDetection("detected-1", (4.,4.,3.))], dimensions=SeedDimensions("synthetic-source", 1., .4))
    reviewed = review_observations(observed, [ObservationReview("detected-1", "accepted", "synthetic axis review",
        corrected_axis_lps=(0,0,1))], reviewer_id="synthetic-reviewer", coverage_status="complete",
        set_review_evidence="synthetic scan coverage")
    catalog = {"schema_version": 1, "by_timepoint": {target: {"current": {
        "preoperative_timepoint_id": source, "reconstruction": reviewed.to_dict(),
    }}}}
    values = {"ct_path": str(path), "ct_data": sitk.GetArrayFromImage(image), "ct_spacing": image.GetSpacing(),
        "ct_origin": image.GetOrigin(), "ct_direction": image.GetDirection(), "ctv_binary_array": np.ones((8,8,8), np.uint8),
        "oar_array": np.zeros((8,8,8), np.uint8), "implanted_seed_reconstruction": catalog}
    store.save_timepoint_results(owner, sid, target, values, expected_state_revision=0)
    model_path = tmp_path / "synthetic-checkpoint-never-loaded.pth"
    model_path.write_bytes(b"synthetic bytes; never deserialized")
    contract = ContinuationSourceContract("synthetic-calibration-v1", "synthetic-source", .5, 37.,
        hashlib.sha256(model_path.read_bytes()).hexdigest(), "synthetic-reviewer", "synthetic model/source review", 1., .4)
    profile = BoreValidationProfile("synthetic-mechanical-v1", .2, 1., .1, 150.)
    agent = SimpleNamespace(config={"_workspace_owner_id": owner, "_workspace_session_id": sid},
        _workspace_store=store, memory=AgentMemory(sid))
    return store, owner, sid, source, target, image, reviewed, model_path, contract, profile, agent


def prepare(owned, monkeypatch, **kwargs):
    from tool_factory.seed_plan import model_support, planning_pipeline
    store, owner, sid, source, target, image, reviewed, path, contract, profile, agent = owned
    monkeypatch.setattr(planning_pipeline, "_resample_for_planning", lambda *a, **k: (
        image, np.ones((8,8,8), np.uint8), np.zeros((8,8,8), np.uint8)))
    captured = {}
    def dose(seeds, *args, **options):
        captured.update(options)
        assert options["strict"] is True
        return np.full((8,8,8), .6), seeds
    monkeypatch.setattr(model_support, "compute_world_seed_dose_grid", dose)
    result = ContinuationPreparationService(agent).prepare(target_timepoint_id=target,
        observation_revision_id=reviewed.revision_id, source_contract=contract, needle_profile=profile,
        dose_model_path=path, dose_model=object(), **kwargs)
    return result, captured


def test_actual_preparation_persists_fixed_observation_and_source_once(owned, monkeypatch):
    result, captured = prepare(owned, monkeypatch)
    store, owner, sid, source, target, image, reviewed, path, contract, profile, agent = owned
    assert result["fixed_seed_count"] == 1
    assert result["dose_basis"] == "projected_total_source_dose"
    assert np.allclose(result["baseline"].dose_model, .6)
    state = store.load_timepoint_snapshot(owner, sid, target, decode_arrays=True)["agent"]["planning_results"]
    assert state["continuation_baseline_record"]["observation_revision_id"] == reviewed.revision_id
    assert state["continuation_source_contract"]["dose_scale_gy"] == 37.
    assert "continuation_baseline_record" not in store.load_timepoint_snapshot(owner, sid, source)["agent"]["planning_results"]
    from tool_factory.seed_plan.continuation_support import resolve_baseline
    restored = SimpleNamespace(memory=SimpleNamespace(retrieve=state.get))
    assert np.allclose(resolve_baseline(restored, current_image=image).dose_model, .6)


@pytest.mark.parametrize('key,value',[('in_situ_needles',[{'needle_id':'current-needle'}]),
    ('continuation_review_profile',{'needle_radius_mm':.7}),('guide_channel_states',{'bore_1':'blocked'}),
    ('guide_placement',{'placement_id':'different-rigid-pose'})])
def test_geometry_changes_cannot_reuse_prepared_candidate_paths(owned,monkeypatch,key,value):
    prepare(owned,monkeypatch)
    store,owner,sid,source,target,image,*_=owned
    state=store.load_timepoint_snapshot(owner,sid,target,decode_arrays=True)['agent']['planning_results']
    state[key]=value
    from tool_factory.seed_plan.continuation_support import resolve_baseline
    with pytest.raises(ValueError,match='needle constraints changed'):
        resolve_baseline(SimpleNamespace(memory=SimpleNamespace(retrieve=state.get)),current_image=image)


def test_traversability_changes_invalidate_paths_but_color_changes_do_not(owned,monkeypatch):
    store,owner,sid,source,target,image,*_=owned
    state=store.load_timepoint_snapshot(owner,sid,target)
    override={'organ_1':{'classification':'oar','target_label':1,'traversability':'traversable','color':'#22d3ee'}}
    store.save_timepoint_results(owner,sid,target,{'structure_overrides':override},
        expected_clinical_revision=state['timepoint_clinical_revision'])
    prepare(owned,monkeypatch)
    state=store.load_timepoint_snapshot(owner,sid,target,decode_arrays=True)['agent']['planning_results']
    from tool_factory.seed_plan.continuation_support import resolve_baseline
    state['structure_overrides']['organ_1']['color']='#ff00aa'
    assert resolve_baseline(SimpleNamespace(memory=SimpleNamespace(retrieve=state.get)),current_image=image)
    state['structure_overrides']['organ_1']['traversability']='non_traversable'
    with pytest.raises(ValueError,match='CTV/OAR/reference changed'):
        resolve_baseline(SimpleNamespace(memory=SimpleNamespace(retrieve=state.get)),current_image=image)


@pytest.mark.parametrize("key,new_value", [("dose_scale_gy", 38.), ("source_strength_u", 1.),
                                           ("temporal_basis", "elapsed_delivered_gy")])
def test_source_change_invalidates_baseline_even_without_new_optimization(owned, monkeypatch, key, new_value):
    prepare(owned, monkeypatch)
    store, owner, sid, source, target, image, reviewed, path, contract, profile, agent = owned
    state = store.load_timepoint_snapshot(owner, sid, target, decode_arrays=True)["agent"]["planning_results"]
    state["continuation_source_contract"][key] = new_value
    from tool_factory.seed_plan.continuation_support import resolve_baseline
    with pytest.raises(ValueError, match="contract changed"):
        resolve_baseline(SimpleNamespace(memory=SimpleNamespace(retrieve=state.get)), current_image=image)


def test_unreviewed_detection_cannot_become_a_fixed_dose_baseline(owned, monkeypatch):
    store, owner, sid, source, target, image, reviewed, path, contract, profile, agent = owned
    unreviewed = replace(reviewed, coverage_status="partial")
    catalog = {"schema_version": 1, "by_timepoint": {target: {"current": {
        "preoperative_timepoint_id": source, "reconstruction": unreviewed.to_dict()}}}}
    store.save_timepoint_results(owner, sid, target, {"implanted_seed_reconstruction": catalog}, expected_clinical_revision=1)
    with pytest.raises(ValueError, match="Review the exact"):
        prepare(owned, monkeypatch)


def test_changed_checkpoint_and_missing_oar_do_not_publish_baseline(owned, monkeypatch):
    store, owner, sid, source, target, image, reviewed, path, contract, profile, agent = owned
    path.write_bytes(b"changed checkpoint")
    with pytest.raises(ValueError, match="checkpoint differs"):
        prepare(owned, monkeypatch)
    assert store.list_timepoints(owner, sid)["items"][target]["clinical_revision"] == 1


def test_source_contract_does_not_confuse_total_source_dose_with_elapsed_dose(owned):
    contract = owned[8]
    with pytest.raises(ValueError, match="elapsed delivered"):
        replace(contract, temporal_basis="elapsed_delivered_gy")


def test_old_guide_pose_on_identical_grid_cannot_be_bound_to_new_ct_revision(owned, monkeypatch):
    # Matching grid/frame or a supplied target-image dictionary is not enough.
    # Compare against the actual saved current-CT content-derived identity.
    with pytest.raises(ValueError, match="current CT content revision"):
        prepare(owned, monkeypatch, guide={"version": 1}, accepted_placement={"review_state": "accepted"},
                target_image={"image_id": "claimed-old-image", "image_revision": "claimed-old-revision", "geometry_id": "same-grid"})


def test_continuous_bore_intervals_retain_physical_axis_and_tip_extent():
    image = sitk.GetImageFromArray(np.zeros((30,30,30)))
    image.SetSpacing((.5,1.,2.))
    candidate = {"candidate_id": "actual-path", "bore_id": "actual-bore", "axis_lps": [0,0,1],
        "tip_lps_mm": [5,5,12.2], "target_intervals_from_inner_mm": [[4.5,7.5],[9.5,13.5]]}
    bore = {"inner_lps_mm": [5,5,0]}
    path = candidate_on_planning_grid(candidate, bore, image)
    assert path.bore_id == "actual-bore"
    assert path.geometry[0] == (2.25, 5., 10.)
    assert path.geometry[2] == (1.5, 1.3499999999999996)
    assert path.geometry[3] == (0., 1.)


def test_anatomy_changes_reuse_source_cnn_but_require_new_baseline_context(owned, monkeypatch):
    from tool_factory.seed_plan import model_support
    from tool_factory.seed_plan.continuation_support import resolve_baseline
    result, _ = prepare(owned, monkeypatch)
    store, owner, sid, source, target, image, reviewed, path, contract, profile, agent = owned
    state = store.load_timepoint_snapshot(owner, sid, target, decode_arrays=True)['agent']['planning_results']
    state['oar_array'] = None
    with pytest.raises(ValueError, match='CTV/OAR/reference'):
        resolve_baseline(SimpleNamespace(memory=SimpleNamespace(retrieve=state.get)), current_image=image)
    changed = np.zeros((8,8,8),np.uint8);changed[0]=1
    store.save_timepoint_results(owner,sid,target,{'oar_array':changed},
        expected_clinical_revision=result['saved_clinical_revision'])
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',lambda *a,**k:pytest.fail('Unchanged source CNN must be reused'))
    refreshed = ContinuationPreparationService(agent).prepare(target_timepoint_id=target,
        observation_revision_id=reviewed.revision_id,source_contract=contract,needle_profile=profile,
        dose_model_path=path,dose_model=object())
    assert refreshed['reused_implanted_dose']
    assert np.allclose(refreshed['baseline'].dose_model,.6)


def test_nominal_model_strength_never_invents_absolute_u(owned):
    contract = replace(owned[8],source_strength_basis='model_nominal_relative',source_strength_u=None)
    assert contract.source_strength_u is None
    with pytest.raises(ValueError,match='invent'):
        replace(contract,source_strength_u=.5)
