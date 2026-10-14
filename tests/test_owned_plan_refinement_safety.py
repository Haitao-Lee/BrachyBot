"""Numerical proposal safety through the real owned adapter and registered tool.

No model substitutes: boundary traps only prove that proposal work never enters
planning/inference. These tests establish advisory isolation, not clinical or
channel feasibility. Canonical capsule checks establish the negative geometry.
"""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from test_agent_timepoint_boundary import owned, activate, grant
from agent_runtime.timepoint_tools import owned_tool_arguments, owned_tool_execution
from agent_runtime.core import ToolResultPipeline
from plans.continuation import (CandidatePath, ContinuationBaseline, FixedSeed,
                                array_sha256, grid_signature, voxel_world)
from tool_factory.plan_quality.plan_refinement import PlanRefinementTool
from tool_factory.seed_plan.continuation_support import baseline_record
from web.timepoints import TimepointError


@pytest.fixture
def tmp_path(tmp_path_factory):
    if os.name == "nt":
        # Durable timepoint filenames exceed MAX_PATH under pytest's default
        # long test-name directories. Use one short, isolated temporary root.
        with tempfile.TemporaryDirectory(prefix="prf-", dir=Path.home()) as folder:
            yield Path(folder)
    else:
        yield tmp_path_factory.mktemp("refinement")


@pytest.fixture(autouse=True)
def windows_test_directory_durability(monkeypatch):
    # Windows cannot os.open/fsync a directory through the POSIX API. This
    # fixture only adapts that unrelated temporary-store durability boundary;
    # the real scope, hydration, adapter and numerical tool run unchanged.
    # These tests make no claims about directory durability on Windows.
    if os.name == "nt":
        monkeypatch.setattr("web.workspace_store.WorkspaceStore._fsync_directory",
                            staticmethod(lambda path: None))


@pytest.fixture
def refinement(owned):
    """Real authenticated detached runtime; all clinical data are synthetic."""
    raw, owner, session, _, target, root = owned
    root.registry.register(PlanRefinementTool())
    runtime = activate(owned, target, message="Propose refinement without computing a plan")
    runtime._waiter(True)
    memory = runtime.view.memory
    shape = (9, 9, 9)
    ctv = np.zeros(shape, np.uint8)
    ctv[2, 2, 2] = ctv[6, 6, 6] = 1
    dose = np.full(shape, 100., np.float32)
    dose[2, 2, 2], dose[6, 6, 6] = 20., 50.
    image = sitk.GetImageFromArray(np.zeros(shape, np.int16))
    image.SetSpacing((2., 3., 4.))
    image.SetOrigin((101., 203., 305.))
    image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
    plan = [[[101., 203., 305.], [1., 0., 0.]]]
    for key, value in {
        "ct_image": image, "ct_spacing": list(image.GetSpacing()),
        "ctv_array": ctv, "ctv_binary_array": ctv,
        "oar_array": np.zeros(shape, np.uint8),
        "dose_distribution_physical_gy": dose,
        "dose_metrics": {"prescription_gy": 100.},
        "plan_config": {"prescription_gy": 100.},
        "seed_plan_serialized": plan,
    }.items():
        memory.store(key, value)
    state = raw.load_timepoint_snapshot(owner, session, target)
    yield runtime, plan, state["timepoint_clinical_revision"]
    assert raw.load_timepoint_snapshot(owner, session, target)["timepoint_clinical_revision"] == state["timepoint_clinical_revision"]
    runtime.close()


def propose(runtime, **overrides):
    params = {"target_v100": .9, "max_iterations": 3, **overrides}
    grant(runtime, "plan_refinement", params)
    args = owned_tool_arguments(runtime.view, "plan_refinement", params)
    with owned_tool_execution(runtime.view):
        result = runtime.view.registry.execute("plan_refinement", **args)
    return result, args


def assert_advisory(result, plan):
    assert result.success, result.error
    assert result.data == plan
    assert result.metadata["refined_plan"] == plan
    assert result.metadata["candidate_seeds"] == []
    assert result.metadata["channel_proposals"] == []
    assert result.metadata["candidate_only"] is True
    assert result.metadata["feasibility_validated"] is False
    assert result.metadata["clinical_use_approved"] is False
    assert result.metadata["refined_plan_is_accepted"] is False
    assert result.metadata["plan_changed"] is False
    assert result.metadata["outside_guide_attempted"] is False
    assert result.metadata["iterations_used"] == 0
    assert result.metadata["requires_dose_recalculation"] is False
    assert result.metadata["improved_metrics"]["final_v100"] is None
    assert result.metadata["improved_metrics"]["dose_engine_required"] is None


