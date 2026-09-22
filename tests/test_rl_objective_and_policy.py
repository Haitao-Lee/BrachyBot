"""Contracts for the RL plan objective, marginal rewards, caches and policy state.

These tests pin the redesigned search signal: the training reward must be the
marginal gain of the same plan objective used for selection, the objective must
keep strict coverage-target dominance while breaking near ties toward fewer
seeds/needles and lower OAR overdose, and the policy must actually condition on
its state.  All of these fail against the previous implementation.
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
    import torch
except ImportError as exc:  # pragma: no cover - deployment image
    raise unittest.SkipTest("torch is required for RL policy tests") from exc

from plans.reward_metrics import plan_objective
try:
    from plans.reinforcement import (
        REINFORCE,
        PolicyNet,
        SeedPlacementReward,
        evaluate_plan_objective,
        generate_plan_res,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - gymnasium optional
    raise unittest.SkipTest(f"reinforcement runtime unavailable: {exc}") from exc


class PlanObjectiveTests(unittest.TestCase):
    def test_meeting_the_coverage_target_beats_any_lower_coverage_plan(self):
        worst_meeting = plan_objective(0.90, 1.0, seed_count=40, needle_count=8, target_coverage=0.90)
        best_missing = plan_objective(0.90 - 1e-9, 0.0, seed_count=0, needle_count=0, target_coverage=0.90)
        self.assertGreater(worst_meeting, best_missing)

    def test_higher_coverage_is_never_worse_outside_the_noise_band(self):
        for met in (False, True):
            base_seed, base_needle, base_oar = 40, 8, 1.0
            low = plan_objective(0.50, base_oar, base_seed, base_needle, target_coverage=0.9)
            high = plan_objective(0.55, base_oar, base_seed, base_needle, target_coverage=0.9)
            self.assertGreater(high, low + 0.045, f"coverage gap collapsed when met={met}")

    def test_fewer_seeds_win_when_clinical_metrics_are_equivalent(self):
        heavy = plan_objective(0.95, 0.10, seed_count=40, needle_count=3, target_coverage=0.9)
        light = plan_objective(0.95, 0.10, seed_count=15, needle_count=3, target_coverage=0.9)
        self.assertGreater(light, heavy)

    def test_fewer_needles_win_when_clinical_metrics_are_equivalent(self):
        many = plan_objective(0.95, 0.10, seed_count=20, needle_count=6, target_coverage=0.9)
        few = plan_objective(0.95, 0.10, seed_count=20, needle_count=2, target_coverage=0.9)
        self.assertGreater(few, many)

    def test_large_oar_damage_differences_still_outweigh_seed_economy(self):
        cleaner = plan_objective(0.95, 0.05, seed_count=40, needle_count=3, target_coverage=0.9)
        cheaper = plan_objective(0.95, 0.15, seed_count=10, needle_count=1, target_coverage=0.9)
        self.assertGreater(cleaner, cheaper)

    def test_oar_overdose_is_penalised_before_the_target_is_met(self):
        safe = plan_objective(0.50, 0.0, seed_count=5, needle_count=1, target_coverage=0.9)
        damaging = plan_objective(0.50, 1.0, seed_count=5, needle_count=1, target_coverage=0.9)
        self.assertGreater(safe, damaging)

    def test_coverage_differences_below_the_target_still_dominate_cost_differences(self):
        frugal = plan_objective(0.50, 0.0, seed_count=5, needle_count=1, target_coverage=0.9)
        expensive_better = plan_objective(0.51, 1.0, seed_count=40, needle_count=8, target_coverage=0.9)
        self.assertGreater(expensive_better, frugal)


class EvaluatePlanObjectiveTests(unittest.TestCase):
    def test_redundant_seeds_are_penalised_for_the_same_total_dose(self):
        radiation_volume = np.array([[[1, 1, 0, 0]]], dtype=np.int16)
        whole = np.array([[[12.0, 12.0, 0.0, 0.0]]], dtype=np.float32)
        half = whole / 2.0
        single_seed_plan = [[None, [(np.zeros(3), np.ones(3))], [whole]]]
        split_seed_plan = [[None, [(np.zeros(3), np.ones(3)), (np.ones(3), np.ones(3))], [half, half]]]

        objective_single, coverage_single = evaluate_plan_objective(
            single_seed_plan, radiation_volume, 1, 10.0, 100.0, 0.9)
        objective_split, coverage_split = evaluate_plan_objective(
            split_seed_plan, radiation_volume, 1, 10.0, 100.0, 0.9)

        self.assertAlmostEqual(coverage_single, coverage_split)
        self.assertGreater(objective_single, objective_split)

    def test_extra_empty_trajectory_is_penalised(self):
        radiation_volume = np.array([[[1, 1, 0, 0]]], dtype=np.int16)
        dose = np.array([[[12.0, 12.0, 0.0, 0.0]]], dtype=np.float32)
        seed = (np.zeros(3), np.ones(3))
        two_needles = [[None, [seed], [dose]], [None, [seed], [dose]]]
        one_needle = [[None, [seed, seed], [dose, dose]]]

        objective_two, _ = evaluate_plan_objective(two_needles, radiation_volume, 1, 10.0, 100.0, 0.9)
        objective_one, _ = evaluate_plan_objective(one_needle, radiation_volume, 1, 10.0, 100.0, 0.9)

        self.assertGreater(objective_one, objective_two)


class SeedPlacementRewardTests(unittest.TestCase):
    def _reward_calculator(self, radiation_volume, in_lowest=10.0, out_highest=100.0, target=0.9):
        model = torch.nn.Linear(1, 1)
        return SeedPlacementReward(
            model,
            None,
            radiation_volume,
            1,
            in_lowest,
            out_highest,
            (8, 8, 8),
            {"length": 4.5, "radius": 0.4},
            -1000.0,
            3000.0,
            255.0,
            target,
        )

    def test_incremental_rewards_sum_to_the_plan_objective(self):
        radiation_volume = np.zeros((1, 1, 6), dtype=np.int16)
        radiation_volume[0, 0, 1:5] = 1  # four target voxels
        calculator = self._reward_calculator(radiation_volume)
        maps = [
            np.zeros((1, 1, 6), dtype=np.float32),
            np.zeros((1, 1, 6), dtype=np.float32),
        ]
        maps[0][0, 0, 1:3] = 12.0
        maps[1][0, 0, 3:5] = 12.0

        def fake_single(pos, *args, **kwargs):
            index = 0 if int(np.ravel(pos)[0]) == 0 else 1
            return maps[index]

        cur = np.zeros((1, 1, 6), dtype=np.float32)
        with patch("plans.utilizations.single_seed_dose_calculation_dl", side_effect=fake_single):
            r1, cur, cov1, _ = calculator.forward(
                [None, [], [], [], []], cur, np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 0.0]),
                seed_count=1, needle_count=1, is_new_needle=True)
            r2, cur, cov2, _ = calculator.forward(
                [None, [], [], [], []], cur, np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]),
                seed_count=2, needle_count=1, is_new_needle=False)

        self.assertGreater(cov1, 0.0)
        self.assertGreaterEqual(cov2, cov1)
        final_objective = plan_objective(cov2, 0.0, seed_count=2, needle_count=1, target_coverage=0.9)
        self.assertAlmostEqual(r1 + r2, final_objective, places=5)
        # A seed that adds no coverage must never look rewarding: only its cost
        # is charged, so the incremental reward is negative.
        with patch("plans.utilizations.single_seed_dose_calculation_dl", side_effect=fake_single):
            r3, _, _, _ = calculator.forward(
                [None, [], [], [], []], cur.copy(), np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 0.0]),
                seed_count=3, needle_count=1, is_new_needle=False)
        self.assertLess(r3, 0.0)

    def test_seed_dose_cache_distinguishes_directions(self):
        radiation_volume = np.zeros((2, 2, 2), dtype=np.int16)
        calculator = self._reward_calculator(radiation_volume)
        calls = []

        def fake_single(pos, direction, *args, **kwargs):
            calls.append((tuple(np.asarray(pos).ravel()), tuple(np.asarray(direction).ravel())))
            return np.ones((2, 2, 2), dtype=np.float32)

        dummy_traj = [None, [], [], [], []]
        with patch("plans.utilizations.single_seed_dose_calculation_dl", side_effect=fake_single):
            calculator.forward(dummy_traj, np.zeros((2, 2, 2), np.float32),
                               np.array([1.0, 0.0, 0.0]), np.array([1.0, 1.0, 1.0]))
            calculator.forward(dummy_traj, np.zeros((2, 2, 2), np.float32),
                               np.array([1.0, 0.0, 0.0]), np.array([1.0, 1.0, 1.0]))
            calculator.forward(dummy_traj, np.zeros((2, 2, 2), np.float32),
                               np.array([0.0, 0.0, 1.0]), np.array([1.0, 1.0, 1.0]))

        self.assertEqual(len(calls), 2, "same position+direction must be cached, different direction must not")
        self.assertEqual(calculator.cache_hits, 1)
        self.assertEqual(calculator.cache_misses, 2)

    def test_failed_seed_dose_is_never_injected_as_zero_dose(self):
        radiation_volume = np.zeros((1, 1, 4), dtype=np.int16)
        radiation_volume[0, 0, 1:3] = 1
        calculator = self._reward_calculator(radiation_volume)
        cur = np.zeros((1, 1, 4), dtype=np.float32)

        def broken(*args, **kwargs):
            raise RuntimeError("dose model exploded")

        with patch("plans.utilizations.single_seed_dose_calculation_dl", side_effect=broken):
            reward, updated, coverage, seed_map = calculator.forward(
                [None, [], [], [], []], cur, np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 0.0]))

        self.assertIsNone(seed_map, "a failed prediction must not fabricate a zero-dose seed")
        self.assertEqual(reward, 0.0)
        np.testing.assert_array_equal(updated, cur)


class PolicyStateTests(unittest.TestCase):
    def test_policy_scores_depend_on_the_state(self):
        torch.manual_seed(0)
        policy = PolicyNet(n_actions=4, state_dim=3)
        low_state = torch.zeros(1, 3)
        high_state = torch.ones(1, 3)
        self.assertFalse(torch.allclose(policy(low_state), policy(high_state)))

    def test_reinforce_accepts_multi_dimensional_states(self):
        agent = REINFORCE(n_actions=3, state_dim=4, lr=0.01)
        action = agent.select_action(np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))
        self.assertIn(action, (0, 1, 2))
        agent.record_reward(0.5)
        agent.finish_episode()


class PlanGeometryTests(unittest.TestCase):
    def test_plan_seed_positions_are_flat_world_vectors(self):
        image = _tiny_image()
        elem = [[0, (np.array([1.0, 1.0, 1.0]), np.array([1.0, 0.0, 0.0])),
                 [np.array([2.0, 1.0, 1.0])], [np.zeros((2, 2, 2), np.float32)], None]]
        planned = generate_plan_res(image, elem)
        position, direction = planned[0][1][0]
        self.assertEqual(np.asarray(position).shape, (3,))
        self.assertEqual(np.asarray(direction).shape, (3,))


def _tiny_image():
    import SimpleITK as sitk
    image = sitk.Image([4, 4, 4], sitk.sitkFloat32)
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetOrigin((0.0, 0.0, 0.0))
    return image


if __name__ == "__main__":
    unittest.main()
