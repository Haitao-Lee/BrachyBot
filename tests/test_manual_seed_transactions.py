from types import SimpleNamespace

import numpy as np

from web.routes.planning_routes import (
    _current_planning_snapshot,
    _manual_seed_geometry_settings,
    _normalize_manual_seed_records,
)


class Memory:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def retrieve(self, key, default=None):
        return self.values.get(key, default)

    def store(self, key, value):
        self.values[key] = value


def test_seed_projection_stays_inside_physical_implant_span():
    memory = Memory({"plan_config": {"seed_info": {"length": 4.5, "radius": 0.4}}})
    needles = [{
        "id": "needle_1",
        "trajectory_id": "traj_1",
        "points": [[0.0, 0.0, 0.0], [0.0, 0.0, 20.0]],
    }]
    seeds = [
        {"id": "near_start", "trajectory_id": "traj_1", "position": [4.0, 2.0, -50.0]},
        {"id": "near_end", "trajectory_id": "traj_1", "position": [-3.0, 1.0, 80.0]},
    ]

    result = _normalize_manual_seed_records(memory, seeds, needles)

    assert np.allclose(result[0]["position"], [0.0, 0.0, 2.25])
    assert np.allclose(result[1]["position"], [0.0, 0.0, 17.75])
    assert np.allclose(result[0]["direction"], [0.0, 0.0, 1.0])
    assert result[0]["axial_position_mm"] == 2.25
    assert result[1]["axial_position_mm"] == 17.75


def test_seed_projection_uses_configured_implant_step():
    memory = Memory({
        "plan_config": {
            "seed_info": {
                "length": 4.5,
                "radius": 0.4,
                "implant_step_mm": 5.0,
            },
        },
    })
    needles = [{
        "id": "needle_1",
        "trajectory_id": "traj_1",
        "points": [[0.0, 0.0, 0.0], [20.0, 0.0, 0.0]],
    }]
    seeds = [{"id": "seed_1", "trajectory_id": "traj_1", "position": [8.1, 7.0, 0.0]}]

    result = _normalize_manual_seed_records(memory, seeds, needles)

    assert np.allclose(result[0]["position"], [7.25, 0.0, 0.0])
    assert _manual_seed_geometry_settings(memory)["implant_step_mm"] == 5.0


def test_empty_manual_seed_list_remains_authoritative_after_last_delete():
    memory = Memory({
        "manual_plan_active": True,
        "manual_seeds": [],
        "manual_needles": [],
        "algorithm_plan_snapshot": {
            "seeds": [{"id": "old_seed"}],
            "needles": [{"id": "old_needle"}],
        },
    })
    agent = SimpleNamespace(memory=memory)

    assert _current_planning_snapshot(agent) == {"seeds": [], "needles": []}


def test_seed_transaction_rejects_missing_owner_and_duplicate_ids():
    memory = Memory()
    needles = [{
        "id": "needle_1",
        "trajectory_id": "traj_1",
        "points": [[0.0, 0.0, 0.0], [20.0, 0.0, 0.0]],
    }]

    try:
        _normalize_manual_seed_records(
            memory,
            [{"id": "seed_1", "trajectory_id": "missing", "position": [1.0, 0.0, 0.0]}],
            needles,
        )
    except ValueError as exc:
        assert "owning needle" in str(exc)
    else:
        raise AssertionError("missing owner should be rejected")

    try:
        _normalize_manual_seed_records(
            memory,
            [
                {"id": "seed_1", "trajectory_id": "traj_1", "position": [5.0, 0.0, 0.0]},
                {"id": "seed_1", "trajectory_id": "traj_1", "position": [10.0, 0.0, 0.0]},
            ],
            needles,
        )
    except ValueError as exc:
        assert "Duplicate seed id" in str(exc)
    else:
        raise AssertionError("duplicate ids should be rejected")


def test_seed_2d_overlay_uses_real_needle_projection_and_transaction_hooks():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    source = (root / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")

    # The 2D interaction must move the persistent planning record along the
    # projected owning needle, then use the same transaction as 3D editing.
    assert "function _projectPointerAlongNeedle2D" in source
    assert "function _ensureSeed2DInteraction" in source
    assert "pointerdown" in source and "pointermove" in source and "pointerup" in source
    assert "_showSeed2DContextMenu" in source
    assert "onManualSeedEdited" in source
    assert "position" in source and "direction" in source


def test_3d_seed_drag_repaints_the_2d_projection_before_commit():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    source = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    marker = "// Keep the 2D projection live while the 3D drag is still in progress."
    assert marker in source
    assert source.index(marker) < source.index("requestRender(1);", source.index(marker))
    assert "redrawSeedNeedleOverlays()" in source
