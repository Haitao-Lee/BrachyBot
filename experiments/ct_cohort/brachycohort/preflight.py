"""Source registry and full-payload, source-specific target preflight."""
from __future__ import annotations
import gzip
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import SimpleITK as sitk

from .core import Blocked, atomic_json, digest, sha256, source_digest, load_json


def records(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for index, line in enumerate(f, 1):
            if line.strip():
                row = json.loads(line)
                if not row.get("row_id") or not row.get("dataset"):
                    raise Blocked("INVALID_MANIFEST_ROW", str(index))
                yield row


def grid(image):
    return {"size_xyz": list(image.GetSize()), "spacing_mm": list(image.GetSpacing()),
            "origin_lps_mm": list(image.GetOrigin()), "direction_lps": list(image.GetDirection())}


def equal_grid(a, b, atol=1e-4):
    return a.GetDimension() == b.GetDimension() == 3 and a.GetSize() == b.GetSize() and all(
        np.allclose(x, y, atol=atol, rtol=0) for x, y in
        ((a.GetSpacing(), b.GetSpacing()), (a.GetOrigin(), b.GetOrigin()), (a.GetDirection(), b.GetDirection())))


def voxel_hash(array, physical_grid):
    array = np.ascontiguousarray(array)
    import hashlib
    h = hashlib.sha256()
    h.update(digest({"dtype": array.dtype.str, "shape": array.shape, "grid": physical_grid}).encode())
    h.update(memoryview(array).cast("B"))
    return h.hexdigest()


def source_path(value, source_root):
    if not value:
        raise Blocked("MISSING_SOURCE_PATH")
    path, root = Path(value).resolve(), Path(source_root).resolve()
    if root not in path.parents or not path.is_file():
        raise Blocked("SOURCE_NOT_AVAILABLE", str(path))
    return path


def check_header(path, unit_override=None):
    img = nib.load(str(path))
    if len(img.shape) != 3 or any(n <= 0 for n in img.shape):
        raise Blocked("NON_3D_VOLUME")
    q, qc = img.get_qform(coded=True)
    s, sc = img.get_sform(coded=True)
    if qc and sc and not np.allclose(q, s, atol=1e-4, rtol=0):
        raise Blocked("QFORM_SFORM_CONFLICT")
    units = img.header.get_xyzt_units()[0]
    if units != "mm":
        if units != "unknown" or not unit_override or unit_override.get("unit") != "mm" or not unit_override.get("evidence"):
            raise Blocked("SPATIAL_UNITS_UNRESOLVED", units)
    return img, {"shape_xyz": list(img.shape), "affine_ras": img.affine.tolist(),
                 "qform_code": int(qc), "sform_code": int(sc), "original_units": units,
                 "unit_override": unit_override if units == "unknown" else None}


def preflight(row, storage, policy, conversion_approval=None):
    result = {**row, "schema_version": 1, "preflight_status": "BLOCKED", "reasons": [], "preflight_policy_hash": digest(policy)}
    try:
        storage.check()
        if row.get("image_modality") not in {"CT", "CT_DICOM"}:
            raise Blocked("NON_CT_OR_NON_TUMOR")
        if Path(row.get("ct_path") or "").is_dir():
            if not conversion_approval:
                raise Blocked("DICOM_CONVERSION_REQUIRED")
            from .dicom import approved_conversion
            conversion = approved_conversion(row, storage, conversion_approval)
            ct, mask = Path(conversion["derived_ct_path"]), Path(conversion["derived_label_path"])
            # Original segment numbers have already been unioned in physical CT space.
            work_row = {**row, "target_values": [1]}
            result["dicom_conversion"] = conversion
        else:
            ct = source_path(row.get("ct_path"), storage.source)
            mask = source_path(row.get("label_path"), storage.source)
            work_row = row
        for path in (ct, mask):
            if not str(path).endswith((".nii", ".nii.gz")):
                raise Blocked("UNSUPPORTED_IMAGE_CONTAINER")
        overrides = policy.get("unit_overrides", {}).get(row["dataset"], {})
        ci, ch = check_header(ct, overrides.get("ct"))
        mi, mh = check_header(mask, overrides.get("label"))
        # Bound decompressed allocation before loading full volumes.
        peak = int(np.prod(ci.shape)) * (ci.get_data_dtype().itemsize + 16) + int(np.prod(mi.shape)) * 24
        if peak > policy.get("max_preflight_memory_bytes", 8 * 1024**3):
            raise Blocked("PREFLIGHT_MEMORY_BUDGET", str(peak))
        source_hashes = {"ct": source_digest(row["ct_path"]), "label": source_digest(row["label_path"])}
        if result.get("dicom_conversion"):
            source_hashes["pet"] = source_digest(row["pet_series_path"])
        ca = np.asarray(ci.dataobj)
        ma = np.asarray(mi.dataobj, dtype=np.float64)
        if not np.isfinite(ca).all() or not np.isfinite(ma).all():
            raise Blocked("NONFINITE_IMAGE")
        rounded = np.rint(ma)
        error = float(np.max(np.abs(ma - rounded)))
        if error > 1e-6 or (error and not policy.get("allow_near_integer_repair", False)):
            raise Blocked("NONINTEGER_LABEL", str(error))
        if rounded.min() < 0 or rounded.max() > 65535:
            raise Blocked("INVALID_LABEL_RANGE")
        labels = np.unique(rounded).astype(int).tolist()
        alphabet = policy.get("label_alphabets", {}).get(row["dataset"])
        if error and (not alphabet or not set(labels) <= set(alphabet)):
            raise Blocked("ENCODING_REPAIR_ALPHABET_UNRESOLVED")
        values = work_row.get("target_values")
        if not values or any(type(v) is not int or v <= 0 for v in values):
            raise Blocked("TARGET_POLICY_UNRESOLVED")
        target = np.isin(rounded, values).astype(np.uint8)
        counts = {str(v): int(np.count_nonzero(rounded == v)) for v in values}
        if not np.count_nonzero(target):
            raise Blocked("METADATA_PAYLOAD_CONFLICT" if row.get("metadata_positive") else "EMPTY_SELECTED_TARGET")
        ct_itk, mask_itk = sitk.ReadImage(str(ct)), sitk.ReadImage(str(mask))
        if not equal_grid(ct_itk, mask_itk):
            raise Blocked("GRID_MISMATCH")
        if any(not np.isfinite(x) or x <= 0 for x in ct_itk.GetSpacing()):
            raise Blocked("INVALID_SPACING")
        # Nibabel xyz -> SimpleITK zyx. Verify this actual reader contract.
        binary_zyx = target.transpose(2, 1, 0)
        actual = np.isin(np.rint(sitk.GetArrayFromImage(mask_itk)), values)
        if not np.array_equal(actual, binary_zyx):
            raise Blocked("READER_TARGET_DISAGREEMENT")
        name = digest({"row_id": row["row_id"], "hashes": source_hashes, "values": values, "policy": policy})
        folder = storage.path("derived/" + name)
        folder.mkdir(parents=True, exist_ok=True)
        derived = folder / "target.nii.gz"
        ni = nib.Nifti1Image(target, mi.affine, mi.header.copy())
        ni.set_data_dtype(np.uint8)
        ni.header.set_slope_inter(1, 0)
        ni.header.set_xyzt_units("mm")
        nib.save(ni, str(derived))
        reread = sitk.ReadImage(str(derived))
        if not equal_grid(ct_itk, reread) or not np.array_equal(sitk.GetArrayFromImage(reread), binary_zyx):
            raise Blocked("DERIVATIVE_VERIFICATION_FAILED")
        voxel_volume = float(np.prod(ct_itk.GetSpacing()))
        cc = sitk.ConnectedComponent(reread)
        stats = sitk.LabelShapeStatisticsImageFilter()
        stats.Execute(cc)
        components = [{"id": int(v), "voxel_count": stats.GetNumberOfPixels(v),
                       "volume_cm3": stats.GetPhysicalSize(v) / 1000,
                       "centroid_lps_mm": stats.GetCentroid(v), "bbox_xyz": stats.GetBoundingBox(v)}
                      for v in stats.GetLabels()]
        stats.Execute(reread)
        # Border contact is a research flag, not proof of complete skin/FOV.
        touches = any(np.any(np.take(binary_zyx, i, axis=axis)) for axis in range(3) for i in (0, -1))
        current = {"ct": source_digest(row["ct_path"]), "label": source_digest(row["label_path"])}
        if "pet" in source_hashes:
            current["pet"] = source_digest(row["pet_series_path"])
        if source_hashes != current:
            raise Blocked("SOURCE_CHANGED_DURING_PREFLIGHT")
        result.update(preflight_status="PASS", reasons=[], derived_ct_path=str(ct), derived_label_path=str(derived),
                      source_hashes=source_hashes, derived_label_sha256=sha256(derived),
                      derived_ct_sha256=sha256(ct),
                      target_hash=voxel_hash(binary_zyx, grid(reread)), target_voxels=int(target.sum()),
                      target_volume_cm3=float(target.sum() * voxel_volume / 1000), target_grid=grid(reread),
                      ct_content_hash=voxel_hash(sitk.GetArrayFromImage(ct_itk), grid(ct_itk)),
                      source_headers={"ct": ch, "label": mh}, selected_label_voxel_counts=counts,
                      components=components, target_touches_fov_boundary=touches,
                      skin_completeness="UNKNOWN", encoding_repair_max_error=error,
                      derivative_recipe={"kind": "supplied_union_no_margin", "target_values": values,
                                         "source_target_values": row["target_values"],
                                         "array_order": "zyx", "coordinates": "LPS_mm", "policy_hash": digest(policy)})
    except (Blocked, OSError, ValueError, RuntimeError) as exc:
        result["reasons"] = [exc.code if isinstance(exc, Blocked) else "IMAGE_READ_ERROR"]
        result["error"] = str(exc)
    return result
