from __future__ import annotations

import csv
import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import SimpleITK as sitk

from web.export_service import ExportJobManager, ExportService
from web.routes.data_routes import _delete_object
from web.structure_service import (
    build_effective_structures,
    delete_structure,
    reclassify_generic_segmentation_masks,
    reclassify_structure,
    replace_structure_source,
)
from web.workspace_store import WorkspaceStore


class _Memory:
    def __init__(self):
        self._lock = threading.RLock()
        self._planning_versions = {}
        self.conversation_state = {
            "data_available": [],
            "ctv_segmented": True,
            "oar_segmented": True,
            "planning_completed": True,
        }
        shape = (10, 9, 8)
        ct = sitk.GetImageFromArray(
            np.arange(np.prod(shape), dtype=np.int16).reshape(shape),
        )
        ct.SetSpacing((0.7, 0.8, 2.5))
        ct.SetOrigin((-120.5, -101.25, 42.0))
        ct.SetDirection((0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        ctv = np.zeros(shape, dtype=np.uint8)
        ctv[3:7, 3:7, 2:6] = 1
        oar = np.zeros(shape, dtype=np.uint16)
        oar[1:4, 1:4, 1:4] = 2
        oar[6:9, 5:8, 4:7] = 3
        dose = np.linspace(0.0, 300.0, np.prod(shape), dtype=np.float32).reshape(shape)
        skin = np.zeros(shape, dtype=np.uint8)
        skin[1:9, 1:8, 1:7] = 1
        skin[2:8, 2:7, 2:6] = 0
        self.planning_results = {
            "ct_image": ct,
            "ctv_array": ctv,
            "ctv_label_map": {1: "Pancreatic Tumor"},
            "ctv_source": "manual_label",
            "oar_array": oar,
            "organ_names": {2: "Duodenum", 3: "Kidney L"},
            "organ_counts": {2: 27, 3: 27},
            "oar_source": "model",
            "dose_distribution_gy": dose,
            "dose_scale_gy": 190.8,
            "dose_metrics": {"v100": 90.0, "d90": 120.0},
            "dvh_data": {
                "CTV": {
                    "dose": [0.0, 120.0, 240.0],
                    "volume_percent": [100.0, 90.0, 20.0],
                    "total_volume_cc": 12.0,
                },
            },
            "plan_config": {
                "in_lowest_energy": 120.0,
                "out_highest_energy": 120.0,
                "iso_dose_params": {"iso_dose_values": [1.0, 1.5]},
                "seed_info": {"length": 4.5, "radius": 0.4, "model": "I-125"},
            },
            "planning_id": "planning-7",
            "planning_version": 7,
            "manual_plan_version": 3,
            "manual_plan_active": True,
            "skin_surface": {
                "object_id": "skin_surface:guide",
                "data_tree_node_id": "skin_surface",
                "label": "Guide skin surface",
                "source": "surgical_guide",
                "data_version": 2,
                "threshold_hu": -300.0,
            },
            "skin_surface_mask": skin,
            "trajectories": [
                {"id": "trajectory_1", "entry": [4, 5, 40], "target": [4, 5, 10]},
            ],
            "manual_needles": [
                {
                    "id": "needle_1",
                    "trajectory_id": "trajectory_1",
                    "points": [[4.0, 5.0, 40.0], [4.0, 5.0, 10.0]],
                },
            ],
            "manual_seeds": [
                {
                    "id": "seed_1",
                    "needle_id": "needle_1",
                    "trajectory_id": "trajectory_1",
                    "position": [4.0, 5.0, 20.0],
                    "direction": [0.0, 0.0, -1.0],
                },
            ],
            "surgical_guide": {
                "status": "ready",
                "version": 2,
                "vertices": [
                    [0.0, 0.0, 0.0],
                    [10.0, 0.0, 0.0],
                    [0.0, 10.0, 0.0],
                    [0.0, 0.0, 10.0],
                ],
                "faces": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
            },
        }
        self.conversation = []
        self.tool_results = []
        self.patient_data = {}
        self.context_summary = ""
        self.compaction_count = 0
        self.current_phase = SimpleNamespace(value="planning")
        self.user_lang = "en"
        self.persist_reasons = []

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)

    def store(self, key, value):
        self.planning_results[key] = value

    def _notify_persistence(self, reason):
        self.persist_reasons.append(reason)

    def get_ui_state(self):
        return {}


class _Agent:
    def __init__(self):
        self.memory = _Memory()
        self.config = {}


def _case(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("export-owner", "hash")
    session = store.create_session(user["id"], "Pancreas export")
    agent = _Agent()
    store.save_snapshot_patch(
        user["id"],
        session.id,
        {
            "chat": {
                "messages": [
                    {
                        "id": "m1",
                        "request_id": "r1",
                        "type": "user",
                        "content": "export",
                        "timestamp": 1000,
                    },
                    {
                        "id": "m2",
                        "request_id": "r1",
                        "type": "bot-response",
                        "content": "ready",
                        "timestamp": 2000,
                        "steps": [
                            {
                                "type": "tool_call",
                                "tool": "planning_pipeline",
                                "status": "done",
                                "input_summary": "case inputs",
                                "output_summary": "plan ready",
                            },
                        ],
                    },
                ],
            },
            "report": {
                "status": "ready",
                "form": {
                    "version": 4,
                    "figures": [{
                        "title": "Dose overview",
                        "dataUrl": (
                            f"/api/sessions/{session.id}/screenshots/figure.png"
                        ),
                    }],
                },
            },
            "ui": {
                "state": {
                    "viewer": {
                        "annotations": [
                            {"id": "a1", "label": "Entry note", "points": [[1, 2, 3]]},
                        ],
                    },
                },
            },
        },
    )
    root = store.workspace_root(user["id"], session.id, create=True)
    report = root / "artifacts" / "reports" / "plan.pdf"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n")
    screenshot = root / "screenshots" / "dose.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"export-test")
    figure = root / "screenshots" / "figure.png"
    figure.write_bytes(b"\x89PNG\r\n\x1a\n" + b"report-figure-test")
    return store, user, session, agent


def test_query_metrics_accepts_numpy_seed_positions_and_reports_oar_metrics():
    """The agent bridge must not evaluate a NumPy array as a boolean."""
    from tool_factory.viewer_command.query_metrics import QueryMetricsTool

    tool = QueryMetricsTool()
    seed_positions = np.zeros((3, 3), dtype=np.float32)
    seed_result = tool._execute(
        metric_type="seed_count",
        seed_positions=seed_positions,
        total_seeds=99,
    )
    assert seed_result.success is True
    assert seed_result.metadata["seed_count"] == 3

    all_result = tool._execute(
        metric_type="all_metrics",
        ctv_array=np.ones((2, 2, 2), dtype=np.uint8),
        oar_array=np.ones((2, 2, 2), dtype=np.uint8),
        organ_names={1: "stomach"},
        ct_spacing=[1.0, 1.0, 1.0],
        seed_positions=seed_positions,
        total_seeds=99,
        metrics={"v100": 0.9},
    )
    assert all_result.success is True
    assert all_result.metadata["seed_count"] == 3
    assert all_result.metadata["stomach"] == 0.01


def test_structure_classification_is_bidirectional_and_persistent(tmp_path):
    store, user, session, agent = _case(tmp_path)
    memory = agent.memory

    original = build_effective_structures(memory)
    duodenum = next(
        item for item in original.structures if item["name"] == "Duodenum"
    )
    object_id = duodenum["object_id"]
    mask = np.array(duodenum["mask"], copy=True)

    promoted = reclassify_structure(memory, object_id, "ctv")
    promoted_row = next(item for item in promoted.structures if item["object_id"] == object_id)
    assert promoted_row["classification"] == "ctv"
    assert np.array_equal(promoted_row["mask"], mask)
    assert memory.retrieve("structure_overrides")[object_id]["classification"] == "ctv"
    assert memory.retrieve("dose_distribution_gy") is None
    assert memory.retrieve("surgical_guide")["status"] == "stale"
    assert memory.retrieve("structure_artifact_status")["planning"] == "stale"
    restored = reclassify_structure(memory, object_id, "oar")
    restored_row = next(item for item in restored.structures if item["object_id"] == object_id)
    assert restored_row["classification"] == "oar"
    assert np.array_equal(restored_row["mask"], mask)

    deleted = delete_structure(memory, object_id)
    assert all(item["object_id"] != object_id for item in deleted.structures)
    assert object_id in memory.retrieve("structure_deleted_ids")


def test_generic_mask_move_updates_effective_structure_set_and_invalidates_dependents():
    memory = _Memory()
    shape = (10, 9, 8)
    generic_mask = np.zeros(shape, dtype=np.uint8)
    generic_mask[2:4, 2:5, 3:6] = 1
    memory.store("generic_segmentation_masks", [{
        "mask_id": "mask_pancreas",
        "object_id": "mask:mask_pancreas",
        "data_tree_node_id": "mask_pancreas",
        "name": "Pancreas",
        "label": "Pancreas",
        "classification": "unclassified",
        "moved_to": None,
        "mask_array": generic_mask,
        "spacing": [0.7, 0.8, 2.5],
        "origin": [-120.5, -101.25, 42.0],
        "direction": [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "data_version": 1,
    }])
    memory.store("dvh_data", {"CTV": {"dose": [0, 120]}})
    memory.store("surgical_guide", {"status": "ready", "version": 1})

    effective = reclassify_generic_segmentation_masks(
        memory, ["mask:mask_pancreas"], "oar",
    )
    moved = next(
        item for item in effective.structures
        if item["object_id"] == "mask:mask_pancreas"
    )

    assert moved["classification"] == "oar"
    assert moved["name"] == "Pancreas"
    assert np.array_equal(moved["mask"], generic_mask.astype(bool))
    persisted = memory.retrieve("generic_segmentation_masks")[0]
    assert persisted["classification"] == "oar"
    assert persisted["moved_to"] == "oar"
    assert np.array_equal(persisted["mask_array"], generic_mask)
    assert np.all(effective.oar_array[generic_mask > 0] > 0)
    assert np.count_nonzero(effective.oar_array) >= np.count_nonzero(generic_mask)
    assert memory.retrieve("dvh_data") is None
    assert memory.retrieve("surgical_guide")["status"] == "stale"

    restored = reclassify_generic_segmentation_masks(
        memory, ["mask_pancreas"], "ctv",
    )
    restored_row = next(
        item for item in restored.structures
        if item["object_id"] == "mask:mask_pancreas"
    )
    assert restored_row["classification"] == "ctv"
    assert np.all(restored.ctv_array[generic_mask > 0] > 0)


def test_model_ctv_anatomy_survives_an_oar_source_refresh():
    """Refreshing OAR must not erase multi-label anatomy from CTV output."""
    memory = _Memory()
    shape = (10, 9, 8)
    full_labels = np.zeros(shape, dtype=np.uint8)
    full_labels[3:7, 3:7, 2:6] = 1
    full_labels[0:2, 0:2, 0:2] = 2
    full_labels[8:10, 7:9, 6:8] = 3
    full_labels[0:2, 7:9, 6:8] = 4
    memory.store("ctv_array", (full_labels == 1).astype(np.uint8))
    memory.store("ctv_full_labels", full_labels)
    memory.store(
        "ctv_label_map",
        {1: "pancreatic tumor", 2: "artery", 3: "vein", 4: "pancreas"},
    )
    memory.store("ctv_source", "nnunet_pancreatic")
    replace_structure_source(memory, "ctv")

    refreshed_oar = np.zeros(shape, dtype=np.uint16)
    refreshed_oar[7:9, 0:2, 0:2] = 1
    memory.store("oar_array", refreshed_oar)
    memory.store("organ_names", {1: "stomach"})
    memory.store("oar_source", "totalsegmentator")
    replace_structure_source(memory, "oar")

    catalog = build_effective_structures(memory).public_catalog()
    names = {item["name"] for item in catalog}
    assert {"pancreatic tumor", "artery", "vein", "pancreas", "stomach"} <= names
    assert memory.retrieve("structure_base_ctv_source") == "nnunet_pancreatic"
    assert memory.retrieve("structure_base_oar_source") == "totalsegmentator"


def test_leaf_delete_contract_cannot_be_promoted_to_recursive_group_delete():
    """The Data Tree must opt in before an OAR/CTV parent can be deleted."""
    root = Path(__file__).resolve().parents[1]
    routes = (root / "web" / "routes" / "data_routes.py").read_text(encoding="utf-8")
    viewer = (root / "web" / "app" / "static" / "js" / "brachybot-viewer-volume.js").read_text(encoding="utf-8")
    assert "Recursive group deletion requires explicit confirmation" in routes
    assert "if (!selectedItems.has(id))" in viewer
    assert "selectedItems.add(id);" in viewer
    assert "recursive_groups: options.recursiveGroups === true" in viewer


def test_export_service_serializes_true_units_geometry_and_types(tmp_path):
    store, user, session, agent = _case(tmp_path)
    service = ExportService(store)
    catalog = {item.object_id: item for item in service.catalog(user["id"], session.id, agent)}
    public_catalog = service.public_catalog(user["id"], session.id, agent)
    destination = tmp_path / "exported"

    expected = {
        "image:ct",
        "structure:ctv:1",
        "structure:oar:2",
        "skin_surface:guide",
        "needle:needle_1",
        "seed:seed_1",
        "dose:volume",
        "dvh:data",
        "dvh:curve",
        "surgical_guide:active",
        "report:pdf",
        "figure:figure.png",
        "chat:history",
        "chat:execution_trace",
        "chat:tool_history",
        "annotation:a1",
        "screenshot:dose.png",
    }
    assert expected <= set(catalog)
    for item in public_catalog["objects"]:
        assert item["session_id"] == session.id
        assert item["case_id"] == session.id
        assert item["planning_id"] == "planning-7"
        assert isinstance(item["data_version"], int)
        assert item["status"]
        assert "error" in item

    ct_path = service.export_object(
        user["id"], session.id, agent, catalog["image:ct"], "nifti", destination,
    )
    exported_ct = sitk.ReadImage(str(ct_path))
    source_ct = agent.memory.retrieve("ct_image")
    assert exported_ct.GetSize() == source_ct.GetSize()
    assert np.allclose(exported_ct.GetSpacing(), source_ct.GetSpacing())
    assert np.allclose(exported_ct.GetOrigin(), source_ct.GetOrigin())
    assert np.allclose(exported_ct.GetDirection(), source_ct.GetDirection())

    structure_path = service.export_object(
        user["id"], session.id, agent, catalog["structure:oar:2"], "nifti", destination,
    )
    structure_image = sitk.ReadImage(str(structure_path))
    assert structure_image.GetDirection() == source_ct.GetDirection()
    assert int(sitk.GetArrayFromImage(structure_image).sum()) == 27

    surface_path = service.export_object(
        user["id"], session.id, agent, catalog["structure:oar:2"], "stl", destination,
    )
    assert surface_path.read_text(encoding="ascii").startswith("solid Duodenum")

    skin_path = service.export_object(
        user["id"], session.id, agent, catalog["skin_surface:guide"], "nifti", destination,
    )
    skin_image = sitk.ReadImage(str(skin_path))
    assert skin_image.GetDirection() == source_ct.GetDirection()
    assert int(sitk.GetArrayFromImage(skin_image).sum()) == int(
        agent.memory.retrieve("skin_surface_mask").sum()
    )
    skin_surface_path = service.export_object(
        user["id"], session.id, agent, catalog["skin_surface:guide"], "stl", destination,
    )
    assert skin_surface_path.read_text(encoding="ascii").startswith(
        "solid Guide skin surface"
    )

    needle_path = service.export_object(
        user["id"], session.id, agent, catalog["needle:needle_1"], "json", destination,
    )
    needle = json.loads(needle_path.read_text(encoding="utf-8"))
    assert needle["start_point"] == [4.0, 5.0, 40.0]
    assert needle["end_point"] == [4.0, 5.0, 10.0]
    assert needle["coordinate_system"] == "LPS"

    seed_path = service.export_object(
        user["id"], session.id, agent, catalog["seed:seed_1"], "json", destination,
    )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    assert seed["position"] == [4.0, 5.0, 20.0]
    assert seed["length_mm"] == 4.5

    dose_path = service.export_object(
        user["id"], session.id, agent, catalog["dose:volume"], "nifti", destination,
    )
    exported_dose = sitk.GetArrayFromImage(sitk.ReadImage(str(dose_path)))
    assert np.allclose(exported_dose, agent.memory.retrieve("dose_distribution_gy"))
    assert float(exported_dose.max()) == 300.0

    dvh_path = service.export_object(
        user["id"], session.id, agent, catalog["dvh:data"], "csv", destination,
    )
    with dvh_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[1]["Volume_cc"] == "10.8"
    assert rows[1]["Volume_Percent"] == "90.0"

    xlsx_path = service.export_object(
        user["id"], session.id, agent, catalog["dvh:data"], "xlsx", destination,
    )
    with zipfile.ZipFile(xlsx_path) as workbook:
        assert "xl/worksheets/sheet1.xml" in workbook.namelist()

    guide_path = service.export_object(
        user["id"], session.id, agent, catalog["surgical_guide:active"], "stl", destination,
    )
    assert guide_path.stat().st_size > 100

    report_path = service.export_object(
        user["id"], session.id, agent, catalog["report:pdf"], "pdf", destination,
    )
    assert report_path.read_bytes().startswith(b"%PDF")

    figure_path = service.export_object(
        user["id"], session.id, agent, catalog["figure:figure.png"], "png", destination,
    )
    assert figure_path.read_bytes().endswith(b"report-figure-test")

    trace_path = service.export_object(
        user["id"], session.id, agent, catalog["chat:execution_trace"], "json", destination,
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["execution_trace"][0]["message_id"] == "m2"


def test_scene_export_builds_manifest_tree_and_zip(tmp_path):
    store, user, session, agent = _case(tmp_path)
    service = ExportService(store)
    catalog = service.catalog(user["id"], session.id, agent)
    selections = [
        {"object_id": item.object_id, "format": item.default_format}
        for item in catalog
        if item.data_type != "dose_isosurface"
    ]
    manager = ExportJobManager(store, lambda _owner, _session_id: agent)
    job = manager.create(user, session.id, selections, session.title)
    deadline = time.monotonic() + 20
    while job.status not in {"completed", "completed_with_errors", "failed"}:
        assert time.monotonic() < deadline
        time.sleep(0.05)

    assert job.status == "completed", job.failures
    assert job.completed == job.total
    assert Path(job.zip_path).is_file()
    manifest_path = Path(job.export_root) / "session_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["session_id"] == session.id
    assert manifest["planning_id"] == "planning-7"
    assert {item["object_id"] for item in manifest["files"]} >= {
        "image:ct",
        "structure:ctv:1",
        "structure:oar:2",
        "needle:needle_1",
        "seed:seed_1",
        "dose:volume",
        "report:pdf",
        "chat:history",
    }
    with zipfile.ZipFile(job.zip_path) as archive:
        names = archive.namelist()
    assert any(name.endswith("/session_manifest.json") for name in names)
    assert any("/Structures/CTV/" in name for name in names)
    assert any("/Planning/Needles/" in name for name in names)
    assert any("/Chat/" in name for name in names)


def test_cancelled_scene_export_stops_before_packaging(tmp_path, monkeypatch):
    store, user, session, agent = _case(tmp_path)
    service = ExportService(store)
    selections = [
        {"object_id": item.object_id, "format": item.default_format}
        for item in service.catalog(user["id"], session.id, agent)
    ]
    original_export = ExportService.export_object

    def slow_export(*args, **kwargs):
        time.sleep(0.05)
        return original_export(*args, **kwargs)

    monkeypatch.setattr(ExportService, "export_object", slow_export)
    manager = ExportJobManager(store, lambda _owner, _session_id: agent)
    job = manager.create(user, session.id, selections, session.title)
    manager.cancel(user["id"], job.job_id)
    deadline = time.monotonic() + 20
    while job.status not in {"cancelled", "failed"}:
        assert time.monotonic() < deadline
        time.sleep(0.02)

    assert job.status == "cancelled"
    assert job.zip_path == ""
    assert not list(Path(job.export_root).parent.glob("*.zip"))


def test_delete_uses_backend_data_and_invalidates_dependents(tmp_path):
    store, user, session, agent = _case(tmp_path)

    result = _delete_object(
        store, user, session.id, agent, "seed:seed_1",
    )
    assert result["invalidated"] == ["dose", "dvh", "report"]
    assert agent.memory.retrieve("manual_seeds") == []
    assert agent.memory.retrieve("manual_plan_active") is True

    skin_result = _delete_object(
        store, user, session.id, agent, "skin_surface:guide",
    )
    assert skin_result["invalidated"] == ["skin_surface", "report"]
    assert agent.memory.retrieve("skin_surface") is None
    assert agent.memory.retrieve("skin_surface_mask") is None

    pdf_result = _delete_object(
        store, user, session.id, agent, "report:pdf",
    )
    assert pdf_result["invalidated"] == ["report_pdf"]
    report_root = (
        store.workspace_root(user["id"], session.id)
        / "artifacts" / "reports"
    )
    assert not list(report_root.glob("*.pdf"))

    screenshot_result = _delete_object(
        store, user, session.id, agent, "screenshot:dose.png",
    )
    assert "screenshot" in screenshot_result["invalidated"]
    assert not (
        store.workspace_root(user["id"], session.id) / "screenshots" / "dose.png"
    ).exists()

    figure_result = _delete_object(
        store, user, session.id, agent, "figure:figure.png",
    )
    assert "report" in figure_result["invalidated"]
    snapshot = store.load_snapshot(user["id"], session.id)
    assert snapshot["report"]["form"]["figures"] == []


def test_frontend_exposes_three_export_levels_and_real_mutations():
    root = Path(__file__).resolve().parents[1]
    viewer = (
        root / "web" / "app" / "static" / "js" / "brachybot-viewer-volume.js"
    ).read_text(encoding="utf-8")
    scene_export = (
        root / "web" / "app" / "static" / "js" / "brachybot-data-export.js"
    ).read_text(encoding="utf-8")
    data_routes = (
        root / "web" / "routes" / "data_routes.py"
    ).read_text(encoding="utf-8")

    assert "moveSelectedStructures('ctv')" in viewer
    assert "moveSelectedStructures('oar')" in viewer
    assert "/data/objects/batch-delete" in viewer
    assert "exportSelectedDataTreeItems" in viewer
    assert "exportDataTreeGroup" in viewer
    assert "hydrateDataTreeArtifactCatalog" in viewer
    assert "openSessionExportDialog" in scene_export
    assert "showDirectoryPicker" in scene_export
    assert "Structured ZIP" in scene_export
    assert "data-export-progress" in scene_export
    assert "data-export-disclosure" in scene_export
    assert "collapsedGroups" in scene_export
    assert "job.status === 'cancelled'" in scene_export
    assert "no download was created" in scene_export
    assert "mark_report_stale(" in data_routes
