import threading
from types import SimpleNamespace

from web.planning_runs import (
    PLANNING_RUN_PREFIX,
    activate_planning_run,
    begin_planning_run,
    current_planning_context,
    fork_planning_run,
    invalidate_planning_dependents,
    list_planning_runs,
    mark_planning_run,
    publish_active_planning_state,
    publish_planning_run,
    reconcile_planning_history,
)


class _Memory:
    def __init__(self):
        self._lock = threading.RLock()
        self.planning_results = {}
        self._planning_versions = {}
        self.conversation_state = {"data_available": []}
        self._notifications = []

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)

    def _notify_persistence(self, reason):
        self._notifications.append(reason)


def _agent():
    return SimpleNamespace(memory=_Memory())


def _publish(agent, planning_id, *, seed):
    memory = agent.memory
    memory.store = lambda key, value: memory.planning_results.__setitem__(key, value)
    memory.planning_results.update({
        "manual_plan_active": True,
        "manual_seeds": [{"id": seed, "position": [1, 2, 3]}],
        "manual_needles": [{"id": f"needle-{seed}", "points": [[0, 0, 0], [1, 1, 1]]}],
        "total_seeds": 1,
        "num_trajectories": 1,
        "dose_metrics": {"d90": 120.0},
        "dose_distribution_gy": [[[1.0, 1.0], [1.0, 1.0]]],
    })
    result = SimpleNamespace(metadata={"planning_id": planning_id, "step_executed": "full"})
    publish_planning_run(agent, result)


def test_full_runs_are_immutable_and_activation_restores_selected_aliases():
    agent = _agent()
    first = begin_planning_run(agent, step="full", force_new=True)
    _publish(agent, first, seed="seed-a")

    second = begin_planning_run(agent, step="full", force_new=True)
    assert second != first
    assert agent.memory.retrieve("manual_seeds") is None
    _publish(agent, second, seed="seed-b")

    runs = list_planning_runs(agent.memory)
    assert [run["label"] for run in runs] == ["Planning_1", "Planning_2"]
    assert runs[0]["visible"] is False
    assert runs[1]["visible"] is True

    activate_planning_run(agent, first)
    assert agent.memory.retrieve("active_planning_id") == first
    assert agent.memory.retrieve("manual_seeds")[0]["id"] == "seed-a"
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + second)["manual_seeds"][0]["id"] == "seed-b"
    assert list_planning_runs(agent.memory)[0]["visible"] is True
    assert list_planning_runs(agent.memory)[1]["visible"] is False


def test_verified_needle_input_provenance_is_persisted_with_the_planning_run():
    agent = _agent()
    planning_id = begin_planning_run(agent, step="full", force_new=True)
    agent.memory.store = lambda key, value: agent.memory.planning_results.__setitem__(key, value)
    context = {
        "schema_version": 1,
        "ct_geometry": {"size_xyz": [20, 20, 20]},
        "ctv_mask": {"sha256": "ctv"},
        "oar_mask": {"sha256": "oar"},
        "obstacle_label_ids": [77],
    }
    agent.memory.store("verified_needle_geometry", {"0": [[0, 0, 0], [1, 1, 1]]})
    agent.memory.store("needle_safety_context", context)
    publish_planning_run(agent, None, status="completed")

    snapshot = agent.memory.retrieve(PLANNING_RUN_PREFIX + planning_id)
    assert snapshot["needle_safety_context"] == context


