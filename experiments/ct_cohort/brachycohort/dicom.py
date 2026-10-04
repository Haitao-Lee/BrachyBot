"""Strict native-CT/PET-referenced binary SEG conversion; no array-copy shortcut."""
from pathlib import Path
import numpy as np
import pydicom
import SimpleITK as sitk

from .core import Blocked, atomic_json, digest, sha256, source_digest, load_json
from .preflight import grid


def read_series(folder, modality):
    files = [p for p in Path(folder).iterdir() if p.is_file()]
    headers = [(p, pydicom.dcmread(p, stop_before_pixels=True)) for p in files if p.suffix.lower() in {".dcm", ""}]
    candidates = [(p, h) for p, h in headers if str(h.get("Modality")) == modality]
    if not candidates:
        raise Blocked("DICOM_MODALITY_MISSING", modality)
    uids = {str(h.SeriesInstanceUID) for _, h in candidates}
    if len(uids) != 1 or any(int(h.get("NumberOfFrames", 1)) != 1 for _, h in candidates):
        raise Blocked("AMBIGUOUS_OR_ENHANCED_DICOM_SERIES")
    first = candidates[0][1]
    orientation = np.array(first.ImageOrientationPatient, dtype=float)
    normal = np.cross(orientation[:3], orientation[3:])
    if not np.isfinite(orientation).all() or not np.isclose(np.linalg.norm(orientation[:3]), 1, atol=1e-4) or not np.isclose(np.linalg.norm(orientation[3:]), 1, atol=1e-4) or not np.isclose(np.dot(orientation[:3], orientation[3:]), 0, atol=1e-4) or not np.isclose(np.linalg.norm(normal), 1, atol=1e-4):
        raise Blocked("INVALID_DICOM_ORIENTATION")
    candidates.sort(key=lambda ph: float(np.dot(np.array(ph[1].ImagePositionPatient, dtype=float), normal)))
    locations = np.array([np.dot(np.array(h.ImagePositionPatient, dtype=float), normal) for _, h in candidates])
    if len(candidates) < 2 or np.min(np.diff(locations)) <= 0 or not np.allclose(np.diff(locations), np.diff(locations)[0], atol=1e-4, rtol=0):
        raise Blocked("DICOM_SLICE_GAPS_OR_DUPLICATES")
    for _, h in candidates:
        if str(h.FrameOfReferenceUID) != str(first.FrameOfReferenceUID) or not np.allclose(h.ImageOrientationPatient, orientation, atol=1e-4, rtol=0):
            raise Blocked("DICOM_GRID_INCONSISTENT")
        if [int(h.Rows), int(h.Columns)] != [int(first.Rows), int(first.Columns)] or not np.allclose(h.PixelSpacing, first.PixelSpacing, atol=1e-4, rtol=0):
            raise Blocked("DICOM_INPLANE_GRID_INCONSISTENT")
    start = np.array(candidates[0][1].ImagePositionPatient, dtype=float)
    for _, h in candidates:
        delta = np.array(h.ImagePositionPatient, dtype=float) - start
        if not np.allclose(delta, normal * np.dot(delta, normal), atol=1e-4, rtol=0):
            raise Blocked("DICOM_GANTRY_TILT_OR_INPLANE_DRIFT")
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames([str(p) for p, _ in candidates])
    image = reader.Execute()
    if not np.isfinite(sitk.GetArrayFromImage(image)).all():
        raise Blocked("NONFINITE_DICOM_PIXELS")
    return image, candidates, first


def functional(ds, frame, sequence, attribute):
    for fg in (frame, ds.SharedFunctionalGroupsSequence[0] if ds.get("SharedFunctionalGroupsSequence") else None):
        if fg is not None and fg.get(sequence):
            item = getattr(fg, sequence)[0]
            if item.get(attribute) is not None:
                return getattr(item, attribute)
    raise Blocked("DICOM_SEG_GEOMETRY_MISSING", attribute)


