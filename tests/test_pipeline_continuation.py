"""Exercise actual main-pipeline stages with synthetic dose, never patient data."""
from types import SimpleNamespace
import copy
import numpy as np
import pytest


@pytest.mark.parametrize('patch, permitted', [
    ({'margin_rate': 1.}, True), ({'seed_avr_dose': 50.}, True), ({'length': 4.6}, False),
    ({'radius': .5}, False), ({'source_model_id': 'different-source'}, False),
])
def test_source_geometry_binding_distinguishes_spacing_from_fixed_capsules(patch, permitted):
    from tool_factory.seed_plan.continuation_support import same_continuation_source_geometry
    reviewed = {'length':4.5,'radius':.4,'margin_rate':1.5}
    requested = {**reviewed, **patch}
    assert same_continuation_source_geometry(requested, reviewed) is permitted
    assert same_continuation_source_geometry(None, reviewed) is False
import SimpleITK as sitk
import torch

from plans.continuation import ContinuationBaseline, CandidatePath, FixedSeed, array_sha256, grid_signature
from tool_factory.seed_plan import planning_pipeline as pipeline
from tool_factory.seed_plan.continuation_support import baseline_record, resolve_baseline, realized_candidates


class Memory:
    def __init__(self, **values):
        self.values = values
    def retrieve(self, key, default=None):
        return self.values.get(key, default)
    def store(self, key, value):
        self.values[key] = value


def fixture(dose=.6, paths=True):
    target = np.ones((8, 6, 6), np.uint8)
    image = sitk.DICOMOrient(sitk.GetImageFromArray(np.zeros(target.shape, np.float32)), "LPI")
    t = [np.array([0., 2., 2.]), np.array([1., 0., 0.]), [7.], [0.], 7.]
    b = ContinuationBaseline.create(np.full(target.shape, dose), image,
        baseline_unit="normalized_model", baseline_grid_signature=grid_signature(image),
        baseline_dose_sha256=array_sha256(np.full(target.shape, dose)), complete_target_mask=target == 1,
        dose_scale_gy=37., dose_contract_id="synthetic-source-v1", needle_radius_mm=.2, clearance_mm=0.,
        candidate_paths=[CandidatePath.from_trajectory("bore-path", t, "bore-1")] if paths else None)
    memory = Memory(ct_image=image, ctv_array=target, ctv_binary_array=target,
        resampled_ct=image, resampled_ctv=target, resampled_oar=None,
        trajectories=[t], refined_trajectories=[t], continuation_baseline_record=baseline_record(b, image))
    config = {"dose_value_unit": "gy", "in_lowest_energy": 37., "out_highest_energy": 37.,
        "seed_info": {"length": 1., "radius": .2, "margin_rate": 1.},
        "rf_params": {"coverage_repair_max_wall_seconds": .01,
                      "coverage_repair_adaptive_enabled": False, "fallback_to_rule_based": True}}
    return target, image, t, b, SimpleNamespace(memory=memory, config={}), config


def test_restart_reconstructs_immutable_baseline_and_rejects_tampered_dose():
    target, image, t, b, agent, _ = fixture()
    restored = resolve_baseline(agent, current_image=image)
    assert restored.candidate_paths == b.candidate_paths
    assert np.array_equal(restored.dose_model, b.dose_model)
    with pytest.raises(ValueError):
        restored.dose_model.setflags(write=True)
    record = copy.deepcopy(agent.memory.retrieve("continuation_baseline_record"))
    record["baseline"]["dose_model"][0, 0, 0] += 1
    agent.memory.store("continuation_baseline_record", record)
    with pytest.raises(ValueError, match="hash"):
        resolve_baseline(agent, current_image=image)


def test_same_grid_different_intraoperative_ct_is_not_a_valid_baseline():
    _, image, _, _, agent, _ = fixture()
    changed = sitk.Image(image)
    changed[1, 1, 1] = 500
    assert grid_signature(changed) == grid_signature(image)
    with pytest.raises(ValueError, match="image changed"):
        resolve_baseline(agent, current_image=changed)


def test_equivalent_ct_axis_order_is_not_a_different_acquisition():
    from tool_factory.seed_plan.continuation_support import image_signature
    _, image, _, _, agent, _ = fixture()
    assert image_signature(image) == image_signature(sitk.DICOMOrient(image, "RAS"))
    assert resolve_baseline(agent, current_image=sitk.DICOMOrient(image, "RAS")) is not None


def test_intraoperative_scope_cannot_fall_back_to_zero():
    agent = SimpleNamespace(memory=Memory(timepoint_context={"stage": "intraoperative"}))
    with pytest.raises(ValueError, match="zero-based"):
        resolve_baseline(agent)


