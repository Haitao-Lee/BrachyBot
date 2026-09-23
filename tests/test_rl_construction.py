"""Structural contracts for RL planning success on full-size cases.

The 2026-09-22 regression: a 238 cm3 case that rule-based planning solves
(24 needles / 181 seeds / V100 ~90%) failed under RL with 57 seeds / 11%
because the RL search could not *express* the plan.  Plans were confined to a
single hierarchical trajectory combo (<= max_hierarchy_depth needles) drawn
from a capacity-blind 20-of-298 subsample (~70 seed slots total), so every
possible RL plan was structurally capped far below the clinical need.  These
tests pin the repair: a deterministic construction phase over the FULL
candidate pool must express and reach plans larger than the combo space, reuse
already-computed dense dose maps instead of re-inferring them, and keep the
hierarchy-level needle economy only once the coverage target is met.
"""
import sys
import time
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
try:
    from plans.reinforcement import (
        SeedPlacementReward,
        construct_plan_over_candidates,
        consolidate_plan_needles,
        evaluate_plan_objective,
    )
    from plans.utilizations import select_hierarchy_level
except ModuleNotFoundError as exc:  # pragma: no cover - gymnasium optional
    raise unittest.SkipTest(f"reinforcement runtime unavailable: {exc}") from exc

GRID = (16, 48, 24)
BLOB_PEAK = 20.0
BLOB_SIGMA2 = 12.0
IN_LOWEST = 5.0
OUT_HIGHEST = 8.0
DVH_TARGET = 0.9
LOBES = (3.0, 12.0, 21.0, 30.0, 39.0)


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


def _structural_case():
    """Five well-separated lobes; each needle can cover at most one lobe.

    A single-seed dose blob reaches ~4.1 voxels while lobe centers sit 9
    apart, so covering >= 90% of the target structurally requires >= 5
    needles.  The hierarchical combo space is capped at 3 needles by
    ``max_hierarchy_depth`` and the learning sub-sample is capped at 3
    candidates: only a full-pool construction can solve this case.
    """
    zz, yy, xx = np.meshgrid(
        np.arange(GRID[0], dtype=np.float32),
        np.arange(GRID[1], dtype=np.float32),
        np.arange(GRID[2], dtype=np.float32),
        indexing="ij",
    )
    radiation_volume = np.zeros(GRID, dtype=np.int16)
    for y_c in LOBES:
        lobe = (((zz - 8.0) / 3.0) ** 2 + ((yy - y_c) / 2.5) ** 2 + ((xx - 12.0) / 2.5) ** 2) <= 1.0
        radiation_volume[lobe] = 1
    image = sitk.GetImageFromArray(np.zeros(GRID, dtype=np.float32))
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetOrigin((0.0, 0.0, 0.0))
    trajectories = []
    for y_c in LOBES:
        point = np.array([3.0, y_c, 12.0])
        direction = np.array([1.0, 0.0, 0.0])
        trajectories.append((point, direction, [10], [0]))
    return image, radiation_volume, trajectories


SEED_INFO = {"radius": 0.4, "length": 3.0, "margin_rate": 1.0}

STRUCTURAL_PARAMS = {
    "lr": 0.01,
    "gamma": 0.9,
    "max_episodes": 8,
    "bandwidth": 8,
    "hierarchical_optimization": True,
    "segmented_rewards": True,
    "candidate_limit": 3,
    "dense_seed_limit": 8,
    "max_hierarchy_depth": 3,
    "max_actions_per_episode": 10,
    "max_wall_seconds": 60,
    "random_seed": 7,
    "greedy_warm_start": True,
}


def _run_search(rf_params, diagnostics=None):
    image, radiation_volume, trajectories = _structural_case()
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
            seed_info=dict(SEED_INFO),
            image_normalize_min=-1000.0,
            image_normalize_max=3000.0,
            image_normalize_scale=255.0,
            parallel_min_distance_mm=1.0,
            parallel_angle_tolerance_deg=5.0,
            diagnostics=diagnostics,
        )


