"""Regression tests for result-preserving planning pipeline accelerations."""

from pathlib import Path
from unittest.mock import patch

import numpy as np

from tool_factory import ToolResult
from tool_factory.seed_plan.planning_pipeline import (
    PlanningPipelineTool,
    _coerce_planning_grid_ct,
    _filter_world_safe_trajectories,
    _planning_grid_array,
)


class _Memory:
    def __init__(self):
        self.values = {}

    def retrieve(self, key):
        return self.values.get(key)

    def store(self, key, value):
        self.values[key] = value


class _Agent:
    def __init__(self):
        self.memory = _Memory()


def test_planning_reuses_the_session_ct_for_the_same_source_path(tmp_path):
    source = tmp_path / "case.nii.gz"
    agent = _Agent()
    loaded_image = object()
    agent.memory.store("ct_path", str(source))
    agent.memory.store("ct_image", loaded_image)

    with patch("SimpleITK.ReadImage") as read_image:
        observed = PlanningPipelineTool()._load_ct(
            {"ct_image_path": Path(source)},
            agent,
        )

    assert observed is loaded_image
    read_image.assert_not_called()
    assert agent.memory.retrieve("ct_image_raw") is loaded_image


def test_planning_does_not_reuse_a_ct_from_another_source(tmp_path):
    current_source = tmp_path / "current.nii.gz"
    requested_source = tmp_path / "requested.nii.gz"
    agent = _Agent()
    agent.memory.store("ct_path", str(current_source))
    agent.memory.store("ct_image", object())
    disk_image = object()

    with (
        patch("SimpleITK.ReadImage", return_value=disk_image) as read_image,
        patch(
            "tool_factory.seed_plan.planning_pipeline._safe_dicom_orient",
            return_value=disk_image,
        ),
    ):
        observed = PlanningPipelineTool()._load_ct(
            {"ct_image_path": requested_source},
            agent,
        )

    assert observed is disk_image
    read_image.assert_called_once_with(requested_source)
    assert agent.memory.retrieve("ct_path") == requested_source


def test_world_safety_filter_reuses_a_precomputed_body_mask():
    with patch(
        "tool_factory.seed_plan.planning_pipeline._body_mask_from_ct"
    ) as build_body_mask:
        observed = _filter_world_safe_trajectories(
            [], None, object(), None, None, set(),
            body_mask=object(),
        )

    assert observed == []
    build_body_mask.assert_not_called()


def test_array_backed_planning_ct_is_rebuilt_with_current_physical_geometry():
    """Hydrated legacy planning grids must remain usable by SimpleITK filters."""
    import SimpleITK as sitk

    reference = sitk.GetImageFromArray(np.zeros((14, 512, 512), dtype=np.int16))
    reference.SetSpacing((0.7, 0.8, 2.5))
    reference.SetOrigin((12.0, -4.0, 8.0))
    reference.SetDirection((1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0))
    legacy_array = np.zeros((64, 128, 128), dtype=np.int16)

    repaired = _coerce_planning_grid_ct(
        legacy_array,
        reference,
        source="test",
    )

    assert repaired.GetSize() == (128, 128, 64)
    assert repaired.GetOrigin() == reference.GetOrigin()
    assert repaired.GetDirection() == reference.GetDirection()
    assert np.allclose(
        repaired.GetSpacing(),
        np.asarray(reference.GetSize()) * np.asarray(reference.GetSpacing())
        / np.asarray(repaired.GetSize()),
    )
    # This is the exact operation that previously raised GetPixelIDValue when
    # an ndarray crossed the seed-planning boundary.
    normalized = sitk.IntensityWindowing(
        repaired,
        windowMinimum=-1000,
        windowMaximum=3000,
        outputMinimum=-1000,
        outputMaximum=3000,
    )
    assert normalized.GetSize() == repaired.GetSize()


