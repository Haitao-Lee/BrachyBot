"""Guide-first priority and physical guide-obstacle negative controls."""
from dataclasses import asdict, replace
import copy
import numpy as np
import pytest
import SimpleITK as sitk
from test_pipeline_continuation import fixture, stub_expensive_geometry
from plans.continuation import CandidatePath, FixedSeed
from tool_factory.seed_plan.continuation_search import (
    GuideFirstPolicy, GuideMaterialObstacle, guide_search_record, resolve_guide_search, _record_digest,
)
from tool_factory.seed_plan.continuation_support import baseline_record
from tool_factory.seed_plan import planning_pipeline as pipe


def cube(low=(-1., -1., -1.), high=(1., 1., 1.)):
    x, y, z = low
    a, b, c = high
    vertices = np.array([[x,y,z],[a,y,z],[a,b,z],[x,b,z],[x,y,c],[a,y,c],[a,b,c],[x,b,c]])
    faces = np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
                      [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
    return vertices, faces


def record(image, vertices, faces, **policy):
    from tool_factory.seed_plan.continuation_support import image_signature
    value = {"schema_version": 1, "current_image_signature": image_signature(image),
        "placement_id": "a" * 32, "placement_revision": 1, "candidate_sha256": "b" * 64,
        "manufactured_geometry_id": "c" * 64, "vertices_lps_mm": vertices.tolist(), "faces": faces.tolist(),
        "policy": asdict(GuideFirstPolicy(**policy)), "source": "reviewed-manufactured-guide-placement",
        "clinical_use_approved": False}
    value["record_sha256"] = _record_digest(value)
    return value


@pytest.mark.parametrize("points,blocked", [
    ([[-3,0,0],[3,0,0]], True), ([[0,0,0],[3,0,0]], True),
    ([[-3,1.1,0],[3,1.1,0]], True), ([[-3,1.5,0],[3,1.5,0]], False),
    ([[-3,3,0],[3,3,0]], False),
])
def test_guide_material_blocks_surface_crossing_inside_and_radius_grazing(points, blocked):
    obstacle = GuideMaterialObstacle(*cube(), needle_radius_mm=.2, clearance_mm=.1, signature="fixture")
    assert obstacle.blocks_segment(points) is blocked


def test_guide_thin_wall_cannot_be_skipped_between_samples():
    obstacle = GuideMaterialObstacle(*cube((0,0,0),(.001,4,4)), needle_radius_mm=.01, clearance_mm=0, signature="fixture")
    assert obstacle.blocks_segment([[-100,2,2],[100,2,2]])
    assert not obstacle.blocks_segment([[-100,5,2],[100,5,2]])


def test_open_guide_and_nonfinite_geometry_fail_closed():
    vertices, faces = cube()
    with pytest.raises(ValueError, match="closed"):
        GuideMaterialObstacle(vertices, faces[:-1], needle_radius_mm=.2, clearance_mm=0, signature="fixture")
    vertices[0,0] = np.nan
    with pytest.raises(ValueError):
        GuideMaterialObstacle(vertices, faces, needle_radius_mm=.2, clearance_mm=0, signature="fixture")


def test_guide_record_builder_requires_accepted_rigid_manufactured_pose():
    from test_guide_bore_manifest import tube_guide
    from web.guide_placement import create_guide_placement, review_guide_placement, image_geometry_identity
    _, image, _, _, _, _ = fixture()
    guide = tube_guide()
    identity = image_geometry_identity(image, image_id="a" * 32, image_revision=1)
    pose = create_guide_placement(guide, np.eye(4), manufactured_guide_id="synthetic-print", target_image=identity,
                                  evidence={"source": "synthetic-reviewed-markers"})
    with pytest.raises(ValueError, match="accepted"):
        guide_search_record(guide, pose, image, identity)
    reviewed = review_guide_placement(pose, reviewer="synthetic-reviewer", decision="accepted",
        profile_id="synthetic-profile", evidence_reviewed=True, manufacturing_confirmed=True)
    result = guide_search_record(guide, reviewed, image, identity)
    assert result["policy"]["outside_guide_enabled"] is True
    assert result["record_sha256"] == _record_digest({k:v for k,v in result.items() if k != "record_sha256"})


def test_stale_guide_obstacle_is_not_used_to_approve_an_external_path():
    _, image, _, baseline, agent, _ = fixture()
    agent.memory.store("continuation_search_record", record(image, *cube()))
    assert resolve_guide_search(agent, image, baseline)
    changed = sitk.Image(image)
    changed[1,1,1] = 5
    with pytest.raises(ValueError, match="image"):
        resolve_guide_search(agent, changed, baseline)
    agent.memory.retrieve("continuation_search_record")["vertices_lps_mm"][0][0] += 1
    with pytest.raises(ValueError, match="changed"):
        resolve_guide_search(agent, image, baseline)


def setup_pipeline(monkeypatch, dose=.6, first_phase_map=.1, no_guide_channels=False):
    target, image, t, baseline, agent, config = fixture(dose=dose)
    stub_expensive_geometry(monkeypatch, target, image, t)
    if no_guide_channels:
        baseline = replace(baseline, candidate_paths=())
        agent.memory.store("continuation_baseline_record", baseline_record(baseline, image))
        agent.memory.store("trajectories", [])
        agent.memory.store("refined_trajectories", [])
    # Guide material in external air above the scan. The fallback must avoid
    # its complete extension, even though CT-grid obstacle projection is empty.
    vertices, faces = cube((1.,1.,9.), (3.,3.,10.))
    agent.memory.store("continuation_search_record", record(image, vertices, faces, search_seconds=4.))
    from plans import core, coverage_repair, utilizations as util
    calls = []
    bad = [np.array([0.,2.,2.]), np.array([1.,0.,0.]), [6], [0], 6]  # crosses guide solid
    outside = [np.array([0.,2.,5.]), np.array([1.,0.,0.]), [7], [0], 7]
    def guide_opt(*args, **kwargs):
        calls.append("guide-optimize")
        return [[t, [(np.array([2.,2.,3.]), np.array([0.,0.,1.]))], [np.full(target.shape, first_phase_map)]]]
    monkeypatch.setattr(core, "optimal_plan", guide_opt)
    def initialize(*args, **kwargs):
        calls.append("outside-init")
        return [bad, outside]
    monkeypatch.setattr(core, "init_plan", initialize)
    def repair(plan, candidates, *args, **kwargs):
        if all(p.bore_id is not None for p in kwargs["continuation"].candidate_paths):
            calls.append("guide-repair")
            return plan, {"initial_coverage": 0., "final_coverage": 0., "stop_reason": "no_safe_positive_gain"}
        calls.append("outside-repair")
        assert len(candidates) == 1  # the guide-crossing candidate was removed
        assert candidates[0][0][2] == 5.
        assert len(plan) == (0 if no_guide_channels else 1)
        world = np.asarray(image.TransformContinuousIndexToPhysicalPoint((5.,2.,3.)))
        result = plan + [[outside, [(world, np.array([0.,0.,-1.]))], [np.full(target.shape, .5)]]]
        return result, {"initial_coverage": 0., "final_coverage": 1., "stop_reason": "target_reached",
                        "added_seeds": 1, "added_needles": 1}
    monkeypatch.setattr(coverage_repair, "repair_coverage", repair)
    monkeypatch.setattr(util, "get_trajectory_spacing_safety_mask", lambda *a, **k: [True])
    # Preserve actual candidate-derived final geometry for the mesh check.
    monkeypatch.setattr(pipe, "_validated_needle_geometry", lambda p, *a, **k: (
        {str(i): pipe._candidate_world_needle_points(e[0], image) for i,e in enumerate(p)}, []))
    return target, image, baseline, agent, config, calls


def test_pipeline_searches_outside_only_after_guide_phase_and_retains_its_dose(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert calls == ["guide-optimize", "guide-repair", "outside-init", "outside-repair"]
    assert len(agent.memory.retrieve("seed_plan")) == 2
    assert np.allclose(agent.memory.retrieve("dose_distribution"), 1.2)  # .6 fixed + .1 guide + .5 outside
    assert result.metadata["continuation_search_status"]["outside_guide_attempted"] is True
    assert result.metadata["continuation_evaluation"]["path_associations"][1]["bore_id"] is None


def test_no_unused_guide_channel_can_still_trigger_bounded_outside_search(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch, no_guide_channels=True)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert "guide-optimize" not in calls
    assert calls == ["guide-repair", "outside-init", "outside-repair"]
    assert np.allclose(agent.memory.retrieve("dose_distribution"), 1.1)


def test_coverage_sufficient_skips_both_guide_and_outside_optimization(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch, dose=1.)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert calls == ["guide-repair"]
    assert result.metadata["total_seeds"] == 0
    assert result.metadata["continuation_search_status"]["outside_guide_attempted"] is False


def test_sufficient_guide_phase_does_not_search_new_skin_entries(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch, first_phase_map=.6)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert calls == ["guide-optimize", "guide-repair"]
    assert result.metadata["continuation_search_status"]["outside_guide_attempted"] is False


def test_all_external_paths_blocked_preserves_first_phase_and_reports_undercoverage(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch)
    from plans import core
    monkeypatch.setattr(core, "init_plan", lambda *a, **k: [])
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error  # a safe partial plan, not a clinical success claim
    assert len(agent.memory.retrieve("seed_plan")) == 1
    assert result.metadata["target_coverage"] == 0
    assert result.metadata["continuation_search_status"]["stop_reason"] == "no_safe_outside_guide_path"
    assert not result.metadata["continuation_evaluation"]["target_reached"]
    assert np.allclose(agent.memory.retrieve("dose_distribution"), .7)


def test_no_channel_and_no_safe_outside_path_is_not_an_empty_success(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch, no_guide_channels=True)
    from plans import core
    monkeypatch.setattr(core, "init_plan", lambda *a, **k: [])
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert not result.success
    assert result.metadata["baseline_retained"] is True
    assert agent.memory.retrieve("seed_plan") is None


def test_outside_search_timeout_keeps_accepted_guide_plan(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch)
    from plans import core
    def expired(*a, **k):
        raise TimeoutError("synthetic bounded initializer timeout")
    monkeypatch.setattr(core, "init_plan", expired)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert np.allclose(agent.memory.retrieve("dose_distribution"), .7)
    assert result.metadata["continuation_search_status"]["stop_reason"] == "outside_search_blocked"


def test_final_geometry_rejects_an_external_path_which_was_rebuilt_across_guide(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch)
    def altered_final(plan, *args, **kwargs):
        geometry = {str(i): pipe._candidate_world_needle_points(e[0], image) for i,e in enumerate(plan)}
        if len(plan) > 1:
            geometry["1"] = [[2.,2.,0.],[2.,2.,12.]]
        return geometry, []
    monkeypatch.setattr(pipe, "_validated_needle_geometry", altered_final)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert not result.success
    assert "positioned manufactured guide" in result.error
    assert agent.memory.retrieve("seed_plan") is None


def test_baseline_coverage_satisfied_does_not_hide_preexisting_oar_excess(monkeypatch):
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch, dose=2.)
    organ = np.zeros(target.shape, bool)
    organ[0,0,0] = True
    baseline = replace(baseline, oar_masks=(("synthetic-critical-organ", organ),))
    agent.memory.store("continuation_baseline_record", baseline_record(baseline, image))
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    evaluation = result.metadata["continuation_evaluation"]
    assert evaluation["target_reached"] is True
    assert evaluation["objectives_met"] is False
    assert "oar_limit:synthetic-critical-organ" in evaluation["unmet_objectives"]
    assert evaluation["oar_metrics"]["synthetic-critical-organ"]["baseline_above_limit_voxels"] == 1
    assert result.metadata["total_seeds"] == 0


def test_expired_initializer_does_not_build_or_publish_candidates():
    from plans.core import init_plan
    _, image, _, _, _, _ = fixture()
    with pytest.raises(TimeoutError):
        init_plan(image, np.ones((8,6,6)), [1,0,0], [1,1,1], .5, 1,0,3,20, deadline=0)


def test_full_zero_addition_pipeline_evaluates_oar_and_publishes_current_run(monkeypatch):
    from agent_runtime.core import AgentMemory
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch, dose=2.)
    values = agent.memory.values
    agent.memory = AgentMemory("a" * 32)
    for key,value in values.items():
        agent.memory.store(key, value)
    agent.config = config
    oar = np.zeros(target.shape, np.uint8)
    oar[0,0,0] = 90
    agent.memory.store("oar_array", oar)
    agent.memory.store("organ_names", {90: "synthetic-brain"})
    monkeypatch.setattr(pipe, "_resample_for_planning", lambda *a, **k: (image, target, oar))
    result = pipe.PlanningPipelineTool()._execute(_agent=agent, step="full", ref_direc=[1,0,0])
    assert result.success, result.error
    assert result.metadata["planning_published"] is True
    assert result.metadata["total_seeds"] == 0
    assert result.metadata["dose_metrics"]["v100"] == 1.
    assert result.metadata["dose_metrics"]["oar_metrics"]["synthetic-brain"]["dmax"] == pytest.approx(74., abs=.001)
    assert result.metadata["continuation_search_status"]["outside_guide_attempted"] is False


def test_real_repair_appends_external_seed_with_nonzero_baseline_and_guide_plan(monkeypatch):
    from plans import coverage_repair, utilizations as util
    original_repair = coverage_repair.repair_coverage
    target, image, baseline, agent, config, calls = setup_pipeline(monkeypatch)
    monkeypatch.setattr(coverage_repair, "repair_coverage", original_repair)
    # Same source engine boundary, deterministic synthetic maps: existing
    # guide slots provide no useful additional coverage, exterior slots do.
    def infer(point, *args, **kwargs):
        return np.full(target.shape, .5 if point[2] == 5 else 0., np.float32)
    monkeypatch.setattr(util, "single_seed_dose_calculation_dl", infer)
    result = pipe.PlanningPipelineTool()._step_seed_planning(image, target, None, "rule_based", config, agent)
    assert result.success, result.error
    assert len(agent.memory.retrieve("seed_plan")) == 2
    assert np.allclose(agent.memory.retrieve("dose_distribution"), 1.2)
    status = result.metadata["continuation_search_status"]
    assert status["additional_seeds"] == 1
    assert status["outside_phase_coverage"] == 1
    assert result.metadata["continuation_evaluation"]["path_associations"][1]["bore_id"] is None
