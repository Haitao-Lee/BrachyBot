"""Regression tests for OAR-to-CT physical-grid alignment."""

from pathlib import Path
import sys
from contextlib import contextmanager
from types import SimpleNamespace
import threading

import numpy as np
import pytest

sitk = pytest.importorskip("SimpleITK")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tool_factory.OAR_seg import totalsegmentator_oar as oar_module
from tool_factory.OAR_seg.totalsegmentator_oar import (
    TotalSegmentatorOARTool,
    _align_segmentation_to_reference,
)


def test_totalsegmentator_labels_are_resampled_by_physical_coordinates(tmp_path):
    reference = sitk.Image([6, 5, 4], sitk.sitkInt16)
    reference.SetSpacing((2.0, 3.0, 4.0))
    reference.SetOrigin((10.0, 20.0, 30.0))

    # Place label 26 at physical point (14, 23, 34), which is index
    # (2, 1, 1) in the CT. The exported segmentation uses a shifted origin,
    # so its corresponding label voxel is (3, 2, 2). A raw array transpose
    # would miss this correspondence; affine-aware resampling must recover it.
    exported = sitk.Image([6, 5, 4], sitk.sitkUInt16)
    exported.SetSpacing(reference.GetSpacing())
    exported.SetOrigin((8.0, 17.0, 26.0))
    exported.SetDirection(reference.GetDirection())
    exported_array = np.zeros((4, 5, 6), dtype=np.uint16)
    exported_array[2, 2, 3] = 26
    exported = sitk.GetImageFromArray(exported_array)
    exported.SetSpacing(reference.GetSpacing())
    exported.SetOrigin((8.0, 17.0, 26.0))
    exported.SetDirection(reference.GetDirection())
    path = tmp_path / "totalseg_output.nii.gz"
    sitk.WriteImage(exported, str(path))

    aligned = _align_segmentation_to_reference(str(path), reference)

    assert aligned.shape == (4, 5, 6)
    assert int(aligned[1, 1, 2]) == 26
    assert int(np.sum(aligned == 26)) == 1


def test_totalsegmentator_gpu_worker_and_device_lease_are_always_released(monkeypatch):
    lifecycle = []

    @contextmanager
    def fake_device_session(*, caller):
        lifecycle.append(("enter", caller))
        try:
            yield SimpleNamespace(device_str="cuda:0")
        finally:
            lifecycle.append(("exit", caller))

    monkeypatch.setattr("plans.device_manager.device_session", fake_device_session)
    tool = TotalSegmentatorOARTool()
    monkeypatch.setattr(
        tool,
        "_totalsegmentator_segmentation_locked",
        lambda image, organ_filter, fast_mode, device: (_ for _ in ()).throw(
            RuntimeError("synthetic failure")
        ),
    )

    with pytest.raises(RuntimeError, match="synthetic failure"):
        tool._totalsegmentator_segmentation(sitk.Image([2, 2, 2], sitk.sitkInt16), None, False)

    assert [item[0] for item in lifecycle] == ["enter", "exit"]
    assert oar_module._TOTALSEG_EXECUTION_LOCK.acquire(blocking=False)
    oar_module._TOTALSEG_EXECUTION_LOCK.release()


def test_label_volume_api_preserves_uploaded_ctv_foreground_and_uint16_oar_labels(
        monkeypatch, tmp_path):
    """The Data Tree and 2D renderer receive the exact imported label IDs."""
    from flask import Flask
    from web.routes import viewer_routes

    class Memory:
        def __init__(self, session_id):
            ctv = np.zeros((3, 4, 5), dtype=np.uint16)
            ctv[1, 1, 1] = 255
            oar = np.zeros((3, 4, 5), dtype=np.uint16)
            oar[0, 1, 2] = 201
            oar[2, 3, 4] = 10000
            self.session_id = session_id
            self.planning_results = {
                "ct_data": np.zeros((3, 4, 5), dtype=np.int16),
                "ctv_array": ctv,
                "ctv_source": "manual_label",
                "oar_array": oar,
                "oar_source": "uploaded_unknown",
                "organ_names": {201: "OAR 1", 10000: "OAR 2"},
                "organ_counts": {201: 1, 10000: 1},
                "oar_segmented": True,
            }
            self.patient_data = {}
            self.conversation = []
            self.tool_results = []
            self.context_summary = ""
            self.compaction_count = 0
            self.conversation_state = {}
            self.user_lang = "en"
            self._ui_state = {}
            self.current_phase = "idle"
            self._lock = threading.RLock()

        def retrieve(self, key, default=None):
            return self.planning_results.get(key, default)

        def store(self, key, value):
            self.planning_results[key] = value

        def set_ui_state(self, state):
            self._ui_state = dict(state or {})

        def get_ui_state(self):
            return dict(self._ui_state)

        def set_persistence_callback(self, callback):
            self._persistence_callback = callback

    class FakeAgent:
        def __init__(self, session_id, config=None):
            self.memory = Memory(session_id)
            self.config = dict(config or {})
            self.brain_available = False
            self._workspace_data_ready = True

        def _get_label_array(self, key):
            return self.memory.retrieve(key)

        def get_status(self):
            return {
                "session_id": self.memory.session_id,
                "phase": "idle",
                "stored_keys": list(self.memory.planning_results),
                "ct_loaded": True,
                "ct_path": "",
            }

    agent = FakeAgent("label-roundtrip")
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
    app.testing = True
    client = app.test_client()
    response = client.get("/api/viewer/label_volume")

    assert response.status_code == 200
    assert response.headers["X-Has-CTV"] == "true"
    assert response.headers["X-Has-OAR"] == "true"
    assert response.headers["X-OAR-Bytes-Per-Voxel"] == "2"
    ctv_size = int(response.headers["X-CTV-Size"])
    ctv = np.frombuffer(response.data[:ctv_size], dtype=np.uint8)
    oar = np.frombuffer(response.data[ctv_size:], dtype="<u2")
    assert int(ctv.max()) == 1
    assert set(np.unique(oar)) == {0, 201, 10000}


