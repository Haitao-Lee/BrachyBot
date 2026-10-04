import copy
import numpy as np
import pytest
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
from pydicom.pixels import pack_bits
import SimpleITK as sitk

from brachycohort.core import Blocked, sha256
from brachycohort.dicom import read_series, convert, approved_conversion
from brachycohort.preflight import preflight


def dataset(path, sop, frame, series):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = sop
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.FrameOfReferenceUID = frame
    ds.SeriesInstanceUID = series
    ds.StudyInstanceUID = generate_uid()
    ds.PatientName = "Synthetic^Test"
    ds.PatientID = "test-only"
    ds.Rows, ds.Columns = 3, 4
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    return ds


def series(folder, modality, frame):
    folder.mkdir()
    uid = generate_uid()
    for i in range(3):
        path = folder / (str(i) + ".dcm")
        sop = CTImageStorage if modality == "CT" else "1.2.840.10008.5.1.4.1.1.128"
        ds = dataset(path, sop, frame, uid)
        ds.Modality = modality
        ds.ImagePositionPatient = [0, 0, i * 2]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing = [1, 1]
        ds.SliceThickness = 2
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.RescaleIntercept, ds.RescaleSlope = 0, 1
        ds.InstanceNumber = i + 1
        ds.PixelData = np.ones((3, 4), dtype=np.uint16).tobytes()
        ds.save_as(path, enforce_file_format=True)
    return uid


@pytest.fixture
def dicom_row(storage):
    frame = generate_uid()
    ct, pet = storage.source / "ct", storage.source / "pet"
    series(ct, "CT", frame)
    pet_uid = series(pet, "PT", frame)
    path = storage.source / "seg.dcm"
    seg = dataset(path, "1.2.840.10008.5.1.4.1.1.66.4", frame, generate_uid())
    seg.Modality = "SEG"
    seg.SegmentationType = "BINARY"
    seg.BitsAllocated = seg.BitsStored = 1
    seg.HighBit = seg.PixelRepresentation = 0
    seg.NumberOfFrames = 2
    desc = Dataset()
    desc.SegmentNumber, desc.SegmentLabel = 1, "Synthetic tumor"
    seg.SegmentSequence = [desc]
    ref = Dataset()
    ref.SeriesInstanceUID = pet_uid
    seg.ReferencedSeriesSequence = [ref]
    fg = []
    for z in (0, 2):
        group = Dataset()
        ident, position, orientation, measure = Dataset(), Dataset(), Dataset(), Dataset()
        ident.ReferencedSegmentNumber = 1
        position.ImagePositionPatient = [0, 0, z]
        orientation.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        measure.PixelSpacing = [1, 1]
        measure.SliceThickness = 2
        group.SegmentIdentificationSequence = [ident]
        group.PlanePositionSequence = [position]
        group.PlaneOrientationSequence = [orientation]
        group.PixelMeasuresSequence = [measure]
        fg.append(group)
    seg.PerFrameFunctionalGroupsSequence = fg
    a = np.zeros((2, 3, 4), dtype=np.uint8)
    a[:, 1, 1] = 1
    seg.PixelData = pack_bits(a, pad=True)
    seg.save_as(path, enforce_file_format=True)
    return {"row_id": "dicom-test", "dataset": "synthetic", "image_modality": "CT_DICOM", "target_values": [1],
            "ct_path": str(ct), "pet_series_path": str(pet), "label_path": str(path), "target_semantics": "research tumor"}


def approval(receipt, storage):
    path = next(storage.path("derived").glob("dicom-*/conversion.json"))
    return {"status": "APPROVED_RESEARCH", "reviewer": "synthetic", "reviewed_at": "test",
            "conversion_path": str(path), "conversion_sha256": sha256(path),
            "checks": {k: "PASS" for k in ("registration_same_frame", "target_site_and_components", "resampling_volume_change")}}


def test_native_ct_conversion_and_reviewed_preflight(storage, dicom_row):
    r = convert(dicom_row, storage)
    assert r["preflight_status"] == "CONVERTED_NOT_APPROVED"
    assert preflight(dicom_row, storage, {})["preflight_status"] == "BLOCKED"
    review = approval(r, storage)
    resolved = preflight(dicom_row, storage, {}, review)
    assert resolved["preflight_status"] == "PASS", resolved
    assert resolved["target_voxels"] == 2
    assert "pet" in resolved["source_hashes"]
    review["checks"]["registration_same_frame"] = "UNKNOWN"
    assert preflight(dicom_row, storage, {}, review)["preflight_status"] == "BLOCKED"


@pytest.mark.parametrize("variant", ["frame", "references", "fractional", "duplicate_frame", "orientation", "position", "no_segment"])
def test_seg_negative_controls(storage, dicom_row, variant):
    p = dicom_row["label_path"]
    seg = pydicom.dcmread(p)
    if variant == "frame":
        seg.FrameOfReferenceUID = generate_uid()
    elif variant == "references":
        seg.ReferencedSeriesSequence[0].SeriesInstanceUID = generate_uid()
    elif variant == "fractional":
        seg.SegmentationType = "FRACTIONAL"
    elif variant == "duplicate_frame":
        seg.PerFrameFunctionalGroupsSequence[1].PlanePositionSequence[0].ImagePositionPatient = [0, 0, 0]
    elif variant == "orientation":
        seg.PerFrameFunctionalGroupsSequence[0].PlaneOrientationSequence[0].ImageOrientationPatient = [0, 1, 0, 1, 0, 0]
    elif variant == "position":
        seg.PerFrameFunctionalGroupsSequence[0].PlanePositionSequence[0].ImagePositionPatient = [0, 0, 1]
    else:
        dicom_row["target_values"] = [2]
    seg.save_as(p, enforce_file_format=True)
    with pytest.raises(Blocked):
        convert(dicom_row, storage)


@pytest.mark.parametrize("change", ["duplicate", "gap", "inplane_drift", "pixel_spacing", "frame"])
def test_series_geometry_rejected(storage, dicom_row, change):
    p = storage.source / "ct/1.dcm"
    ds = pydicom.dcmread(p)
    if change == "duplicate":
        ds.ImagePositionPatient = [0, 0, 0]
    elif change == "gap":
        ds.ImagePositionPatient = [0, 0, 1]
    elif change == "inplane_drift":
        ds.ImagePositionPatient = [1, 0, 2]
    elif change == "pixel_spacing":
        ds.PixelSpacing = [2, 1]
    else:
        ds.FrameOfReferenceUID = generate_uid()
    ds.save_as(p, enforce_file_format=True)
    with pytest.raises(Blocked):
        read_series(storage.source / "ct", "CT")
