from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_preview_emitter_is_bounded_ephemeral_and_lifecycle_ordered():
    from plans.planning_preview import PlanningPreviewEmitter

    events = []
    emitter = PlanningPreviewEmitter(
        events.append,
        session_id="case-a",
        planning_id="planning-a",
        min_frame_interval=0.05,
    )
    emitter.start("trajectory_init")
    emitter.frame(
        {
            "trajectories": [
                {"id": f"t-{index}", "points": [[index, 0, 0], [index, 1, 1]]}
                for index in range(100)
            ],
            "needles": [
                {"id": f"n-{index}", "points": [[0, index, 0], [1, index, 1]]}
                for index in range(50)
            ],
            "seeds": [
                {"id": f"s-{index}", "position": [index, 0, 0], "direction": [0, 0, 1]}
                for index in range(300)
            ],
        },
        force=True,
    )
    emitter.complete("trajectory_init")
    emitter.cleanup("completed")

    assert [event["action"] for event in events] == [
        "start", "frame", "complete", "cleanup"
    ]
    frame = events[1]
    assert frame["session_id"] == "case-a"
    assert frame["run_id"] == "planning-a"
    assert frame["ephemeral"] is True
    assert frame["editable"] is False
    assert frame["persistent"] is False
    assert len(frame["geometry"]["trajectories"]) == 64
    assert len(frame["geometry"]["needles"]) == 32
    assert len(frame["geometry"]["seeds"]) == 256
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]


def test_preview_callback_failure_cannot_fail_planning_observer():
    from plans.planning_preview import PlanningPreviewEmitter, safe_preview

    def broken(_payload):
        raise RuntimeError("browser disconnected")

    safe_preview(broken, {"type": "planning_preview"})
    emitter = PlanningPreviewEmitter(
        broken,
        session_id="case-a",
        planning_id="planning-a",
    )
    emitter.start("seed_planning")
    emitter.frame({"seeds": []}, force=True)
    emitter.complete("seed_planning")
    emitter.cleanup("failed")


def test_candidate_generation_observer_reports_real_incremental_geometry(monkeypatch):
    import numpy as np
    from plans import core

    directions = [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])]
    monkeypatch.setattr(core.utilizations, "get_cone", lambda *_args: directions)
    monkeypatch.setattr(
        core.utilizations,
        "get_close_points",
        lambda *_args: (np.array([[1.0, 2.0, 3.0]]), 12.0),
    )

    generated = []

    def fake_init(_points, _volume, direction, *_args):
        index = len(generated)
        trajectory = (
            np.array([index + 1.0, 2.0, 3.0]),
            np.asarray(direction),
            [2.0],
            [4.0],
            6.0,
        )
        generated.append(trajectory)
        return [trajectory]

    monkeypatch.setattr(
        core.utilizations,
        "init_trajectories_with_depth",
        fake_init,
    )
    observations = []
    result = core.init_plan(
        dose_image=object(),
        radiation_volume=np.zeros((4, 4, 4), dtype=np.uint8),
        ref_direc=np.array([0.0, 0.0, 1.0]),
        direc_resolution=[0.5, 0.1, 2],
        extract_angle=0.5,
        target_value=2,
        background_value=0,
        obstacle_value=3,
        maximum_candidate_trajectories=20,
        min_depth=1,
        preview_callback=observations.append,
    )

    assert result == generated
    assert observations
    assert observations[-1]["force"] is True
    assert observations[-1]["current"] == len(directions)
    assert observations[-1]["trajectories"] == result


def test_preview_transport_is_live_latest_frame_bounded_and_not_serialized():
    runtime = _read("agent_runtime/llm_runtime.py")
    agent = _read("AgenticSys.py")
    workflow = _read("agent_runtime/chat_workflows.py")

    assert 'event_type == "planning_preview"' in runtime
    assert "take_callback_events()" in runtime
    assert "_tool_thread.join(timeout=0.25)" in runtime
    assert "preview_callback=tool_planning_preview_callback" in runtime
    assert 'params["preview_callback"] = preview_callback' in agent
    assert "'preview_callback'" in agent
    assert "_execute_planning_tool_with_events" in workflow
    assert 'yield yield_event("planning_preview", payload)' in workflow


def test_preview_layer_is_read_only_outside_data_tree_and_clears_on_boundaries():
    viewer = _read("web/app/static/js/brachybot-3d-manual.js")
    chat = _read("web/app/static/js/brachybot-chat-todo.js")
    workspace = _read("web/app/static/js/brachybot-ui-api.js")
    index = _read("web/app/index.html")

    assert "__planning_preview_ephemeral__" in viewer
    assert "scene3D.scene.add(group)" in viewer
    assert "latest-frame queue: capacity 1" in viewer
    assert "editable: false" in viewer
    assert "persistent: false" in viewer
    assert "scene3D.meshes[group.name]" not in viewer
    assert "scheduleCameraFitForSceneMutation?.('planning-preview" not in viewer
    assert "window.handlePlanningPreviewEvent" in viewer
    assert "currentEvent === 'planning_preview'" in chat
    assert "window.clearPlanningPreview?.('workspace-transition')" in workspace
    assert 'id="planningPreviewStatus"' in index


def test_algorithm_observers_do_not_replace_formal_planning_contracts():
    core = _read("plans/core.py")
    pipeline = _read("tool_factory/seed_plan/planning_pipeline.py")
    reinforcement = _read("plans/reinforcement.py")
    utilizations = _read("plans/utilizations.py")

    assert "preview_callback=None" in core
    assert "safe_preview(preview_callback" in core
    assert "PlanningPreviewEmitter" in pipeline
    assert 'agent.memory.store("planning_preview"' not in pipeline
    assert '"ephemeral": True' not in pipeline  # envelope belongs to the emitter
    assert "preview_callback=preview_callback" in utilizations
    assert "_emit_preview(" in reinforcement
