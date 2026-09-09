import numpy as np

from tool_factory.seed_plan.planning_pipeline import (
    _build_radiation_volume,
    _default_obstacle_label_ids,
    _resolve_data_tree_obstacle_labels,
    _trajectory_path_hits_obstacle,
)


class _Memory:
    def __init__(self, ui_state):
        self._ui_state = ui_state

    def get_ui_state(self):
        return self._ui_state

    def retrieve(self, key):
        return None


class _Agent:
    def __init__(self, ui_state):
        self.memory = _Memory(ui_state)


def test_default_policy_covers_bones_cartilage_and_vessels_only():
    labels = _default_obstacle_label_ids()
    assert {25, 52, 54, 65, 79, 91, 92, 116, 117}.issubset(labels)
    assert not ({6, 15, 16, 17, 18, 19, 20, 51} & labels)


def test_data_tree_adds_hard_labels_without_downgrading_default_policy():
    agent = _Agent({
        "data_tree": {
            "organs": [
                {"id": "organ_6", "label_id": 6, "category": "non_traversable", "source": "oar"},
                {"id": "organ_5", "label_id": 5, "category": "traversable", "source": "oar"},
                {"id": "ctv_2", "label_id": 2, "category": "non_traversable", "source": "ctv"},
            ]
        }
    })
    labels, source = _resolve_data_tree_obstacle_labels(agent)
    assert 6 in labels
    assert _default_obstacle_label_ids().issubset(labels)
    assert source == "data_tree_plus_default"

    ctv = np.array([[[1, 2, 0, 0]]], dtype=np.int16)
    oar = np.array([[[6, 0, 5, 0]]], dtype=np.int16)
    volume = _build_radiation_volume(ctv, oar, obstacle_labels=labels, obstacle_source=source)
    assert volume[0, 0, 0] == 1
    assert volume[0, 0, 1] == 2  # CTV vessel labels remain hard obstacles.
    assert volume[0, 0, 2] == 0  # Label 52 remains traversable; the baseline is not weakened.
    assert volume[0, 0, 3] == 0


def test_trajectory_obstacle_gate_checks_forward_and_reverse_segments():
    volume = np.zeros((1, 1, 12), dtype=np.int16)
    trajectory = (np.array([0, 0, 3]), np.array([0.0, 0.0, 1.0]), [3], [3], 3)

    volume[0, 0, 7] = 2
    assert _trajectory_path_hits_obstacle(trajectory, volume, 2)

    volume[0, 0, 7] = 0
    volume[0, 0, 1] = 2
    assert _trajectory_path_hits_obstacle(trajectory, volume, 2)

    volume[0, 0, 1] = 0
    assert not _trajectory_path_hits_obstacle(trajectory, volume, 2)

class _OverrideMemory(_Memory):
    def __init__(self, ui_state, values):
        super().__init__(ui_state)
        self.values = dict(values)

    def retrieve(self, key):
        return self.values.get(key)


def test_persisted_traversability_override_changes_planning_obstacle_volume_both_ways():
    ui_state = {
        "data_tree": {
            "organs": [
                {"id": "organ_52", "label_id": 52, "category": "traversable", "source": "oar"},
            ]
        }
    }
    values = {
        "structure_catalog": [
            {"object_id": "structure:oar:52", "classification": "oar", "target_label": 52,
             "traversability": "traversable"},
        ],
        "structure_overrides": {
            "structure:oar:52": {"classification": "oar", "target_label": 52,
                                  "traversability": "traversable"},
        },
    }
    agent = _Agent(ui_state)
    agent.memory = _OverrideMemory(ui_state, values)
    labels, source = _resolve_data_tree_obstacle_labels(agent)
    assert 52 not in labels
    assert source == "data_tree_override"
    traversable = _build_radiation_volume(
        np.array([[[0]]], dtype=np.int16),
        np.array([[[52]]], dtype=np.int16),
        obstacle_labels=labels,
        obstacle_source=source,
    )
    assert traversable[0, 0, 0] == 0
    values["structure_catalog"][0]["traversability"] = "non_traversable"
    values["structure_overrides"]["structure:oar:52"]["traversability"] = "non_traversable"
    ui_state["data_tree"]["organs"][0]["category"] = "non_traversable"
    labels, source = _resolve_data_tree_obstacle_labels(agent)
    assert 52 in labels
    assert source == "data_tree_override"
    blocked = _build_radiation_volume(
        np.array([[[0]]], dtype=np.int16),
        np.array([[[52]]], dtype=np.int16),
        obstacle_labels=labels,
        obstacle_source=source,
    )
    assert blocked[0, 0, 0] == 2
