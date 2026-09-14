import numpy as np

from plans import utilizations


def test_select_optimal_trajectory_prefers_safe_multi_seed_capacity(monkeypatch):
    candidates = [
        (np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])),
        (np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    ]

    monkeypatch.setattr(
        utilizations,
        "get_candidate_traj_weights",
        lambda *args, **kwargs: np.ones(2),
    )
    monkeypatch.setattr(
        utilizations,
        "get_candidate_traj_radiation",
        lambda *args, **kwargs: np.array([1.0, 0.93]),
    )
    monkeypatch.setattr(
        utilizations,
        "get_candidate_traj_edge_distance",
        lambda *args, **kwargs: np.ones(2),
    )
    monkeypatch.setattr(
        utilizations,
        "get_candidate_traj_dir_score",
        lambda *args, **kwargs: np.ones(2),
    )
    monkeypatch.setattr(
        utilizations,
        "get_trajectory_spacing_safety_mask",
        lambda *args, **kwargs: np.ones(2, dtype=bool),
    )
    monkeypatch.setattr(
        utilizations,
        "get_available_position",
        lambda trajectory, *args, **kwargs: [1] if trajectory[0][0] == 0 else [1, 2, 3, 4],
    )

    selected, index = utilizations.select_optimal_trajectory(
        candidates,
        [],
        np.zeros((4, 4, 4)),
        object(),
        0.8,
        10.0,
        2.0,
        True,
        np.ones((4, 4, 4)),
        {"length": 4.5, "margin_rate": 1.5},
        [],
    )

    assert index == 1
    assert selected is candidates[1]
