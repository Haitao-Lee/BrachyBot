"""Stage user-uploaded multi-label masks as explicit Data Tree candidates.

The source file is represented by an Upload Mask parent and one binary child
per positive label. Children remain generic/unclassified until a real backend
classification transaction moves one to CTV or OAR.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np
import SimpleITK as sitk


class UploadedMaskError(ValueError):
    """Raised when an uploaded mask cannot be staged safely."""

    def __init__(self, message: str, *, code: str = "uploaded_mask_invalid"):
        super().__init__(message)
        self.code = str(code or "uploaded_mask_invalid")


_COLLECTIONS = "uploaded_mask_collections"
_LATEST_COLLECTION = "uploaded_mask_latest"
_MASKS = "generic_segmentation_masks"
_LATEST_MASK = "generic_segmentation_latest"
_PRESENTATION_KEYS = ("color", "opacity", "visible", "visible2D", "visible3D", "data_version")
_STRUCTURE_CLASSIFICATIONS = frozenset({"ctv", "oar"})

# A CTV upload is a small discrete segmentation catalogue, not an arbitrary
# intensity volume.  Expanding every positive value into a browser/Data Tree
# child is both clinically meaningless for a CTV and capable of creating
# thousands of concurrent volume/mesh jobs when a CT is uploaded by mistake.
# Keep the limit deliberately conservative; callers that need a large
# anatomical label set should import it through the dedicated OAR/DICOM-RT
# path instead of the manual CTV-mask staging path.
MAX_UPLOADED_MASK_LABELS = 64


def _batch(memory: Any, updates: Mapping[str, Any]) -> None:
    try:
        from web.structure_service import _batch_memory_update
        _batch_memory_update(memory, updates)
    except (ImportError, AttributeError):
        for key, value in updates.items():
            memory.store(key, value)


def _public(entry: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        str(key): value for key, value in dict(entry).items()
        if key not in {"mask_array", "voxels", "data"}
    }


def _object_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("mask:"):
        return raw
    if raw.startswith("mask_"):
        return f"mask:{raw[5:]}"
    return f"mask:{raw}" if raw else ""


def is_uploaded_mask_label(entry: Any) -> bool:
    if not isinstance(entry, Mapping):
        return False
    return bool(
        str(entry.get("kind") or "").strip().lower() == "uploaded_mask_label"
        or str(entry.get("source") or "").strip().lower() == "uploaded_mask"
        or str(entry.get("upload_mask_id") or "").strip()
    )


def _validated_source(value: Any) -> np.ndarray:
    try:
        array = np.asarray(value)
    except Exception as exc:
        raise UploadedMaskError(f"Unable to read uploaded mask array: {exc}") from exc
    if array.ndim != 3:
        raise UploadedMaskError(
            f"Uploaded mask must be three-dimensional; received shape {array.shape}."
        )
    if not np.issubdtype(array.dtype, np.number) or np.issubdtype(array.dtype, np.complexfloating):
        raise UploadedMaskError("Uploaded mask must contain numeric discrete labels.")
    if np.issubdtype(array.dtype, np.floating):
        if not np.all(np.isfinite(array)) or not np.all(array == np.rint(array)):
            raise UploadedMaskError("Uploaded mask contains non-finite or non-integer labels.")
    if not np.any(array > 0):
        raise UploadedMaskError("Uploaded mask does not contain any positive labels.")
    return np.ascontiguousarray(array)


def _labels(array: np.ndarray) -> tuple[list[int], dict[int, int]]:
    values, counts = np.unique(array, return_counts=True)
    positive: list[int] = []
    result: dict[int, int] = {}
    for value, count in zip(values.tolist(), counts.tolist()):
        if value <= 0:
            continue
        try:
            label = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise UploadedMaskError(f"Uploaded label value is not representable: {value}") from exc
        positive.append(label)
        result[label] = int(count)
    if not positive:
        raise UploadedMaskError("Uploaded mask does not contain any positive labels.")
    if len(positive) > MAX_UPLOADED_MASK_LABELS:
        raise UploadedMaskError(
            "The uploaded CTV mask contains "
            f"{len(positive):,} positive values, exceeding the safe limit of "
            f"{MAX_UPLOADED_MASK_LABELS}. This usually means a CT/intensity "
            "volume was uploaded in the mask field. Upload a discrete mask "
            "with a small number of integer labels instead.",
            code="too_many_mask_labels",
        )
    return positive, result


def _same_path(left: Any, right: Any) -> bool:
    """Return whether two upload paths identify the same file."""
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    try:
        left_path = Path(left_text).expanduser().resolve()
        right_path = Path(right_text).expanduser().resolve()
        if left_path == right_path:
            return True
        return bool(os.path.samefile(left_path, right_path))
    except (OSError, RuntimeError, ValueError):
        return False


def _looks_like_intensity_volume(
    array: np.ndarray,
    labels: list[int],
    counts: Mapping[int, int],
    reference: Optional[np.ndarray] = None,
) -> bool:
    """Detect common CT-as-mask mistakes before creating child objects.

    The hard cardinality cap in :func:`_labels` is the primary protection.
    This secondary check catches compact/quantised CT exports that happen to
    contain fewer than the cap but still have intensity-like spacing/range,
    and catches a copied CT when the two paths differ.
    """
    try:
        candidate = np.asarray(array)
        if reference is not None:
            ref = np.asarray(reference)
            if candidate.shape == ref.shape and np.array_equal(candidate, ref):
                return True
        if len(labels) < 8:
            return False
        spread = int(max(labels) - min(labels))
        if spread >= 1024:
            return True
        if len(labels) < 16 or spread < 256:
            return False
        singleton_fraction = sum(
            1 for value in counts.values() if int(value) <= 2
        ) / float(len(labels))
        return singleton_fraction >= 0.25
    except Exception:
        # This is a safety heuristic, not a reason to reject a valid upload
        # when metadata is unusual. The cardinality cap remains authoritative.
        return False


def _quarantine_oversized_uploaded_masks(planning_results: Dict[str, Any]) -> bool:
    """Remove legacy unclassified explosions before they reach the browser.

    Older snapshots may already contain one child per CT intensity.  New
    uploads are rejected before staging, but hydration must also be safe for
    those snapshots. Keep any explicitly promoted clinical children (their
    effective CTV/OAR object is authoritative), remove only the unclassified
    upload children, and mark the parent so the UI can explain the rejection.
    """
    raw_entries = planning_results.get(_MASKS)
    if not isinstance(raw_entries, list):
        return False
    grouped: Dict[str, list[Mapping[str, Any]]] = {}
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping) or not is_uploaded_mask_label(raw_entry):
            continue
        upload_id = str(raw_entry.get("upload_mask_id") or "").strip()
        if upload_id:
            grouped.setdefault(upload_id, []).append(raw_entry)
    oversized = {
        upload_id: entries
        for upload_id, entries in grouped.items()
        if len(entries) > MAX_UPLOADED_MASK_LABELS
    }
    if not oversized:
        return False

    oversized_ids = set(oversized)
    next_entries: list[Dict[str, Any]] = []
    kept_by_upload: Dict[str, list[Mapping[str, Any]]] = {}
    changed = False
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = dict(raw_entry)
        upload_id = str(entry.get("upload_mask_id") or "").strip()
        if upload_id not in oversized_ids:
            next_entries.append(entry)
            continue
        classification = _normalised_classification(entry)
        if classification in _STRUCTURE_CLASSIFICATIONS:
            next_entries.append(entry)
            kept_by_upload.setdefault(upload_id, []).append(entry)
        else:
            # Do not let a legacy CT upload create thousands of source rows or
            # volume requests during restart hydration.
            changed = True

    if changed:
        planning_results[_MASKS] = next_entries

    raw_collections = planning_results.get(_COLLECTIONS)
    if isinstance(raw_collections, list):
        next_collections: list[Dict[str, Any]] = []
        for raw_collection in raw_collections:
            if not isinstance(raw_collection, Mapping):
                continue
            collection = dict(raw_collection)
            upload_id = str(collection.get("upload_id") or "").strip()
            if upload_id not in oversized_ids:
                next_collections.append(collection)
                continue
            kept = kept_by_upload.get(upload_id, [])
            kept_ids = [str(item.get("mask_id") or "") for item in kept if item.get("mask_id")]
            collection["child_mask_ids"] = kept_ids
            collection["source_labels"] = [
                int(item.get("source_label") or 0) for item in kept
            ]
            collection["source_label_counts"] = {
                str(item.get("source_label")): int(item.get("source_label_count") or 0)
                for item in kept
                if item.get("source_label") is not None
            }
            collection["rejected_label_count"] = len(oversized[upload_id])
            collection["error_code"] = "too_many_mask_labels"
            collection["error"] = (
                "Upload Mask was quarantined because it contains too many "
                "positive values; it may be a CT/intensity volume."
            )
            collection["status"] = "partially_quarantined" if kept else "rejected"
            existing_promotions = collection.get("promoted_children")
            if isinstance(existing_promotions, Mapping):
                collection["promoted_children"] = {
                    str(key): value
                    for key, value in existing_promotions.items()
                    if str(key) in kept_ids
                    or str((value or {}).get("object_id") or "") in {
                        _object_id(item.get("object_id") or item.get("mask_id"))
                        for item in kept
                    }
                }
            changed = True
            next_collections.append(collection)
        planning_results[_COLLECTIONS] = next_collections

    latest = str(planning_results.get(_LATEST_MASK) or "")
    if latest and not any(str(item.get("mask_id") or "") == latest for item in next_entries):
        planning_results[_LATEST_MASK] = (
            str(next_entries[-1].get("mask_id") or "") if next_entries else None
        )
        changed = True
    return changed


def _geometry(image: sitk.Image, shape: Iterable[int]) -> Dict[str, Any]:
    return {
        "shape": [int(value) for value in shape],
        "spacing": [float(value) for value in image.GetSpacing()],
        "origin": [float(value) for value in image.GetOrigin()],
        "direction": [float(value) for value in image.GetDirection()],
    }


def _fingerprint(path: Any) -> str:
    raw = str(path or "").strip()
    try:
        resolved = str(Path(raw).expanduser().resolve())
        stat = os.stat(resolved)
        return f"{resolved}|{stat.st_size}|{stat.st_mtime_ns}"
    except (OSError, RuntimeError, ValueError):
        return str(Path(raw).expanduser())


def _signature(label_path: Any, ct_path: Any = None, array: Optional[np.ndarray] = None) -> str:
    digest = hashlib.sha256()
    digest.update(_fingerprint(label_path).encode("utf-8", "surrogatepass"))
    digest.update(b"\0")
    digest.update(_fingerprint(ct_path).encode("utf-8", "surrogatepass"))
    if array is not None and not str(label_path or "").strip():
        digest.update(b"\0array\0")
        digest.update(np.ascontiguousarray(array).tobytes(order="C"))
        digest.update(str(array.dtype).encode("ascii", "replace"))
        digest.update(str(tuple(array.shape)).encode("ascii"))
    return digest.hexdigest()


def _ct_image(memory: Any, image_path: str) -> sitk.Image:
    current = memory.retrieve("ct_image") if hasattr(memory, "retrieve") else None
    if isinstance(current, sitk.Image):
        return current
    try:
        return sitk.ReadImage(str(image_path))
    except Exception as exc:
        raise UploadedMaskError(f"Unable to read CT image: {exc}") from exc


def _entries(memory: Any) -> list[Dict[str, Any]]:
    value = memory.retrieve(_MASKS) or []
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _normalised_classification(entry: Mapping[str, Any]) -> str:
    """Return the persisted clinical classification, if one exists."""
    # ``classification`` was introduced after ``moved_to``.  In legacy
    # browser snapshots the former can contain the placeholder
    # ``unclassified`` while the latter already contains the user's explicit
    # destination, so a truthy-first lookup would lose a real promotion.
    for raw_value in (
        entry.get("classification"),
        entry.get("moved_to"),
        entry.get("movedTo"),
    ):
        value = str(raw_value or "").strip().lower()
        if value in _STRUCTURE_CLASSIFICATIONS:
            return value
    return ""


def normalize_uploaded_mask_results(planning_results: Mapping[str, Any]) -> bool:
    """Repair uploaded-mask metadata without touching voxel data.

    Uploaded labels are durable source objects.  Their classification must not
    be inferred from whether the browser happened to render a standalone row.
    Older snapshots can contain the authoritative ``structure_catalog`` (or
    the Upload Mask parent's promotion record) while the child metadata still
    says ``unclassified``.  Reconcile those records at hydration time so a
    restart cannot silently move a promoted label back to Upload Mask.

    The function mutates only the supplied decoded planning-results mapping and
    returns whether any metadata changed.  It is deliberately array-agnostic,
    so it is safe during the lightweight metadata hydration pass as well as
    full array hydration.
    """
    if not isinstance(planning_results, dict):
        return False
    changed = _quarantine_oversized_uploaded_masks(planning_results)
    raw_entries = planning_results.get(_MASKS)
    if not isinstance(raw_entries, list):
        return changed

    catalog_by_id: Dict[str, Mapping[str, Any]] = {}
    raw_catalog = planning_results.get("structure_catalog")
    if isinstance(raw_catalog, list):
        for item in raw_catalog:
            if not isinstance(item, Mapping):
                continue
            object_id = _object_id(item.get("object_id") or item.get("mask_id"))
            classification = _normalised_classification(item)
            if object_id and classification in _STRUCTURE_CLASSIFICATIONS:
                catalog_by_id[object_id] = item

    promoted_by_upload: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    raw_collections = planning_results.get(_COLLECTIONS)
    if isinstance(raw_collections, list):
        for collection in raw_collections:
            if not isinstance(collection, Mapping):
                continue
            upload_id = str(collection.get("upload_id") or "").strip()
            if not upload_id:
                continue
            promoted = collection.get("promoted_children")
            if isinstance(promoted, Mapping):
                promoted_by_upload[upload_id] = {
                    str(key): value for key, value in promoted.items()
                    if isinstance(value, Mapping)
                }

    normalised_entries: list[Dict[str, Any]] = []
    effective_promotions: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = dict(raw_entry)
        if not is_uploaded_mask_label(entry):
            normalised_entries.append(entry)
            continue

        mask_id = str(entry.get("mask_id") or "").strip()
        stable_id = _object_id(entry.get("object_id") or mask_id)
        if stable_id and entry.get("object_id") != stable_id:
            entry["object_id"] = stable_id
            changed = True

        classification = _normalised_classification(entry)
        catalog_item = catalog_by_id.get(stable_id)
        if not classification and catalog_item is not None:
            classification = _normalised_classification(catalog_item)
        upload_id = str(entry.get("upload_mask_id") or "").strip()
        parent_promotions = promoted_by_upload.get(upload_id, {})
        promotion = parent_promotions.get(mask_id) or parent_promotions.get(stable_id)
        if not classification and isinstance(promotion, Mapping):
            classification = _normalised_classification(promotion)
        if classification not in _STRUCTURE_CLASSIFICATIONS:
            classification = ""

        if classification:
            desired = {
                "classification": classification,
                "moved_to": classification,
                "parent_group": classification,
            }
            for key, value in desired.items():
                if entry.get(key) != value:
                    entry[key] = value
                    changed = True
            if not isinstance(entry.get("ctv_promoted_from_upload"), Mapping) and classification == "ctv":
                entry["ctv_promoted_from_upload"] = {
                    "upload_mask_id": upload_id,
                    "object_id": stable_id,
                    "source_label": int(entry.get("source_label") or 0),
                    "source_path": str(entry.get("source_path") or ""),
                }
                changed = True
            effective_promotions.setdefault(upload_id, {})[mask_id] = {
                "object_id": stable_id,
                "classification": classification,
                "source_label": int(entry.get("source_label") or 0),
                "updated_at": entry.get("ctv_promoted_at") or entry.get("updated_at") or time.time(),
            }
        else:
            # An unclassified upload label remains a selectable Upload Mask
            # child.  Do not overwrite a user's explicit presentation values.
            if not entry.get("parent_group"):
                entry["parent_group"] = "upload_masks"
                changed = True
        normalised_entries.append(entry)

    if changed:
        planning_results[_MASKS] = normalised_entries

    if isinstance(raw_collections, list):
        next_collections: list[Dict[str, Any]] = []
        collections_changed = False
        for raw_collection in raw_collections:
            if not isinstance(raw_collection, Mapping):
                continue
            collection = dict(raw_collection)
            upload_id = str(collection.get("upload_id") or "").strip()
            if upload_id in effective_promotions:
                existing_promotions = collection.get("promoted_children")
                merged = {
                    **(
                        {str(key): dict(value) for key, value in existing_promotions.items()
                         if isinstance(value, Mapping)}
                        if isinstance(existing_promotions, Mapping) else {}
                    ),
                    **effective_promotions[upload_id],
                }
                # Keep only children that are still present in this collection.
                child_ids = {str(value) for value in collection.get("child_mask_ids") or []}
                merged = {
                    key: value for key, value in merged.items()
                    if key in child_ids or str(value.get("object_id") or "") in {
                        _object_id(child_id) for child_id in child_ids
                    }
                }
                if collection.get("promoted_children") != merged:
                    collection["promoted_children"] = merged
                    collections_changed = True
            next_collections.append(collection)
        if collections_changed:
            planning_results[_COLLECTIONS] = next_collections
            changed = True
    return changed


def normalize_uploaded_mask_state(memory: Any) -> bool:
    """Reconcile uploaded-mask metadata in live AgentMemory."""
    with memory._lock:
        results = memory.planning_results
        changed = normalize_uploaded_mask_results(results)
        updates = {
            key: results.get(key)
            for key in (_MASKS, _COLLECTIONS)
            if key in results
        }
    if changed and updates:
        _batch(memory, updates)
    return changed


def _existing_collection(memory: Any, signature: str) -> Optional[Dict[str, Any]]:
    value = memory.retrieve(_COLLECTIONS) or []
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, Mapping) and str(item.get("source_signature") or "") == signature:
            return dict(item)
    return None


def _stage(
    memory: Any,
    source: Any,
    *,
    source_path: str,
    ct_path: str,
    geometry: Mapping[str, Any],
    signature: str,
    reference_array: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    array = _validated_source(source)
    labels, counts = _labels(array)
    if _looks_like_intensity_volume(array, labels, counts, reference_array):
        raise UploadedMaskError(
            "The uploaded CTV mask looks like a CT/intensity volume rather "
            "than a discrete segmentation mask. Please select a label mask "
            "file in the CTV-mask field.",
            code="ct_uploaded_as_mask",
        )
    # Normalize metadata before looking up a reusable collection.  Re-staging
    # the same source after a restart must preserve which children were moved
    # into the effective Structure Set.
    normalize_uploaded_mask_state(memory)
    existing = _existing_collection(memory, signature)
    entries = _entries(memory)
    by_id = {str(item.get("mask_id") or ""): item for item in entries if item.get("mask_id")}

    if existing is not None:
        child_ids = [str(value) for value in existing.get("child_mask_ids") or []]
        if child_ids and all(child_id in by_id for child_id in child_ids):
            children = [_public(by_id[child_id]) for child_id in child_ids]
            return {
                "upload_mask": _public(existing),
                "children": children,
                "labels": [int(value) for value in existing.get("source_labels") or labels],
                "label_counts": {
                    str(key): int(value)
                    for key, value in (existing.get("source_label_counts") or counts).items()
                },
                "total_labels": len(children),
                "reused": True,
            }

    digest = signature[:20]
    upload_id = str(existing.get("upload_id") if existing else f"upload_mask_{digest}")
    parent_id = str(existing.get("object_id") if existing else f"upload_mask:{digest}")
    child_ids = [f"{upload_id}_label_{label}" for label in labels]
    now = time.time()
    parent = {
        **(existing or {}),
        "upload_id": upload_id,
        "object_id": parent_id,
        "data_tree_node_id": upload_id,
        "name": "Upload Mask",
        "label": "Upload Mask",
        "kind": "uploaded_mask_collection",
        "source": "uploaded_mask",
        "source_path": str(source_path or ""),
        "source_filename": Path(str(source_path)).name if source_path else "uploaded_mask",
        "ct_path": str(ct_path or ""),
        "source_signature": signature,
        "session_id": str(getattr(memory, "session_id", "")),
        "case_id": str(memory.retrieve("case_id") or getattr(memory, "session_id", "")),
        "planning_id": memory.retrieve("active_planning_id"),
        "source_labels": [int(value) for value in labels],
        "source_label_counts": {str(key): int(value) for key, value in counts.items()},
        "child_mask_ids": child_ids,
        "status": "ready",
        "created_at": float((existing or {}).get("created_at") or now),
        "updated_at": now,
        **dict(geometry),
    }
    spacing = np.asarray(geometry.get("spacing") or [1, 1, 1], dtype=np.float64)
    children: list[Dict[str, Any]] = []
    for label in labels:
        mask_id = f"{upload_id}_label_{label}"
        prior = by_id.get(mask_id, {})
        binary = np.ascontiguousarray(array == label, dtype=np.uint8)
        count = int(np.count_nonzero(binary))
        prior_classification = _normalised_classification(prior)
        child = {
            **prior,
            "mask_id": mask_id,
            "object_id": f"mask:{mask_id}",
            "data_tree_node_id": mask_id,
            "name": f"Label {label}",
            "label": f"Label {label}",
            "kind": "uploaded_mask_label",
            "source": "uploaded_mask",
            "upload_mask_id": upload_id,
            "upload_mask_object_id": parent_id,
            "upload_mask_name": "Upload Mask",
            "source_path": str(source_path or ""),
            "source_filename": Path(str(source_path)).name if source_path else "uploaded_mask",
            "source_label": int(label),
            "source_label_count": count,
            "source_signature": signature,
            "classification": prior_classification or "unclassified",
            "parent_group": (
                prior_classification
                if prior_classification in _STRUCTURE_CLASSIFICATIONS
                else "upload_masks"
            ),
            "moved_to": prior_classification or None,
            "session_id": str(getattr(memory, "session_id", "")),
            "case_id": str(memory.retrieve("case_id") or getattr(memory, "session_id", "")),
            "planning_id": memory.retrieve("active_planning_id"),
            "shape": list(geometry.get("shape") or array.shape),
            "spacing": list(geometry.get("spacing") or [1, 1, 1]),
            "origin": list(geometry.get("origin") or [0, 0, 0]),
            "direction": list(geometry.get("direction") or [1, 0, 0, 0, 1, 0, 0, 0, 1]),
            "voxel_count": count,
            "volume_mm3": float(count * np.prod(spacing)),
            "status": "ready",
            "error": None,
            "mask_array": binary,
        }
        for key in _PRESENTATION_KEYS:
            if key in prior:
                child[key] = prior[key]
        children.append(child)

    promoted_children = {
        str(child["mask_id"]): {
            "object_id": child["object_id"],
            "classification": child["classification"],
            "source_label": int(child.get("source_label") or 0),
            "updated_at": child.get("updated_at") or now,
        }
        for child in children
        if str(child.get("classification") or "").lower() in _STRUCTURE_CLASSIFICATIONS
    }
    parent["promoted_children"] = promoted_children

    next_entries = [item for item in entries if str(item.get("upload_mask_id") or "") != upload_id]
    next_entries.extend(children)
    raw_collections = memory.retrieve(_COLLECTIONS) or []
    collections = [
        dict(item) for item in raw_collections
        if isinstance(item, Mapping) and str(item.get("upload_id") or "") != upload_id
    ]
    collections.append(parent)
    _batch(memory, {
        _MASKS: next_entries,
        _LATEST_MASK: children[-1]["mask_id"],
        _COLLECTIONS: collections,
        _LATEST_COLLECTION: upload_id,
    })
    return {
        "upload_mask": _public(parent),
        "children": [_public(item) for item in children],
        "labels": [int(value) for value in labels],
        "label_counts": {str(key): int(value) for key, value in counts.items()},
        "total_labels": len(children),
        "reused": False,
    }


def stage_uploaded_ctv_mask(memory: Any, image_path: str, label_path: str) -> Dict[str, Any]:
    """Align and stage every positive label; do not mutate the current CTV."""
    if not str(image_path or "").strip() or not str(label_path or "").strip():
        raise UploadedMaskError("Both CT image and uploaded mask paths are required.")
    if _same_path(image_path, label_path):
        raise UploadedMaskError(
            "The CT image was supplied as the CTV mask. Please choose a "
            "discrete CTV label/mask file instead of the CT volume.",
            code="ct_uploaded_as_mask",
        )
    try:
        from tool_factory.segmentation_alignment import align_label_to_reference
        ct_image = _ct_image(memory, image_path)
        label_image = align_label_to_reference(label_path, ct_image, "LPI")
    except Exception as exc:
        raise UploadedMaskError(f"Unable to align uploaded mask to the CT grid: {exc}") from exc
    source = sitk.GetArrayFromImage(label_image)
    try:
        reference_array = sitk.GetArrayFromImage(sitk.DICOMOrient(ct_image, "LPI"))
    except Exception:
        reference_array = None
    return _stage(
        memory,
        source,
        source_path=str(label_path),
        ct_path=str(image_path),
        geometry=_geometry(label_image, source.shape),
        signature=_signature(label_path, image_path),
        reference_array=reference_array,
    )


def stage_uploaded_ctv_array(
    memory: Any,
    array: Any,
    *,
    source_path: str = "",
    ct_path: str = "",
    geometry: Optional[Mapping[str, Any]] = None,
    source_signature: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage an already CT-aligned raw array returned by a segmentation tool."""
    source = _validated_source(array)
    if geometry is None:
        reference = memory.retrieve("ct_image") if hasattr(memory, "retrieve") else None
        geometry = _geometry(reference, source.shape) if isinstance(reference, sitk.Image) else {
            "shape": list(source.shape),
            "spacing": list(memory.retrieve("ct_spacing") or [1, 1, 1]),
            "origin": list(memory.retrieve("ct_origin") or [0, 0, 0]),
            "direction": list(memory.retrieve("ct_direction") or [1, 0, 0, 0, 1, 0, 0, 0, 1]),
        }
    return _stage(
        memory,
        source,
        source_path=str(source_path or ""),
        ct_path=str(ct_path or ""),
        geometry=geometry,
        signature=source_signature or _signature(source_path, ct_path, source if not source_path else None),
    )


def public_uploaded_mask_collections(memory: Any) -> list[Dict[str, Any]]:
    value = memory.retrieve(_COLLECTIONS) or []
    return [_public(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def remove_uploaded_mask_child(memory: Any, stable_id: str) -> bool:
    """Delete one child and remove or update its Upload Mask parent."""
    wanted = _object_id(stable_id)
    entries = _entries(memory)
    removed = None
    remaining = []
    for item in entries:
        if removed is None and _object_id(item.get("object_id") or item.get("mask_id")) == wanted:
            removed = item
        else:
            remaining.append(item)
    if removed is None:
        return False

    upload_id = str(removed.get("upload_mask_id") or "")
    raw_collections = memory.retrieve(_COLLECTIONS) or []
    collections = []
    for raw in raw_collections if isinstance(raw_collections, list) else []:
        if not isinstance(raw, Mapping):
            continue
        collection = dict(raw)
        if str(collection.get("upload_id") or "") == upload_id:
            removed_id = str(removed.get("mask_id") or "")
            child_ids = [str(value) for value in collection.get("child_mask_ids") or [] if str(value) != removed_id]
            if not child_ids:
                continue
            collection["child_mask_ids"] = child_ids
            source_label = int(removed.get("source_label") or -1)
            collection["source_labels"] = [
                int(value) for value in collection.get("source_labels") or [] if int(value) != source_label
            ]
            counts = dict(collection.get("source_label_counts") or {})
            counts.pop(str(source_label), None)
            collection["source_label_counts"] = counts
            collection["updated_at"] = time.time()
        collections.append(collection)
    _batch(memory, {
        _MASKS: remaining,
        _LATEST_MASK: str(remaining[-1].get("mask_id") or "") if remaining else None,
        _COLLECTIONS: collections,
        _LATEST_COLLECTION: str(collections[-1].get("upload_id") or "") if collections else None,
    })
    return True


__all__ = [
    "UploadedMaskError",
    "MAX_UPLOADED_MASK_LABELS",
    "is_uploaded_mask_label",
    "normalize_uploaded_mask_results",
    "normalize_uploaded_mask_state",
    "public_uploaded_mask_collections",
    "remove_uploaded_mask_child",
    "stage_uploaded_ctv_array",
    "stage_uploaded_ctv_mask",
]
