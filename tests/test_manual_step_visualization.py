import numpy as np
import pytest


def test_completed_manual_init_projection_includes_paths_and_close_points(monkeypatch):
    from plans import utilizations
    from tool_factory.seed_plan import planning_pipeline

    monkeypatch.setattr(
        planning_pipeline,
        "_candidate_world_needle_points",
        lambda candidate, _image: np.asarray(
            [[candidate, 0, 0], [candidate, 1, 2]], dtype=float
        ),
    )
    monkeypatch.setattr(
        utilizations,
        "position_transform",
        lambda _image, point: (np.asarray(point, dtype=float), None),
    )
    candidates = list(range(200))
    close_points = np.asarray([[i, 0, 0] for i in range(300)], dtype=float)
    result = planning_pipeline._preview_trajectory_geometry(
        candidates,
        object(),
        close_points=close_points,
        status="safe",
        trajectory_limit=512,
    )

    assert len(result["trajectories"]) == 200
    assert result["trajectories"][199]["points"] == [[199.0, 0.0, 0.0], [199.0, 1.0, 2.0]]
    assert len(result["close_points"]) == 256
    assert result["close_points"][0]["position"] == [0.0, 0.0, 0.0]


def test_manual_trajectory_projection_is_bounded_for_large_plan(monkeypatch):
    from tool_factory.seed_plan import planning_pipeline

    monkeypatch.setattr(
        planning_pipeline,
        "_candidate_world_needle_points",
        lambda candidate, _image: np.asarray([[candidate, 0, 0], [candidate, 1, 0]]),
    )
    result = planning_pipeline._preview_trajectory_geometry(
        list(range(1000)), object(), trajectory_limit=512
    )
    assert len(result["trajectories"]) == 512
    assert result["trajectories"][0]["id"] == "preview_trajectory_0"
    assert result["trajectories"][-1]["id"] == "preview_trajectory_999"


def test_completed_outputs_are_full_world_geometry_and_persist_with_plan(monkeypatch):
    from types import SimpleNamespace
    import threading
    from plans import utilizations
    from tool_factory.seed_plan import planning_pipeline
    from web.manual_step_outputs import record_manual_step_output
    from web.planning_runs import begin_planning_run, publish_planning_run, activate_planning_run

    class Memory:
        def __init__(self):
            self._lock = threading.RLock()
            self.planning_results = {}
            self._planning_versions = {}
            self.conversation_state = {"data_available": []}

        def retrieve(self, key, default=None):
            return self.planning_results.get(key, default)

        def _notify_persistence(self, _reason):
            pass

    agent = SimpleNamespace(memory=Memory())
    monkeypatch.setattr(planning_pipeline, "_candidate_world_needle_points",
                        lambda candidate, image: np.asarray([[candidate, 0, 0], [candidate, 10, 0]]))
    monkeypatch.setattr(utilizations, "position_transform",
                        lambda image, point: (np.asarray(point) + [10, 20, 30], None))
    planning_id = begin_planning_run(agent, step="trajectory_init")
    agent.memory.planning_results["resampled_ct"] = object()
    agent.memory.planning_results["total_seeds"] = 181
    result = SimpleNamespace(data=list(range(1000)), metadata={
        "manual_close_points": [[i, 0, 0] for i in range(300)]})
    first = record_manual_step_output(agent, "trajectory_init", result, planning_id)
    assert first["stages"][0]["shown_trajectories"] == 1000
    assert first["stages"][0]["close_point_count"] == 300
    assert first["stages"][0]["geometry"]["close_points"][0]["position"] == [10., 20., 30.]
    for step in ("trajectory_refine", "seed_planning", "dose_calc", "dose_eval"):
        catalog = record_manual_step_output(agent, step, result, planning_id)
    assert len(catalog["stages"]) == 5
    assert catalog["stages"][2]["seed_count"] == 181
    assert "geometry" not in catalog["stages"][2], "do not clone clinical seeds or dose grids"
    publish_planning_run(agent, None, status="completed")
    second = begin_planning_run(agent, step="full", force_new=True)
    assert second != planning_id
    assert agent.memory.retrieve("manual_step_outputs") is None
    activate_planning_run(agent, planning_id)
    restored = agent.memory.retrieve("manual_step_outputs")
    assert restored == catalog
    rerun = record_manual_step_output(agent, "trajectory_refine", result, planning_id)
    assert [item["step"] for item in rerun["stages"]] == ["trajectory_init", "trajectory_refine"]
    assert rerun["stages"][0]["revision"] == first["stages"][0]["revision"]
    assert rerun["stages"][1]["revision"] != catalog["stages"][1]["revision"]


@pytest.mark.parametrize("step", ["trajectory_init", "trajectory_refine", "seed_planning", "dose_calc", "dose_eval"])
def test_manual_output_is_recorded_before_the_existing_snapshot_commit(step):
    from types import SimpleNamespace
    from unittest.mock import patch
    from tool_factory import ToolResult
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    values = {}
    agent = SimpleNamespace(config={}, memory=SimpleNamespace(
        retrieve=lambda key, default=None: values.get(key, default),
        store=lambda key, value: values.__setitem__(key, value)))
    tool = PlanningPipelineTool()
    calls = []

    def publish(_agent, result, *, status):
        assert calls == ["record"], "the snapshot must include this step's display output"
        calls.append("publish")
        assert status == ("completed" if step == "dose_eval" else "running")
        return result.metadata["planning_id"]

    with (
        patch.object(tool, "_load_ct", return_value=object()),
        patch.object(tool, "_load_ctv", return_value=np.zeros((2, 2, 2), dtype=np.uint8)),
        patch.object(tool, "_load_oar", return_value=np.zeros((2, 2, 2), dtype=np.uint8)),
        patch("tool_factory.seed_plan.planning_pipeline._merge_embedded_hard_obstacles", return_value=(object(), set())),
        patch("tool_factory.seed_plan.planning_pipeline._resolve_ref_direc", return_value=[0., -1., 0.]),
        patch("web.planning_runs.begin_planning_run", return_value="planning-test"),
        patch.object(tool, "_step_" + step, return_value=ToolResult(success=True)),
        patch("web.manual_step_outputs.record_manual_step_output", side_effect=lambda *args: calls.append("record")),
        patch("web.planning_runs.publish_planning_run", side_effect=publish),
    ):
        result = tool._execute(step=step, _agent=agent, _manual_step_presentation=True)
    assert result.success
    assert calls == ["record", "publish"]
