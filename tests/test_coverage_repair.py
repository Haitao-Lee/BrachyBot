"""Behavioral coverage regressions with deterministic dose fields."""
import numpy as np
import SimpleITK as sitk
from plans import core, utilizations as util
from plans.coverage_repair import repair_coverage, dose_gain


def setup_case(monkeypatch):
    volume = np.ones((8, 8, 8), dtype=np.uint8)
    image = sitk.GetImageFromArray(volume)
    image.SetOrigin((20, 30, 40))
    trajectory = (np.array([2., 2., 2.]), np.array([1., 0., 0.]), [5], [], 5)
    monkeypatch.setattr(util, 'get_available_position', lambda *a: [1])
    return volume, image, trajectory


def run_case(volume, image, trajectory, **kwargs):
    return repair_coverage([], [trajectory], volume, image, 1,
                           np.zeros_like(volume, dtype=bool), 1., 1., .9,
                           {'length': 1., 'margin_rate': 1.}, **kwargs)


def test_adds_seed_with_exact_dose_and_world_coordinates(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    plan, status = run_case(volume, image, trajectory,
        infer_dose=lambda *a: np.full(volume.shape, 1.1), validate=lambda *a: True)
    assert status['final_coverage'] == 1
    assert status['added_needles'] == 1
    # Array (3,2,2) is physical xyz (22,32,43).
    np.testing.assert_allclose(plan[0][1][0][0], [22, 32, 43])


def test_accepts_continuous_deficit_improvement_before_v100_changes(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    plan, status = run_case(volume, image, trajectory,
        infer_dose=lambda *a: np.full(volume.shape, .25), validate=lambda *a: True)
    assert status['final_coverage'] == 0
    assert len(plan) == 1


def test_rejected_geometry_never_calls_dose_model(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    def forbidden(*a):
        raise AssertionError('unsafe candidate reached dose model')
    plan, status = run_case(volume, image, trajectory,
        infer_dose=forbidden, validate=lambda *a: False)
    assert plan == []
    assert status['trials'] == 0


def test_timeout_keeps_original_plan(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    plan, status = run_case(volume, image, trajectory, seconds=0,
        infer_dose=lambda *a: None, validate=lambda *a: True)
    assert plan == []
    assert status['trials'] == 0


def test_local_candidates_are_used_after_existing_pool_fails(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    extra = (np.array([4., 2., 2.]), trajectory[1], [5], [], 5)
    plan, status = run_case(volume, image, trajectory,
        infer_dose=lambda *a: np.full(volume.shape, 1.1),
        validate=lambda t, selected: t[0][0] == 4,
        generate=lambda *a: [extra])
    assert status['generated'] == 1
    assert status['final_coverage'] == 1


def test_nonfinite_and_excessive_organ_dose_are_not_improvements():
    dose = np.zeros((2,))
    target = np.array([True, False])
    organs = ~target
    assert dose_gain(dose, np.array([1., 100.]), target, organs, 1., 1.) < 0
    assert dose_gain(dose, np.array([np.nan, 0.]), target, organs, 1., 1.) == -np.inf


def test_exhausted_selection_does_not_return_first_path(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    monkeypatch.setattr(util, 'get_candidate_traj_weights', lambda *a: [1])
    monkeypatch.setattr(util, 'get_candidate_traj_radiation', lambda *a: [1])
    monkeypatch.setattr(util, 'get_candidate_traj_edge_distance', lambda *a: [1])
    monkeypatch.setattr(util, 'get_candidate_traj_dir_score', lambda *a: [1])
    monkeypatch.setattr(util, 'get_trajectory_spacing_safety_mask', lambda *a, **k: np.array([True]))
    chosen = util.select_optimal_trajectory([trajectory], [], volume, image,
        .8, 10, .8, 1, volume, {}, [0])
    assert chosen == (None, None)


def test_rl_sampling_keeps_separated_candidate_groups():
    candidates = [(np.array([float(i), 0., 0.]), np.array([1., 0., 0.])) for i in range(100)]
    selected = core.sample_spatial_trajectories(candidates, 4)
    assert min(t[0][0] for t in selected) == 0
    assert max(t[0][0] for t in selected) == 99


def test_oblique_repair_preserves_continuous_inference_position(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    image.SetSpacing((.7, 1.2, 2.5))
    image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., -1.))
    trajectory = (trajectory[0], np.array([1., .37, .21]), [5], [], 5)
    inferred = []
    def infer(point, direction):
        inferred.append(point.copy())
        return np.full(volume.shape, 1.1)
    plan, _ = run_case(volume, image, trajectory, infer_dose=infer, validate=lambda *a: True)
    expected = trajectory[0] + trajectory[1]
    np.testing.assert_allclose(inferred[0], expected)
    world = util.position_transform(image, expected)[0]
    np.testing.assert_allclose(plan[0][1][0][0], world)
    axis = util.direction_transform(image, trajectory[1]).reshape(3)
    anchor = util.position_transform(image, trajectory[0])[0]
    assert np.linalg.norm(np.cross(world-anchor, axis)) < 1e-9


def test_repair_can_fill_more_than_one_seed_on_a_needle_without_mutating_input(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    monkeypatch.setattr(util, 'get_available_position', lambda t, seeds, *a: [1, 3, 5])
    original = core.seed_plan_to_world_coordinates([
        [trajectory, [(trajectory[0]+trajectory[1], trajectory[1])], [np.full(volume.shape, .25)]]
    ], image)
    result, status = repair_coverage(original, [trajectory], volume, image, 1,
        np.zeros_like(volume, dtype=bool), 1., 1., .9, {'length': 1., 'margin_rate': 1.},
        lambda *a: np.full(volume.shape, .4), lambda t, selected: not selected, rounds=4)
    assert len(original[0][1]) == 1
    assert len(result) == 1
    assert len(result[0][1]) == 3
    assert status['final_coverage'] == 1
    assert status['added_needles'] == 0
    assert status['added_seeds'] == 2


def test_targeted_generation_runs_even_when_existing_paths_improve(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    calls = []
    def generate(*args):
        calls.append(True)
        return []
    run_case(volume, image, trajectory, infer_dose=lambda *a: np.full(volume.shape, 1.1),
             validate=lambda *a: True, generate=generate)
    assert calls == [True]


def test_unhelpful_shortlist_does_not_hide_remaining_safe_candidates(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    candidates = [(np.array([float(i), 2., 2.]), trajectory[1], [5], [], 5)
                  for i in range(4)]
    calls = []
    def infer(*args):
        calls.append(True)
        return np.full(volume.shape, 1.1 if len(calls) == 4 else 0.)
    result, status = repair_coverage([], candidates, volume, image, 1,
        np.zeros_like(volume, dtype=bool), 1., 1., .9, {'length': 1., 'margin_rate': 1.},
        infer, lambda *a: True, shortlist=3)
    assert len(calls) == 4
    assert status['final_coverage'] == 1
    assert len(result) == 1


def test_other_positions_on_same_needle_are_tested_after_proxy_fails(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    monkeypatch.setattr(util, 'get_available_position', lambda *a: [1, 2, 3])
    calls = []
    def infer(point, *args):
        calls.append(point.copy())
        return np.full(volume.shape, 1.1 if len(calls) == 2 else 0.)
    result, status = run_case(volume, image, trajectory, infer_dose=infer,
                             validate=lambda *a: True, shortlist=1)
    assert len(calls) == 2
    assert not np.array_equal(calls[0], calls[1])
    assert status['final_coverage'] == 1


def test_normal_seed_placement_infers_at_the_published_point(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    trajectory = (trajectory[0], np.array([1., .37, .21]), [5], [], 5)
    inferred=[]
    def infer(point, *args, **kwargs):
        inferred.append(point.copy())
        return np.full(volume.shape, 1.1)
    monkeypatch.setattr(util, 'single_seed_dose_calculation_dl', infer)
    seeds, coverage, _ = util.put_seeds(volume, image, None, (8,8,8),
        np.zeros(volume.shape), 1, 1., trajectory, {'length':1.,'margin_rate':1.},
        .9, np.ones(volume.shape), -1000, 3000, 255)
    assert coverage == 1
    np.testing.assert_allclose(inferred[0], trajectory[0]+trajectory[1])
    np.testing.assert_allclose(seeds[0][0], inferred[0])


def test_empty_seed_candidate_does_not_stop_remaining_candidates(monkeypatch):
    volume, image, trajectory = setup_case(monkeypatch)
    other = (np.array([4., 2., 2.]), trajectory[1], [5], [], 5)
    choices = iter([(trajectory, 0), (other, 1)])
    monkeypatch.setattr(util, 'select_optimal_trajectory', lambda *a, **k: next(choices))
    calls = []
    def put(*args, **kwargs):
        calls.append(args[7])
        if len(calls) == 1:
            return [], 0., []
        return [(np.array([4., 2., 2.]), trajectory[1])], 1., [np.full(volume.shape, 1.1)]
    monkeypatch.setattr(util, 'put_seeds', put)
    monkeypatch.setattr(util, 'replan', lambda plan, vol, dose, *a, **k: (plan, 0., dose, False))
    class Context:
        seed_dose_cache_hits = seed_dose_cache_misses = _seed_dose_cache_bytes = 0
        _seed_dose_cache = {}
    monkeypatch.setattr(util, 'DoseImageContext', lambda *a: Context())
    plan = core.optimal_plan([trajectory, other], volume, image, None, {},
        .8, 10., .8, 1, 0, 2, (8, 8, 8), 1., 1., .9,
        {'length': 1., 'margin_rate': 1.}, 0, -1000, 3000, 255)
    assert len(calls) == 2
    assert len(plan) == 1
