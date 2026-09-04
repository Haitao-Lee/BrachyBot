"""Regression tests for stale viewer slice requests after a CT switch."""

import base64
from io import BytesIO

from flask import Flask
import numpy as np
from PIL import Image


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


def test_viewer_fallback_slice_orientation_matches_client_mpr_contract(monkeypatch):
    """Server-rendered fallback slices must use the same LPI display mapping."""
    from web.routes import viewer_routes

    class Memory:
        session_id = "slice-orientation"

        def __init__(self):
            self.values = {
                # Every voxel is a sentinel value, so an accidental Z reversal
                # is observable in the returned PNG rather than only in shape.
                "ct_data": np.arange(3 * 2 * 4, dtype=np.int16).reshape(3, 2, 4),
                "ct_axis_map": {"axial": 0, "sagittal": 2, "coronal": 1},
                "ct_spacing": (1.0, 1.0, 2.0),
                "ct_window_center": 8,
                "ct_window_width": 20,
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

    ct = agent.memory.values["ct_data"]
    lower, upper = -2, 18
    windowed = (np.clip(ct, lower, upper) - lower) / (upper - lower) * 255
    windowed = windowed.astype(np.uint8)
    # The PNG fallback uses the same nearest-neighbor Z resampling as the
    # browser MPR renderer: depth 3 at a 2:1 Z/in-plane spacing becomes 6.
    z_indices = np.minimum((np.arange(6) / 2.0).astype(int), 2)

    def rendered(axis, index):
        response = app.test_client().post(
            "/api/viewer/slice",
            json={
                "axis": axis,
                "slice_index": index,
                "window_center": 8,
                "window_width": 20,
            },
        )
        assert response.status_code == 200
        payload = response.get_json()["data"].split(",", 1)[1]
        return np.asarray(Image.open(BytesIO(base64.b64decode(payload))).convert("L"))

    # Axial display index is reversed; reformatted vertical Z is direct.
    np.testing.assert_array_equal(rendered("axial", 0), windowed[2])
    np.testing.assert_array_equal(rendered("sagittal", 1), windowed[z_indices, :, 1])
    np.testing.assert_array_equal(rendered("coronal", 0), windowed[z_indices, 0, :])
