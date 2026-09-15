"""Format-independence contracts for CT and mask inputs.

Every supported container (NIfTI/.nii.gz, MetaImage/.mha, NRRD, DICOM series)
must resolve to the same physical volume on the planning grid. The pipeline
under test mirrors the server routes:

    CT:   load -> normalize_ct_image -> DICOMOrient(LPI) -> array
    mask: align_label_to_reference(path, ct_image, "LPI")
"""

import os

import numpy as np
import pytest
import SimpleITK as sitk

from tool_factory.segmentation_alignment import align_label_to_reference
from utils.ct_volume import normalize_ct_image


SIZE_XYZ = (6, 5, 4)
SPACING_XYZ = (0.7, 0.8, 5.0)
ORIGIN_XYZ = (10.0, 20.0, 30.0)
# 90-degree rotation about Z: proves DICOMOrient really permutes axes.
DIRECTION = (0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _ct_image():
    hu = np.zeros((SIZE_XYZ[2], SIZE_XYZ[1], SIZE_XYZ[0]), dtype=np.int16)
    for k in range(SIZE_XYZ[2]):
        for j in range(SIZE_XYZ[1]):
            for i in range(SIZE_XYZ[0]):
                hu[k, j, i] = (i + 1) * 100 + (j + 1) * 10 + (k + 1) - 2000
    image = sitk.GetImageFromArray(hu)
    image.SetSpacing(SPACING_XYZ)
    image.SetOrigin(ORIGIN_XYZ)
    image.SetDirection(DIRECTION)
    return image


def _lpi_result(path_or_dir):
    if os.path.isdir(path_or_dir):
        reader = sitk.ImageSeriesReader()
        reader.SetOutputPixelType(sitk.sitkFloat32)
        series_ids = reader.GetGDCMSeriesIDs(path_or_dir) or []
        assert series_ids, "DICOM series writer produced an unreadable directory"
        reader.SetFileNames(reader.GetGDCMSeriesFileNames(path_or_dir, series_ids[0]))
        image = reader.Execute()
    else:
        image = sitk.ReadImage(path_or_dir)
    image, _meta = normalize_ct_image(image)
    oriented = sitk.DICOMOrient(image, "LPI")
    return {
        "array": sitk.GetArrayFromImage(oriented),
        "spacing": tuple(round(float(v), 6) for v in oriented.GetSpacing()),
        "origin": tuple(round(float(v), 6) for v in oriented.GetOrigin()),
        "direction": tuple(round(float(v), 6) for v in oriented.GetDirection()),
    }


def _write_dicom_series(directory, image, *, rescale_intercept=-1024):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

    array = sitk.GetArrayFromImage(image)  # Z, Y, X
    matrix = np.array(image.GetDirection()).reshape(3, 3)
    x_axis, y_axis, z_axis = matrix[:, 0], matrix[:, 1], matrix[:, 2]
    study_uid, series_uid = generate_uid(), generate_uid()
    for k in range(array.shape[0]):
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = CTImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        path = os.path.join(directory, f"IM{k:03d}.dcm")
        dataset = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
        dataset.SOPClassUID = CTImageStorage
        dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        dataset.StudyInstanceUID = study_uid
        dataset.SeriesInstanceUID = series_uid
        dataset.Modality = "CT"
        dataset.PatientName = "Format^Equivalence"
        dataset.PatientID = "FMTEQ"
        dataset.SeriesNumber = 1
        dataset.InstanceNumber = k + 1
        dataset.Rows = array.shape[1]
        dataset.Columns = array.shape[2]
        dataset.PixelSpacing = [float(SPACING_XYZ[1]), float(SPACING_XYZ[0])]
        dataset.SliceThickness = float(SPACING_XYZ[2])
        dataset.SpacingBetweenSlices = float(SPACING_XYZ[2])
        dataset.ImageOrientationPatient = [
            float(v) for v in (list(x_axis) + list(y_axis))
        ]
        position = np.array(ORIGIN_XYZ) + k * SPACING_XYZ[2] * z_axis
        dataset.ImagePositionPatient = [float(v) for v in position]
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.BitsAllocated = 16
        dataset.BitsStored = 16
        dataset.HighBit = 15
        dataset.PixelRepresentation = 1
        dataset.RescaleSlope = 1.0
        dataset.RescaleIntercept = float(rescale_intercept)
        raw = (array[k].astype(np.int32) - rescale_intercept).astype("<i2")
        dataset.PixelData = raw.tobytes()
        try:
            dataset.save_as(path, enforce_file_format=True)  # pydicom 3.x
        except TypeError:
            dataset.save_as(path, write_like_original=False)  # pydicom 2.x


def test_ct_volume_formats_match_nifti(tmp_path):
    image = _ct_image()
    reference_path = tmp_path / "ct.nii.gz"
    sitk.WriteImage(image, str(reference_path))
    reference = _lpi_result(str(reference_path))

    candidates = {}
    for extension in (".mha", ".nrrd"):
        path = tmp_path / f"ct{extension}"
        sitk.WriteImage(image, str(path))
        candidates[extension] = str(path)

    dicom_dir = tmp_path / "dicom-series"
    dicom_dir.mkdir()
    _write_dicom_series(str(dicom_dir), image)
    candidates["DICOM series"] = str(dicom_dir)

    for name, path in candidates.items():
        result = _lpi_result(path)
        assert result["spacing"] == reference["spacing"], name
        assert result["origin"] == reference["origin"], name
        assert result["direction"] == reference["direction"], name
        assert np.array_equal(
            np.asarray(result["array"]).astype(np.int32),
            np.asarray(reference["array"]).astype(np.int32),
        ), f"{name} produced a different voxel array than NIfTI"


def test_mask_formats_align_exactly_to_ct_grid(tmp_path):
    ct = _ct_image()
    label = sitk.GetImageFromArray(
        np.pad(
            np.ones((3, 2, 2), dtype=np.uint8),
            ((1, 0), (1, 2), (2, 2)),
        )
    )
    label.CopyInformation(ct)
    expected = sitk.GetArrayFromImage(sitk.DICOMOrient(label, "LPI"))

    paths = []
    for extension in (".nii.gz", ".mha", ".nrrd"):
        path = tmp_path / f"mask{extension}"
        sitk.WriteImage(label, str(path))
        paths.append(str(path))

    # The same physical mask stored in a different anatomical frame must be
    # re-oriented back onto the CT grid without mirroring or translation.
    rotated = sitk.DICOMOrient(label, "PIL")
    rotated_path = tmp_path / "mask_rotated.nii.gz"
    sitk.WriteImage(rotated, str(rotated_path))
    paths.append(str(rotated_path))

    for path in paths:
        aligned = align_label_to_reference(path, ct, "LPI")
        assert np.array_equal(sitk.GetArrayFromImage(aligned), expected), path