def test_current_planning_context_never_mixes_active_run_with_foreign_aliases():
    agent = _agent()
    memory = agent.memory
    memory.store = lambda key, value: memory.planning_results.__setitem__(key, value)
    active_id = "planning-active"
    memory.planning_results.update({
        "active_planning_id": active_id,
        "planning_run_id": "planning-foreign",
        "dose_metrics": {"v100": 0.25, "d90": 30.0},
        "metrics": {"oar_metrics": {"brain": {"dmax": 999.0, "d2cc": 99.0}}},
        "total_seeds": 999,
        f"{PLANNING_RUN_PREFIX}{active_id}": {
            "dose_metrics": {
                "v100": 0.903,
                "d90": 120.59,
                "oar_metrics": {"spinal_cord": {"dmax": 20.0, "d2cc": 7.0}},
            },
            "plan_config": {"prescription_gy": 120.0},
            "total_seeds": 35,
            "num_trajectories": 5,
        },
    })

    restored = current_planning_context(memory)

    assert restored["planning_id"] == active_id
    assert restored["metrics"]["v100"] == 0.903
    assert set(restored["metrics"]["oar_metrics"]) == {"spinal_cord"}
    assert restored["total_seeds"] == 35
    assert restored["num_trajectories"] == 5
    assert restored["source"] == "active_planning_run"

    # Once the legacy aliases identify the same active run, a live edit is
    # newer than the immutable checkpoint and must be visible immediately.
    memory.planning_results["planning_run_id"] = active_id
    memory.planning_results["dose_metrics"] = {"v100": 0.91, "d90": 123.0}
    memory.planning_results["metrics"] = {"v100": 0.91, "d90": 123.0}
    live = current_planning_context(memory)
    assert live["metrics"]["v100"] == 0.91


def test_current_planning_context_merges_nested_ctv_and_oar_metric_aliases():
    agent = _agent()
    memory = agent.memory
    memory.store = lambda key, value: memory.planning_results.__setitem__(key, value)
    planning_id = "planning-active"
    memory.planning_results.update({
        "active_planning_id": planning_id,
        "planning_run_id": planning_id,
        "dose_metrics": {
            "metrics": {
                "CTV": {"D90": 120.2, "V100": 0.901},
                "oars": {
                    "spinal_cord": {"Dmax": 20.52, "D2cc": 7.30},
                    "brain": {"Dmax": 6.70, "D2cc": 4.77},
                },
            },
            "prescription_gy": 120.0,
        },
        "metrics": {
            "v100": 0.905,
            "oar_metrics": {
                "thyroid_gland": {"dmax": 1.28, "d2cc": 0.0},
                "spinal_cord": {"d1cc": 8.77},
            },
        },
    })

    metrics = current_planning_context(memory)["metrics"]

    assert metrics["D90"] == 120.2
    assert metrics["v100"] == 0.905
    assert metrics["prescription_gy"] == 120.0
    assert metrics["oar_metrics"]["spinal_cord"] == {
        "Dmax": 20.52,
        "D2cc": 7.30,
        "d1cc": 8.77,
    }
    assert metrics["oar_metrics"]["brain"]["D2cc"] == 4.77
    assert metrics["oar_metrics"]["thyroid_gland"]["dmax"] == 1.28


def test_stepwise_stages_reuse_running_run_but_completed_replan_forks():
    agent = _agent()
    first = begin_planning_run(agent, step="trajectory_init")
    same = begin_planning_run(agent, step="trajectory_refine")
    assert same == first
    _publish(agent, first, seed="seed-a")
    second = begin_planning_run(agent, step="trajectory_init")
    assert second != first


def test_legacy_has_dose_rows_remain_current_until_reconciled():
    """Old registry rows must not disappear merely because new flags are absent."""
    agent = _agent()
    agent.memory.planning_results.update({
        "active_planning_id": "planning-legacy",
        "planning_runs": [{
            "planning_id": "planning-legacy",
            "sequence": 0,
            "label": "Planning_1",
            "status": "completed",
            "visible": True,
            "has_dose": True,
        }],
    })

    run = list_planning_runs(agent.memory)[0]
    assert run["has_dose"] is True
    assert run["has_current_dose"] is True
    assert run["has_display_dose"] is True


