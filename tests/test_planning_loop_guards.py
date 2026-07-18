"""Regression tests for planning loops whose progress must be explicit."""

import sys
import time
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from plans import geometry, utilizations
    from plans.config import setting
    from tool_factory.seed_plan.planning_pipeline import _apply_planning_overrides
except ImportError as exc:  # pragma: no cover - deployment dependency guard.
    raise unittest.SkipTest("Planning geometry dependencies are unavailable") from exc


class _ImageSpacingOnly:
    """Minimal image contract for invalid-direction validation."""

    def GetSpacing(self):
        return (1.0, 1.0, 1.0)


class PlanningLoopGuardTests(unittest.TestCase):
    def test_shrink_mask_reaches_the_requested_volume_without_a_retry_loop(self):
        mask = np.ones((5, 5, 5), dtype=np.uint8)

        result = geometry.shrink_island_by_distance(mask, target_percentage=0.5)

        self.assertEqual(int(np.count_nonzero(result)), 62)
        self.assertTrue(np.all((result == 0) | (result == 1)))

    def test_ray_tracing_normalizes_tiny_nonzero_normals_before_stepping(self):
        image = np.zeros((6, 1, 1), dtype=np.int8)
        image[0, 0, 0] = 1
        normals = np.zeros(image.shape + (3,), dtype=np.float64)
        normals[0, 0, 0] = (1e-8, 0.0, 0.0)

        started = time.monotonic()
        rays = geometry.ray_tracing(
            image,
            surface_points=np.array([[0, 0, 0]]),
            normals=normals,
            obs_val=-1,
            angle_range=180,
        )

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(len(rays), 1)

    def test_trajectory_scan_rejects_a_zero_direction_without_walking(self):
        array = np.zeros((6, 6, 6), dtype=np.int8)

        started = time.monotonic()
        blocked, target_lengths, background_lengths = geometry.get_trajectory_info(
            np.array([2.0, 2.0, 2.0]),
            array,
            np.zeros(3),
            target_value=1,
            background_value=0,
            obstacle_value=2,
        )

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(blocked)
        self.assertEqual(target_lengths, [])
        self.assertEqual(background_lengths, [])

    def test_zero_direction_has_no_seed_candidates(self):
        trajectory = [np.array([0.0, 0.0, 0.0]), np.zeros(3), [3], []]

        available = utilizations.get_available_position(
            trajectory,
            seeds=[],
            seed_info={"length": 4.5, "margin_rate": 1.0},
            dose_image=_ImageSpacingOnly(),
            distance_map=np.ones((3, 3, 3), dtype=np.float32),
        )

        self.assertEqual(available, [])

    def test_per_run_overrides_are_reproducible_for_every_pipeline_stage(self):
        overrides = {
            "in_lowest_energy": 1.15,
            "iter_rate": 3,
            "radiation_array_params": {
                "backlit_angle": 0.75,
                "maximum_candidate_trajectories": 37,
                "min_depth": 2,
            },
            "distance_filter": {"interval_rate": 4},
        }

        initial = _apply_planning_overrides(setting(), overrides)
        later_stage = _apply_planning_overrides(setting(), overrides)

        self.assertEqual(initial.in_lowest_energy, later_stage.in_lowest_energy)
        self.assertEqual(initial.iter_rate, later_stage.iter_rate)
        self.assertEqual(
            initial.radiation_array_params["maximum_candidate_trajectories"], 37,
        )
        self.assertEqual(
            later_stage.radiation_array_params["maximum_candidate_trajectories"], 37,
        )
        self.assertEqual(initial.distance_filtter["interval_rate"], 4)
        self.assertEqual(later_stage.distance_filtter["interval_rate"], 4)

    def test_rl_runtime_limits_are_validated_and_reused(self):
        overrides = {
            "rf_params": {
                "candidate_limit": 11,
                "dense_seed_limit": 9,
                "max_hierarchy_depth": 3,
                "max_actions_per_episode": 7,
                "max_wall_seconds": 95,
            }
        }

        args = _apply_planning_overrides(setting(), overrides)

        self.assertEqual(args.rf_params["candidate_limit"], 11)
        self.assertEqual(args.rf_params["dense_seed_limit"], 9)
        self.assertEqual(args.rf_params["max_hierarchy_depth"], 3)
        self.assertEqual(args.rf_params["max_actions_per_episode"], 7)
        self.assertEqual(args.rf_params["max_wall_seconds"], 95)


if __name__ == "__main__":
    unittest.main()
