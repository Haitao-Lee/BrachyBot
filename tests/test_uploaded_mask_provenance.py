"""Regression tests for user-supplied CTV/OAR mask provenance."""

import numpy as np
import SimpleITK as sitk

from tool_factory.CTV_seg import CTVSegmentationTool
from tool_factory.OAR_seg import OARSegmentationTool
from web.server_support import _oar_display_name_map


class _Memory:
    def __init__(self, values):
        self.values = values

    def retrieve(self, key, default=None):
        return self.values.get(key, default)


class _Agent:
    def __init__(self, values):
        self.memory = _Memory(values)

    def _get_label_array(self, key):
        return self.memory.retrieve(key)


def _write_case(tmp_path):
    image = sitk.GetImageFromArray(np.zeros((6, 8, 10), dtype=np.int16))
    image.SetSpacing((0.7, 0.8, 1.5))
    image.SetOrigin((10.0, -20.0, 30.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
    ct_path = tmp_path / "ct.nii.gz"
    sitk.WriteImage(image, str(ct_path))

    ctv = np.zeros((6, 8, 10), dtype=np.uint8)
    ctv[2:4, 3:6, 4:7] = 1
    ctv_img = sitk.GetImageFromArray(ctv)
    ctv_img.CopyInformation(image)
    ctv_path = tmp_path / "uploaded_ctv.nii.gz"
    sitk.WriteImage(ctv_img, str(ctv_path))

    # Deliberately use labels that have no anatomical meaning. They must not
    # be interpreted as TotalSegmentator IDs 1 and 7.
    oar = np.zeros((6, 8, 10), dtype=np.uint8)
    oar[1:3, 1:3, 1:3] = 1
    oar[3:5, 5:7, 6:8] = 7
    oar_img = sitk.GetImageFromArray(oar)
    oar_img.CopyInformation(image)
    oar_path = tmp_path / "uploaded_oar.nii.gz"
    sitk.WriteImage(oar_img, str(oar_path))
    return str(ct_path), str(ctv_path), str(oar_path)


def test_uploaded_oar_uses_numbered_names_and_provenance(tmp_path):
    ct_path, _, oar_path = _write_case(tmp_path)
    result = OARSegmentationTool()._execute(image_path=ct_path, label_path=oar_path)

    assert result.success
    # The metadata mask must be the aligned uploaded OAR image, not the CT
    # reference image used during physical-grid alignment.
    assert sitk.GetArrayFromImage(result.metadata["oar_mask"]).max() == 7
    assert result.metadata["oar_source"] == "uploaded_unknown"
    assert result.metadata["oar_mask_provenance"] == "uploaded_unknown"
    assert result.metadata["organ_names"] == {1: "OAR 1", 7: "OAR 2"}

    agent = _Agent({
        "oar_source": "uploaded_unknown",
        "organ_names": result.metadata["organ_names"],
        "oar_array": result.metadata["oar_array"],
    })
    assert _oar_display_name_map(agent) == {1: "OAR 1", 7: "OAR 2"}


def test_uploaded_ctv_uses_selected_tumor_type(tmp_path):
    ct_path, ctv_path, _ = _write_case(tmp_path)
    result = CTVSegmentationTool()._execute(
        image_path=ct_path,
        label_path=ctv_path,
        tumor_type="nnunet_pancreatic",
    )

    assert result.success
    assert result.metadata["ctv_source"] == "manual_label"
    assert result.metadata["label_map"][1] == "pancreatic tumor"


def test_uploaded_multilabel_ctv_selects_only_requested_target(tmp_path):
    ct_path, _, _ = _write_case(tmp_path)
    reference = sitk.ReadImage(ct_path)
    labels = np.zeros((6, 8, 10), dtype=np.uint8)
    labels[:, 1:7, 1:9] = 1  # large body/organ contour
    labels[2:4, 3:6, 4:7] = 2  # actual target selected in the UI
    label_image = sitk.GetImageFromArray(labels)
    label_image.CopyInformation(reference)
    label_path = tmp_path / "multilabel_ctv.nii.gz"
    sitk.WriteImage(label_image, str(label_path))

    result = CTVSegmentationTool()._execute(
        image_path=ct_path,
        label_path=str(label_path),
        tumor_type="nnunet_pancreatic",
        target_value=2,
    )

    assert result.success
    assert set(np.unique(result.metadata["ctv_array"]).tolist()) == {0, 1}
    assert int(np.count_nonzero(result.metadata["ctv_array"])) == 2 * 3 * 3
    assert result.metadata["ctv_target_value"] == 2
    assert result.metadata["ctv_requested_target_value"] == 2
    assert result.metadata["ctv_source_labels"] == [1, 2]
    assert result.metadata["ctv_source_label_counts"][2] == 2 * 3 * 3
    assert result.metadata["ctv_normalized_binary"] is True
    assert result.metadata["label_map"] == {1: "pancreatic tumor"}


def test_uploaded_multilabel_ctv_rejects_absent_requested_target(tmp_path):
    ct_path, _, _ = _write_case(tmp_path)
    reference = sitk.ReadImage(ct_path)
    labels = np.zeros((6, 8, 10), dtype=np.uint8)
    labels[1:3, 1:3, 1:3] = 1
    labels[3:5, 5:7, 6:8] = 2
    label_image = sitk.GetImageFromArray(labels)
    label_image.CopyInformation(reference)
    label_path = tmp_path / "missing_target_ctv.nii.gz"
    sitk.WriteImage(label_image, str(label_path))

    result = CTVSegmentationTool()._execute(
        image_path=ct_path,
        label_path=str(label_path),
        target_value=3,
    )

    assert not result.success
    assert result.metadata["code"] == "invalid_ctv_target_label"
    assert "available positive labels are 1, 2" in result.error


def test_unknown_oar_source_never_falls_back_to_anatomy_mapping(tmp_path):
    _, _, oar_path = _write_case(tmp_path)
    result = OARSegmentationTool()._execute(label_path=oar_path)
    # The helper must keep the numbered namespace even for labels that match
    # known TotalSegmentator IDs.
    agent = _Agent({
        "oar_source": "uploaded_unknown",
        "organ_names": {},
        "oar_array": result.metadata["oar_array"],
    })
    assert _oar_display_name_map(agent) == {1: "OAR 1", 7: "OAR 2"}


def test_uploaded_oar_ignores_stale_anatomy_names(tmp_path):
    """A replaced opaque mask must not inherit names from the old case/run."""
    _, _, oar_path = _write_case(tmp_path)
    result = OARSegmentationTool()._execute(label_path=oar_path)
    agent = _Agent({
        "oar_source": "uploaded_unknown",
        "organ_names": {1: "stomach", 7: "vertebrae_L1"},
        "oar_array": result.metadata["oar_array"],
    })
    assert _oar_display_name_map(agent) == {1: "OAR 1", 7: "OAR 2"}


def test_uploaded_oar_control_plane_uses_numeric_labels(tmp_path):
    """The upload response must expose stable Data Tree rows for each label."""
    ct_path, _, oar_path = _write_case(tmp_path)
    result = OARSegmentationTool()._execute(image_path=ct_path, label_path=oar_path)
    names = {str(key): value for key, value in result.metadata["organ_names"].items()}
    counts = {str(key): value for key, value in result.metadata["organ_counts"].items()}

    rows = {
        label_id: {
            "name": names[label_id],
            "voxel_count": int(counts[label_id]),
        }
        for label_id in names
    }
    assert set(rows) == {"1", "7"}
    assert rows["1"]["name"] == "OAR 1"
    assert rows["7"]["name"] == "OAR 2"
    assert all(row["voxel_count"] > 0 for row in rows.values())


def test_oar_module_star_import_only_exports_registered_symbols():
    """The public OAR namespace must not expose removed legacy VoCo classes."""
    namespace = {}
    exec("from tool_factory.OAR_seg import *", namespace)
    assert "OARSegmentationTool" in namespace
    assert "VoCoTotalSegmentatorTool" not in namespace
    assert "VoCoAortaVesselTool" not in namespace


def test_all_oar_3d_request_routes_to_group_reconstruction():
    from AgenticSys import BrachyAgent

    class Memory:
        def retrieve(self, key, default=None):
            return "/tmp/case.nii.gz" if key == "ct_path" else default

        def get_ui_state(self):
            return {}

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    calls = agent._detect_tool_request("请对所有OAR mask进行3D 重建")

    assert calls == [{
        "id": "tool_ui_reconstruct_all_oar",
        "tool": "ui_controller",
        "params": {
            "actions": [{
                "target": "tree.group.reconstruct3d",
                "command": "run",
                "value": "oar",
            }]
        },
    }]


def test_ctv_auxiliary_labels_are_read_from_the_separate_snapshot_collection():
    """A user-selected CTV hard label remains part of the obstacle whitelist."""
    from tool_factory.seed_plan.planning_pipeline import _resolve_data_tree_obstacle_labels

    class Memory:
        def retrieve(self, key, default=None):
            return default

        def get_ui_state(self):
            return {
                "data_tree": {
                    "organs": [],
                    "ctv_labels": [{
                        "id": "ctv_9",
                        "label_id": 9,
                        "source": "ctv",
                        "category": "non_traversable",
                    }],
                }
            }

    agent = object.__new__(_Agent)
    agent.memory = Memory()
    labels, source = _resolve_data_tree_obstacle_labels(agent)

    assert 9 in labels
    assert source == "data_tree_plus_default"
