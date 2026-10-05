"""Minimal linked DICOM-RT exporter for a BrachyBot planning workspace.

The exporter deliberately writes an unapproved RTSTRUCT/RTPLAN/RTDOSE set.
It validates that every mask and the dose grid use the current CT grid before
writing anything, and it never claims clinical approval or replaces a TPS.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence as TypingSequence, Tuple

import numpy as np

from tool_factory import BaseTool, ToolResult


def _require_pydicom():
    try:
        import pydicom
        from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
        from pydicom.sequence import Sequence
        from pydicom.uid import (
            ExplicitVRLittleEndian,
            RTDoseStorage,
            RTPlanStorage,
            RTStructureSetStorage,
            generate_uid,
        )
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError("pydicom is required for DICOM-RT export") from exc
    return {
        "pydicom": pydicom,
        "Dataset": Dataset,
        "FileDataset": FileDataset,
        "FileMetaDataset": FileMetaDataset,
        "Sequence": Sequence,
        "ExplicitVRLittleEndian": ExplicitVRLittleEndian,
        "RTDoseStorage": RTDoseStorage,
        "RTPlanStorage": RTPlanStorage,
        "RTStructureSetStorage": RTStructureSetStorage,
        "generate_uid": generate_uid,
    }


def _safe_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:64] or fallback


def _grid_shape(ct_image) -> Tuple[int, int, int]:
    return tuple(int(value) for value in reversed(ct_image.GetSize()))


def _normalize_seed(value: Any) -> Tuple[List[float], List[float]] | None:
    if isinstance(value, dict):
        position = value.get("position") or value.get("pos")
        direction = value.get("direction") or value.get("dir") or [0.0, 0.0, 1.0]
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        position, direction = value[0], value[1]
    else:
        return None
    try:
        pos = np.asarray(position, dtype=float).reshape(-1)[:3]
        direc = np.asarray(direction, dtype=float).reshape(-1)[:3]
        if pos.size != 3 or direc.size != 3 or not np.all(np.isfinite(pos)) or not np.all(np.isfinite(direc)):
            return None
        return pos.tolist(), direc.tolist()
    except Exception:
        return None


def _normalize_channels(seed_plan: Any = None, seeds: Any = None) -> List[List[Tuple[List[float], List[float]]]]:
    channels: List[List[Tuple[List[float], List[float]]]] = []
    if seed_plan:
        entries = seed_plan if isinstance(seed_plan, list) else [seed_plan]
        for entry in entries:
            raw_seeds = entry.get("seeds", []) if isinstance(entry, dict) else []
            normalized_seeds = [normalized for raw in raw_seeds if (normalized := _normalize_seed(raw))]
            if isinstance(entry, dict) and entry.get("trajectory") is None and len(normalized_seeds) > 1:
                # A trajectory-less legacy payload describes independent
                # channels. Real pipeline payloads carry a trajectory object
                # and remain grouped into one channel.
                channels.extend([[seed] for seed in normalized_seeds])
            elif normalized_seeds:
                channels.append(normalized_seeds)
    elif seeds:
        channel = [normalized for raw in seeds if (normalized := _normalize_seed(raw))]
        if channel:
            channels.append(channel)
    return channels


def _base_dataset(
    dicom: Dict[str, Any],
    sop_class_uid: str,
    sop_instance_uid: str,
    modality: str,
    study_uid: str,
    frame_uid: str,
    tags: Dict[str, Any],
):
    meta = dicom["FileMetaDataset"]()
    meta.FileMetaInformationVersion = b"\x00\x01"
    meta.MediaStorageSOPClassUID = sop_class_uid
    meta.MediaStorageSOPInstanceUID = sop_instance_uid
    meta.TransferSyntaxUID = dicom["ExplicitVRLittleEndian"]
    meta.ImplementationClassUID = dicom["generate_uid"]()
    ds = dicom["FileDataset"](None, {}, file_meta=meta, preamble=b"\x00" * 128)
    # The transfer syntax in File Meta is authoritative. Avoid assigning the
    # deprecated pydicom byte-order flags so this exporter remains compatible
    # with pydicom 3+ while retaining explicit-VR little-endian output.
    ds.SOPClassUID = sop_class_uid
    ds.SOPInstanceUID = sop_instance_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = dicom["generate_uid"]()
    ds.FrameOfReferenceUID = frame_uid
    ds.Modality = modality
    ds.PatientName = _safe_text(tags.get("patient_name"), "Anonymous")
    ds.PatientID = _safe_text(tags.get("patient_id"), "BrachyBotCase")
    ds.StudyID = _safe_text(tags.get("study_id"), "BrachyBot")
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.StudyDate = _dt.datetime.now().strftime("%Y%m%d")
    ds.StudyTime = _dt.datetime.now().strftime("%H%M%S")
    return ds


def _image_geometry(image) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.asarray(image.GetSpacing(), dtype=float),
        np.asarray(image.GetOrigin(), dtype=float),
        np.asarray(image.GetDirection(), dtype=float).reshape(3, 3),
    )


def _mask_contours(mask: np.ndarray, image) -> Iterable[List[float]]:
    """Preserve disconnected regions and holes at half-voxel boundaries.

    Padding closes masks touching the image edge. All rings in one ROI use
    CLOSEDPLANAR_XOR: a hole must not be exported as another filled organ.
    Bounding boxes are not contours and must never stand in for segmentation.
    """
    from skimage.measure import find_contours
    for z in range(mask.shape[0]):
        plane = np.pad(np.asarray(mask[z], dtype=np.uint8), 1)
        for ring in find_contours(plane, .5, fully_connected="high"):
            if len(ring) < 4 or not np.allclose(ring[0], ring[-1]):
                raise ValueError("Structure contour is not a closed polygon")
            points: List[float] = []
            for y, x in ring[:-1]:
                physical = image.TransformContinuousIndexToPhysicalPoint((float(x - 1), float(y - 1), float(z)))
                points.extend(float(value) for value in physical)
            yield points


class DicomRTExporterTool(BaseTool):
    @property
    def name(self) -> str:
        return "dicom_rt_exporter"

    @property
    def description(self) -> str:
        return "Export linked, unapproved DICOM RTSTRUCT, RTPLAN, and RTDOSE files on one planning grid."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["ct_image", "structures", "output_dir"],
            "properties": {
                "ct_image": {"type": "object"},
                "structures": {"type": "object"},
                "dose_array": {"type": "array"},
                "dose_units": {"type": "string", "enum": ["gy", "physical_gy", "normalized", "normalized_model", "normalized_model_output"]},
                "dose_scale_gy": {"type": "number", "exclusiveMinimum": 0},
                "seed_plan": {"type": "array"},
                "seeds": {"type": "array"},
                "output_dir": {"type": "string"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        dicom = _require_pydicom()
        ct_image = kwargs.get("ct_image")
        structures = kwargs.get("structures") or {}
        dose_array = kwargs.get("dose_array")
        output_dir = kwargs.get("output_dir")
        from utils.tool_security import output_directory, workspace_root
        if workspace_root() is not None:
            output_dir = str(output_directory("dicom_rt", "."))
        if ct_image is None or not hasattr(ct_image, "GetSize"):
            return ToolResult(success=False, error="ct_image must be a SimpleITK image")
        if not isinstance(structures, dict) or not structures:
            return ToolResult(success=False, error="At least one structure mask is required")
        if not output_dir:
            return ToolResult(success=False, error="output_dir is required")

        shape = _grid_shape(ct_image)
        normalized_structures: Dict[str, np.ndarray] = {}
        for name, raw_mask in structures.items():
            mask = np.asarray(raw_mask)
            if tuple(mask.shape) != shape:
                return ToolResult(
                    success=False,
                    error=f"Structure {name!r} grid {tuple(mask.shape)} does not match planning grid {shape}",
                )
            normalized_structures[_safe_text(name, "Structure")] = mask.astype(bool)
        if dose_array is None:
            return ToolResult(success=False, error="dose_array is required for linked DICOM-RT export")
        dose = np.asarray(dose_array, dtype=np.float32)
        if tuple(dose.shape) != shape:
            return ToolResult(
                success=False,
                error=f"Dose grid {tuple(dose.shape)} does not match planning grid {shape}",
            )
        if not np.all(np.isfinite(dose)) or np.any(dose < 0):
            return ToolResult(success=False, error="Dose grid must contain finite non-negative values")

        channels = _normalize_channels(kwargs.get("seed_plan"), kwargs.get("seeds"))
        if not channels:
            return ToolResult(success=False, error="At least one seed trajectory is required")
        tags = kwargs.get("dicom_tags") if isinstance(kwargs.get("dicom_tags"), dict) else {}
        from utils.dose_units import physical_volume, PHYSICAL_UNITS
        units = kwargs.get("dose_units")
        # A caller with a saved explicit calibration is a legacy normalized
        # caller; neither unit nor calibration must ever default to 1 Gy.
        if not units and kwargs.get("dose_scale_gy") is not None:
            units = "normalized"
        try:
            physical_dose = physical_volume(dose, units=units, scale=kwargs.get("dose_scale_gy"))
            scale_gy = 1.0 if str(units).lower() in PHYSICAL_UNITS else float(kwargs["dose_scale_gy"])
            spacing, _, direction = _image_geometry(ct_image)
            if (not np.isfinite(spacing).all() or np.any(spacing <= 0)
                    or not np.isfinite(direction).all()
                    or not np.allclose(direction.T @ direction, np.eye(3), atol=1e-6)):
                raise ValueError("DICOM-RT requires a finite orthonormal image grid with positive spacing")
        except (ValueError, TypeError, KeyError) as exc:
            return ToolResult(success=False, error=str(exc))
        prescription = kwargs.get("prescription_gy")
        try:
            prescription = float(prescription) if prescription is not None else None
        except (TypeError, ValueError):
            prescription = None

        out = Path(output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        study_uid = dicom["generate_uid"]()
        frame_uid = dicom["generate_uid"]()
        struct_uid = dicom["generate_uid"]()
        plan_uid = dicom["generate_uid"]()
        dose_uid = dicom["generate_uid"]()

        rtstruct = self._build_rtstruct(dicom, ct_image, normalized_structures, struct_uid, study_uid, frame_uid, tags)
        rtplan = self._build_rtplan(dicom, channels, plan_uid, struct_uid, study_uid, frame_uid, tags, prescription)
        rtdose = self._build_rtdose(dicom, ct_image, physical_dose, dose_uid, plan_uid, struct_uid, study_uid, frame_uid, tags)

        paths = [out / "RTSTRUCT.dcm", out / "RTPLAN.dcm", out / "RTDOSE.dcm"]
        for dataset, path in zip((rtstruct, rtplan, rtdose), paths):
            try:
                dataset.save_as(str(path), enforce_file_format=True)
            except TypeError:  # pydicom < 3 does not expose the modern flag.
                dataset.save_as(str(path), write_like_original=False)
        manifest = {
            "clinical_status": "UNAPPROVED",
            "grid_shape_zyx": list(shape),
            "structures": list(normalized_structures),
            "channels": len(channels),
            "seeds": sum(len(channel) for channel in channels),
            "dose_scale_gy": scale_gy,
            "prescription_gy": prescription,
        }
        return ToolResult(
            success=True,
            data=[str(path) for path in paths],
            message="Linked unapproved DICOM-RT objects exported on one planning grid.",
            metadata={"clinical_status": "UNAPPROVED", "manifest": manifest},
        )

    def _build_rtstruct(self, dicom, image, structures, sop_uid, study_uid, frame_uid, tags):
        ds = _base_dataset(dicom, dicom["RTStructureSetStorage"], sop_uid, "RTSTRUCT", study_uid, frame_uid, tags)
        ds.StructureSetLabel = "BRACHYBOT"
        ds.StructureSetDate = _dt.datetime.now().strftime("%Y%m%d")
        ds.StructureSetTime = _dt.datetime.now().strftime("%H%M%S")
        ref = dicom["Dataset"]()
        ref.FrameOfReferenceUID = frame_uid
        ref.RTReferencedStudySequence = dicom["Sequence"]([dicom["Dataset"]()])
        ds.ReferencedFrameOfReferenceSequence = dicom["Sequence"]([ref])
        ds.StructureSetROISequence = dicom["Sequence"]()
        ds.ROIContourSequence = dicom["Sequence"]()
        for roi_number, (name, mask) in enumerate(structures.items(), start=1):
            roi = dicom["Dataset"]()
            roi.ROINumber = roi_number
            roi.ReferencedFrameOfReferenceUID = frame_uid
            roi.ROIName = name
            roi.ROIGenerationAlgorithm = "AUTOMATIC"
            ds.StructureSetROISequence.append(roi)
            roi_contour = dicom["Dataset"]()
            roi_contour.ReferencedROINumber = roi_number
            roi_contour.ROIDisplayColor = [255, 0, 0] if name.upper() == "CTV" else [0, 200, 255]
            roi_contour.ContourSequence = dicom["Sequence"]()
            for contour_data in _mask_contours(mask, image):
                contour = dicom["Dataset"]()
                contour.ContourGeometricType = "CLOSEDPLANAR_XOR"
                contour.NumberOfContourPoints = len(contour_data) // 3
                contour.ContourData = contour_data
                roi_contour.ContourSequence.append(contour)
            ds.ROIContourSequence.append(roi_contour)
        return ds

    def _build_rtplan(self, dicom, channels, sop_uid, struct_uid, study_uid, frame_uid, tags, prescription):
        ds = _base_dataset(dicom, dicom["RTPlanStorage"], sop_uid, "RTPLAN", study_uid, frame_uid, tags)
        ds.RTPlanLabel = "BRACHYBOT_PLAN"
        ds.RTPlanName = "BrachyBot seed implant plan"
        ds.RTPlanGeometry = "PATIENT"
        ds.ApprovalStatus = "UNAPPROVED"
        ds.BrachyTreatmentTechnique = "LDR"
        ds.FractionGroupSequence = dicom["Sequence"]([dicom["Dataset"]()])
        ds.FractionGroupSequence[0].FractionGroupNumber = 1
        ds.FractionGroupSequence[0].NumberOfFractionsPlanned = 1
        ds.FractionGroupSequence[0].NumberOfBrachyApplicationSetups = 1
        setup = dicom["Dataset"]()
        setup.ApplicationSetupNumber = 1
        setup.ApplicationSetupType = "MULTIPLE_PLANAR"
        setup.ApplicationSetupName = "BrachyBot"
        setup.ChannelSequence = dicom["Sequence"]()
        ds.SourceSequence = dicom["Sequence"]()
        source_number = 1
        for channel_number, channel in enumerate(channels, start=1):
            channel_ds = dicom["Dataset"]()
            channel_ds.ChannelNumber = channel_number
            channel_ds.ChannelLength = 150.0
            channel_ds.SourceMovementType = "STEPWISE"
            channel_ds.NumberOfControlPoints = len(channel)
            channel_ds.BrachyControlPointSequence = dicom["Sequence"]()
            for control_point_number, (position, direction) in enumerate(channel):
                cp = dicom["Dataset"]()
                cp.ControlPointIndex = control_point_number
                cp.ControlPointRelativePosition = float(control_point_number)
                cp.ControlPoint3DPosition = [float(value) for value in position]
                channel_ds.BrachyControlPointSequence.append(cp)
                source = dicom["Dataset"]()
                source.SourceNumber = source_number
                source.SourceIsotopeName = _safe_text("I-125", "I-125")
                source.ReferenceAirKermaRate = 0.0
                ds.SourceSequence.append(source)
                source_number += 1
            setup.ChannelSequence.append(channel_ds)
        ds.ApplicationSetupSequence = dicom["Sequence"]([setup])
        ref_struct = dicom["Dataset"]()
        ref_struct.ReferencedSOPClassUID = dicom["RTStructureSetStorage"]
        ref_struct.ReferencedSOPInstanceUID = struct_uid
        ds.ReferencedStructureSetSequence = dicom["Sequence"]([ref_struct])
        return ds

    def _build_rtdose(self, dicom, image, physical_dose, sop_uid, plan_uid, struct_uid, study_uid, frame_uid, tags):
        ds = _base_dataset(dicom, dicom["RTDoseStorage"], sop_uid, "RTDOSE", study_uid, frame_uid, tags)
        spacing, origin, direction = _image_geometry(image)
        maximum = float(np.max(physical_dose)) if physical_dose.size else 0.0
        # RTDOSE readers are substantially more interoperable with unsigned
        # 16-bit pixels than with 32-bit OW data. Dynamic scaling preserves the
        # dose maximum exactly and keeps the quantization error bounded.
        pixel_max = float(np.iinfo(np.uint16).max)
        scaling = maximum / pixel_max if maximum > 0 else 1.0
        pixels = np.rint(physical_dose / scaling).clip(0, pixel_max).astype(np.uint16)
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.NumberOfFrames = int(physical_dose.shape[0])
        ds.Rows = int(physical_dose.shape[1])
        ds.Columns = int(physical_dose.shape[2])
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.DoseUnits = str("GY")
        ds.DoseType = "PHYSICAL"
        ds.DoseSummationType = "PLAN"
        ds.DoseGridScaling = float(scaling)
        ds.PixelSpacing = [float(spacing[1]), float(spacing[0])]
        ds.SliceThickness = float(spacing[2])
        # Offsets are signed along cross(row, column), not always image k.
        sign = float(np.dot(np.cross(direction[:, 0], direction[:, 1]), direction[:, 2]))
        ds.GridFrameOffsetVector = [float(index * spacing[2] * sign) for index in range(physical_dose.shape[0])]
        ds.FrameIncrementPointer = [0x3004000C]
        ds.ImagePositionPatient = [float(value) for value in origin]
        ds.ImageOrientationPatient = [
            float(direction[0, 0]), float(direction[1, 0]), float(direction[2, 0]),
            float(direction[0, 1]), float(direction[1, 1]), float(direction[2, 1]),
        ]
        ref_plan = dicom["Dataset"]()
        ref_plan.ReferencedSOPClassUID = dicom["RTPlanStorage"]
        ref_plan.ReferencedSOPInstanceUID = plan_uid
        ds.ReferencedRTPlanSequence = dicom["Sequence"]([ref_plan])
        ref_struct = dicom["Dataset"]()
        ref_struct.ReferencedSOPClassUID = dicom["RTStructureSetStorage"]
        ref_struct.ReferencedSOPInstanceUID = struct_uid
        ds.ReferencedStructureSetSequence = dicom["Sequence"]([ref_struct])
        ds.PixelData = pixels.tobytes(order="C")
        return ds


__all__ = ["DicomRTExporterTool"]
