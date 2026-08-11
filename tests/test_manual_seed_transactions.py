from types import SimpleNamespace

import numpy as np

from web.routes.planning_routes import (
    _current_planning_snapshot,
    _deduplicate_manual_needle_records,
    _deduplicate_manual_seed_records,
    _manual_seed_geometry_settings,
    _normalize_manual_seed_records,
    _submitted_manual_needles,
)
from web.server_support import _manual_grid_array, _seed_interference_report


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


def test_seed_interference_uses_finite_cylinder_clearance_and_trajectory_owner():
    """Seed clearance must follow real cylinder axes, not matching positions."""
    memory = Memory({
        "plan_config": {
            "seed_info": {
                "length": 4.5,
                "radius": 0.4,
                "minimum_clearance_mm": 0.5,
            },
        },
    })
    agent = SimpleNamespace(memory=memory)
    needles = [
        {"id": "needle_a", "trajectory_id": "traj_1", "points": [[0, 0, 0], [0, 0, 20]]},
        {"id": "needle_b", "trajectory_id": "traj_2", "points": [[0.2, 0, 0], [0.2, 0, 20]]},
    ]
    seeds = [
        {"id": "seed_a", "trajectory_id": "traj_1", "position": [0, 0, 10]},
        {"id": "seed_b", "trajectory_id": "traj_2", "position": [0.2, 0, 10]},
    ]

    report = _seed_interference_report(agent, seeds, needles)

    assert report["status"] == "attention"
    assert report["threshold_mm"] == 1.3
    assert report["close_pairs"][0]["first_id"] == "seed_a"
    assert report["close_pairs"][0]["second_id"] == "seed_b"
    assert report["close_pairs"][0]["first_needle_id"] == "traj_1"
    assert report["close_pairs"][0]["axis_distance_mm"] == 0.2
    assert report["close_pairs"][0]["risk"] == "overlap"


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


def test_manual_snapshot_accepts_numpy_restored_records_without_truthiness():
    memory = Memory({
        "manual_plan_active": True,
        "manual_seeds": np.asarray([{"id": "seed_1"}], dtype=object),
        "manual_needles": np.asarray([{"id": "needle_1"}], dtype=object),
    })
    agent = SimpleNamespace(memory=memory)

    assert _current_planning_snapshot(agent) == {
        "seeds": [{"id": "seed_1"}],
        "needles": [{"id": "needle_1"}],
    }


def test_automatic_snapshot_uses_the_same_public_ids_as_viewer_endpoints():
    """Zero-based dose-map storage must never leak into public object IDs."""
    memory = Memory({
        "algorithm_plan_snapshot": {
            "seeds": [{"id": "seed_0_0"}],
            "needles": [{"id": "needle_0"}],
        },
        "seed_plan_serialized": [{
            "seeds": [([1.0, 2.0, 3.0], [0.0, 0.0, 1.0])],
        }],
        "verified_needle_geometry": {
            "0": [[1.0, 2.0, 0.0], [1.0, 2.0, 10.0]],
        },
    })

    snapshot = _current_planning_snapshot(SimpleNamespace(memory=memory))

    assert snapshot["seeds"][0]["id"] == "seed_1_1"
    assert snapshot["seeds"][0]["trajectory_id"] == "traj_1"
    assert snapshot["needles"][0]["id"] == "needle_1"
    assert snapshot["needles"][0]["trajectory_id"] == "traj_1"


def test_hydrated_flattened_volume_is_restored_to_the_ct_grid():
    flat = np.arange(2 * 3 * 4, dtype=np.int16)

    restored = _manual_grid_array(flat, (2, 3, 4), label="CTV")

    assert restored.shape == (2, 3, 4)
    assert restored[1, 2, 3] == flat[-1]


def test_hydrated_volume_with_wrong_size_is_rejected():
    try:
        _manual_grid_array(np.zeros(11, dtype=np.uint8), (2, 3, 4), label="OAR")
    except ValueError as exc:
        assert "OAR shape" in str(exc)
    else:
        raise AssertionError("a mismatched persisted volume must be rejected")


def test_explicit_empty_needles_is_a_real_delete_request():
    current = [{"id": "needle_old"}]

    assert _submitted_manual_needles({"needles": []}, current) == []
    assert _submitted_manual_needles({}, current) == current
    assert _submitted_manual_needles({"needles": None}, current) == current


