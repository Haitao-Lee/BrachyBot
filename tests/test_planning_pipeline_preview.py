def test_trajectory_preview_accepts_numpy_close_points(monkeypatch):
    import numpy as np
    from plans import utilizations
    from tool_factory.seed_plan import planning_pipeline

    monkeypatch.setattr(
        utilizations,
        "position_transform",
        lambda _image, point: (
            np.asarray(point, dtype=np.float64),
            None,
        ),
    )
    monkeypatch.setattr(
        planning_pipeline,
        "_candidate_world_needle_points",
        lambda _trajectory, _image: np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
            dtype=np.float64,
        ),
    )

    geometry = planning_pipeline._preview_trajectory_geometry(
        [],
        object(),
        close_points=np.asarray(
            [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]],
            dtype=np.float64,
        ),
    )

    assert [item["position"] for item in geometry["close_points"]] == [
        [0.0, 1.0, 2.0],
        [3.0, 4.0, 5.0],
    ]