def test_owned_positive_ranks_actual_total_gy_voxels_without_physical_seed_claim(refinement):
    runtime, plan, _ = refinement
    result, args = propose(runtime)
    assert_advisory(result, plan)
    locations = result.metadata["advisory_locations"]
    assert [p["index_zyx"] for p in locations] == [[2., 2., 2.], [6., 6., 6.]]
    assert [p["dose"] for p in locations] == [20., 50.]
    assert all(p["coordinate_frame"] == "dose_array_zyx" and not p["is_seed"] for p in locations)
    assert all(p["validation_status"] == "unvalidated_advisory" for p in locations)
    assert result.metadata["metrics_before"]["d90"] == pytest.approx(23.)
    assert result.metadata["metrics_before"]["v100"] == 0.
    # An oblique anisotropic physical frame cannot be confused with ZYX.
    assert not np.allclose(voxel_world(runtime.view.memory.retrieve("ct_image"), [2,2,2]), [2,2,2])
    assert args["_agent"] is runtime.view
    assert args["prescribed_dose"] == 100.
    assert result.metadata["dose_units"] == "physical_gy"
    assert result.metadata["dose_basis"] == "current_total"
    for formatted in (result.to_dict()["message"], ToolResultPipeline.format("plan_refinement", result)):
        assert "current total dose in Gy" in formatted
        assert "current plan is unmodified" in formatted
        assert "No feasible seed or channel" in formatted
        assert "ZYX" in formatted
    result.data[0][0][0] = -999.
    assert runtime.view.memory.retrieve("seed_plan_serialized")[0][0][0] == 101.


def test_owned_provider_arrays_and_policy_cannot_replace_saved_input(refinement):
    runtime, plan, _ = refinement
    result, args = propose(runtime, _candidate_only=False, _agent=None,
        current_plan=[], dose_distribution=np.full((1,1,1), 999.),
        ctv_mask=np.ones((1,1,1)), oar_mask=np.ones((1,1,1)))
    assert_advisory(result, plan)
    assert args["_candidate_only"] is True
    assert args["dose_distribution"].shape == (9,9,9)
    assert result.metadata["advisory_count"] == 2


@pytest.mark.parametrize("prescription", [1., 200., None, np.nan, np.inf, True])
def test_owned_rx_override_is_rejected_before_proposal(refinement, prescription):
    runtime, plan, _ = refinement
    with pytest.raises(TimepointError, match="cannot override the current prescription"):
        owned_tool_arguments(runtime.view, "plan_refinement", {
            "prescribed_dose": prescription, "target_v100": .9})
    assert runtime.view.memory.retrieve("seed_plan_serialized") == plan
    assert runtime.view.memory.retrieve("plan_config")["prescription_gy"] == 100.


def test_owned_equal_rx_and_sufficient_coverage_produce_no_location(refinement):
    runtime, plan, _ = refinement
    memory = runtime.view.memory
    memory.store("dose_distribution_physical_gy", np.full((9,9,9), 100., np.float32))
    result, _ = propose(runtime, prescribed_dose=100.)
    assert_advisory(result, plan)
    assert result.metadata["advisory_locations"] == []
    assert result.metadata["metrics_before"]["v100"] == 1.


def test_owned_oar_overlap_is_excluded_without_clearance_grid_computation(refinement, monkeypatch):
    runtime, plan, _ = refinement
    organs = np.zeros((9,9,9), np.uint8)
    organs[2,2,2] = 90
    runtime.view.memory.store("oar_array", organs)
    def forbidden(*args, **kwargs):
        pytest.fail("An advisory proposal must not build a full OAR clearance grid")
    monkeypatch.setattr("scipy.ndimage.distance_transform_edt", forbidden)
    result, _ = propose(runtime)
    assert_advisory(result, plan)
    assert [p["index_zyx"] for p in result.metadata["advisory_locations"]] == [[6.,6.,6.]]
    organs[6,6,6] = 90
    result, _ = propose(runtime)
    assert result.metadata["advisory_locations"] == []


@pytest.mark.parametrize("dose", [np.nan, np.inf, -1.])
def test_owned_nonfinite_or_negative_current_dose_fails(refinement, dose):
    runtime, _, _ = refinement
    array = np.full((9,9,9), 100., np.float32)
    array[2,2,2] = dose
    runtime.view.memory.store("dose_distribution_physical_gy", array)
    with pytest.raises(TimepointError, match="finite nonnegative"):
        owned_tool_arguments(runtime.view, "plan_refinement", {"target_v100": .9})


