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