def test_same_ct_with_changed_observation_revision_cannot_reuse_old_dose():
    _, image, _, _, agent, _ = fixture()
    agent.memory.store("implanted_seed_reconstruction", {"schema_version": 1, "by_timepoint": {
        "b" * 32: {"current": {"reconstruction": {"revision_id": "c" * 32}}},
    }})
    # A previously standalone baseline has no authority once a real observed
    # set exists. Neither image equality nor an old success flag is enough.
    with pytest.raises(ValueError, match="revision changed or was not bound"):
        resolve_baseline(agent, current_image=image)
    record = agent.memory.retrieve("continuation_baseline_record")
    record["timepoint_id"], record["observation_revision_id"] = "b" * 32, "d" * 32
    with pytest.raises(ValueError, match="revision changed or was not bound"):
        resolve_baseline(agent, current_image=image)


def test_reviewed_observations_bind_real_dimensions_and_antipodal_axes():
    from dataclasses import replace
    from uuid import uuid4
    from utils.implant_reconstruction import (ImageReference, ImageGeometry, SeedDetection, SeedDimensions,
        PhysicalPCAOrientationProvider, review_observations, ObservationReview)
    target, image, t, baseline, agent, _ = fixture()
    reference = ImageReference("a" * 32, "b" * 32, "c" * 32, 1, "d" * 64, ImageGeometry.from_image(image))
    detected = PhysicalPCAOrientationProvider().estimate_seed_axes(reference, image,
        [SeedDetection("detection-1", (4.,4.,3.))], dimensions=SeedDimensions("synthetic-source-v1", 1., .4))
    reviewed = review_observations(detected, [ObservationReview("detection-1", "accepted", "synthetic geometry review",
        corrected_axis_lps=(0,0,-1))], reviewer_id="synthetic-reviewer", coverage_status="complete",
        set_review_evidence="synthetic complete-volume review")
    seed = FixedSeed("observed:" + reviewed.observations[0].observation_id, (4.,4.,3.), (0,0,1), 1., .2)
    baseline = replace(baseline, fixed_seeds=(seed,))
    record = baseline_record(baseline, image, observation_revision_id=reviewed.revision_id, timepoint_id="b" * 32)
    agent.memory.store("continuation_baseline_record", record)
    agent.memory.store("implanted_seed_reconstruction", {"schema_version": 1, "by_timepoint": {
        "b" * 32: {"current": {"reconstruction": reviewed.to_dict()}},
    }})
    assert resolve_baseline(agent, current_image=image).fixed_seeds == baseline.fixed_seeds
    changed = replace(baseline, fixed_seeds=(replace(seed, length_mm=2.),))
    agent.memory.store("continuation_baseline_record", baseline_record(changed, image,
        observation_revision_id=reviewed.revision_id, timepoint_id="b" * 32))
    with pytest.raises(ValueError, match="differs from the reviewed"):
        resolve_baseline(agent, current_image=image)


def test_existing_printed_guide_cannot_be_silently_omitted_from_additional_planning():
    from tool_factory.seed_plan.continuation_support import pipeline_baseline
    target, image, _, baseline, agent, config = fixture()
    agent.memory.store("continuation_guide_requirement", {"manufactured_guide_present": True, "placement_prepared": False})
    with pytest.raises(ValueError, match="printed guide has not been placed"):
        pipeline_baseline(config, agent, image)
    assert pipeline_baseline(config, agent, image, allow_unplaced_guide=True) is not None
    sufficient = fixture(dose=1.)[3]
    agent.memory.store("continuation_baseline_record", baseline_record(sufficient, image))
    assert pipeline_baseline(config, agent, image) is not None  # no additional paths are needed


def test_realized_candidates_and_empty_channel_set_are_distinct_from_freehand():
    _, image, t, b, _, _ = fixture()
    assert len(realized_candidates(b, image)) == 1
    record = b.to_record()
    record["candidate_paths"] = []
    assert realized_candidates(ContinuationBaseline.from_record(record), image) == []
    assert realized_candidates(fixture(paths=False)[3], image) is None


def test_rebuilding_after_safety_pruning_keeps_baseline_exactly_once():
    target, _, t, b, _, _ = fixture()
    entry = [t, [(np.array([2., 2., 3.]), np.array([0., 0., 1.]))], [np.full(target.shape, .3)]]
    assert np.allclose(pipeline._sum_plan_seed_doses([entry], target, b), .9)
    assert np.allclose(pipeline._sum_plan_seed_doses([], target, b), .6)
    assert pipeline._plan_target_coverage([entry], target, 1, .85, b) == 1
    assert pipeline._plan_target_coverage([], target, 1, .85, b) == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.])
