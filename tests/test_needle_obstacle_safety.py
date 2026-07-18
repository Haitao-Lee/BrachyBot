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
    _merge_embedded_hard_obstacles,
    _resample_for_planning,
    _build_radiation_volume,
    _filter_world_safe_trajectories,
    _seed_plan_entry_needle_points,
    _world_segment_hits_obstacle,
    _resolve_data_tree_obstacle_labels,
)
from web.server_support import ManualNeedleSafetyError, _validate_manual_needle_safety
from AgenticSys import BrachyAgent


def _image_and_masks():
    image = sitk.Image([20, 20, 20], sitk.sitkInt16)
    image.SetOrigin((0.0, 0.0, 0.0))
    image.SetSpacing((1.0, 1.0, 1.0))
    ctv = np.zeros((20, 20, 20), dtype=np.uint8)
    oar = np.zeros((20, 20, 20), dtype=np.uint8)
    oar[10, 10, 5:15] = 77
    return image, ctv, oar


class _Memory:
    def __init__(self, embedded=None, organ_names=None):
        self.values = {
            "ctv_embedded_oar_array": embedded,
            "organ_names": organ_names or {},
        }

    def retrieve(self, key):
        return self.values.get(key)

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


class _DirectPlanningMemory(_Memory):
    def __init__(self, image, oar):
        super().__init__()
        self.values.update({
            "ct_image": image,
            "ctv_array": np.zeros_like(oar, dtype=np.uint8),
            "oar_array": oar,
        })


class _DirectPlanningAgent:
    def __init__(self, image, oar):
        self.memory = _DirectPlanningMemory(image, oar)


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

    def test_embedded_ctv_vessel_mask_survives_full_oar_namespace(self):
        _, _, full_oar = _image_and_masks()
        embedded = np.zeros_like(full_oar)
        embedded[10, 10, 2:5] = 1
        merged, labels = _merge_embedded_hard_obstacles(full_oar, _AgentWithEmbedded(embedded))
        self.assertEqual(len(labels), 1)
        synthetic = next(iter(labels))
        self.assertTrue(np.all(merged[10, 10, 2:5] == synthetic))
        self.assertEqual(int(merged[10, 10, 10]), 77)

    def test_bone_label_is_blocked_after_resampling_without_uint8_wrap(self):
        image = sitk.Image([20, 20, 20], sitk.sitkInt16)
        image.SetSpacing((1.0, 1.0, 1.0))
        ctv = np.zeros((20, 20, 20), dtype=np.uint8)
        oar = np.zeros((20, 20, 20), dtype=np.int32)
        # TotalSegmentator label 26 is vertebrae_S1. The candidate crosses
        # this thin axial bone slab in the planning grid.
        oar[10, 10, 8:12] = 26
        resampled_ct, resampled_ctv, resampled_oar = _resample_for_planning(
            image, ctv, oar, new_size=[20, 20, 20]
        )
        radiation = _build_radiation_volume(
            resampled_ctv,
            resampled_oar,
            target_value=1,
            obstacle_value=2,
            obstacle_labels={26},
            obstacle_source="test",
        )
        self.assertEqual(int(resampled_oar[10, 10, 9]), 26)
        self.assertEqual(int(radiation[10, 10, 9]), 2)

    def test_direct_planning_entry_point_uses_current_data_tree_obstacles(self):
        image, _, oar = _image_and_masks()
        agent = object.__new__(BrachyAgent)
        agent.memory = _DirectPlanningMemory(image, oar)
        context = agent._current_planning_obstacle_context()
        trajectory = [
            np.array([10.0, 10.0, 10.0]),
            np.array([0.0, 0.0, 1.0]),
            [3.0],
            [],
            3.0,
        ]
        filtered, _ = agent._filter_direct_planning_trajectories([trajectory], context)
        assert filtered == []


class _AgentWithEmbedded:
    def __init__(self, embedded):
        self.memory = _Memory(embedded=embedded)


def test_data_tree_ctv_bone_label_is_merged_into_final_hard_obstacle_grid():
    image = sitk.Image([12, 12, 12], sitk.sitkInt16)
    ctv = np.zeros((12, 12, 12), dtype=np.uint8)
    full_labels = np.zeros((12, 12, 12), dtype=np.uint8)
    full_labels[6, 6, 4:8] = 9

    class Memory(_Memory):
        def __init__(self):
            super().__init__()
            self.values.update({
                "ctv_full_labels": full_labels,
                "ctv_label_map": {1: "tumor", 9: "bone"},
            })

        def get_ui_state(self):
            return {"data_tree": {"organs": [{
                "id": "ctv_9", "label_id": 9, "source": "ctv",
                "category": "non_traversable",
            }]}}

    agent = type("Agent", (), {"memory": Memory()})()
    labels, _ = _resolve_data_tree_obstacle_labels(agent)
    merged, synthetic = _merge_embedded_hard_obstacles(None, agent)
    assert 9 in labels
    assert synthetic
    assert np.all(merged[6, 6, 4:8] == next(iter(synthetic)))


if __name__ == "__main__":
    unittest.main()
