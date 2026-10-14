"""Synthetic dose tests for actual rule/RL/repair continuation branches.

No trained model, patient image, GPU inference, deployment or service is used.
"""
from dataclasses import FrozenInstanceError
import numpy as np
import pytest
import SimpleITK as sitk
import torch

from plans import core, utilizations as util
from plans.continuation import (ContinuationBaseline, FixedSeed, FixedNeedle,
    CandidatePath, array_sha256, grid_signature, initial_radiation, sum_plan_dose,
    finalize_continuation, continuation_slots, voxel_world)
from plans.coverage_repair import repair_coverage
from plans.reinforcement import (SeedPlacementReward, HighLevelEnv,
    evaluate_plan_objective, construct_plan_over_candidates, consolidate_plan_needles)
from tool_factory.seed_plan.model_support import (compute_world_seed_dose_grid,
    compute_continuation_baseline, continuation_dose_threshold)


SEED = {'length': 1., 'radius': .2, 'margin_rate': 1.}


def case():
    volume = np.ones((8, 6, 6), dtype=np.uint8)
    volume[0, 0, 0] = 3
    image = sitk.GetImageFromArray(np.zeros(volume.shape, dtype=np.float32))
    trajectory = (np.array([0., 2., 2.]), np.array([1., 0., 0.]), [7], [0])
    return volume, image, trajectory


def baseline(volume, image, dose=.6, **kwargs):
    dose = np.full(volume.shape, dose, dtype=np.float64) if np.isscalar(dose) else np.array(dose)
    options = dict(baseline_unit='normalized_model', baseline_grid_signature=grid_signature(image),
        baseline_dose_sha256=array_sha256(dose), complete_target_mask=volume == 1,
        dose_scale_gy=37., dose_contract_id='synthetic-source-model-calibration-v1',
        needle_radius_mm=.2, clearance_mm=0., oar_masks=(('organ', volume == 3),))
    options.update(kwargs)
    return ContinuationBaseline.create(dose, image, **options)


def fake_maps(monkeypatch, volume, value=.6):
    def infer(*args, **kwargs):
        return np.where(volume == 1, value, 0.).astype(np.float32)
    monkeypatch.setattr(util, 'single_seed_dose_calculation_dl', infer)
    monkeypatch.setattr(util, 'batch_seed_dose_calculation_dl',
                        lambda seeds, *a, **k: [infer() for _ in seeds])
    return infer


def rule(volume, image, trajectories, continuation, **kwargs):
    return core.optimal_plan(trajectories, volume, image, torch.nn.Linear(1, 1), {},
        .8, 10., .8, 1, 0, 3, (8, 8, 8), 1., 1., .9, SEED, 2,
        -1000, 3000, 255, continuation=continuation, **kwargs)


def rl(volume, image, trajectories, continuation, **params):
    options = dict(max_episodes=6, bandwidth=5, max_wall_seconds=30.,
        random_seed=3, candidate_limit=4, dense_seed_limit=4, max_hierarchy_depth=3,
        max_actions_per_episode=6, segmented_rewards=True, hierarchical_optimization=True,
        greedy_warm_start=True)
    options.update(params)
    return core.optimal_plan_rf(trajectories, volume, image, torch.nn.Linear(1, 1), {},
        options, 2., 1, (8, 8, 8), 1., 1., .9, SEED, -1000, 3000, 255,
        continuation=continuation)


def evaluation(plan, b, volume, image):
    return finalize_continuation(plan, b, volume, image, 1, SEED, 1., 1., .9)


def reward(volume, image, b):
    return SeedPlacementReward(torch.nn.Linear(1, 1), image, volume, 1, 1., 1.,
        (8, 8, 8), SEED, -1000, 3000, 255, .9, continuation=b)


