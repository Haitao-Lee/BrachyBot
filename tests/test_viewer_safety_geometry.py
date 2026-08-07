"""Regression coverage for 3D meshes that represent hard planning obstacles."""

from web.routes.viewer_routes import _pad_surface_volume, _requires_label_faithful_mesh
from web.routes.planning_routes import _pad_dose_surface_volume

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


def test_embedded_ctv_vessels_are_always_label_faithful():
    assert _requires_label_faithful_mesh(_Agent([]), "ctv", 2)
    assert _requires_label_faithful_mesh(_Agent([]), "ctv", 3)


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