def _plan_counts(plan):
    seeds = 0
    needles = 0
    for entry in plan:
        entry_seeds = entry[1] or []
        entry_maps = entry[2] or []
        count = len(entry_seeds) if entry_seeds else len(entry_maps)
        seeds += count
        if count:
            needles += 1
    return needles, seeds


class ConstructionExpressivenessTests(unittest.TestCase):
    def test_full_pool_construction_reaches_target_beyond_the_combo_space(self):
        """The incident regression in miniature.

        Learning sees 3 candidates and combos cap at 3 needles (max ~60%
        coverage), yet the returned plan must reach the 90% target using the
        full 5-needle pool.  A one-combo RL plan can never pass this.
        """
        plan = _run_search(dict(STRUCTURAL_PARAMS))
        self.assertTrue(plan, "the structural case must produce a plan")
        needles, seeds = _plan_counts(plan)
        image, radiation_volume, _ = _structural_case()
        objective, coverage = evaluate_plan_objective(
            plan, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST, DVH_TARGET)
        self.assertGreaterEqual(
            coverage, DVH_TARGET,
            f"coverage {coverage:.4f} must reach the target with needles={needles} seeds={seeds}")
        self.assertGreaterEqual(
            needles, len(LOBES),
            "the plan must express more needles than the hierarchical combo cap")
        self.assertLessEqual(
            seeds, 2 * len(LOBES),
            "construction must stay objective-economical instead of padding seeds")

    def test_construction_stops_cleanly_on_an_expired_deadline(self):
        image, radiation_volume, trajectories = _structural_case()
        calculator = SeedPlacementReward(
            torch.nn.Linear(1, 1), image, radiation_volume, 1,
            IN_LOWEST, OUT_HIGHEST, (8, 8, 8), dict(SEED_INFO),
            -1000.0, 3000.0, 255.0, DVH_TARGET)
        from scipy.ndimage import distance_transform_edt
        distance_map = distance_transform_edt(radiation_volume == 1)
        plan = construct_plan_over_candidates(
            calculator,
            trajectories,
            radiation_volume,
            1,
            image,
            distance_map,
            dict(SEED_INFO),
            interval_rate=2,
            deadline=time.monotonic() - 1.0,
            parallel_min_distance_mm=1.0,
            parallel_angle_tolerance_deg=5.0,
        )
        self.assertEqual(plan, [])


class DenseDoseReuseTests(unittest.TestCase):
    def test_imported_dense_maps_avoid_repeated_model_inference(self):
        image, radiation_volume, _ = _structural_case()
        calculator = SeedPlacementReward(
            torch.nn.Linear(1, 1), image, radiation_volume, 1,
            IN_LOWEST, OUT_HIGHEST, (8, 8, 8), dict(SEED_INFO),
            -1000.0, 3000.0, 255.0, DVH_TARGET)
        pos = np.array([5.0, 3.0, 12.0])
        axis = np.array([1.0, 0.0, 0.0])
        dense_map = _blob(pos)
        traj_elem = [0, (pos, axis, [10], [0]), [(pos, axis)], [dense_map], dense_map]
        calculator.import_trajectory_dose_maps(traj_elem)

        with patch("plans.utilizations.batch_seed_dose_calculation_dl",
                   side_effect=_fake_batch) as batch_mock, \
             patch("plans.utilizations.single_seed_dose_calculation_dl",
                   side_effect=_fake_single) as single_mock:
            filled = calculator.prefetch_positions([(pos, axis)])
            cur = np.zeros(GRID, dtype=np.float32)
            reward, cur, coverage, returned = calculator.forward(
                traj_elem, cur, axis, pos)

        self.assertEqual(filled, 0, "already-computed dense maps must satisfy the prefetch")
        self.assertEqual(batch_mock.call_count, 0, "prefetch must not re-infer imported maps")
        self.assertEqual(single_mock.call_count, 0, "forward must hit the imported map")
        self.assertIsNotNone(returned)