def convert(row, storage):
    """Supports regular single-frame CT/PET and geometrically explicit binary SEG."""
    if not row.get("pet_series_path"):
        raise Blocked("DICOM_REFERENCE_UNRESOLVED")
    for key in ("ct_path", "pet_series_path", "label_path"):
        p = Path(row[key]).resolve()
        if storage.source not in p.parents:
            raise Blocked("DICOM_SOURCE_OUTSIDE_ROOT")
    storage.check()
    source_hashes = {"ct": source_digest(row["ct_path"]), "label": source_digest(row["label_path"]),
                     "pet": source_digest(row["pet_series_path"])}
    ct, ct_files, ct_head = read_series(row["ct_path"], "CT")
    pet, pet_files, pet_head = read_series(row["pet_series_path"], "PT")
    seg_path = Path(row["label_path"])
    seg = pydicom.dcmread(seg_path)
    if str(seg.get("Modality")) != "SEG" or seg.get("SegmentationType") != "BINARY":
        raise Blocked("UNSUPPORTED_SEG_ENCODING")
    frame_uid = str(ct_head.FrameOfReferenceUID)
    if frame_uid != str(pet_head.FrameOfReferenceUID) or frame_uid != str(seg.get("FrameOfReferenceUID")):
        raise Blocked("DICOM_FRAME_OF_REFERENCE_MISMATCH")
    declared = {int(s.SegmentNumber) for s in seg.SegmentSequence}
    values = set(row.get("target_values", []))
    if not values or not values <= declared:
        raise Blocked("DICOM_SEGMENT_SELECTION_UNRESOLVED")
    refs = {str(s.SeriesInstanceUID) for s in seg.get("ReferencedSeriesSequence", [])}
    if refs != {str(pet_head.SeriesInstanceUID)}:
        raise Blocked("DICOM_SEG_NOT_EXCLUSIVELY_PET_REFERENCED")
    frames = seg.pixel_array
    if frames.ndim == 2:
        frames = frames[None]
    groups = seg.get("PerFrameFunctionalGroupsSequence", [])
    if len(groups) != len(frames):
        raise Blocked("DICOM_SEG_FRAME_COUNT_MISMATCH")
    mask = np.zeros(tuple(reversed(pet.GetSize())), dtype=np.uint8)
    seen, selected_frames = set(), 0
    pet_orientation = np.array(pet_head.ImageOrientationPatient, dtype=float)
    for pixels, fg in zip(frames, groups):
        number = int(fg.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
        if number not in values:
            continue
        position = np.array(functional(seg, fg, "PlanePositionSequence", "ImagePositionPatient"), dtype=float)
        orientation = np.array(functional(seg, fg, "PlaneOrientationSequence", "ImageOrientationPatient"), dtype=float)
        pixel_spacing = np.array(functional(seg, fg, "PixelMeasuresSequence", "PixelSpacing"), dtype=float)
        if pixels.shape != mask.shape[1:] or not np.allclose(orientation, pet_orientation, atol=1e-4, rtol=0) or not np.allclose(pixel_spacing, pet_head.PixelSpacing, atol=1e-4, rtol=0):
            raise Blocked("SEG_PET_GRID_MISMATCH")
        index = np.array(pet.TransformPhysicalPointToContinuousIndex(position.tolist()))
        rounded = np.rint(index).astype(int)
        if not np.allclose(index, rounded, atol=1e-4, rtol=0) or tuple(rounded[:2]) != (0, 0) or not 0 <= rounded[2] < mask.shape[0]:
            raise Blocked("SEG_FRAME_POSITION_MISMATCH")
        if (number, int(rounded[2])) in seen:
            raise Blocked("DUPLICATE_SEG_FRAME")
        seen.add((number, int(rounded[2])))
        if not np.isin(pixels, [0, 1]).all():
            raise Blocked("SEG_NOT_BINARY")
        mask[rounded[2]] |= pixels.astype(np.uint8)
        selected_frames += 1
    if not selected_frames or not np.any(mask):
        raise Blocked("EMPTY_SELECTED_SEGMENT")
    native_seg = sitk.GetImageFromArray(mask)
    native_seg.CopyInformation(pet)
    target = sitk.Resample(native_seg, ct, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    ct_target = sitk.GetArrayFromImage(target)
    if not np.any(ct_target):
        raise Blocked("TARGET_OUTSIDE_CT_FIELD")
    inputs = {"ct_slices": [{"path": str(p), "sha256": sha256(p)} for p, _ in ct_files],
              "pet_slices": [{"path": str(p), "sha256": sha256(p)} for p, _ in pet_files],
              "seg": {"path": str(seg_path), "sha256": sha256(seg_path)}}
    root = storage.path("derived/dicom-" + digest([row["row_id"], inputs]))
    root.mkdir(parents=True, exist_ok=True)
    ct_path, mask_path = root / "ct-native.nii.gz", root / "target-on-ct.nii.gz"
    sitk.WriteImage(ct, str(ct_path), True)
    sitk.WriteImage(target, str(mask_path), True)
    source_volume = int(mask.sum()) * np.prod(pet.GetSpacing()) / 1000
    target_volume = int(ct_target.sum()) * np.prod(ct.GetSpacing()) / 1000
    receipt = {"row_id": row["row_id"], "input_hashes": inputs, "native_ct_grid": grid(ct), "referenced_pet_grid": grid(pet),
               "source_hashes": source_hashes,
               "method": "identity_same_frame_LPS_nearest_neighbor_PET_SEG_to_native_CT",
               "source_volume_cm3": float(source_volume), "target_volume_cm3": float(target_volume),
               "relative_volume_change": float(target_volume / source_volume - 1), "selected_segments": sorted(values),
               "derived_ct_path": str(ct_path), "derived_label_path": str(mask_path),
               "derived_ct_sha256": sha256(ct_path), "derived_label_sha256": sha256(mask_path),
               "registration_review": "REQUIRED", "target_site_component_policy": "REQUIRED",
               "preflight_status": "CONVERTED_NOT_APPROVED"}
    if source_hashes != {"ct": source_digest(row["ct_path"]), "label": source_digest(row["label_path"]),
                         "pet": source_digest(row["pet_series_path"])}:
        raise Blocked("DICOM_SOURCE_CHANGED_DURING_CONVERSION")
    atomic_json(root / "conversion.json", receipt)
    return receipt


def approved_conversion(row, storage, approval):
    if approval.get("status") != "APPROVED_RESEARCH" or not approval.get("reviewer") or not approval.get("reviewed_at"):
        raise Blocked("DICOM_CONVERSION_REVIEW_REQUIRED")
    path = Path(approval.get("conversion_path", "")).resolve()
    if storage.base not in path.parents or not path.is_file() or sha256(path) != approval.get("conversion_sha256"):
        raise Blocked("DICOM_CONVERSION_RECEIPT_MISMATCH")
    r = load_json(path)
    current = {"ct": source_digest(row["ct_path"]), "label": source_digest(row["label_path"]),
               "pet": source_digest(row["pet_series_path"])}
    if r.get("row_id") != row["row_id"] or r.get("source_hashes") != current or r.get("selected_segments") != sorted(row["target_values"]):
        raise Blocked("DICOM_SOURCE_OR_SEGMENT_CHANGED")
    for name in ("registration_same_frame", "target_site_and_components", "resampling_volume_change"):
        if approval.get("checks", {}).get(name) != "PASS":
            raise Blocked("DICOM_CONVERSION_REVIEW_INCOMPLETE", name)
    for key in ("derived_ct", "derived_label"):
        p = Path(r[key + "_path"]).resolve()
        if storage.base not in p.parents or sha256(p) != r[key + "_sha256"]:
            raise Blocked("DICOM_DERIVATIVE_CHANGED")
    return r