def test_baseline_and_fixed_geometry_are_detached_and_immutable():
    volume, image, _ = case()
    dose = np.full(volume.shape, .6)
    center = [4., 4., 3.]
    fixed = FixedSeed('physical-1', center, [0., 0., 1.], 1., .2)
    b = baseline(volume, image, dose, fixed_seeds=[fixed])
    center[0] = 99
    dose[:] = 99
    assert b.fixed_seeds[0].center_lps_mm == (4., 4., 3.)
    assert np.all(b.dose_model == .6)
    with pytest.raises(ValueError):
        b.dose_model.setflags(write=True)
    with pytest.raises(ValueError):
        b.complete_target_mask.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        fixed.center_lps_mm = (0, 0, 0)
    initial_radiation(volume, b)[:] = 123
    b.assert_unchanged()


@pytest.mark.parametrize('options', [dict(baseline_unit='unknown'),
    dict(baseline_grid_signature='wrong'), dict(baseline_dose_sha256='wrong'),
    dict(dose_scale_gy=0), dict(dose_contract_id=''), dict(needle_radius_mm=0),
    dict(clearance_mm=-1)])
def test_invalid_unit_grid_hash_and_profile_fail_closed(options):
    volume, image, _ = case()
    with pytest.raises(ValueError):
        baseline(volume, image, **options)


@pytest.mark.parametrize('dose', [np.nan, -1., np.inf])
def test_invalid_baseline_values_are_not_sanitized(dose):
    volume, image, _ = case()
    with pytest.raises(ValueError):
        baseline(volume, image, dose)


def test_gy_conversion_uses_explicit_calibration_once():
    volume, image, _ = case()
    b = baseline(volume, image, 22.2, baseline_unit='Gy')
    np.testing.assert_allclose(b.dose_model, .6)
    assert continuation_dose_threshold(37., 'Gy', b) == 1.
    assert continuation_dose_threshold(1., 'normalized_model', b) == 1.
    np.testing.assert_allclose(evaluation([], b, volume, image)['total_dose_gy'], 22.2)


def test_complete_target_and_rotated_grid_are_enforced():
    volume, image, _ = case()
    b = baseline(volume, image)
    partial = volume.copy()
    partial[1] = 0
    with pytest.raises(ValueError, match='complete target'):
        rule(partial, image, [], b)
    changed = sitk.Image(image)
    changed.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
    with pytest.raises(ValueError, match='grid'):
        rule(volume, changed, [], b)


def test_duplicate_seed_identity_unknown_axis_and_out_of_fov_are_rejected():
    volume, image, _ = case()
    fixed = FixedSeed('one', [2., 4., 3.], [0., 0., 1.], 1., .2)
    with pytest.raises(ValueError, match='Duplicate'):
        baseline(volume, image, fixed_seeds=[fixed, fixed])
    with pytest.raises(ValueError):
        FixedSeed('unknown-axis', [2., 4., 3.], [0, 0, 0], 1., .2)
    with pytest.raises(ValueError, match='outside'):
        baseline(volume, image, fixed_seeds=[FixedSeed('outside', [99, 0, 0], [0, 0, 1], 1, .2)])


@pytest.mark.parametrize('mode', ['rule', 'rl'])
def test_zero_additions_preserves_baseline_and_existing_oar_violation(monkeypatch, mode):
    volume, image, trajectory = case()
    b = baseline(volume, image, 1.2)
    def forbidden(*a, **k):
        raise AssertionError('already covered baseline must not run inference')
    monkeypatch.setattr(util, 'single_seed_dose_calculation_dl', forbidden)
    monkeypatch.setattr(util, 'batch_seed_dose_calculation_dl', forbidden)
    plan = (rule if mode == 'rule' else rl)(volume, image, [trajectory], b)
    assert plan == []
    e = evaluation(plan, b, volume, image)
    assert e['target_metrics']['voxel_count'] == int((volume == 1).sum())
    assert e['target_metrics']['V100'] == 1.
    assert e['oar_metrics']['organ']['baseline_above_limit_voxels'] == 1
    assert not e['objectives_met'] and e['unmet_objectives'] == ['oar_limit:organ']
    np.testing.assert_array_equal(e['total_dose'], b.dose_model)
    assert not e['additional_dose'].any()