def test_generic_biomedparse_mask_catalogue_and_volume_are_session_scoped(monkeypatch):
    from flask import Flask
    from web.routes import viewer_routes

    mask = np.zeros((2, 3, 4), dtype=np.uint8)
    mask[1, 1, 2] = 1

    class Memory:
        session_id = "generic-roundtrip"

        def __init__(self):
            self.values = {
                "ct_data": np.zeros_like(mask),
                "generic_segmentation_masks": [{
                    "mask_id": "mask_bp_test",
                    "object_id": "mask:mask_bp_test",
                    "data_tree_node_id": "mask_bp_test",
                    "target": "liver",
                    "label": "liver",
                    "kind": "generic_segmentation",
                    "spacing": [0.7, 0.8, 2.0],
                    "origin": [1.0, 2.0, 3.0],
                    "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                    "voxel_count": 1,
                    "mask_array": mask,
                }],
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    class Agent:
        def __init__(self):
            self.memory = Memory()
            self._workspace_data_ready = True

    agent = Agent()
    monkeypatch.setattr(viewer_routes, "require_api_key", lambda func: func)
    monkeypatch.setattr(viewer_routes, "rate_limit", lambda func: func)
    app = Flask(__name__)
    viewer_routes.register_viewer_routes(
        app,
        lambda **_kwargs: agent,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: {},
    )

    client = app.test_client()
    catalogue = client.get("/api/viewer/generic_masks")
    assert catalogue.status_code == 200
    assert catalogue.json["masks"][0]["target"] == "liver"
    assert "mask_array" not in catalogue.json["masks"][0]

    volume = client.get("/api/viewer/generic_mask_volume?mask_id=mask_bp_test")
    assert volume.status_code == 200
    assert volume.headers["X-Shape-Z"] == "2"
    assert volume.headers["X-Target"] == "liver"
    assert np.count_nonzero(np.frombuffer(volume.data, dtype=np.uint8)) == 1


def test_thin_oar_mesh_falls_back_when_presentation_cleanup_erases_mask(monkeypatch):
    """A one-slice label must produce a mesh instead of a marching-cubes 500."""
    from flask import Flask
    from web.routes import viewer_routes

    ct = np.zeros((1, 9, 9), dtype=np.int16)
    oar = np.zeros_like(ct, dtype=np.uint16)
    oar[0, 3:6, 3:6] = 501

    class Memory:
        session_id = "thin-oar"

        def __init__(self):
            self.values = {
                "ct_data": ct,
                "oar_array": oar,
                "ct_spacing": (0.7, 0.7, 5.0),
                "ct_origin": (0.0, 0.0, 0.0),
                "ct_direction": (1, 0, 0, 0, 1, 0, 0, 0, 1),
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    class Agent:
        def __init__(self):
            self.memory = Memory()
            self._workspace_data_ready = True

        def _get_label_array(self, key):
            return self.memory.retrieve(key)

    monkeypatch.setattr(viewer_routes, "require_api_key", lambda func: func)
    monkeypatch.setattr(viewer_routes, "rate_limit", lambda func: func)
    monkeypatch.setattr(viewer_routes, "_requires_label_faithful_mesh", lambda *_args: False)
    app = Flask(__name__)
    viewer_routes.register_viewer_routes(
        app,
        lambda **_kwargs: Agent(),
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: {},
    )

    response = app.test_client().post(
        "/api/viewer/3d_mask",
        json={"source": "oar", "label_id": 501},
    )
    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["vertex_count"] > 0
    assert response.json["preprocessing_fallback"] is True


def test_embedded_pancreas_labels_do_not_wrap_before_uint16_transport(monkeypatch):
    """The nnUNet artery/vein/pancreas remap must preserve IDs 201-203."""
    from flask import Flask
    from web.routes import viewer_routes

    class Memory:
        def __init__(self):
            ct = np.zeros((2, 3, 4), dtype=np.int16)
            ctv = np.zeros_like(ct, dtype=np.uint8)
            ctv[0, 0, :4] = [1, 2, 3, 4]
            self.values = {
                "ct_data": ct,
                "ct_image": sitk.GetImageFromArray(ct),
                "ctv_source": "model",
                "ctv_full_labels": ctv,
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    class Agent:
        def __init__(self):
            self.memory = Memory()
            self._workspace_data_ready = True

        def _get_label_array(self, key):
            return self.memory.retrieve(key)

    agent = Agent()
    monkeypatch.setattr(viewer_routes, "require_api_key", lambda func: func)
    monkeypatch.setattr(viewer_routes, "rate_limit", lambda func: func)
    app = Flask(__name__)
    viewer_routes.register_viewer_routes(
        app,
        lambda **_kwargs: agent,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: {},
    )
    response = app.test_client().get("/api/viewer/label_volume")

    assert response.status_code == 200
    assert response.headers["X-OAR-Bytes-Per-Voxel"] == "2"
    ctv_size = int(response.headers["X-CTV-Size"])
    oar = np.frombuffer(response.data[ctv_size:], dtype="<u2")
    assert set(np.unique(oar)) == {0, 201, 202, 203}