def test_legacy_manual_needles_and_seeds_are_deduplicated_by_stable_id():
    needles, needle_ids = _deduplicate_manual_needle_records([
        {"id": "needle_manual_1", "points": [[0, 0, 0], [0, 0, 1]]},
        {"id": "needle_manual_1", "points": [[0, 0, 0], [0, 0, 2]]},
    ])
    seeds, seed_ids = _deduplicate_manual_seed_records([
        {"id": "seed_manual_1", "position": [0, 0, 1]},
        {"id": "seed_manual_1", "position": [0, 0, 2]},
    ])

    assert needle_ids == ["needle_manual_1"]
    assert len(needles) == 1
    assert needles[0]["points"][-1] == [0, 0, 2]
    assert seed_ids == ["seed_manual_1"]
    assert len(seeds) == 1
    assert seeds[0]["position"] == [0, 0, 2]


def test_manual_needle_mutations_use_authoritative_backend_transactions():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    routes = (root / "web/routes/planning_routes.py").read_text(encoding="utf-8")

    assert "await _persistNeedleGeometryOnly({" in manual
    assert "reason: 'needle_add'" in manual
    assert "await _commitManualSeeds('needle_delete', rollback.seeds, rollback.needles)" in manual
    assert "expected_version: payload.planning_version" in manual
    assert '"artifact_status": artifact_status' in routes
    assert 'memory.store("manual_plan_version", next_version)' in routes
    assert "_mark_manual_dependents_stale(" in routes


def test_manual_tree_repairs_duplicate_planning_rows_before_render():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    viewer = (root / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")

    assert "function _dedupeManualNeedles(needles)" in manual
    assert "dataTreeState.planning.needles = _dedupeManualNeedles" in manual
    assert "function _deduplicatePlanningRows()" in viewer
    assert "_deduplicatePlanningRows();" in viewer


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


def test_3d_seed_drag_owns_the_webgl_pointer_before_orbit_controls():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    source = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    # A wrapper-level bubble listener lets OrbitControls consume the same
    # pointerdown first. Seed editing must be capture-phase on the renderer
    # surface and use one prior confirmation decision for the commit path.
    assert "const handlePlanningPointerDown = (event) =>" in source
    assert "interactionCanvas.addEventListener(\n        'pointerdown',\n        handlePlanningPointerDown,\n        true,\n    );" in source
    assert "canvas.addEventListener('mousedown', (event) =>" not in source
    assert "event.stopImmediatePropagation();" in source
    assert "nearestSeedOnPointerRay" in source
    assert "doseRecomputeDecision" in source


def test_manual_dose_marks_the_backend_commit_before_slow_viewer_hydration():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    source = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    assert "_refreshManualDoseViews(data, wasDoseTextureEnabled, { background: true })" in source
    assert "manualPlanningState.backgroundDoseViewerRefresh = refreshPromise" in source


def test_seed_drag_rejects_interference_before_dose_and_restores_authoritative_state():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    routes = (root / "web/routes/planning_routes.py").read_text(encoding="utf-8")

    update_seeds_start = routes.index("def api_manual_planning_update_seeds")
    update_seeds = routes[update_seeds_start:]
    assert update_seeds.index("interference = _seed_interference_report") < update_seeds.index("planning_id = fork_planning_run")
    assert '"code": "manual_seed_interference"' in update_seeds
    assert "const authoritativeSeeds = Array.isArray(data?.seeds)" in manual
    assert "pair.first_id || '?'" in manual
    assert "window.restoreSeedToOriginalPosition = restoreAlgorithmPlan" in manual
    assert "incrementalSeedEdit ? 600000 : 900000" in manual


def test_active_manual_plan_is_the_only_seed_source_for_3d_reloads():
    """A Viewer reload must not redraw immutable automatic geometry after a drag."""
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    viewer = (root / "web/routes/viewer_routes.py").read_text(encoding="utf-8")

    assert 'manual_plan_serialized = agent.memory.retrieve("manual_plan_serialized") or []' in viewer
    assert "if has_manual_geometry:" in viewer
    assert "plan_source = manual_plan_serialized or seed_plan_serialized" in viewer
    assert "manual_plan_active" in viewer
    assert 'else f"seed_{i + 1}_{j + 1}"' in viewer
