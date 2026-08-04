import threading
from types import SimpleNamespace

from web.planning_runs import (
    PLANNING_RUN_PREFIX,
    activate_planning_run,
    begin_planning_run,
    fork_planning_run,
    invalidate_planning_dependents,
    list_planning_runs,
    mark_planning_run,
    publish_planning_run,
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
    assert [run["label"] for run in runs] == ["Planning_0", "Planning_1"]
    assert runs[0]["visible"] is False
    assert runs[1]["visible"] is True

    activate_planning_run(agent, first)
    assert agent.memory.retrieve("active_planning_id") == first
    assert agent.memory.retrieve("manual_seeds")[0]["id"] == "seed-a"
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + second)["manual_seeds"][0]["id"] == "seed-b"
    assert list_planning_runs(agent.memory)[0]["visible"] is True
    assert list_planning_runs(agent.memory)[1]["visible"] is False


def test_stepwise_stages_reuse_running_run_but_completed_replan_forks():
    agent = _agent()
    first = begin_planning_run(agent, step="trajectory_init")
    same = begin_planning_run(agent, step="trajectory_refine")
    assert same == first
    _publish(agent, first, seed="seed-a")
    second = begin_planning_run(agent, step="trajectory_init")
    assert second != first


def test_manual_edit_forks_without_mutating_parent_and_saves_draft_geometry():
    agent = _agent()
    first = begin_planning_run(agent, step="full", force_new=True)
    _publish(agent, first, seed="seed-a")

    child = fork_planning_run(agent, reason="seed_drag")
    invalidate_planning_dependents(agent.memory, reason="seed_drag")
    agent.memory.store("manual_seeds", [{"id": "seed-b", "position": [3, 2, 1]}])
    agent.memory.store("manual_needles", [{"id": "needle-b", "points": [[0, 0, 0], [2, 2, 2]]}])
    publish_planning_run(agent, None, status="draft")

    assert child != first
    assert agent.memory.retrieve("dose_distribution_gy") is None
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + first)["manual_seeds"][0]["id"] == "seed-a"
    assert agent.memory.retrieve(PLANNING_RUN_PREFIX + child)["manual_seeds"][0]["id"] == "seed-b"
    assert list_planning_runs(agent.memory)[-1]["status"] == "draft"


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
