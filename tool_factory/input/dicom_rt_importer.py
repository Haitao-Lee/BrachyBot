"""Read-only DICOM-RT metadata importer.

The importer intentionally returns contours and dose-grid metadata instead of
silently rasterising a structure onto a CT grid.  Rasterisation needs an
explicit frame-of-reference and registration decision; hiding that decision
would make a clinically unsafe import look like a native mask.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np


def _require_pydicom():
    try:
        import pydicom
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError("pydicom is required for DICOM-RT import") from exc
    return pydicom


def _uid(value: Any) -> str:
    return str(value or "").strip()


def _read_rtstruct(dataset: Any) -> Dict[str, Any]:
    names = {
        _uid(item.ROINumber): str(item.ROIName or f"ROI_{item.ROINumber}")
        for item in getattr(dataset, "StructureSetROISequence", [])
    }
    structures: List[Dict[str, Any]] = []
    for roi in getattr(dataset, "ROIContourSequence", []):
        number = _uid(getattr(roi, "ReferencedROINumber", ""))
        contours = []
        for contour in getattr(roi, "ContourSequence", []):
            values = np.asarray(getattr(contour, "ContourData", []), dtype=float)
            if values.size < 9 or values.size % 3:
                continue
            contours.append({
                "geometric_type": str(getattr(contour, "ContourGeometricType", "")),
                "number_of_points": int(values.size // 3),
                "points_lps_mm": values.reshape(-1, 3).tolist(),
            })
        structures.append({
            "roi_number": number,
            "name": names.get(number, f"ROI_{number or 'unknown'}"),
            "display_color": list(getattr(roi, "ROIDisplayColor", []) or []),
            "contours": contours,
        })
    return {
        "modality": "RTSTRUCT",
        "frame_of_reference_uid": _uid(getattr(dataset, "FrameOfReferenceUID", "")),
        "structure_set_instance_uid": _uid(getattr(dataset, "SOPInstanceUID", "")),
        "structures": structures,
        "rasterization_required": True,
    }


def _read_rtdose(dataset: Any) -> Dict[str, Any]:
    pixels = np.asarray(dataset.pixel_array)
    scaling = float(getattr(dataset, "DoseGridScaling", 1.0) or 1.0)
    if scaling <= 0 or not np.isfinite(scaling):
        raise ValueError("RTDOSE DoseGridScaling must be positive and finite")
    dose_gy = pixels.astype(np.float32) * scaling
    return {
        "modality": "RTDOSE",
        "sop_instance_uid": _uid(getattr(dataset, "SOPInstanceUID", "")),
        "frame_of_reference_uid": _uid(getattr(dataset, "FrameOfReferenceUID", "")),
        "dose_units": str(getattr(dataset, "DoseUnits", "")),
        "dose_grid_scaling": scaling,
        "dose_shape_zyx": list(dose_gy.shape),
        "dose_min": float(np.min(dose_gy)) if dose_gy.size else 0.0,
        "dose_max": float(np.max(dose_gy)) if dose_gy.size else 0.0,
        "grid": {
            "rows": int(getattr(dataset, "Rows", 0) or 0),
            "columns": int(getattr(dataset, "Columns", 0) or 0),
            "number_of_frames": int(getattr(dataset, "NumberOfFrames", 1) or 1),
            "pixel_spacing": [float(v) for v in (getattr(dataset, "PixelSpacing", []) or [])],
            "grid_frame_offset_vector": [float(v) for v in (getattr(dataset, "GridFrameOffsetVector", []) or [])],
            "image_position_patient": [float(v) for v in (getattr(dataset, "ImagePositionPatient", []) or [])],
        },
        # The route stores this in the case workspace as a non-clinical import
        # until the operator confirms frame registration and interpolation.
        "requires_registration_check": True,
    }


def import_dicom_rt(path: str | Path) -> Dict[str, Any]:
    """Parse RTSTRUCT or RTDOSE without mutating planning state."""
    pydicom = _require_pydicom()
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))
    dataset = pydicom.dcmread(str(file_path), force=False)
    modality = str(getattr(dataset, "Modality", "")).upper()
    if modality == "RTSTRUCT":
        result = _read_rtstruct(dataset)
    elif modality == "RTDOSE":
        result = _read_rtdose(dataset)
    else:
        raise ValueError(f"Unsupported DICOM-RT modality: {modality or 'unknown'}")
    result["path"] = str(file_path)
    result["patient_id"] = _uid(getattr(dataset, "PatientID", ""))
    return result
