import base64
import io
import json
import zipfile
import numpy as np
import pytest
import SimpleITK as sitk
from brachycohort.core import Blocked, atomic_json
from brachycohort.observer import decode, physical_target_equal, terminal_task
from brachycohort.runner import endpoint
from brachycohort.verify import archive_manifest, geometry, pdf, unzip_verified, verify_archive, dose_field


@pytest.mark.parametrize("rows", [[], [{"id": "x", "pos": [1, 2, float("nan")]}],
    [{"id": "x", "pos": [1, 2]}], [{"pos": [1, 2, 3]}],
    [{"id": "x", "pos": [1, 2, 3]}, {"id": "x", "pos": [4, 5, 6]}]])
def test_geometry_negative_controls(rows):
    assert geometry(rows, ["pos"])["status"] == "FAIL"


def test_empty_checklist_not_success():
    assert endpoint({}) == "UNKNOWN"
    assert endpoint({"target": {"status": "FAIL"}}) == "FAIL"


def test_real_bytes_required(tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"%PDF-1.4 fake %%EOF")
    assert pdf(p)["status"] != "PASS"
    atomic_json(tmp_path / "metric.json", {"dose": 42})
    entries = archive_manifest(tmp_path)
    assert verify_archive(tmp_path, entries)["status"] == "PASS"
    (tmp_path / "metric.json").write_text("corrupt")
    assert verify_archive(tmp_path, entries)["status"] == "FAIL"


@pytest.mark.parametrize("name", ["../bad", "/absolute", "a/../../bad"])
def test_zip_traversal(tmp_path, name):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(name, "bad")
    with pytest.raises(Blocked):
        unzip_verified(p, tmp_path / "export")


def test_checkpoint_array_does_not_allow_pickle_or_escape(tmp_path):
    with pytest.raises(Blocked):
        decode({"$array": "../../escape.npy"}, tmp_path)
    with pytest.raises(Blocked):
        decode({"$ndarray_inline": "AA==", "dtype": "float64", "shape": [2]}, tmp_path)


def test_lossless_reorientation_not_interpolation():
    a = sitk.GetImageFromArray(np.array([[[0, 1, 0], [0, 0, 0]], [[0, 0, 1], [0, 0, 0]]], dtype=np.uint8))
    a.SetSpacing([1, 2, 3])
    b = sitk.DICOMOrient(a, "RAS")
    assert physical_target_equal(a, b)
    changed = sitk.GetImageFromArray(np.zeros((2, 2, 3), dtype=np.uint8))
    changed.CopyInformation(a)
    assert not physical_target_equal(a, changed)
    b.SetOrigin([100, 200, 300])
    assert not physical_target_equal(a, b)


@pytest.mark.parametrize("status", ["running", "finalizing", "idle", None])
def test_reply_or_idle_is_not_task_terminal(status):
    assert not terminal_task({"task": {"task_id": "t", "status": status}}, "t")
    assert not terminal_task({"task": {"task_id": "other", "status": "completed"}}, "t")


@pytest.mark.parametrize("value", [float("nan"), -1, 0])
def test_dose_invalid(tmp_path, value):
    ct = sitk.GetImageFromArray(np.ones((3, 3, 3), dtype=np.float32))
    d = sitk.GetImageFromArray(np.full((3, 3, 3), value, dtype=np.float32))
    sitk.WriteImage(ct, str(tmp_path / "ct.nii.gz"))
    sitk.WriteImage(d, str(tmp_path / "dose.nii.gz"))
    assert dose_field(tmp_path / "dose.nii.gz", tmp_path / "ct.nii.gz")["status"] == "FAIL"
