"""Dose Viewer restore semantics for current and geometry-only Planning runs."""

import threading
from types import SimpleNamespace

import numpy as np

from web.routes.planning_routes import _dose_display_context, _dose_display_metadata


class _Memory:
    def __init__(self, values):
        self._lock = threading.RLock()
        self.planning_results = dict(values)
        self._planning_versions = {}
        self.conversation_state = {"data_available": []}

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)


def _agent(values):
    return SimpleNamespace(memory=_Memory(values), config={})


def test_geometry_only_child_uses_parent_algorithm_dose_as_stale_reference():
    current_alias = np.full((2, 2, 2), 9.0, dtype=np.float32)
    baseline = np.full((2, 2, 2), 3.0, dtype=np.float32)
    agent = _agent({
        "active_planning_id": "planning-child",
        "planning_runs": [{
            "planning_id": "planning-child",
            "parent_planning_id": "planning-parent",
            "sequence": 1,
            "label": "Planning_2",
            "visible": True,
        }],
        "manual_geometry_only": True,
        "manual_artifact_status": {"dose": "stale", "dvh": "stale"},
        # A legacy snapshot may retain these aliases. They must not win over
        # the immutable parent baseline or look current.
        "dose_distribution_gy": current_alias,
        "dose_metrics": {"v100": 0.1},
        "algorithm_plan_dose_distribution_gy": baseline,
        "algorithm_plan_dose_metrics": {"v100": 0.9},
        "algorithm_plan_dvh_data": {"CTV": {"dose": [0, 120]}},
    })

    context = _dose_display_context(agent)
    metadata = _dose_display_metadata(agent, context)
    assert context["array"] is baseline
    assert context["metrics"]["v100"] == 0.9
    assert context["source_planning_id"] == "planning-parent"
    assert metadata["dose_stale"] is True
    assert metadata["has_current_dose"] is False
    assert metadata["has_display_dose"] is True


def test_current_dose_has_precedence_for_a_ready_planning():
    current = np.full((2, 2, 2), 4.0, dtype=np.float32)
    agent = _agent({
        "active_planning_id": "planning-ready",
        "planning_runs": [{
            "planning_id": "planning-ready",
            "sequence": 0,
            "label": "Planning_1",
            "visible": True,
        }],
        "dose_distribution_gy": current,
        "dose_metrics": {"v100": 0.92},
        "algorithm_plan_dose_distribution_gy": np.ones_like(current),
    })

    context = _dose_display_context(agent)
    assert context["array"] is current
    assert context["stale"] is False
    assert context["source"] == "current_planning"


def test_physical_only_legacy_dose_is_recovered_to_normalized_display_units():
    physical = np.full((2, 2, 2), 100.0, dtype=np.float32)
    agent = _agent({
        "active_planning_id": "planning-physical",
        "planning_runs": [{
            "planning_id": "planning-physical",
            "sequence": 0,
            "label": "Planning_1",
            "visible": True,
        }],
        "dose_distribution_physical_gy": physical,
        "dose_scale_gy": 200.0,
        "dose_metrics": {"v100": 0.91},
    })

    context = _dose_display_context(agent)
    assert np.allclose(context["array"], 0.5)
    assert context["original_ct_space"] is True
    assert context["stale"] is False
    assert context["source"] == "current_physical_gy_recovered"