class HierarchyLevelPolicyTests(unittest.TestCase):
    def test_below_target_the_level_with_more_coverage_wins(self):
        shallow = [([[object()], [object()]], 0.50)]
        deep = [([[object()] for _ in range(5)], 0.70)]
        chosen = select_hierarchy_level(
            [shallow, deep], needle_penalty=0.01, target_coverage=0.9)
        self.assertIs(chosen, deep)

    def test_at_target_needle_economy_still_decides(self):
        shallow = [([[object()], [object()]], 0.90)]
        deep = [([[object()] for _ in range(5)], 0.91)]
        chosen = select_hierarchy_level(
            [shallow, deep], needle_penalty=0.01, target_coverage=0.9)
        self.assertIs(chosen, shallow)


class ConsolidationTests(unittest.TestCase):
    """Needle economy under the plan objective.

    Marginal-gain construction reaches the target with a slightly spread
    layout (the 238 cm3 case: 29 needles x 6.3 seeds vs rule-based 24 x 7.5)
    because it stops a needle when its fringe slots stop paying and opens a
    new one instead.  After the target is met one needle costs the objective
    as much as ~6.7 seeds, so thin needles must be droppable whenever their
    seeds can ride on surviving needles' free slots.
    """

    def _calculator(self, image, radiation_volume):
        return SeedPlacementReward(
            torch.nn.Linear(1, 1), image, radiation_volume, 1,
            IN_LOWEST, OUT_HIGHEST, (8, 8, 8), dict(SEED_INFO),
            -1000.0, 3000.0, 255.0, DVH_TARGET)

    def _single_lobe_case(self):
        zz, yy, xx = np.meshgrid(
            np.arange(GRID[0], dtype=np.float32),
            np.arange(GRID[1], dtype=np.float32),
            np.arange(GRID[2], dtype=np.float32),
            indexing="ij",
        )
        lobe = (((zz - 8.0) / 5.0) ** 2 + ((yy - 3.0) / 2.5) ** 2 + ((xx - 12.0) / 2.5) ** 2) <= 1.0
        radiation_volume = np.zeros(GRID, dtype=np.int16)
        radiation_volume[lobe] = 1
        image = sitk.GetImageFromArray(np.zeros(GRID, dtype=np.float32))
        image.SetSpacing((1.0, 1.0, 1.0))
        image.SetOrigin((0.0, 0.0, 0.0))
        return image, radiation_volume

    @staticmethod
    def _world(image, voxel_point):
        return np.asarray(
            utilizations.position_transform(image, np.asarray(voxel_point))[0]).reshape(-1)

    def test_consolidation_trades_a_thin_needle_for_a_denser_pack(self):
        from scipy.ndimage import distance_transform_edt
        image, radiation_volume = self._single_lobe_case()
        calculator = self._calculator(image, radiation_volume)
        distance_map = distance_transform_edt(radiation_volume == 1)
        axis = np.array([1.0, 0.0, 0.0])
        # Two thin parallel needles through one lobe, one seed each.  Needle 0
        # has a free slot at the same depth as needle 1's only seed, so the
        # second puncture is surplus the objective should trade away.
        traj_a = (np.array([1.0, 3.0, 12.0]), axis, [14], [0])
        traj_b = (np.array([1.0, 3.6, 12.0]), axis, [14], [0])
        seed_a = np.array([5.0, 3.0, 12.0])
        seed_b = np.array([11.0, 3.0, 12.0])
        entries = [
            [traj_a, [[self._world(image, seed_a), axis]], [_blob(seed_a)]],
            [traj_b, [[self._world(image, seed_b), axis]], [_blob(seed_b)]],
        ]
        before_objective, before_coverage = evaluate_plan_objective(
            entries, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST, DVH_TARGET)
        self.assertGreaterEqual(before_coverage, DVH_TARGET)

        with patch("plans.utilizations.single_seed_dose_calculation_dl",
                   side_effect=_fake_single), \
             patch("plans.utilizations.batch_seed_dose_calculation_dl",
                   side_effect=_fake_batch):
            consolidated = consolidate_plan_needles(
                calculator, entries, image, distance_map, dict(SEED_INFO),
            )

        after_objective, after_coverage = evaluate_plan_objective(
            consolidated, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST, DVH_TARGET)
        self.assertEqual(len(consolidated), 1, "the thin needle must be absorbed")
        self.assertEqual(sum(len(e[1]) for e in consolidated), 2)
        self.assertGreaterEqual(after_coverage, before_coverage - 1e-6)
        self.assertGreater(after_objective, before_objective)

    def test_consolidation_keeps_a_needle_when_replacement_cannot_pay(self):
        from scipy.ndimage import distance_transform_edt
        image, radiation_volume, trajectories = _structural_case()
        calculator = self._calculator(image, radiation_volume)
        distance_map = distance_transform_edt(radiation_volume == 1)
        # Two far-apart lobes, one needle each.  The other needle cannot
        # reach the cold lobe at all, so dropping either one loses coverage
        # the objective must refuse to trade.
        traj_a, traj_b = trajectories[0], trajectories[1]
        axis = np.array([1.0, 0.0, 0.0])
        seeds_a = [np.array([4.0, 3.0, 12.0]), np.array([8.0, 3.0, 12.0])]
        seeds_b = [np.array([4.0, 12.0, 12.0]), np.array([8.0, 12.0, 12.0])]
        entries = [
            [traj_a, [[self._world(image, p), axis] for p in seeds_a],
             [_blob(p) for p in seeds_a]],
            [traj_b, [[self._world(image, p), axis] for p in seeds_b],
             [_blob(p) for p in seeds_b]],
        ]
        before_objective, _ = evaluate_plan_objective(
            entries, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST, DVH_TARGET)

        with patch("plans.utilizations.single_seed_dose_calculation_dl",
                   side_effect=_fake_single), \
             patch("plans.utilizations.batch_seed_dose_calculation_dl",
                   side_effect=_fake_batch):
            consolidated = consolidate_plan_needles(
                calculator, entries, image, distance_map, dict(SEED_INFO),
            )

        after_objective, after_coverage = evaluate_plan_objective(
            consolidated, radiation_volume, 1, IN_LOWEST, OUT_HIGHEST, DVH_TARGET)
        self.assertEqual(len(consolidated), 2, "both load-bearing needles must stay")
        self.assertGreaterEqual(after_objective, before_objective - 1e-9)
        self.assertGreaterEqual(after_coverage, 0.2)