def test_manual_edit_forks_without_mutating_parent_and_saves_draft_geometry():
    agent = _agent()
    first = begin_planning_run(agent, step="full", force_new=True)
    _publish(agent, first, seed="seed-a")
    previous_dose = {
        "d90": 120.0,
        "oar_metrics": {"spinal_cord": {"dmax": 20.0, "d2cc": 7.0}},
    }
    for key, value in (
        ("algorithm_plan_dose_metrics", previous_dose),
        ("algorithm_plan_dvh_data", {"spinal_cord": {"dose": [20.0]}}),
        ("algorithm_plan_dose_distribution", [[[20.0]]]),
    ):
        agent.memory.store(key, value)
    publish_planning_run(agent, None, status="completed")

    child = fork_planning_run(agent, reason="seed_drag")
    invalidate_planning_dependents(agent.memory, reason="seed_drag")
    agent.memory.store("manual_seeds", [{"id": "seed-b", "position": [3, 2, 1]}])
    agent.memory.store("manual_needles", [{"id": "needle-b", "points": [[0, 0, 0], [2, 2, 2]]}])
    publish_planning_run(agent, None, status="draft")

    assert child != first
    assert agent.memory.retrieve("dose_distribution_gy") is None
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + first)["manual_seeds"][0]["id"] == "seed-a"
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + child)["manual_seeds"][0]["id"] == "seed-b"
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + first)["algorithm_plan_dose_metrics"] == previous_dose
    child_snapshot = agent.memory.retrieve(PLANNING_RUN_PREFIX + child)
    assert "algorithm_plan_dose_metrics" not in child_snapshot
    assert "algorithm_plan_dvh_data" not in child_snapshot
    assert "algorithm_plan_dose_distribution" not in child_snapshot
    assert current_planning_context(agent.memory)["metrics"] == {}
    assert list_planning_runs(agent.memory)[-1]["status"] == "draft"


def test_restore_fork_can_skip_copying_outgoing_large_artifacts():
    """A restore keeps the persisted parent as rollback instead of cloning dose again."""
    agent = _agent()
    first = begin_planning_run(agent, step="full", force_new=True)
    _publish(agent, first, seed="seed-a")

    child = fork_planning_run(
        agent,
        reason="restore_algorithm_needle",
        capture_current=False,
    )

    assert child != first
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + child) == {
        "manual_planning_id": child,
    }
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + first)["dose_distribution_gy"] == [
        [[1.0, 1.0], [1.0, 1.0]],
    ]


def test_failed_new_run_restores_previous_visible_run():
    agent = _agent()
    first = begin_planning_run(agent, step="full", force_new=True)
    _publish(agent, first, seed="seed-a")
    second = begin_planning_run(agent, step="full", force_new=True)
    assert second != first
    assert mark_planning_run(agent, second, "failed", "inference failed")

    assert agent.memory.retrieve("active_planning_id") == first
    assert agent.memory.retrieve("manual_seeds")[0]["id"] == "seed-a"
    runs = list_planning_runs(agent.memory)
    assert runs[0]["visible"] is True
    assert runs[1]["visible"] is False
    assert runs[1]["status"] == "failed"


def test_artifact_snapshot_refresh_preserves_draft_status_and_skin_surface():
    agent = _agent()
    planning_id = begin_planning_run(agent, step="full", force_new=True)
    agent.memory.store = lambda key, value: agent.memory.planning_results.__setitem__(key, value)
    agent.memory.store("skin_surface", {"object_id": "skin_surface:guide", "data_version": 1})
    agent.memory.store("skin_surface_mask", [[[1, 0], [0, 0]]])
    publish_planning_run(agent, None, status="draft")

    agent.memory.store("skin_surface", {"object_id": "skin_surface:guide", "data_version": 2})
    assert publish_active_planning_state(agent) == planning_id

    run = list_planning_runs(agent.memory)[0]
    snapshot = agent.memory.retrieve(PLANNING_RUN_PREFIX + planning_id)
    assert run["status"] == "draft"
    assert snapshot["skin_surface"]["data_version"] == 2
    assert snapshot["skin_surface_mask"] == [[[1, 0], [0, 0]]]


