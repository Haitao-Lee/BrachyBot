"""Integration contracts for the RL search: batch prefetch, hierarchy-level
selection, greedy incumbent and the end-to-end synthetic planning run.

The synthetic case fakes the DoseUNet with deterministic Gaussian blobs so the
whole search path (dense evaluation, hierarchical state spaces, REINFORCE
episodes, greedy incumbent, plan conversion) runs without GPU weights.  It
pins three properties the previous implementation could not guarantee:
reproducibility under a fixed seed, non-empty successful planning, and that
the greedy warm start can only improve the returned objective.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import SimpleITK as sitk
    import torch
except ImportError as exc:  # pragma: no cover - deployment image
    raise unittest.SkipTest("SimpleITK and torch are required") from exc

from plans import core, utilizations
from plans.reward_metrics import plan_objective
try:
    from plans.reinforcement import SeedPlacementReward, evaluate_plan_objective
    from plans.utilizations import select_hierarchy_level
except ModuleNotFoundError as exc:  # pragma: no cover - gymnasium optional
    raise unittest.SkipTest(f"reinforcement runtime unavailable: {exc}") from exc


GRID = (20, 20, 28)
BLOB_PEAK = 20.0
BLOB_SIGMA2 = 12.0
IN_LOWEST = 5.0
OUT_HIGHEST = 8.0
DVH_TARGET = 0.9


def _blob(seed_point):
    seed_point = np.asarray(seed_point, dtype=np.float32).reshape(-1)
    zz, yy, xx = np.meshgrid(
        np.arange(GRID[0], dtype=np.float32),
        np.arange(GRID[1], dtype=np.float32),
        np.arange(GRID[2], dtype=np.float32),
        indexing="ij",
    )
    d2 = (zz - seed_point[0]) ** 2 + (yy - seed_point[1]) ** 2 + (xx - seed_point[2]) ** 2
    return (BLOB_PEAK * np.exp(-d2 / BLOB_SIGMA2)).astype(np.float32)


def _fake_single(pos, *args, **kwargs):
    return _blob(pos)


def _fake_batch(seeds, *args, **kwargs):
    return [_blob(seed[0]) for seed in seeds]


def _synthetic_case():
    # Elongated target along z: one seed cannot cover it, so needle choice,
    # seed spacing and the seed budget all matter for the plan objective.
    zz, yy, xx = np.meshgrid(
        np.arange(GRID[0], dtype=np.float32),
        np.arange(GRID[1], dtype=np.float32),
        np.arange(GRID[2], dtype=np.float32),
        indexing="ij",
    )
    # Two separate lobes 6 mm apart: one needle can never cover both, so the
    # multi-needle hierarchy path is structurally mandatory and comparable.
    lobe_a = (((zz - 10.0) / 5.0) ** 2 + ((yy - 7.0) / 2.5) ** 2 + ((xx - 14.0) / 2.5) ** 2) <= 1.0
    lobe_b = (((zz - 10.0) / 5.0) ** 2 + ((yy - 13.0) / 2.5) ** 2 + ((xx - 14.0) / 2.5) ** 2) <= 1.0
    radiation_volume = np.zeros(GRID, dtype=np.int16)
    radiation_volume[lobe_a | lobe_b] = 1
    image = sitk.GetImageFromArray(np.zeros(GRID, dtype=np.float32))
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetOrigin((0.0, 0.0, 0.0))
    trajectories = []
    for y in (7.0, 13.0):
        point = np.array([3.0, y, 14.0])
        direction = np.array([1.0, 0.0, 0.0])
        trajectories.append((point, direction, [14], [0]))
    return image, radiation_volume, trajectories


def _run_search(rf_params, diagnostics=None):
    image, radiation_volume, trajectories = _synthetic_case()
    with patch("plans.utilizations.single_seed_dose_calculation_dl", side_effect=_fake_single), \
         patch("plans.utilizations.batch_seed_dose_calculation_dl", side_effect=_fake_batch):
        return core.optimal_plan_rf(
            init_trajectories=trajectories,
            radiation_volume=radiation_volume,
            dose_image=image,
            dose_cal_model=torch.nn.Linear(1, 1),
            dl_params={},
            rf_params=rf_params,
            interval_rate=2,
            target_value=1,
            infer_img_size=(8, 8, 8),
            in_lowest_dose=IN_LOWEST,
            out_highest_dose=OUT_HIGHEST,
            DVH_rate=DVH_TARGET,
            seed_info={"radius": 0.4, "length": 3.0, "margin_rate": 1.0},
            image_normalize_min=-1000.0,
            image_normalize_max=3000.0,
            image_normalize_scale=255.0,
            parallel_min_distance_mm=0.5,
            parallel_angle_tolerance_deg=5.0,
            diagnostics=diagnostics,
        )


def _objective_of(plan):
    image, radiation_volume, _ = _synthetic_case()
    objective, coverage = evaluate_plan_objective(
        plan, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST, DVH_TARGET)
    return objective, coverage


FAST_PARAMS = {
    "lr": 0.01,
    "gamma": 0.9,
    "max_episodes": 12,
    "bandwidth": 8,
    "hierarchical_optimization": True,
    "segmented_rewards": True,
    "candidate_limit": 10,
    "dense_seed_limit": 8,
    "max_hierarchy_depth": 3,
    "max_actions_per_episode": 10,
    "max_wall_seconds": 60,
    "random_seed": 7,
}


class HierarchyLevelTests(unittest.TestCase):
    def test_equivalent_coverage_prefers_the_level_with_fewer_needles(self):
        shallow = [([[object()], [object()]], 0.90)]
        deep = [([[object()] for _ in range(5)], 0.91)]
        chosen = select_hierarchy_level([shallow, deep], needle_penalty=0.01)
        self.assertIs(chosen, shallow)

    def test_material_coverage_gain_still_justifies_another_needle(self):
        shallow = [([[object()], [object()]], 0.70)]
        deep = [([[object()] for _ in range(4)], 0.95)]
        chosen = select_hierarchy_level([shallow, deep], needle_penalty=0.01)
        self.assertIs(chosen, deep)


class PrefetchTests(unittest.TestCase):
    def test_prefetch_positions_fills_the_cache_in_one_batch_call(self):
        model = torch.nn.Linear(1, 1)
        image, radiation_volume, _ = _synthetic_case()
        calculator = SeedPlacementReward(
            model, image, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST,
            (8, 8, 8), {"length": 3.0, "radius": 0.4, "margin_rate": 1.0},
            -1000.0, 3000.0, 255.0, DVH_TARGET)
        candidates = [
            (np.array([7.0, 8.0, 10.0]), np.array([1.0, 0.0, 0.0])),
            (np.array([8.0, 8.0, 10.0]), np.array([1.0, 0.0, 0.0])),
        ]
        with patch("plans.utilizations.batch_seed_dose_calculation_dl",
                   side_effect=_fake_batch) as batch_mock, \
             patch("plans.utilizations.single_seed_dose_calculation_dl",
                   side_effect=_fake_single) as single_mock:
            filled = calculator.prefetch_positions(candidates)
            dummy_traj = [None, [], [], [], []]
            cur = np.zeros(GRID, dtype=np.float32)
            calculator.forward(dummy_traj, cur, np.array([1.0, 0.0, 0.0]), candidates[0][0])

        self.assertEqual(filled, 2)
        self.assertEqual(batch_mock.call_count, 1, "candidates must be filled in a single batch")
        self.assertEqual(single_mock.call_count, 0, "a prefetched position must not hit the model")


class SyntheticSearchTests(unittest.TestCase):
    def test_search_places_seeds_and_reaches_target_coverage(self):
        plan = _run_search(dict(FAST_PARAMS))
        self.assertTrue(plan, "the synthetic case must produce a plan")
        total_seeds = sum(len(entry[1]) for entry in plan)
        self.assertGreater(total_seeds, 0)
        _, coverage = _objective_of(plan)
        self.assertGreaterEqual(coverage, 0.5)

    def test_search_is_reproducible_under_a_fixed_seed(self):
        first = _run_search(dict(FAST_PARAMS))
        second = _run_search(dict(FAST_PARAMS))
        self.assertTrue(first and second, "both runs must plan successfully")

        def signature(plan):
            return [
                (np.round(np.asarray(seed[0]), 4).tolist(),
                 np.round(np.asarray(seed[1]), 4).tolist())
                for entry in plan for seed in entry[1]
            ]

        self.assertEqual(signature(first), signature(second))

    def test_greedy_warm_start_never_lowers_the_result(self):
        without = dict(FAST_PARAMS)
        without["greedy_warm_start"] = False
        with_greedy = dict(FAST_PARAMS)
        with_greedy["greedy_warm_start"] = True

        plan_without = _run_search(without)
        plan_with = _run_search(with_greedy)
        self.assertTrue(plan_without and plan_with, "both runs must plan successfully")
        objective_without, _ = _objective_of(plan_without)
        objective_with, _ = _objective_of(plan_with)

        self.assertGreaterEqual(objective_with, objective_without - 1e-9)

    def test_search_meets_the_target_without_brute_force_seed_padding(self):
        plan = _run_search(dict(FAST_PARAMS))
        _, coverage = _objective_of(plan)
        seed_count = sum(len(entry[1]) for entry in plan)
        self.assertGreaterEqual(coverage, DVH_TARGET)
        # The seed budget is part of the objective, so the search must stop
        # once another seed stops paying for itself instead of packing needles.
        self.assertLessEqual(
            seed_count, 6,
            "the search must not brute-force coverage with redundant seeds")


if __name__ == "__main__":
    unittest.main()
