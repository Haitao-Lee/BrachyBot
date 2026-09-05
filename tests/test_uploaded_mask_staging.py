"""Regression tests for source-first uploaded CTV mask staging."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import SimpleITK as sitk
import pytest

from web.structure_service import (
    StructureError,
    build_effective_structures,
    ensure_structure_registry_for_hydrated_uploads,
    initialize_structure_registry,
    reclassify_generic_segmentation_masks,
)
from web.uploaded_mask_service import (
    normalize_uploaded_mask_results,
    stage_uploaded_ctv_mask,
)


class _Memory:
    def __init__(self):
        self._lock = threading.RLock()
        self._planning_versions = {}
        self.planning_results = {}
        self.conversation_state = {"data_available": []}
        self.session_id = "uploaded-mask-test"

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)

    def store(self, key, value):
        self.planning_results[key] = value
        self._planning_versions[key] = self._planning_versions.get(key, 0) + 1

    def _notify_persistence(self, reason):
        return None


def _write_case(tmp_path):
    shape = (5, 6, 7)
    ct = sitk.GetImageFromArray(np.zeros(shape, dtype=np.int16))
    ct.SetSpacing((0.7, 0.8, 2.5))
    labels = np.zeros(shape, dtype=np.uint8)
    labels[0, 0, 0] = 1
    labels[1:4, 2:4, 3:6] = 2
    label = sitk.GetImageFromArray(labels)
    label.CopyInformation(ct)
    ct_path = tmp_path / "ct.nii.gz"
    label_path = tmp_path / "uploaded_labels.nii.gz"
    sitk.WriteImage(ct, str(ct_path))
    sitk.WriteImage(label, str(label_path))
    return ct_path, label_path, labels


def test_multilabel_upload_creates_parent_and_binary_children_without_ctv(tmp_path):
    ct_path, label_path, labels = _write_case(tmp_path)
    memory = _Memory()

    staged = stage_uploaded_ctv_mask(memory, str(ct_path), str(label_path))
    repeated = stage_uploaded_ctv_mask(memory, str(ct_path), str(label_path))

    assert staged["total_labels"] == 2
    assert staged["labels"] == [1, 2]
    assert repeated["reused"] is True
    assert len(memory.retrieve("uploaded_mask_collections")) == 1
    children = memory.retrieve("generic_segmentation_masks")
    assert len(children) == 2
    assert {int(item["source_label"]) for item in children} == {1, 2}
    assert all(item["parent_group"] == "upload_masks" for item in children)
    assert all(set(np.unique(item["mask_array"]).tolist()) <= {0, 1} for item in children)
    assert all(
        int(np.count_nonzero(item["mask_array"])) == int(np.count_nonzero(labels == item["source_label"]))
        for item in children
    )
    assert memory.retrieve("ctv_array") is None
    assert memory.retrieve("ctv_mask") is None


def test_only_explicit_ctv_move_promotes_selected_uploaded_child():
    memory = _Memory()
    shape = (5, 6, 7)
    ct = sitk.GetImageFromArray(np.zeros(shape, dtype=np.int16))
    ct.SetSpacing((1.0, 1.0, 1.0))
    memory.store("ct_image", ct)
    memory.store("ct_data", np.zeros(shape, dtype=np.int16))
    selected = np.zeros(shape, dtype=np.uint8)
    selected[1:3, 2:4, 3:5] = 1
    other = np.zeros(shape, dtype=np.uint8)
    other[3:5, 0:2, 0:2] = 1
    memory.store("generic_segmentation_masks", [
        {
            "mask_id": "upload_mask_demo_label_1",
            "object_id": "mask:upload_mask_demo_label_1",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_mask_demo",
            "source_label": 1,
            "classification": "unclassified",
            "moved_to": None,
            "mask_array": selected,
            "spacing": [1.0, 1.0, 1.0],
            "volume_mm3": float(np.count_nonzero(selected)),
        },
        {
            "mask_id": "upload_mask_demo_label_2",
            "object_id": "mask:upload_mask_demo_label_2",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_mask_demo",
            "source_label": 2,
            "classification": "unclassified",
            "moved_to": None,
            "mask_array": other,
            "spacing": [1.0, 1.0, 1.0],
            "volume_mm3": float(np.count_nonzero(other)),
        },
    ])

    effective = reclassify_generic_segmentation_masks(
        memory, ["mask:upload_mask_demo_label_1"], "ctv",
    )

    assert np.array_equal(effective.ctv_array, selected)
    entries = memory.retrieve("generic_segmentation_masks")
    assert entries[0]["classification"] == "ctv"
    assert entries[0]["ctv_promoted_from_upload"]["source_label"] == 1
    assert entries[1]["classification"] == "unclassified"


def test_all_explicit_ctv_children_are_merged_for_planning_but_keep_source_rows():
    memory = _Memory()
    shape = (4, 5, 6)
    first = np.zeros(shape, dtype=np.uint8)
    first[0:2, 1:3, 1:3] = 1
    second = np.zeros(shape, dtype=np.uint8)
    second[2:4, 3:5, 3:5] = 1
    memory.store("generic_segmentation_masks", [
        {
            "mask_id": "upload_union_label_1",
            "object_id": "mask:upload_union_label_1",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_union",
            "source_label": 1,
            "classification": "unclassified",
            "mask_array": first,
            "spacing": [1.0, 1.0, 1.0],
            "volume_mm3": float(np.count_nonzero(first)),
        },
        {
            "mask_id": "upload_union_label_2",
            "object_id": "mask:upload_union_label_2",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_union",
            "source_label": 2,
            "classification": "unclassified",
            "mask_array": second,
            "spacing": [1.0, 1.0, 1.0],
            "volume_mm3": float(np.count_nonzero(second)),
        },
    ])

    reclassify_generic_segmentation_masks(
        memory, ["mask:upload_union_label_1"], "ctv",
    )
    effective_one = build_effective_structures(memory)
    assert np.array_equal(effective_one.ctv_array > 0, first > 0)

    effective_both = reclassify_generic_segmentation_masks(
        memory, ["mask:upload_union_label_2"], "ctv",
    )
    expected = (first > 0) | (second > 0)
    assert np.array_equal(effective_both.ctv_array > 0, expected)
    assert set(memory.retrieve("ctv_source_object_ids")) == {
        "mask:upload_union_label_1",
        "mask:upload_union_label_2",
    }
    # The Data Tree source rows remain durable even though planning consumes
    # one binary union mask.
    assert len(memory.retrieve("generic_segmentation_masks")) == 2
    assert all(item["classification"] == "ctv" for item in memory.retrieve("generic_segmentation_masks"))


def test_planning_loads_the_effective_binary_union_not_the_raw_uploaded_path(tmp_path):
    ct_path, label_path, labels = _write_case(tmp_path)
    memory = _Memory()
    ct = sitk.ReadImage(str(ct_path))
    memory.store("ct_image", ct)
    memory.store("ct_data", sitk.GetArrayFromImage(ct))
    staged = stage_uploaded_ctv_mask(memory, str(ct_path), str(label_path))
    # Label 2 has enough voxels for the same clinical plausibility guard used
    # by the real Move-to-CTV route; label 1 is intentionally a tiny distractor.
    selected_id = next(
        item["object_id"] for item in staged["children"]
        if int(item["source_label"]) == 2
    )
    reclassify_generic_segmentation_masks(memory, [selected_id], "ctv")

    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    loaded = PlanningPipelineTool.__new__(PlanningPipelineTool)._load_ctv(
        {"ctv_mask_path": str(label_path)}, SimpleNamespace(memory=memory), ct,
    )
    assert loaded is not None
    assert np.array_equal(loaded > 0, labels == 2)


def test_raw_multilabel_path_is_rejected_until_an_upload_label_is_classified(tmp_path):
    ct_path, label_path, _ = _write_case(tmp_path)
    memory = _Memory()
    ct = sitk.ReadImage(str(ct_path))
    memory.store("ct_image", ct)
    memory.store("ct_data", sitk.GetArrayFromImage(ct))
    stage_uploaded_ctv_mask(memory, str(ct_path), str(label_path))

    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    loaded = PlanningPipelineTool.__new__(PlanningPipelineTool)._load_ctv(
        {"ctv_mask_path": str(label_path)}, SimpleNamespace(memory=memory), ct,
    )
    assert loaded is None


def test_ctv_node_with_multiple_transport_labels_is_merged_to_one_planning_target():
    memory = _Memory()
    shape = (3, 4, 5)
    labels = np.zeros(shape, dtype=np.uint8)
    labels[0, 0, 0] = 1
    labels[2, 3, 4] = 2
    memory.store("ctv_array", labels)
    memory.store("ctv_source", "manual_label")
    memory.store("ctv_label_map", {1: "lesion A", 2: "lesion B"})
    initialize_structure_registry(memory)

    effective = build_effective_structures(memory)
    assert np.array_equal(effective.ctv_array > 0, labels > 0)
    assert {item["source_label"] for item in effective.structures
            if item["classification"] == "ctv"} == {1, 2}


def test_legacy_placeholder_does_not_hide_moved_to_classification():
    results = {
        "generic_segmentation_masks": [{
            "mask_id": "upload_legacy_label_2",
            "object_id": "mask:upload_legacy_label_2",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_legacy",
            "classification": "unclassified",
            "moved_to": "ctv",
            "mask_array": np.ones((2, 2, 2), dtype=np.uint8),
        }],
    }
    assert normalize_uploaded_mask_results(results) is True
    entry = results["generic_segmentation_masks"][0]
    assert entry["classification"] == "ctv"
    assert entry["parent_group"] == "ctv"


def test_hydrated_explicit_upload_promotion_creates_registry_without_losing_child():
    memory = _Memory()
    source = np.zeros((2, 3, 4), dtype=np.uint8)
    source[0, 1, 1] = 1
    memory.store("ctv_array", np.zeros_like(source))
    memory.store("ctv_source", "manual_label")
    memory.store("generic_segmentation_masks", [{
        "mask_id": "upload_restore_label_1",
        "object_id": "mask:upload_restore_label_1",
        "kind": "uploaded_mask_label",
        "source": "uploaded_mask",
        "upload_mask_id": "upload_restore",
        "source_label": 1,
        "classification": "ctv",
        "moved_to": "ctv",
        "mask_array": source,
        "volume_mm3": 1.0,
    }])

    assert ensure_structure_registry_for_hydrated_uploads(memory) is True
    effective = build_effective_structures(memory)
    assert np.array_equal(effective.ctv_array > 0, source > 0)
    assert memory.retrieve("structure_registry_initialized") is True
    assert memory.retrieve("generic_segmentation_masks")[0]["object_id"] == "mask:upload_restore_label_1"


def test_live_legacy_move_does_not_reintroduce_unselected_raw_upload_labels():
    """Promoting a child must also repair an old live raw multi-label base."""
    memory = _Memory()
    shape = (4, 5, 6)
    raw = np.zeros(shape, dtype=np.uint8)
    raw[0:2, 0:2, 0:2] = 1
    raw[2:4, 3:5, 3:5] = 2
    selected = (raw == 1).astype(np.uint8)
    sibling = (raw == 2).astype(np.uint8)
    source_path = "/case/uploads/legacy-labels.nii.gz"
    memory.store("ctv_array", raw)
    memory.store("ctv_source", "classified")
    memory.store("ctv_mask_path", source_path)
    memory.store("generic_segmentation_masks", [
        {
            "mask_id": "upload_live_label_1",
            "object_id": "mask:upload_live_label_1",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_live",
            "source_path": source_path,
            "source_label": 1,
            "classification": "unclassified",
            "mask_array": selected,
            "volume_mm3": float(np.count_nonzero(selected)),
        },
        {
            "mask_id": "upload_live_label_2",
            "object_id": "mask:upload_live_label_2",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": "upload_live",
            "source_path": source_path,
            "source_label": 2,
            "classification": "unclassified",
            "mask_array": sibling,
            "volume_mm3": float(np.count_nonzero(sibling)),
        },
    ])

    effective = reclassify_generic_segmentation_masks(
        memory, ["mask:upload_live_label_1"], "ctv",
    )

    assert np.array_equal(effective.ctv_array > 0, selected > 0)
    assert memory.retrieve("structure_base_ctv_array") is None
    assert memory.retrieve("generic_segmentation_masks")[1]["classification"] == "unclassified"


def test_implausible_uploaded_child_is_rejected_at_ctv_promotion():
    memory = _Memory()
    shape = (3, 3, 3)
    ct = sitk.GetImageFromArray(np.zeros(shape, dtype=np.int16))
    memory.store("ct_image", ct)
    memory.store("ct_data", np.zeros(shape, dtype=np.int16))
    candidate = np.zeros(shape, dtype=np.uint8)
    candidate[1, 1, 1] = 1
    memory.store("generic_segmentation_masks", [{
        "mask_id": "upload_mask_large_label_1",
        "object_id": "mask:upload_mask_large_label_1",
        "kind": "uploaded_mask_label",
        "source": "uploaded_mask",
        "upload_mask_id": "upload_mask_large",
        "source_label": 1,
        "classification": "unclassified",
        "mask_array": candidate,
        "spacing": [1.0, 1.0, 1.0],
        "volume_mm3": 1_500_000.0,
    }])

    with pytest.raises(StructureError, match="not a plausible brachytherapy target"):
        reclassify_generic_segmentation_masks(
            memory, ["mask:upload_mask_large_label_1"], "ctv",
        )


def test_uploaded_mask_frontend_keeps_hydration_and_staging_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    manual = (root / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    viewer = (root / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")
    routes = (root / "web/routes/planning_routes.py").read_text(encoding="utf-8")

    assert "maxPendingAttempts = 240" in ui_api
    assert "payload.retry_after_ms" in ui_api
    assert "staged_only" in ui_api
    assert "maxPendingAttempts" not in manual or "attempt <= 240" in manual
    assert "Upload Mask" in manual
    assert "upload_masks" in viewer
    assert "metadata.kind || existing.kind" in viewer
    assert "stage_uploaded_ctv_mask" in routes


def test_rate_limit_retry_contract_waits_for_the_oldest_request_to_expire():
    from web import server_support

    client_ip = "uploaded-mask-rate-limit-test"
    now = time.time()
    with server_support._rate_limit_lock:
        previous_store = dict(server_support._rate_limit_store)
        server_support._rate_limit_store[client_ip] = [now - 1.0, now - 0.5]
    try:
        old_requests = server_support.RATE_LIMIT_REQUESTS
        old_window = server_support.RATE_LIMIT_WINDOW
        server_support.RATE_LIMIT_REQUESTS = 2
        server_support.RATE_LIMIT_WINDOW = 60
        retry_after_ms = server_support._rate_limit_retry_after_ms(client_ip)
    finally:
        server_support.RATE_LIMIT_REQUESTS = old_requests
        server_support.RATE_LIMIT_WINDOW = old_window
        with server_support._rate_limit_lock:
            server_support._rate_limit_store.clear()
            server_support._rate_limit_store.update(previous_store)

    assert 58_000 <= retry_after_ms <= 60_000


def test_rate_limit_aware_upload_retry_does_not_poll_faster_than_the_limiter():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    server_support = (root / "web/server_support.py").read_text(encoding="utf-8")

    assert "_segmentationHydrationInFlight" in ui_api
    assert "payload.code === 'rate_limit_exceeded'" in ui_api
    assert "Math.max(1000" in ui_api
    assert '"code": "rate_limit_exceeded"' in server_support
    assert '"Retry-After-Ms"' in server_support


def test_viewer_hydration_uses_an_independent_rate_limit_bucket():
    from flask import Flask
    from web import server_support

    app = Flask(__name__)

    @server_support.rate_limit
    def endpoint():
        return "ok"

    old_trust = server_support._TRUST_NETWORK
    old_default_budget = server_support.RATE_LIMIT_REQUESTS
    old_data_budget = server_support.RATE_LIMIT_DATA_REQUESTS
    old_window = server_support.RATE_LIMIT_WINDOW
    with server_support._rate_limit_lock:
        old_default_store = dict(server_support._rate_limit_store)
        old_data_store = dict(server_support._rate_limit_data_store)
        server_support._rate_limit_store.clear()
        server_support._rate_limit_data_store.clear()
    try:
        server_support._TRUST_NETWORK = False
        server_support.RATE_LIMIT_REQUESTS = 1
        server_support.RATE_LIMIT_DATA_REQUESTS = 2
        server_support.RATE_LIMIT_WINDOW = 60

        with app.test_request_context('/api/segmentation', method='POST'):
            assert endpoint() == "ok"
            blocked = endpoint()
            assert blocked[1] == 429

        with app.test_request_context('/api/viewer/3d_mask', method='POST'):
            assert endpoint() == "ok"
            assert endpoint() == "ok"
            blocked = endpoint()
            assert blocked[1] == 429
    finally:
        server_support._TRUST_NETWORK = old_trust
        server_support.RATE_LIMIT_REQUESTS = old_default_budget
        server_support.RATE_LIMIT_DATA_REQUESTS = old_data_budget
        server_support.RATE_LIMIT_WINDOW = old_window
        with server_support._rate_limit_lock:
            server_support._rate_limit_store.clear()
            server_support._rate_limit_store.update(old_default_store)
            server_support._rate_limit_data_store.clear()
            server_support._rate_limit_data_store.update(old_data_store)


def test_uploaded_mask_label_ids_use_registry_for_all_tree_controls():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    viewer = (root / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")
    layout = (root / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")
    manual_3d = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    index = (root / "web/app/index.html").read_text(encoding="utf-8")

    # Uploaded children use upload_mask_<digest>_label_<label>, which is not
    # covered by the pre-existing mask_ / mask: prefix convention.
    assert "function _isDataTreeMaskId(nodeId)" in viewer
    assert "|| !!_maskStateEntry(value);" in viewer
    assert "const isMaskId = _isDataTreeMaskId(id);" in viewer
    assert "else if (_isDataTreeMaskId(id))" in viewer
    assert "if (_isDataTreeMaskId(id))" in viewer
    assert "window.isDataTreeMaskId = _isDataTreeMaskId;" in viewer
    assert "mask.kind === 'uploaded_mask_label'" in layout
    assert "window.isDataTreeMaskId" in manual_3d
    assert "brachybot-viewer-volume.js?v=51" in index
    assert "brachybot-viewer-layout.js?v=38" in index
    assert "brachybot-3d-manual.js?v=82" in index
