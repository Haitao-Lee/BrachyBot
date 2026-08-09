"""Regression tests for result-preserving planning pipeline accelerations."""

from pathlib import Path
from unittest.mock import patch

from tool_factory.seed_plan.planning_pipeline import (
    PlanningPipelineTool,
    _filter_world_safe_trajectories,
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