def test_partial_baseline_uses_complete_ctv_for_optimization_and_dvh(monkeypatch):
    volume, image, trajectory = case()
    dose = np.full(volume.shape, .2)
    dose[:4] = 1.2
    dose[volume == 3] = 0.
    b = baseline(volume, image, dose)
    infer = fake_maps(monkeypatch, volume, .9)
    initial = evaluation([], b, volume, image)
    expected_initial = np.mean(dose[volume == 1] > 1.)
    assert initial['target_metrics']['V100'] == expected_initial
    plan, status = repair_coverage([], [trajectory], volume, image, 1, volume == 3,
        1., 1., .9, SEED, infer, lambda *a: True, continuation=b)
    assert status['initial_coverage'] == expected_initial
    e = status['continuation_evaluation']
    np.testing.assert_allclose(e['total_dose'][volume == 1], (dose + .9)[volume == 1])
    assert e['target_metrics']['V100'] == 1.
    curve = e['total_dvh_gy']['target']
    at_rx = np.where(curve['dose_gy'] == 37.)[0]
    assert curve['volume_fraction'][at_rx[0]] == 1.
    assert e['target_metrics']['voxel_count'] == int((volume == 1).sum())


def test_baseline_oar_damage_is_included_in_final_rl_objective():
    volume, image, _ = case()
    safe = np.full(volume.shape, .6)
    hot = safe.copy()
    safe[volume == 3] = 0.
    hot[volume == 3] = 2.
    safe_b, hot_b = baseline(volume, image, safe), baseline(volume, image, hot)
    safe_score, _ = evaluate_plan_objective([], volume, 1, 1., 1., .9, continuation=safe_b)
    hot_score, _ = evaluate_plan_objective([], volume, 1, 1., 1., .9, continuation=hot_b)
    assert hot_score < safe_score


def test_seed_removal_subtracts_only_supplemental_contribution():
    volume, image, trajectory = case()
    b = baseline(volume, image)
    seed = (np.array([3., 2., 2.]), trajectory[1])
    addition = np.where(volume == 1, .6, 0.)
    plan = [[trajectory, [seed], [addition]]]
    result, total = util.remove_seed_sequentially(plan, [seed], 0, b.dose_model + addition)
    np.testing.assert_allclose(total, b.dose_model)
    assert result[0][1] == [] and result[0][2] == []
    b.assert_unchanged()


def test_rule_all_stages_preserve_baseline_and_only_return_additions(monkeypatch):
    volume, image, trajectory = case()
    b = baseline(volume, image, fixed_seeds=[FixedSeed('fixed', [4., 4., 3.], [0, 0, 1], 1., .2)])
    fake_maps(monkeypatch, volume)
    calls = []
    original_replan, original_add = util.replan, util.add_proper_seed
    def rebuilding(plan, vol, dose, *a, **k):
        assert np.all(dose >= b.dose_model - 1e-6)
        calls.append('rebuild')
        return original_replan(plan, vol, dose, *a, **k)
    def refinement(plan, vol, dose, *a, **k):
        assert np.all(dose >= b.dose_model - 1e-6)
        calls.append('refine')
        return original_add(plan, vol, dose, *a, **k)
    monkeypatch.setattr(util, 'replan', rebuilding)
    monkeypatch.setattr(util, 'add_proper_seed', refinement)
    plan = rule(volume, image, [trajectory], b)
    assert 'rebuild' in calls and 'refine' in calls
    assert len(plan) == 1 and len(plan[0][1]) == 1
    e = evaluation(plan, b, volume, image)
    np.testing.assert_allclose(e['total_dose'][volume == 1], 1.2)
    assert e['fixed_seed_ids'] == ('fixed',)
    assert e['target_metrics']['V100'] == 1.


