from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import web.surgical_guide as surgical_guide


class _Memory:
    def __init__(self, values):
        self.values = dict(values)

    def retrieve(self, key):
        return self.values.get(key)

    def store(self, key, value):
        self.values[key] = value


def test_guide_retry_accepts_migrated_numpy_seed_coordinates(monkeypatch):
    """A coordinate-migrated snapshot must be usable by guide regeneration."""

    snapshot = {
        "seeds": [
            {
                "id": "seed_0_0",
                "position": np.array([10.0, 20.0, 30.0]),
                "direction": np.array([0.0, 0.0, 1.0]),
                "trajectory_id": "traj_1",
            }
        ],
        "needles": [
            {
                "id": "needle_0",
                "trajectory_id": "traj_1",
                "points": [[10.0, 20.0, 30.0], [10.0, 20.0, 0.0]],
            }
        ],
    }
    agent = SimpleNamespace(
        memory=_Memory(
            {
                "algorithm_plan_snapshot": snapshot,
                "manual_seeds": None,
                "manual_needles": None,
                "ct_image": object(),
                "ct_data": np.zeros((4, 4, 4), dtype=np.float32),
            }
        )
    )

    baseline = surgical_guide._algorithm_planning_snapshot(agent)
    assert np.array_equal(baseline["seeds"][0]["position"], [10.0, 20.0, 30.0])
    assert len(surgical_guide.planning_signature(baseline)) == 64

    monkeypatch.setattr(
        surgical_guide,
        "_segment_crosses_truncated_boundary",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        surgical_guide,
        "_sample_skin_entry",
        lambda *_args, **_kwargs: (
            np.array([10.0, 20.0, 1.0]),
            np.array([0.0, 0.0, 1.0]),
        ),
    )

    paths = surgical_guide._path_records(
        agent,
        np.zeros((4, 4, 4), dtype=bool),
        truncated_boundary_faces={
            "z_min": False,
            "z_max": False,
            "y_min": False,
            "y_max": False,
            "x_min": False,
            "x_max": False,
        },
    )

    assert len(paths) == 1
    assert paths[0].needle_id == "needle_0"
    assert paths[0].seed_count == 1