def test_invalid_addition_never_publishes_dose(bad):
    target, _, t, b, _, _ = fixture()
    with pytest.raises(ValueError):
        pipeline._sum_plan_seed_doses([[t, [], [np.full(target.shape, bad)]]], target, b)


def stub_expensive_geometry(monkeypatch, target, image, t):
    monkeypatch.setattr(pipeline, "_filter_world_safe_trajectories", lambda ts, *a, **k: list(ts))
    monkeypatch.setattr(pipeline, "_validated_needle_geometry", lambda p, *a, **k: (
        {str(i): [[2., 2., 0.], [2., 2., 7.]] for i, _ in enumerate(p)}, []))
    monkeypatch.setattr(pipeline, "_load_dose_model", lambda: (torch.nn.Linear(1, 1), None))
    monkeypatch.setattr(pipeline, "build_needle_safety_provenance", lambda *a, **k: {})


@pytest.mark.parametrize("mode", ["rule_based", "rl"])
def test_actual_seed_stage_passes_baseline_to_optimizer_and_repair(monkeypatch, mode):
    target, image, t, b, agent, config = fixture()
    stub_expensive_geometry(monkeypatch, target, image, t)
    calls = []
    world_plan = [[t, [(np.array([2., 2., 3.]), np.array([0., 0., 1.]))], [np.full(target.shape, .6)]]]
    def optimize(*args, **kwargs):
        calls.append("optimize")
        assert kwargs["continuation"].baseline_dose_sha256 == b.baseline_dose_sha256
        # These are model units under the explicitly non-default calibration.
        assert args[12 if mode == "rule_based" else 9] == pytest.approx(1.)
        return world_plan
    from plans import core, coverage_repair
    monkeypatch.setattr(core, "optimal_plan" if mode == "rule_based" else "optimal_plan_rf", optimize)
    def repair(plan, *args, **kwargs):
        calls.append("repair")
        assert kwargs["continuation"].dose_scale_gy == 37.
        assert args[11](np.zeros((1, 3)), 9999999999.) == []  # no invented guide channel
        return plan, {"initial_coverage": 1., "final_coverage": 1., "stop_reason": "target_reached"}
    monkeypatch.setattr(coverage_repair, "repair_coverage", repair)
    result = pipeline.PlanningPipelineTool()._step_seed_planning(image, target, None, mode, config, agent)
    assert result.success, result.error
    assert calls == ["optimize", "repair"]
    assert agent.memory.retrieve("coverage_repair_status")["stop_reason"] == "target_reached"
    assert np.allclose(agent.memory.retrieve("dose_distribution"), 1.2)
    assert np.allclose(agent.memory.retrieve("additional_dose_distribution"), .6)
    assert result.metadata["target_coverage"] == 1.
    assert result.metadata["continuation_evaluation"]["path_associations"] == [{"candidate_id": "bore-path", "bore_id": "bore-1"}]
    dose = pipeline.PlanningPipelineTool()._step_dose_calc(image, target, None, config, agent)
    assert dose.success, dose.error
    assert np.allclose(agent.memory.retrieve("dose_distribution_physical_gy"), 1.2 * 37.)


def test_baseline_already_covers_target_does_not_add_needles_or_load_model(monkeypatch):
    target, image, t, b, agent, config = fixture(dose=1.)
    stub_expensive_geometry(monkeypatch, target, image, t)
    agent.memory.store("trajectories", [])
    agent.memory.store("refined_trajectories", [])
    monkeypatch.setattr(pipeline, "_load_dose_model", lambda: pytest.fail("no inference is necessary"))
    from plans import core
    monkeypatch.setattr(core, "optimal_plan", lambda *a, **k: pytest.fail("baseline is sufficient"))
    result = pipeline.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert result.metadata["total_seeds"] == 0
    assert result.metadata["target_coverage"] == 1
    assert np.allclose(agent.memory.retrieve("dose_distribution"), 1.)
    assert np.allclose(agent.memory.retrieve("additional_dose_distribution"), 0.)
    assert pipeline.PlanningPipelineTool()._step_dose_calc(image, target, None, config, agent).success