@pytest.mark.parametrize('failure', ['exception', 'stalled'])
def test_rule_reconstruction_rollback_does_not_lose_or_double_baseline(monkeypatch, failure):
    volume, image, trajectory = case()
    b = baseline(volume, image)
    fake_maps(monkeypatch, volume)
    def stalled(plan, vol, dose, *a, **k):
        if failure == 'exception':
            raise RuntimeError('synthetic rebuild failure')
        return plan, 0., dose, True
    monkeypatch.setattr(util, 'replan', stalled)
    plan = rule(volume, image, [trajectory], b)
    np.testing.assert_allclose(evaluation(plan, b, volume, image)['total_dose'][volume == 1], 1.2)


@pytest.mark.parametrize('hierarchical,greedy', [(True, True), (True, False), (False, True), (False, False)])
def test_actual_rl_modes_reset_and_reconstruct_with_baseline(monkeypatch, hierarchical, greedy):
    volume, image, trajectory = case()
    b = baseline(volume, image)
    fake_maps(monkeypatch, volume)
    plan = rl(volume, image, [trajectory], b,
              hierarchical_optimization=hierarchical, greedy_warm_start=greedy)
    assert any(entry[1] for entry in plan)
    e = evaluation(plan, b, volume, image)
    expected = b.dose_model + sum((d for entry in plan for d in entry[2]), np.zeros(volume.shape))
    np.testing.assert_allclose(e['total_dose'], expected)
    assert e['target_metrics']['V100'] == 1.
    b.assert_unchanged()


def test_rl_episode_reset_restores_dose_coverage_and_oar_state(monkeypatch):
    volume, image, trajectory = case()
    b = baseline(volume, image, 1.2)
    r = reward(volume, image, b)
    elem = [0, trajectory, [], [], np.zeros(volume.shape)]
    env = HighLevelEnv([[elem]], [2], [[(2,)]], [1], 1, image, volume, SEED, r, .9, True)
    env.cur_radiation[:] = 99
    env.planned_positions[0].append([1, 2, 3])
    env.reset()
    np.testing.assert_allclose(env.cur_radiation, b.dose_model)
    assert env.cur_DVH_rate == 1.
    assert r.last_out_damage > 0
    assert env.planned_positions == [[]]
    env.reset()
    np.testing.assert_allclose(env.cur_radiation, b.dose_model)


def test_continuation_rl_uncached_inference_uses_the_published_continuous_point(monkeypatch):
    volume, image, _ = case()
    trajectory = (np.array([0., 2., 2.]), np.array([1., .1, 1. / 30]), [7], [0])
    point = trajectory[0] + 3. * trajectory[1]
    b = baseline(volume, image)
    r = reward(volume, image, b)
    inferred = []
    def infer(position, *a, **k):
        inferred.append(position.copy())
        return np.where(volume == 1, .6, 0.).astype(np.float32)
    monkeypatch.setattr(util, 'single_seed_dose_calculation_dl', infer)
    _, total, coverage, addition = r.forward([0, trajectory, [], [], None],
        initial_radiation(volume, b), trajectory[1], point)
    np.testing.assert_allclose(inferred[0], point)
    assert coverage == 1. and addition is not None
    np.testing.assert_allclose(total[volume == 1], 1.2)


def test_dense_hierarchy_sums_baseline_once(monkeypatch):
    volume, image, trajectory = case()
    other = (np.array([0., 4., 2.]), trajectory[1], [7], [0])
    b = baseline(volume, image)
    addition = np.where(volume == 1, .3, 0.)
    elems = [[[[i, t, [], [], addition]], 0.] for i, t in enumerate([trajectory, other])]
    hierarchy, _, _ = util.generate_hierarchical_state_spaces(elems, SEED, image, 2.,
        (volume == 1).astype(float), int((volume == 1).sum()), 1., .9, 5,
        core._MockProgressDialog(), max_levels=2, continuation=b,
        parallel_min_distance_mm=1.)
    assert len(hierarchy) == 2
    assert hierarchy[1][0][1] == 1.
    # Entry[4] must remain supplemental, never carry another baseline copy.
    np.testing.assert_array_equal(hierarchy[1][0][0][0][4], addition)