def test_owned_stale_source_dose_cannot_be_ranked(refinement):
    runtime, _, _ = refinement
    runtime.view.memory.store("artifact_status", {"dose": {"stale": True}})
    with pytest.raises(TimepointError, match="dose is stale"):
        owned_tool_arguments(runtime.view, "plan_refinement", {"target_v100": .9})


@pytest.mark.parametrize("collides", [False, True])
@pytest.mark.parametrize("guide_prepared", [False, True])
def test_fixed_capsule_and_guide_admission_never_become_owned_seed_proposals(
        refinement, collides, guide_prepared):
    runtime, plan, _ = refinement
    memory = runtime.view.memory
    image = memory.retrieve("ct_image")
    trajectory = [[0.,2.,2.], [1.,0.,0.], [8.], [0.], 8.]
    fixed_point = [4.,2.,2.] if collides else [4.,7.,7.]
    fixed = FixedSeed("synthetic-implanted-source", tuple(voxel_world(image, fixed_point)),
                      (0.,0.,1.), 3., .4)
    target = np.ones((9,9,9), bool)
    dose = np.zeros((9,9,9))
    baseline = ContinuationBaseline.create(dose, image, baseline_unit="normalized_model",
        baseline_grid_signature=grid_signature(image), baseline_dose_sha256=array_sha256(dose),
        complete_target_mask=target, dose_scale_gy=100., dose_contract_id="synthetic-source",
        needle_radius_mm=.5, clearance_mm=.2, fixed_seeds=(fixed,),
        candidate_paths=(CandidatePath.from_trajectory("synthetic-path", trajectory, "synthetic-bore"),))
    # Real numerical validator: the negative path crosses the physical capsule.
    assert baseline.path_allowed(trajectory, image) is (not collides)
    assert baseline.seed_allowed(trajectory, [4.,2.,2.], [1.,0.,0.], image,
                                 {"length":3., "radius":.4}) is (not collides)
    memory.store("continuation_baseline_record", baseline_record(baseline, image))
    memory.store("continuation_guide_requirement", {
        "manufactured_guide_present": True, "placement_prepared": guide_prepared})
    memory.store("continuation_input_seed_info", {"length":3., "radius":.4})
    result, _ = propose(runtime)
    assert_advisory(result, plan)
    assert result.metadata["advisory_count"] == 2
    assert "fixed_implant_capsules" in result.metadata["unvalidated_checks"]
    assert "guide_first_admission" in result.metadata["unvalidated_checks"]


def test_stale_guide_or_empty_channel_inventory_has_no_freehand_fallback(refinement):
    runtime, plan, _ = refinement
    memory = runtime.view.memory
    memory.store("continuation_search_record", {"record_sha256": "stale", "candidate_paths": []})
    result, _ = propose(runtime)
    assert_advisory(result, plan)
    assert "have not been validated" in result.message


def test_proposal_never_calls_canonical_planning_or_model_boundary(refinement, monkeypatch):
    runtime, plan, _ = refinement
    def forbidden(*args, **kwargs):
        pytest.fail("Proposal attempted an unauthorized planning or inference operation")
    monkeypatch.setattr("tool_factory.seed_plan.planning_pipeline.PlanningPipelineTool.execute", forbidden)
    monkeypatch.setattr("tool_factory.seed_plan.model_support.resolve_dose_model", forbidden)
    monkeypatch.setattr("tool_factory.seed_plan.model_support.compute_continuation_baseline", forbidden)
    monkeypatch.setattr("web.continuation_service.ContinuationPreparationService.prepare", forbidden)
    monkeypatch.setattr("tool_factory.seed_plan.continuation_search.search_outside_guide", forbidden)
    result, _ = propose(runtime)
    assert_advisory(result, plan)


def test_bound_tool_cannot_be_downgraded_by_bypassing_injector(refinement):
    runtime, plan, _ = refinement
    tool = runtime.view.registry.get("plan_refinement")
    assert tool._agent is runtime.view
    result = tool.execute(current_plan=plan, dose_distribution=np.zeros((9,9,9)),
        ctv_mask=np.ones((9,9,9)), prescribed_dose=100., target_v100=.9,
        _candidate_only=False, _agent=SimpleNamespace(memory=None))
    assert_advisory(result, plan)


