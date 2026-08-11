import numpy as np
import pytest

sitk = pytest.importorskip("SimpleITK")

from plans.guide_geometry import (
    DEFAULT_GUIDE_CHANNEL_DIAMETER_MM,
    guide_primary_bore_diameter_mm,
)
from plans.utilizations import (
    get_parallel_trajectory_safety_mask,
    select_optimal_trajectory,
    update_available_traj,
)


def _dose_image():
    image = sitk.Image([64, 64, 64], sitk.sitkFloat32)
    image.SetSpacing([1.0, 1.0, 1.0])
    return image


def _trajectory(point, direction):
    # Planner trajectories carry depth metadata after the point and direction.
    return (np.asarray(point, dtype=float), np.asarray(direction, dtype=float), [], [], 10.0)


def test_default_spacing_is_the_physical_guide_bore_diameter():
    assert guide_primary_bore_diameter_mm() == pytest.approx(2.6)
    assert DEFAULT_GUIDE_CHANNEL_DIAMETER_MM == pytest.approx(2.6)


def test_parallel_candidate_below_guide_bore_diameter_is_rejected():
    image = _dose_image()
    planned = _trajectory([10, 10, 10], [0, 0, 1])
    candidate = _trajectory([12, 10, 10], [0, 0, 1])

    mask = get_parallel_trajectory_safety_mask([candidate], [planned], image)

    assert mask.tolist() == [False]


def test_non_parallel_candidate_keeps_the_historical_spacing_behavior():
    image = _dose_image()
    planned = _trajectory([10, 10, 10], [0, 0, 1])
    candidate = _trajectory([10, 12, 10], [1, 0, 0])

    mask = get_parallel_trajectory_safety_mask([candidate], [planned], image)
    available, is_valid = update_available_traj(
        [candidate],
        [planned],
        {"radius": 0.4},
        image,
        interval_rate=2,
    )

    # The paths are 2 mm apart: above the historical 1.6 mm threshold but
    # below the new 2.6 mm parallel-only threshold.
    assert mask.tolist() == [True]
    assert is_valid is True
    assert available == [candidate]


def test_selection_mask_cannot_be_bypassed_by_a_higher_score(monkeypatch):
    image = _dose_image()
    planned = _trajectory([10, 10, 10], [0, 0, 1])
    crowded = _trajectory([12, 10, 10], [0, 0, 1])
    safe = _trajectory([14, 10, 10], [0, 0, 1])

    monkeypatch.setattr(
        "plans.utilizations.get_candidate_traj_weights",
        lambda *args: [100.0, 1.0],
    )
    monkeypatch.setattr(
        "plans.utilizations.get_candidate_traj_radiation",
        lambda *args: [1.0, 1.0],
    )
    monkeypatch.setattr(
        "plans.utilizations.get_candidate_traj_edge_distance",
        lambda *args: [1.0, 1.0],
    )
    monkeypatch.setattr(
        "plans.utilizations.get_candidate_traj_dir_score",
        lambda *args: [1.0, 1.0],
    )
    monkeypatch.setattr(
        "plans.utilizations.get_available_position",
        lambda *args: [1],
    )

    selected, selected_index = select_optimal_trajectory(
        [crowded, safe],
        [planned],
        np.zeros((4, 4, 4), dtype=float),
        image,
        0.8,
        10.0,
        0.8,
        120.0,
        np.ones((4, 4, 4), dtype=float),
        {"radius": 0.4},
        [],
    )

    assert selected is safe
    assert selected_index == 1