@pytest.mark.parametrize('mode', ['rule', 'rl', 'repair'])
def test_fixed_seed_and_needle_collision_blocks_inference(monkeypatch, mode):
    volume, image, trajectory = case()
    b = baseline(volume, image, fixed_seeds=[FixedSeed('fixed', [2., 2., 4.], [0, 0, 1], 1., .2)],
        fixed_needles=[FixedNeedle('in-situ', [0, 2, 3], [4, 2, 3], .2)])
    def forbidden(*a, **k):
        raise AssertionError('fixed geometry collision reached dose inference')
    monkeypatch.setattr(util, 'single_seed_dose_calculation_dl', forbidden)
    monkeypatch.setattr(util, 'batch_seed_dose_calculation_dl', forbidden)
    if mode == 'repair':
        plan, status = repair_coverage([], [trajectory], volume, image, 1, volume == 3,
            1., 1., .9, SEED, forbidden, lambda *a: True, continuation=b)
        assert status['trials'] == 0
    else:
        plan = (rule if mode == 'rule' else rl)(volume, image, [trajectory], b)
    assert plan == []
    np.testing.assert_allclose(evaluation(plan, b, volume, image)['total_dose'], .6)


def test_seed_capsule_collision_is_checked_separately_from_needle():
    volume, image, trajectory = case()
    b = baseline(volume, image, needle_radius_mm=.1,
        fixed_seeds=[FixedSeed('adjacent', [2., 2.7, 3.], [0, 0, 1], .2, .2)])
    assert b.path_allowed(trajectory, image)
    large_seed = dict(SEED, radius=.6)
    assert not b.seed_allowed(trajectory, np.array([3., 2., 2.]), trajectory[1], image, large_seed)
    assert b.seed_allowed(trajectory, np.array([6., 2., 2.]), trajectory[1], image, large_seed)


def test_rotated_anisotropic_collision_uses_physical_coordinates():
    volume, image, trajectory = case()
    image.SetSpacing((.7, 1.3, 2.1))
    image.SetOrigin((10., -15., 20.))
    image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
    center = voxel_world(image, [4., 2., 2.])
    b = baseline(volume, image, fixed_seeds=[FixedSeed('physical', center, [0, 0, 1], 1., .2)])
    assert not b.path_allowed(trajectory, image)


def test_bore_candidates_cannot_be_moved_or_refilled_freehand(monkeypatch):
    volume, image, trajectory = case()
    forbidden = (np.array([0., 4., 2.]), trajectory[1], [7], [0])
    path = CandidatePath.from_trajectory('candidate-one', trajectory, 'manufactured-bore-one')
    b = baseline(volume, image, candidate_paths=[path])
    assert b.path_allowed(trajectory, image)
    assert not b.path_allowed(forbidden, image)
    changed_depth = (trajectory[0], trajectory[1], [8], [0])
    assert not b.path_allowed(changed_depth, image)
    calls = []
    def infer(point, direction):
        calls.append(point)
        return np.where(volume == 1, .6, 0.)
    plan, status = repair_coverage([], [forbidden], volume, image, 1, volume == 3,
        1., 1., .9, SEED, infer, lambda *a: True, generate=lambda *a: [forbidden], continuation=b)
    assert plan == [] and not calls
    assert status['generated'] == 0
    fake_maps(monkeypatch, volume)
    plan = rule(volume, image, [trajectory, forbidden], b)
    assert evaluation(plan, b, volume, image)['path_associations'] == [
        {'candidate_id': 'candidate-one', 'bore_id': 'manufactured-bore-one'}]


