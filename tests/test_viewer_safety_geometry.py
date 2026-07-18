"""Regression coverage for 3D meshes that represent hard planning obstacles."""

from web.routes.viewer_routes import _requires_label_faithful_mesh


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