def test_activation_restores_all_planning_owned_downstream_artifacts():
    agent = _agent()
    first = begin_planning_run(agent, step="full", force_new=True)
    agent.memory.store = lambda key, value: agent.memory.planning_results.__setitem__(key, value)
    first_values = {
        "dose_distribution_gy": [[1.0]],
        "dose_metrics": {"v100": 90.0, "d90": 120.0},
        "dvh_data": {"CTV": {"dose": [0.0, 120.0], "volume_percent": [100.0, 90.0]}},
        "skin_surface": {"object_id": "skin_surface:guide", "data_version": 1},
        "skin_surface_mask": [[1]],
        "surgical_guide": {"status": "ready", "version": 1},
        "surgical_guide_versions": [{"version": 1, "planning_id": first}],
        "artifact_status": {
            "dose": "ready", "dvh": "ready", "report": "ready", "surgical_guide": "ready",
        },
    }
    for key, value in first_values.items():
        agent.memory.store(key, value)
    publish_planning_run(agent, None, status="completed")

    second = begin_planning_run(agent, step="full", force_new=True)
    second_values = {
        "dose_distribution_gy": [[2.0]],
        "dose_metrics": {"v100": 91.0, "d90": 121.0},
        "dvh_data": {"CTV": {"dose": [0.0, 121.0], "volume_percent": [100.0, 91.0]}},
        "skin_surface": {"object_id": "skin_surface:guide", "data_version": 2},
        "skin_surface_mask": [[2]],
        "surgical_guide": {"status": "ready", "version": 2},
        "surgical_guide_versions": [{"version": 2, "planning_id": second}],
        "artifact_status": {
            "dose": "ready", "dvh": "ready", "report": "ready", "surgical_guide": "ready",
        },
    }
    for key, value in second_values.items():
        agent.memory.store(key, value)
    publish_planning_run(agent, None, status="completed")

    activate_planning_run(agent, first)
    for key, value in first_values.items():
        assert agent.memory.retrieve(key) == value
    runs = list_planning_runs(agent.memory)
    assert runs[0]["visible"] is True
    assert runs[1]["visible"] is False

    activate_planning_run(agent, second)
    for key, value in second_values.items():
        assert agent.memory.retrieve(key) == value
    runs = list_planning_runs(agent.memory)
    assert runs[0]["visible"] is False
    assert runs[1]["visible"] is True


def test_hydration_reconciles_partial_active_run_to_complete_persisted_run():
    """Restart recovery must restore the complete run, not an empty shell."""
    agent = _agent()
    memory = agent.memory
    memory.store = lambda key, value: memory.planning_results.__setitem__(key, value)

    complete = begin_planning_run(agent, step="full", force_new=True)
    memory.store("manual_seeds", [{"id": "seed-complete", "position": [1, 2, 3]}])
    memory.store("manual_needles", [{"id": "needle-complete", "points": [[0, 0, 0], [1, 1, 1]]}])
    memory.store("dose_distribution_gy", [[[120.0]]])
    memory.store("dose_metrics", {"v100": 91.0, "d90": 122.0})
    memory.store("dvh_data", {"CTV": {"dose": [0.0, 120.0], "volume_percent": [100.0, 91.0]}})
    memory.store("surgical_guide", {"status": "ready", "version": 1})
    publish_planning_run(agent, None, status="completed")

    partial = begin_planning_run(agent, step="full", force_new=True)
    memory.store("manual_seeds", [{"id": "seed-partial", "position": [4, 5, 6]}])
    memory.store("manual_needles", [{"id": "needle-partial", "points": [[0, 0, 0], [0, 1, 0]]}])
    # This is the persisted state observed after a restart while Planning_2
    # was still running: it has a namespaced snapshot but no dose products.
    publish_planning_run(agent, None, status="running")

    result = reconcile_planning_history(memory, recover_running=True)

    assert result["active_planning_id"] == complete
    assert result["restored_aliases"]
    assert memory.retrieve("active_planning_id") == complete
    assert memory.retrieve("manual_seeds")[0]["id"] == "seed-complete"
    assert memory.retrieve("dose_distribution_gy") == [[[120.0]]]
    runs = list_planning_runs(memory)
    assert runs[0]["planning_id"] == complete
    assert runs[0]["visible"] is True
    assert runs[1]["planning_id"] == partial
    assert runs[1]["status"] == "interrupted"
    assert runs[1]["visible"] is False