def test_repair_and_disabled_repair_keep_baseline_once(monkeypatch):
    volume, image, trajectory = case()
    b = baseline(volume, image)
    infer = fake_maps(monkeypatch, volume)
    plan, info = repair_coverage([], [trajectory], volume, image, 1, volume == 3,
        1., 1., .9, SEED, infer, lambda *a: True, continuation=b)
    assert info['initial_coverage'] == 0. and info['final_coverage'] == 1.
    np.testing.assert_allclose(info['continuation_evaluation']['total_dose'][volume == 1], 1.2)
    unchanged, disabled = repair_coverage(plan, [], volume, image, 1, volume == 3,
        1., 1., .9, SEED, infer, lambda *a: True, continuation=b, seconds=0.)
    np.testing.assert_allclose(disabled['continuation_evaluation']['total_dose'][volume == 1], 1.2)
    assert len(unchanged[0][1]) == len(plan[0][1]) == 1


def test_rule_deadline_and_empty_rl_candidates_preserve_fixed_total(monkeypatch):
    volume, image, trajectory = case()
    b = baseline(volume, image)
    fake_maps(monkeypatch, volume)
    assert rule(volume, image, [trajectory], b, deadline=0.) == []
    assert rl(volume, image, [], b) == []
    np.testing.assert_allclose(evaluation([], b, volume, image)['total_dose'], .6)


def test_rule_previews_identify_supplemental_geometry_and_total_coverage(monkeypatch):
    volume, image, trajectory = case()
    b = baseline(volume, image)
    fake_maps(monkeypatch, volume)
    previews = []
    rule(volume, image, [trajectory], b, preview_callback=previews.append)
    assert previews
    for frame in previews:
        assert frame['supplemental_only']
        assert frame['coverage_component'] == 'total'
        assert frame['baseline_dose_sha256'] == b.baseline_dose_sha256
        assert frame['baseline_grid_signature'] == b.baseline_grid_signature
    assert previews[-1]['coverage'] == 1.


def test_cross_candidate_construction_and_needle_consolidation_keep_baseline(monkeypatch):
    volume, image, trajectory = case()
    b = baseline(volume, image)
    fake_maps(monkeypatch, volume)
    r = reward(volume, image, b)
    plan = construct_plan_over_candidates(r, [trajectory], volume, 1, image,
        np.ones(volume.shape), SEED)
    assert len(plan) == 1 and len(plan[0][1]) == 1
    objective, coverage = evaluate_plan_objective(plan, volume, 1, 1., 1., .9, continuation=b)
    assert coverage == 1.
    # Two supplemental needles are redundant with the baseline; dropping one
    # must retain total coverage, and fixed seeds never enter the removal pool.
    other = (np.array([0., 4., 2.]), trajectory[1], [7], [0])
    second = core.seed_plan_to_world_coordinates([[other, [(np.array([3., 4., 2.]), other[1])],
        [np.where(volume == 1, .6, 0.).astype(np.float32)]]], image)[0]
    reduced = consolidate_plan_needles(r, plan + [second], image, np.ones(volume.shape), SEED)
    assert len(reduced) == 1
    assert evaluate_plan_objective(reduced, volume, 1, 1., 1., .9, continuation=b)[1] == 1.
    np.testing.assert_allclose(evaluation(reduced, b, volume, image)['total_dose'][volume == 1], 1.2)


def test_invalid_additional_map_and_fixed_geometry_cannot_be_published():
    volume, image, trajectory = case()
    b = baseline(volume, image)
    p = core.seed_plan_to_world_coordinates([[trajectory, [(np.array([3., 2., 2.]), trajectory[1])],
        [np.full(volume.shape, np.nan)]]], image)
    with pytest.raises(ValueError, match='dose map'):
        evaluation(p, b, volume, image)
    with pytest.raises(ValueError, match='one to one'):
        sum_plan_dose([[trajectory, [], [np.ones(volume.shape)]]], volume, b)


