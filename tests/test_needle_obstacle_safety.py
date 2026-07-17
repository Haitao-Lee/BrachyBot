"""Regression coverage for full physical needle obstacle validation."""

import unittest
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import SimpleITK as sitk
except ImportError as exc:  # pragma: no cover - controlled by deployment image.
    raise unittest.SkipTest("SimpleITK is required for needle safety tests") from exc

from tool_factory.seed_plan.planning_pipeline import (
    _filter_world_safe_trajectories,
    _seed_plan_entry_needle_points,
    _world_segment_hits_obstacle,
)
from web.server_support import ManualNeedleSafetyError, _validate_manual_needle_safety


def _image_and_masks():
    image = sitk.Image([20, 20, 20], sitk.sitkInt16)
    image.SetOrigin((0.0, 0.0, 0.0))
    image.SetSpacing((1.0, 1.0, 1.0))
    ctv = np.zeros((20, 20, 20), dtype=np.uint8)
    oar = np.zeros((20, 20, 20), dtype=np.uint8)
    oar[10, 10, 5:15] = 77
    return image, ctv, oar


class _Memory:
    def get_ui_state(self):
        return {
            "data_tree": {
                "organs": [{
                    "id": "organ_77",
                    "label_id": 77,
                    "label": "case_specific_hard_structure",
                    "category": "non_traversable",
                    "source": "oar",
                }]
            }
        }


class _Agent:
    memory = _Memory()


class NeedleObstacleSafetyTests(unittest.TestCase):
    def test_full_world_needle_segment_rejects_hard_oar(self):
        image, ctv, oar = _image_and_masks()

        self.assertTrue(_world_segment_hits_obstacle(
            [np.array([0.0, 10.0, 10.0]), np.array([19.0, 10.0, 10.0])],
            image,
            ctv,
            oar,
            {77},
        ))
        self.assertFalse(_world_segment_hits_obstacle(
            [np.array([0.0, 0.0, 0.0]), np.array([19.0, 0.0, 0.0])],
            image,
            ctv,
            oar,
            {77},
        ))

    def test_candidate_filter_checks_same_150mm_world_geometry_as_viewer(self):
        image, ctv, oar = _image_and_masks()
        trajectory = [
            np.array([10.0, 10.0, 10.0]),
            np.array([0.0, 0.0, 1.0]),
            [3.0],
            [],
        ]

        self.assertEqual(
            _filter_world_safe_trajectories([trajectory], image, image, ctv, oar, {77}),
            [],
        )

        entry = [None, [
            (np.array([10.0, 8.0, 6.0]), np.array([1.0, 0.0, 0.0])),
            (np.array([20.0, 8.0, 6.0]), np.array([1.0, 0.0, 0.0])),
        ]]
        points = _seed_plan_entry_needle_points(entry, 150.0)
        self.assertTrue(np.allclose(points[0], [20.0, 8.0, 6.0]))
        self.assertTrue(np.allclose(points[1], [-140.0, 8.0, 6.0]))

    def test_manual_needles_cannot_bypass_data_tree_hard_obstacles(self):
        image, ctv, oar = _image_and_masks()
        unsafe = [{
            "id": "needle_manual_1",
            "points": [[0.0, 10.0, 10.0], [19.0, 10.0, 10.0]],
        }]

        with self.assertRaises(ManualNeedleSafetyError) as exc_info:
            _validate_manual_needle_safety(_Agent(), unsafe, image, ctv, oar)
        self.assertEqual(exc_info.exception.rejected_needle_ids, ["needle_manual_1"])


if __name__ == "__main__":
    unittest.main()