def legacy(**overrides):
    params = dict(current_plan=[[[0.,0.,0.], [0.,1.,0.]]],
        dose_distribution=np.zeros((9,9,9)), ctv_mask=np.ones((9,9,9)),
        prescribed_dose=1., target_v100=.9, max_iterations=3)
    params.update(overrides)
    return PlanRefinementTool().execute(**params)


def test_legacy_positive_retains_explicit_axis_and_candidate_list_contract():
    plan = [[[0.,0.,0.], [0.,1.,0.]]]
    result = legacy(current_plan=plan)
    assert result.success, result.error
    candidates = result.metadata["candidate_seeds"]
    assert len(candidates) == 3
    assert all(seed[1] == [0.,1.,0.] for seed in candidates)
    positions = [np.asarray(p[0]) for p in plan + candidates]
    for i, point in enumerate(positions):
        assert all(np.linalg.norm(point-other) >= 4. for other in positions[:i])
    assert result.data == plan + candidates
    assert result.metadata["requires_dose_recalculation"] is True
    assert result.metadata["feasibility_validated"] is False
    assert result.metadata["proposal_kind"] == "unvalidated_legacy_seed_candidates"
    assert plan == [[[0.,0.,0.], [0.,1.,0.]]]


def test_legacy_all_cold_voxels_too_close_has_no_unsafe_centroid_fallback():
    result = legacy(dose_distribution=np.zeros((3,3,3)), ctv_mask=np.ones((3,3,3)),
                    current_plan=[[[1.,1.,1.], [0.,1.,0.]]])
    assert result.success
    assert result.metadata["candidate_seeds"] == []
    assert result.metadata["advisory_locations"] == []
    assert result.data == [[[1.,1.,1.], [0.,1.,0.]]]


def test_legacy_disconnected_target_with_oar_mean_has_no_centroid_fallback():
    ctv = np.zeros((5,5,5), np.uint8)
    ctv[1,2,2] = ctv[3,2,2] = 1
    organs = np.zeros_like(ctv)
    organs[2,2,2] = 1  # old mean fallback landed outside CTV and inside OAR
    result = legacy(ctv_mask=ctv, dose_distribution=np.zeros_like(ctv, float), oar_mask=organs,
                    current_plan=[[[1.,2.,2.], [1.,0.,0.]]])
    assert result.success
    assert result.metadata["candidate_seeds"] == []
    assert result.metadata["advisory_locations"] == []


def test_legacy_cold_oar_voxel_is_never_proposed():
    ctv = np.zeros((9,9,9), np.uint8)
    ctv[6,6,6] = 1
    organs = ctv.copy()
    result = legacy(ctv_mask=ctv, oar_mask=organs)
    assert result.success
    assert result.metadata["candidate_seeds"] == []


@pytest.mark.parametrize("plan", [[], [[[0.,0.,0.], [0.,0.,0.]]],
                                  [[[0.,0.,0.], [np.nan,0.,1.]]]])
def test_legacy_missing_or_invalid_axis_never_invents_direction(plan):
    result = legacy(current_plan=plan)
    assert result.success
    assert result.metadata["candidate_seeds"] == []
    assert result.metadata["advisory_locations"]
    assert result.metadata["feasibility_validated"] is False


@pytest.mark.parametrize("field,value", [("prescribed_dose", np.inf),
    ("prescribed_dose", np.nan), ("target_v100", np.nan), ("max_iterations", 0),
    ("max_iterations", True), ("max_iterations", 129)])
def test_invalid_numeric_proposal_configuration_fails(field, value):
    result = legacy(**{field:value})
    assert not result.success
    assert field in result.error


@pytest.mark.parametrize("memory_values", [{"timepoint_context": {"stage":"intraoperative"}},
    {"continuation_baseline_record": {}}, {"implanted_seed_reconstruction": {}}])
def test_older_agent_binding_with_implants_cannot_use_legacy_seed_path(memory_values):
    agent = SimpleNamespace(memory=SimpleNamespace(retrieve=memory_values.get))
    result = PlanRefinementTool(agent).execute(current_plan=[[[0.,0.,0.],[0.,1.,0.]]],
        dose_distribution=np.zeros((9,9,9)), ctv_mask=np.ones((9,9,9)),
        prescribed_dose=100., target_v100=.9)
    assert result.success
    assert result.metadata["candidate_only"] is True
    assert result.metadata["candidate_seeds"] == []