def test_moved_seed_axis_and_calibration_overflow_cannot_be_published():
    volume, image, trajectory = case()
    b = baseline(volume, image)
    addition = np.where(volume == 1, .6, 0.)
    moved = core.seed_plan_to_world_coordinates([[trajectory,
        [(np.array([3., 3., 2.]), trajectory[1])], [addition]]], image)
    with pytest.raises(ValueError, match='Supplemental seed'):
        evaluation(moved, b, volume, image)
    rotated = core.seed_plan_to_world_coordinates([[trajectory,
        [(np.array([3., 2., 2.]), np.array([0., 1., 0.]))], [addition]]], image)
    with pytest.raises(ValueError, match='Supplemental seed'):
        evaluation(rotated, b, volume, image)
    overflowing = baseline(volume, image, dose=2., dose_scale_gy=1e308)
    with pytest.raises(ValueError, match='overflowed'):
        evaluation([], overflowing, volume, image)


def test_strict_fixed_dose_rejects_guessed_axes_partial_or_invalid_inference(monkeypatch):
    volume, image, _ = case()
    with pytest.raises(ValueError, match='accepted identity'):
        compute_world_seed_dose_grid([{'id': 's', 'position': [2, 2, 2]}], image, object(), {}, SEED, strict=True)
    with pytest.raises(ValueError, match='Incomplete'):
        compute_world_seed_dose_grid([{'id': 's', 'position': [99, 2, 2], 'direction': [0, 0, 1]}],
                                    image, object(), {}, SEED, strict=True)
    monkeypatch.setattr(util, 'batch_seed_dose_calculation_dl', lambda *a, **k: [np.full(volume.shape, np.nan)])
    with pytest.raises(ValueError, match='Invalid fixed-seed'):
        compute_world_seed_dose_grid([{'id': 's', 'position': [2, 2, 2], 'direction': [0, 0, 1]}],
                                    image, object(), {}, SEED, strict=True)


def test_compute_baseline_reuses_supplied_cnn_and_freezes_all_fixed_ids(monkeypatch):
    volume, image, _ = case()
    fake_maps(monkeypatch, volume)
    fixed = [FixedSeed('observed', [2, 2, 2], [0, 0, 1], 1., .2)]
    b = compute_continuation_baseline(fixed, image, object(), {}, SEED,
        complete_target_mask=volume == 1, dose_scale_gy=37., dose_contract_id='synthetic-v1',
        needle_radius_mm=.2, clearance_mm=0.)
    np.testing.assert_allclose(b.dose_model[volume == 1], .6)
    assert b.fixed_seeds == tuple(fixed)


@pytest.mark.parametrize('tool_name', ['unified-rule', 'unified-rl', 'rule', 'rl'])
def test_standalone_tools_forward_baseline_and_publish_total_metadata(monkeypatch, tool_name):
    from tool_factory.seed_plan import SeedPlanningTool, RuleBasedSeedPlanningTool, RLSeedPlanningTool
    volume, image, _ = case()
    b = baseline(volume, image, 1.2)
    tool = {'unified-rule': SeedPlanningTool, 'unified-rl': SeedPlanningTool,
            'rule': RuleBasedSeedPlanningTool, 'rl': RLSeedPlanningTool}[tool_name]()
    result = tool._execute(trajectories=[], radiation_volume=volume, dose_image=image,
        dose_cal_model=torch.nn.Linear(1, 1), continuation=b, seed_info=SEED,
        in_lowest_dose=37., out_highest_dose=37., mode='rl' if 'rl' in tool_name else 'rule_based')
    assert result.success and result.data == []
    assert result.metadata['supplemental_only']
    assert result.metadata['dose_units'] == 'normalized_model'
    np.testing.assert_allclose(result.metadata['dose_distribution'], 1.2)
    np.testing.assert_allclose(result.metadata['dose_distribution_gy'], 44.4)