def test_sufficient_baseline_real_geometry_and_dose_stages_without_patching():
    # Numerical acceptance on a declared synthetic baseline: the real stage
    # must handle zero supplemental geometry, not rely on patched validators.
    target,image,_,baseline,agent,config=fixture(dose=1.)
    agent.memory.store('trajectories',[])
    agent.memory.store('refined_trajectories',[])
    tool=pipeline.PlanningPipelineTool()
    result=tool._step_seed_planning(image,target,None,'rule_based',config,agent)
    assert result.success,result.error
    assert result.metadata['total_seeds']==0
    assert agent.memory.retrieve('seed_plan')==[]
    assert np.array_equal(agent.memory.retrieve('dose_distribution'),baseline.dose_model)
    assert np.count_nonzero(agent.memory.retrieve('additional_dose_distribution'))==0
    dose=tool._step_dose_calc(image,target,None,config,agent)
    assert dose.success,dose.error
    assert np.allclose(agent.memory.retrieve('dose_distribution_physical_gy'),37.)


def test_actual_rl_fallback_compares_total_dose_and_keeps_fixed_baseline(monkeypatch):
    target, image, t, b, agent, config = fixture()
    stub_expensive_geometry(monkeypatch, target, image, t)
    from plans import core, coverage_repair
    calls = []
    def candidate(value):
        return [[t, [(np.array([2., 2., 3.]), np.array([0., 0., 1.]))], [np.full(target.shape, value)]]]
    def rl(*args, **kwargs):
        calls.append("rl")
        assert kwargs["continuation"].baseline_dose_sha256 == b.baseline_dose_sha256
        return candidate(.2)  # total .8 is below prescription
    def fallback(*args, **kwargs):
        calls.append("fallback")
        assert kwargs["continuation"].baseline_dose_sha256 == b.baseline_dose_sha256
        return candidate(.6)  # total 1.2, not .6, reaches prescription
    monkeypatch.setattr(core, "optimal_plan_rf", rl)
    monkeypatch.setattr(core, "optimal_plan", fallback)
    monkeypatch.setattr(coverage_repair, "repair_coverage", lambda p, *a, **k: (p, {
        "initial_coverage": 1., "final_coverage": 1., "stop_reason": "target_reached"}))
    result = pipeline.PlanningPipelineTool()._step_seed_planning(image, target, None, "rl", config, agent)
    assert result.success, result.error
    assert calls == ["rl", "fallback"]
    assert result.metadata["rl_fallback_used"] is True
    assert result.metadata["rl_target_coverage"] == 0.
    assert result.metadata["rl_fallback_coverage"] == 1.
    assert np.allclose(agent.memory.retrieve("dose_distribution"), 1.2)


def test_continuation_dose_cannot_be_labeled_current_grid_if_resample_fails(monkeypatch):
    target, image, t, b, agent, config = fixture()
    agent.memory.store("seed_plan", [[t, [], []]])
    agent.memory.store("dose_distribution", np.ones(target.shape))
    monkeypatch.setattr(sitk.ResampleImageFilter, "Execute", lambda *a: (_ for _ in ()).throw(RuntimeError("synthetic resample failure")))
    result = pipeline.PlanningPipelineTool()._step_dose_calc(image, target, None, config, agent)
    assert not result.success
    assert agent.memory.retrieve("dose_distribution_physical_gy") is None


def test_legacy_intraoperative_entrypoint_cannot_plan_from_unreviewed_centers(monkeypatch):
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    _, image, _, _, agent, _ = fixture()
    agent.memory.values.pop("continuation_baseline_record")
    workflow = ChatWorkflowMixin()
    workflow.memory, workflow.config = agent.memory, {}
    monkeypatch.setattr(pipeline.PlanningPipelineTool, "_execute", lambda *a, **k: pytest.fail("unreviewed continuation"))
    result = workflow._trigger_replanning(image, [], [{"position": [1, 1, 1]}], "unused")
    assert not result["success"]
    assert result["automatic_replanning_blocked"]


def test_legacy_entrypoint_rejects_preoperative_ct_with_same_grid(monkeypatch):
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    _, image, _, _, agent, _ = fixture()
    changed = sitk.Image(image)
    changed[0, 0, 0] = 7
    agent.memory.store("ct_image", changed)
    workflow = ChatWorkflowMixin()
    workflow.memory, workflow.config = agent.memory, {}
    monkeypatch.setattr(pipeline.PlanningPipelineTool, "_execute", lambda *a, **k: pytest.fail("wrong anatomy"))
    result = workflow._trigger_replanning(image, [], None, "unused")
    assert not result["success"]
    assert "captured intraoperative image" in result["error"]