def test_planning_grid_array_accepts_numpy_oar_without_simpleitk_conversion():
    """OAR labels are arrays; converting them must not call GetPixelIDValue."""
    import SimpleITK as sitk

    oar = np.zeros((4, 5, 6), dtype=np.int32)
    oar[1, 2, 3] = 10000
    assert np.array_equal(_planning_grid_array(oar, source="test OAR"), oar)

    image = sitk.GetImageFromArray(oar)
    assert np.array_equal(_planning_grid_array(image, source="test OAR image"), oar)


def test_seed_planning_repairs_array_grid_before_dose_optimizer():
    """The observed ndarray/SimpleITK mismatch must fail cleanly, not crash."""
    import SimpleITK as sitk

    class Memory:
        def __init__(self):
            self.values = {}

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

    reference = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    reference.SetSpacing((1.0, 1.0, 1.0))
    target = np.zeros((4, 4, 4), dtype=np.uint8)
    target[1, 1, 1] = 1
    radiation = np.zeros_like(target, dtype=np.int32)
    radiation[target > 0] = 1
    trajectory = [
        np.asarray([1.0, 1.0, 1.0]),
        np.asarray([1.0, 0.0, 0.0]),
        [1],
        [],
        1,
    ]
    memory = Memory()
    memory.values.update({
        "refined_trajectories": [trajectory],
        "resampled_ct": np.zeros((4, 4, 4), dtype=np.int16),
        "resampled_ctv": target,
        "resampled_oar": None,
        "radiation_volume": radiation,
    })
    agent = type("Agent", (), {"memory": memory, "config": {}})()

    with (
        patch("tool_factory.seed_plan.planning_pipeline._load_dose_model", return_value=(object(), None)),
        patch(
            "tool_factory.seed_plan.planning_pipeline._filter_world_safe_trajectories",
            return_value=[trajectory],
        ),
        patch("plans.core.optimal_plan", return_value=[]),
    ):
        result = PlanningPipelineTool()._step_seed_planning(
            reference,
            target,
            None,
            "rule_based",
            {},
            agent,
        )

    assert result.success is False
    assert "could not place any valid seeds" in result.error
    assert hasattr(memory.retrieve("resampled_ct"), "GetPixelIDValue")


def test_successful_full_pipeline_publishes_reserved_planning_run_before_return():
    """A successful replan must be restorable, not only present in live memory."""

    class Memory:
        def __init__(self):
            self.values = {}

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

    agent = type("Agent", (), {"memory": Memory(), "config": {}})()
    tool = PlanningPipelineTool()
    published = {}

    def fake_publish(current_agent, result, *, status):
        published["planning_id"] = result.metadata["planning_id"]
        published["status"] = status
        return result.metadata["planning_id"]

    with (
        patch.object(tool, "_load_ct", return_value=object()),
        patch.object(tool, "_load_ctv", return_value=np.zeros((2, 2, 2), dtype=np.uint8)),
        patch.object(tool, "_load_oar", return_value=np.zeros((2, 2, 2), dtype=np.uint8)),
        patch(
            "tool_factory.seed_plan.planning_pipeline._merge_embedded_hard_obstacles",
            return_value=(object(), set()),
        ),
        patch(
            "tool_factory.seed_plan.planning_pipeline._resolve_ref_direc",
            return_value=[0.0, -1.0, 0.0],
        ),
        patch(
            "web.planning_runs.begin_planning_run",
            return_value="planning-test",
        ),
        patch.object(
            tool,
            "_run_full_pipeline",
            return_value=ToolResult(
                success=True,
                metadata={"total_seeds": 52, "num_trajectories": 8},
            ),
        ),
        patch(
            "web.planning_runs.publish_planning_run",
            side_effect=fake_publish,
        ),
    ):
        result = tool._execute(step="full", _agent=agent)

    assert result.success is True
    assert published == {"planning_id": "planning-test", "status": "completed"}
    assert result.metadata["planning_published"] is True
