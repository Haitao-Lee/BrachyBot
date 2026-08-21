"""Regression tests for stale viewer slice requests after a CT switch."""

from flask import Flask
import numpy as np


def test_viewer_slice_clamps_index_from_previous_volume(monkeypatch):
    from web.routes import viewer_routes

    class Memory:
        session_id = "slice-bounds"

        def __init__(self):
            self.values = {
                "ct_data": np.arange(3 * 4 * 5, dtype=np.int16).reshape(3, 4, 5),
                "ct_axis_map": {"axial": 0, "sagittal": 2, "coronal": 1},
                "ct_window_center": 40,
                "ct_window_width": 400,
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    class Agent:
        def __init__(self):
            self.memory = Memory()
            self._workspace_ct_ready = True
            self._workspace_data_ready = True

    agent = Agent()
    monkeypatch.setattr(viewer_routes, "require_api_key", lambda func: func)
    monkeypatch.setattr(viewer_routes, "rate_limit", lambda func: func)

    app = Flask(__name__)
    app.secret_key = "test-secret"
    viewer_routes.register_viewer_routes(
        app,
        lambda **_kwargs: agent,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: {},
    )

    client = app.test_client()
    cases = [
        ({"axis": "axial", "slice_index": 24}, 2, 3),
        ({"axis": "sagittal", "slice_index": -4}, 0, 5),
        ({"axis": "coronal", "slice_index": 999}, 3, 4),
    ]
    for payload, expected_index, expected_total in cases:
        response = client.post("/api/viewer/slice", json=payload)
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["slice_index"] == expected_index
        assert body["total_slices"] == expected_total
        assert body["requested_slice_index"] == payload["slice_index"]


def test_viewer_load_returns_retryable_pending_while_agent_initializes(monkeypatch):
    """Cold Session restore must not surface a false CT HTTP 500."""
    from web.routes import viewer_routes

    monkeypatch.setattr(viewer_routes, "require_api_key", lambda func: func)
    monkeypatch.setattr(viewer_routes, "rate_limit", lambda func: func)

    app = Flask(__name__)
    app.secret_key = "test-secret"
    viewer_routes.register_viewer_routes(
        app,
        lambda **_kwargs: None,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: {},
    )

    response = app.test_client().post(
        "/api/viewer/load",
        json={"ct_path": "/case/inputs/ct.nii.gz"},
    )
    assert response.status_code == 202
    assert response.json["pending"] is True
    assert response.json["code"] == "workspace_agent_initializing"