class PhaseOrderTests(unittest.TestCase):
    def test_construction_precedes_the_dense_learning_phase(self):
        """Construction must claim its wall-clock budget before the learning
        sub-sample's dense evaluation.  The 2026-09-23 morning run showed the
        failure mode: a contended GPU stretched dense evaluation to 184 s,
        construction was left ~110 s and reached only 3 needles, and the plan
        had to be rescued by the deterministic fallback.
        """
        order = []
        import plans.reinforcement as reinforcement_mod

        real_construct = reinforcement_mod.construct_plan_over_candidates
        real_spaces = utilizations.generate_hierarchical_state_spaces

        def spy_construct(*args, **kwargs):
            order.append("construct")
            return real_construct(*args, **kwargs)

        def spy_spaces(*args, **kwargs):
            order.append("hierarchy")
            return real_spaces(*args, **kwargs)

        with patch.object(reinforcement_mod, "construct_plan_over_candidates",
                          spy_construct), \
             patch.object(utilizations, "generate_hierarchical_state_spaces",
                          spy_spaces), \
             patch("plans.utilizations.single_seed_dose_calculation_dl",
                   side_effect=_fake_single), \
             patch("plans.utilizations.batch_seed_dose_calculation_dl",
                   side_effect=_fake_batch):
            plan = _run_search(dict(STRUCTURAL_PARAMS))

        self.assertTrue(plan, "the case must still plan")
        self.assertEqual(order[0], "construct",
                         f"construction must run first, got order={order}")


if __name__ == "__main__":
    unittest.main()
