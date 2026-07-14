import numpy as np

from tool_factory.seed_plan.planning_pipeline import (
    _build_radiation_volume,
    _default_obstacle_label_ids,
    _resolve_data_tree_obstacle_labels,
)


class _Memory:
    def __init__(self, ui_state):
        self._ui_state = ui_state

    def get_ui_state(self):
        return self._ui_state


class _Agent:
    def __init__(self, ui_state):
        self.memory = _Memory(ui_state)


def test_default_policy_covers_bones_cartilage_and_vessels_only():
    labels = _default_obstacle_label_ids()
    assert {25, 52, 54, 65, 79, 91, 92, 116, 117}.issubset(labels)
    assert not ({6, 15, 16, 17, 18, 19, 20, 51} & labels)


def test_data_tree_whitelist_overrides_default_policy():
    agent = _Agent({
        "data_tree": {
            "organs": [
                {"id": "organ_6", "label_id": 6, "category": "non_traversable", "source": "oar"},
                {"id": "organ_52", "label_id": 52, "category": "traversable", "source": "oar"},
                {"id": "ctv_2", "label_id": 2, "category": "non_traversable", "source": "ctv"},
            ]
        }
    })
    labels, source = _resolve_data_tree_obstacle_labels(agent)
    assert labels == {6}
    assert source == "data_tree"

    ctv = np.array([[[1, 2, 0, 0]]], dtype=np.int16)
    oar = np.array([[[6, 0, 52, 0]]], dtype=np.int16)
    volume = _build_radiation_volume(ctv, oar, obstacle_labels=labels, obstacle_source=source)
    assert volume[0, 0, 0] == 1
    assert volume[0, 0, 1] == 2  # CTV vessel labels remain hard obstacles.
    assert volume[0, 0, 2] == 0  # Traversable by the current Data tree state.
    assert volume[0, 0, 3] == 0
