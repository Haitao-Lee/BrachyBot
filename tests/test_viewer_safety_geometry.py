"""Regression coverage for 3D meshes that represent hard planning obstacles."""

from web.routes.viewer_routes import _pad_surface_volume, _requires_label_faithful_mesh
from web.routes.planning_routes import _dose_coverage_audit, _pad_dose_surface_volume

import numpy as np


class _Memory:
    def __init__(self, organs):
        self._organs = organs

    def retrieve(self, _key):
        return None

    def get_ui_state(self):
        return {"data_tree": {"organs": self._organs}}


class _Agent:
    def __init__(self, organs):
        self.memory = _Memory(organs)


def test_non_traversable_data_tree_label_uses_faithful_mesh_geometry():
    agent = _Agent([{
        "id": "organ_6",
        "label_id": 6,
        "source": "oar",
        "category": "non_traversable",
    }])

    assert _requires_label_faithful_mesh(agent, "oar", 6)


def test_soft_tissue_mesh_keeps_presentation_smoothing():
    agent = _Agent([{
        "id": "organ_6",
        "label_id": 6,
        "source": "oar",
        "category": "traversable",
    }])

    assert not _requires_label_faithful_mesh(agent, "oar", 6)


def test_every_ctv_label_uses_the_same_boundary_as_dose_evaluation():
    assert _requires_label_faithful_mesh(_Agent([]), "ctv", 1)
    assert _requires_label_faithful_mesh(_Agent([]), "ctv", 2)
    assert _requires_label_faithful_mesh(_Agent([]), "ctv", 3)
    assert _requires_label_faithful_mesh(_Agent([]), "CTV", 99)


def test_surface_padding_closes_volume_boundary_without_moving_original_voxels():
    mask = np.zeros((2, 3, 4), dtype=np.uint8)
    mask[0, 1, 2] = 1

    padded, offset_zyx = _pad_surface_volume(mask)

    assert padded.shape == (4, 5, 6)
    assert np.array_equal(padded[1:-1, 1:-1, 1:-1], mask)
    assert np.array_equal(offset_zyx, np.array([1.0, 1.0, 1.0]))
    assert padded[0].sum() == 0
    assert padded[-1].sum() == 0


def test_dose_surface_padding_preserves_grid_and_uses_background_fill():
    dose = np.full((2, 3, 4), 0.25, dtype=np.float32)
    dose[0, 1, 2] = 1.0

    padded, offset_zyx = _pad_dose_surface_volume(dose, fill_value=0.25)

    assert padded.shape == (4, 5, 6)
    assert np.array_equal(padded[1:-1, 1:-1, 1:-1], dose)
    assert np.array_equal(offset_zyx, np.array([1.0, 1.0, 1.0]))
    assert np.all(padded[0] == 0.25)
    assert np.all(padded[-1] == 0.25)


def test_dose_surface_coverage_audit_matches_fraction_dvh_metric():
    target = np.ones((1, 2, 2), dtype=np.uint8)
    dose = np.array([[[0.7, 0.7], [0.7, 0.1]]], dtype=np.float32)

    audit = _dose_coverage_audit(
        dose,
        target,
        0.5,
        threshold_gy=120.0,
        prescription_gy=120.0,
        dose_metrics={"v100": 0.75, "volume_metric_units": "fraction"},
        grid="original_ct",
    )

    assert audit["covered_target_voxels"] == 3
    assert audit["coverage_percent"] == 75.0
    assert audit["reported_metric"] == "v100"
    assert audit["reported_coverage_percent"] == 75.0
    assert audit["consistent"] is True


def test_dose_surface_coverage_audit_understands_percent_and_flags_mismatch():
    target = np.ones((1, 2, 2), dtype=np.uint8)
    dose = np.array([[[0.7, 0.1], [0.1, 0.1]]], dtype=np.float32)

    audit = _dose_coverage_audit(
        dose,
        target,
        0.5,
        threshold_gy=120.0,
        prescription_gy=120.0,
        dose_metrics={"v100": 90.0, "volume_metric_units": "percent"},
    )

    assert audit["coverage_percent"] == 25.0
    assert audit["reported_coverage_percent"] == 90.0
    assert audit["delta_percentage_points"] == -65.0
    assert audit["consistent"] is False