def test_actual_full_pipeline_initializes_only_real_channels_and_evaluates_total(monkeypatch):
    target, image, t, b, agent, config = fixture()
    stub_expensive_geometry(monkeypatch, target, image, t)
    from agent_runtime.core import AgentMemory
    previous = agent.memory.values
    agent.memory = AgentMemory("a" * 32)
    for key, value in previous.items():
        agent.memory.store(key, value)
    agent.config = config
    agent.memory.store('manual_artifact_status', {'dose':'stale','dvh':'stale',
        'quality_check':'stale','report':'stale','surgical_guide':'stale'})
    agent.memory.store('artifact_status', {'dose':'stale','dvh':'stale','quality_check':'stale'})
    agent.memory.store('manual_geometry_only', True)
    agent.memory.store("oar_array", np.zeros_like(target))
    monkeypatch.setattr(pipeline, "_resample_for_planning", lambda *a, **k: (image, target, np.zeros_like(target)))
    from plans import core, coverage_repair
    monkeypatch.setattr(core, "init_plan", lambda *a, **k: pytest.fail("printed guide forbids freehand initialization"))
    def optimize(candidates, volume, *args, **kwargs):
        assert len(candidates) == 1
        assert kwargs["continuation"].candidate_paths[0].bore_id == "bore-1"
        assert np.array_equal(volume == 1, target == 1)
        return [[candidates[0], [(np.array([2., 2., 3.]), np.array([0., 0., 1.]))], [np.full(target.shape, .6)]]]
    monkeypatch.setattr(core, "optimal_plan", optimize)
    monkeypatch.setattr(coverage_repair, "repair_coverage", lambda p, *a, **k: (p, {
        "initial_coverage": 1., "final_coverage": 1., "stop_reason": "target_reached"}))
    result = pipeline.PlanningPipelineTool()._execute(_agent=agent, step="full", ref_direc=[1., 0., 0.], mode="rule_based")
    assert result.success, result.error
    assert result.metadata["planning_published"] is True
    assert agent.memory.retrieve("dose_metrics")["v100"] == 1.
    assert agent.memory.retrieve('dose_metrics')['source_set'] == 'total'
    assert agent.memory.retrieve('manual_geometry_only') is False
    for key in ('manual_artifact_status','artifact_status'):
        status = agent.memory.retrieve(key)
        assert status['dose'] == status['dvh'] == status['quality_check'] == 'ready'
        assert status['report'] == 'stale'
    from web.planning_runs import current_planning_context
    assert current_planning_context(agent.memory)['metrics']['source_set'] == 'total'
    assert agent.memory.retrieve("dose_metrics")["d90"] == pytest.approx(44.4, abs=.001)
    assert np.allclose(agent.memory.retrieve("dose_distribution_physical_gy"), 44.4)
    assert agent.memory.retrieve("seed_plan")[0][0][2] == [7.]


def test_fractional_candidate_depth_does_not_extend_seed_sampling_past_target():
    from plans.utilizations import get_available_position
    target, image, t, _, _, _ = fixture()
    t[2], t[3], t[4] = [3.7], [0.], 3.7
    positions = get_available_position(t, [], {"length": .1, "radius": .01, "margin_rate": .1}, image,
                                       np.ones(target.shape) * 100)
    assert positions == [1, 2, 3]
    t[2] = [float("nan")]
    with pytest.raises(ValueError):
        get_available_position(t, [], {"length": .1, "radius": .01, "margin_rate": .1}, image,
                               np.ones(target.shape) * 100)


@pytest.mark.parametrize('failed_stage', ['dose_calc', 'dose_eval'])
def test_full_orchestration_does_not_claim_completion_after_dose_failure(monkeypatch, failed_stage):
    """Declared stage transport fixtures test the real orchestration failure path."""
    from tool_factory import ToolResult
    target, image, _, _, agent, config = fixture()
    tool = pipeline.PlanningPipelineTool()
    executed = []
    for stage in ('trajectory_init', 'trajectory_refine', 'seed_planning', 'dose_calc', 'dose_eval'):
        def transport(*args, stage=stage, **kwargs):
            executed.append(stage)
            return ToolResult(success=stage != failed_stage,
                error='Declared synthetic stage failure' if stage == failed_stage else None,
                metadata={'step_executed':stage}, data=None)
        monkeypatch.setattr(tool, '_step_' + stage, transport)
    result = tool._run_full_pipeline(image, target, np.zeros_like(target), [1.,0.,0.],
        'rule_based', config, agent)
    assert result.success is False
    assert result.metadata['step_executed'] == failed_stage
    assert executed[-1] == failed_stage
    if failed_stage == 'dose_calc':
        assert 'dose_eval' not in executed
