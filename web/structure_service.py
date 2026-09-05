"""Authoritative structure classification and deletion transactions.

The browser Data Tree is a presentation of this state, never the source of
truth.  A structure keeps one stable ``object_id`` while its CTV/OAR
classification and transport label may change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np


_BASE_KEYS = (
    "structure_base_ctv_array",
    "structure_base_ctv_full_labels",
    "structure_base_ctv_label_map",
    "structure_base_ctv_source",
    "structure_base_oar_array",
    "structure_base_organ_names",
    "structure_base_oar_source",
)

_DOWNSTREAM_KEYS = (
    "dose_distribution",
    "dose_distribution_gy",
    "dose_distribution_physical_gy",
    "dose_metrics",
    "dvh_data",
    # Keep the legacy algorithm-prefixed aliases in the same invalidation
    # transaction.  Some restored sessions expose these names instead of the
    # canonical dose keys, which otherwise lets an old result look current
    # after a structure classification change.
    "algorithm_plan_dose_distribution",
    "algorithm_plan_dose_distribution_gy",
    "algorithm_plan_dose_metrics",
    "algorithm_plan_dvh_data",
    "manual_ai_dose",
    "metrics",
    "plan_score",
    "radiation_volume",
    "manual_planning_preview",
)


class StructureError(ValueError):
    """Raised when a structure transaction cannot be completed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _int_map(value: Any) -> Dict[int, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[int, Any] = {}
    for raw_key, item in value.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError):
            continue
        if key > 0:
            result[key] = item
    return result


def _copy_array(value: Any, dtype=None) -> Optional[np.ndarray]:
    """Copy a 3-D mask from an array-like value or a SimpleITK image.

    Segmentation tools may return a SimpleITK image while hydrated sessions
    usually contain NumPy arrays.  Treating the former with ``np.asarray``
    produces a scalar object array and silently removes the structure from
    the effective registry.  Keep the conversion at this boundary so all
    callers use the same spatial voxel ordering.
    """
    if value is None:
        return None
    array = None
    try:
        candidate = np.asarray(value, dtype=dtype)
        if candidate.ndim == 3:
            array = candidate
    except (TypeError, ValueError):
        array = None
    if array is None:
        get_size = getattr(value, "GetSize", None)
        if not callable(get_size):
            return None
        try:
            import SimpleITK as sitk

            array = sitk.GetArrayFromImage(value)
            if dtype is not None:
                array = np.asarray(array, dtype=dtype)
        except (ImportError, TypeError, ValueError, RuntimeError):
            return None
    if array.ndim != 3:
        return None
    return np.array(array, copy=True)


def _explicit_structure_classification(value: Mapping[str, Any]) -> str:
    """Read a valid structure class without trusting placeholder fields.

    Older Upload Mask rows may carry ``classification=unclassified`` beside
    a real legacy ``moved_to=ctv/oar`` value.  A truthy-first expression would
    discard the explicit move and make the effective Structure Set incomplete.
    """
    for raw_value in (
        value.get("classification"),
        value.get("moved_to"),
        value.get("movedTo"),
    ):
        classification = str(raw_value or "").strip().lower()
        if classification in {"ctv", "oar"}:
            return classification
    return ""


def _is_model_ctv_source(source: Any) -> bool:
    """Return whether a CTV source may carry embedded anatomy labels."""
    token = str(source or "").strip().lower()
    return (
        token in {
            "model",
            "biomedparse_v2",
            "biomedparse_v2_research_candidate",
            "totalsegmentator",
            "totalsegmentator_liver_tumor",
            "sat3d",
        }
        or token.startswith("nnunet_")
        or token.startswith("biomedparse_")
        or token.startswith("totalsegmentator_")
        or token.startswith("sat3d")
    )


def _batch_memory_update(memory: Any, updates: Mapping[str, Any], removals: Iterable[str] = ()) -> None:
    """Apply one versioned memory transaction and schedule one checkpoint."""
    with memory._lock:
        available = set(memory.conversation_state.get("data_available", []))
        for key in removals:
            memory.planning_results.pop(key, None)
            memory._planning_versions[key] = memory._planning_versions.get(key, 0) + 1
            available.discard(key)
        for key, value in updates.items():
            memory.planning_results[key] = value
            memory._planning_versions[key] = memory._planning_versions.get(key, 0) + 1
            if value is None:
                available.discard(key)
            else:
                available.add(key)
        memory.conversation_state["data_available"] = sorted(available)
    memory._notify_persistence("structure.transaction")


def _base_ctv_volume(memory: Any) -> tuple[Optional[np.ndarray], Dict[int, str], str]:
    source = str(
        memory.retrieve("structure_base_ctv_source")
        or memory.retrieve("ctv_source")
        or ""
    ).strip().lower()
    label_map = {
        key: str(value)
        for key, value in _int_map(
            memory.retrieve("structure_base_ctv_label_map")
            or memory.retrieve("ctv_label_map")
            or {}
        ).items()
    }
    ctv_array = _copy_array(
        memory.retrieve("structure_base_ctv_array")
        if memory.retrieve("structure_registry_initialized")
        else memory.retrieve("ctv_array")
    )
    full_labels = _copy_array(
        memory.retrieve("structure_base_ctv_full_labels")
        if memory.retrieve("structure_registry_initialized")
        else memory.retrieve("ctv_full_labels")
    )

    if _is_model_ctv_source(source) and full_labels is not None:
        # The validated pancreatic model reserves label 1 for the actual tumor.
        # Labels 2-4 are anatomy and are represented as OAR source objects below.
        if np.any(full_labels == 1):
            return (full_labels == 1).astype(np.uint8), {
                1: label_map.get(1, "pancreatic tumor")
            }, source
    if ctv_array is None:
        return None, {}, source
    labels = [int(value) for value in np.unique(ctv_array) if int(value) > 0]
    if not labels:
        return None, {}, source
    if len(labels) == 1 and labels[0] != 1:
        ctv_array = (ctv_array > 0).astype(np.uint8)
        labels = [1]
    return ctv_array, {
        label: label_map.get(label, "CTV" if label == 1 else f"CTV {label}")
        for label in labels
    }, source


def _base_oar_volume(memory: Any) -> tuple[Optional[np.ndarray], Dict[int, str], str]:
    source = str(
        memory.retrieve("structure_base_oar_source")
        or memory.retrieve("oar_source")
        or ""
    ).strip().lower()
    array = _copy_array(
        memory.retrieve("structure_base_oar_array")
        if memory.retrieve("structure_registry_initialized")
        else memory.retrieve("oar_array"),
        dtype=np.uint16,
    )
    names = {
        key: str(value)
        for key, value in _int_map(
            memory.retrieve("structure_base_organ_names")
            or memory.retrieve("organ_names")
            or {}
        ).items()
    }
    return array, names, source


def _source_structures(memory: Any) -> list[Dict[str, Any]]:
    ctv, ctv_names, ctv_source = _base_ctv_volume(memory)
    oar, oar_names, oar_source = _base_oar_volume(memory)
    result: list[Dict[str, Any]] = []

    if ctv is not None:
        for label in sorted(int(value) for value in np.unique(ctv) if int(value) > 0):
            mask = ctv == label
            result.append({
                "object_id": f"structure:ctv:{label}",
                "source_classification": "ctv",
                "source_label": label,
                "name": ctv_names.get(label, "CTV" if label == 1 else f"CTV {label}"),
                "source": ctv_source,
                "mask": mask,
            })

    if oar is not None:
        for label in sorted(int(value) for value in np.unique(oar) if int(value) > 0):
            mask = oar == label
            result.append({
                "object_id": f"structure:oar:{label}",
                "source_classification": "oar",
                "source_label": label,
                "name": oar_names.get(label, f"OAR {label}"),
                "source": oar_source,
                "mask": mask,
            })

    # The pancreatic CTV model exposes embedded anatomy in labels 2-4.  The
    # viewer historically created these only at render time, which made them
    # impossible to reclassify or export.  Promote them to real source objects.
    full = _copy_array(
        memory.retrieve("structure_base_ctv_full_labels")
        if memory.retrieve("structure_registry_initialized")
        else memory.retrieve("ctv_full_labels")
    )
    if _is_model_ctv_source(ctv_source) and full is not None and oar_source not in {
        "manual_label", "uploaded_unknown", "uploaded", "manual_upload",
    }:
        embedded = {2: (201, "artery"), 3: (202, "vein"), 4: (203, "pancreas")}
        existing_ids = {item["object_id"] for item in result}
        for source_label, (display_label, name) in embedded.items():
            object_id = f"structure:embedded:{source_label}"
            if object_id in existing_ids or not np.any(full == source_label):
                continue
            result.append({
                "object_id": object_id,
                "source_classification": "oar",
                "source_label": display_label,
                "name": name,
                "source": "ctv_model_embedded",
                "mask": full == source_label,
            })

    # Open/generic segmentation results start as independent Data Tree masks.
    # Once the user explicitly moves one to CTV or OAR, the same persisted
    # object becomes a real Structure Set source.  Keeping this conversion in
    # the authoritative source builder means planning, DVH, export, restore,
    # and both viewers all consume the same classification instead of a
    # browser-only presentation flag.
    generic_masks = memory.retrieve("generic_segmentation_masks") or []
    if isinstance(generic_masks, list):
        for raw_entry in generic_masks:
            if not isinstance(raw_entry, Mapping):
                continue
            classification = _explicit_structure_classification(raw_entry)
            if classification not in {"ctv", "oar"}:
                continue
            mask = _copy_array(raw_entry.get("mask_array"), dtype=np.uint8)
            if mask is None or not np.any(mask):
                continue
            mask_id = str(
                raw_entry.get("object_id")
                or f"mask:{raw_entry.get('mask_id') or ''}"
            ).strip()
            # Older browser snapshots used ``mask_<id>`` as a DOM identifier.
            # Keep the persisted object identity stable when those snapshots
            # are rebuilt into the authoritative Structure Set.
            if mask_id.startswith("mask_"):
                mask_id = f"mask:{mask_id[5:]}"
            elif not mask_id.startswith("mask:"):
                mask_id = f"mask:{mask_id}"
            if not mask_id or mask_id == "mask:":
                continue
            result.append({
                "object_id": mask_id,
                "source_classification": classification,
                "source_label": 1,
                "name": str(
                    raw_entry.get("name")
                    or raw_entry.get("label")
                    or raw_entry.get("target")
                    or raw_entry.get("mask_id")
                    or mask_id
                ),
                "source": "generic_segmentation",
                "mask": mask > 0,
                "generic_mask_id": str(raw_entry.get("mask_id") or ""),
            })
    return result


def _allocate_label(preferred: int, used: set[int], maximum: int) -> int:
    if 0 < preferred <= maximum and preferred not in used:
        used.add(preferred)
        return preferred
    for candidate in range(1, maximum + 1):
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise StructureError("No transport label is available for this structure class")


@dataclass
class EffectiveStructures:
    ctv_array: Optional[np.ndarray]
    oar_array: Optional[np.ndarray]
    ctv_label_map: Dict[int, str]
    organ_names: Dict[int, str]
    organ_counts: Dict[int, int]
    structures: list[Dict[str, Any]]

    def public_catalog(self) -> list[Dict[str, Any]]:
        return [
            {key: value for key, value in item.items() if key != "mask"}
            for item in self.structures
        ]


def build_effective_structures(memory: Any) -> EffectiveStructures:
    source_items = _source_structures(memory)
    overrides = memory.retrieve("structure_overrides") or {}
    deleted = set(memory.retrieve("structure_deleted_ids") or [])

    shape = None
    for item in source_items:
        shape = item["mask"].shape
        break
    if shape is None:
        return EffectiveStructures(None, None, {}, {}, {}, [])

    ctv_out = np.zeros(shape, dtype=np.uint8)
    oar_out = np.zeros(shape, dtype=np.uint16)
    ctv_names: Dict[int, str] = {}
    oar_names: Dict[int, str] = {}
    oar_counts: Dict[int, int] = {}
    public_items: list[Dict[str, Any]] = []
    used_ctv: set[int] = set()
    used_oar: set[int] = set()

    # Generic masks are explicit user-promoted structures.  Apply them after
    # the original CTV/OAR sources so an intentional move is visible in the
    # effective label volume when the masks overlap an older source.
    for item in sorted(
        source_items,
        key=lambda row: (
            1 if str(row.get("source") or "") == "generic_segmentation" else 0,
            row["object_id"],
        ),
    ):
        object_id = item["object_id"]
        if object_id in deleted:
            continue
        override = overrides.get(object_id) if isinstance(overrides, Mapping) else None
        classification = str(
            (override or {}).get("classification") or item["source_classification"]
        ).lower()
        if classification not in {"ctv", "oar"}:
            raise StructureError(f"Invalid classification for {object_id}")
        preferred = int((override or {}).get("target_label") or item["source_label"] or 1)
        if classification == "ctv":
            target_label = _allocate_label(preferred, used_ctv, 255)
            ctv_out[item["mask"]] = target_label
            ctv_names[target_label] = str(item["name"])
        else:
            target_label = _allocate_label(preferred, used_oar, 65535)
            oar_out[item["mask"]] = target_label
            oar_names[target_label] = str(item["name"])
            oar_counts[target_label] = int(np.count_nonzero(item["mask"]))
        public_items.append({
            **item,
            "classification": classification,
            "target_label": target_label,
            "voxel_count": int(np.count_nonzero(item["mask"])),
        })

    return EffectiveStructures(
        ctv_out if np.any(ctv_out) else None,
        oar_out if np.any(oar_out) else None,
        ctv_names,
        oar_names,
        oar_counts,
        public_items,
    )


def initialize_structure_registry(memory: Any) -> None:
    if memory.retrieve("structure_registry_initialized"):
        return
    updates = {
        "structure_registry_initialized": True,
        "structure_base_ctv_array": _copy_array(memory.retrieve("ctv_array")),
        "structure_base_ctv_full_labels": _copy_array(memory.retrieve("ctv_full_labels")),
        "structure_base_ctv_label_map": dict(memory.retrieve("ctv_label_map") or {}),
        "structure_base_ctv_source": str(memory.retrieve("ctv_source") or ""),
        "structure_base_oar_array": _copy_array(memory.retrieve("oar_array"), dtype=np.uint16),
        "structure_base_organ_names": dict(memory.retrieve("organ_names") or {}),
        "structure_base_oar_source": str(memory.retrieve("oar_source") or ""),
        "structure_overrides": {},
        "structure_deleted_ids": [],
    }
    _batch_memory_update(memory, updates)


def ensure_structure_registry_for_hydrated_uploads(memory: Any) -> bool:
    """Migrate a legacy promoted Upload Mask into the source registry.

    Before the Structure Set transaction was introduced, a browser could show
    an uploaded label under CTV while the durable memory still contained only
    the raw multi-label ``ctv_array``.  Rebuilding an effective set from that
    state would either duplicate the uploaded label or, worse, reintroduce
    every positive label from the source file after a restart.  This helper is
    intentionally called only during hydration when an explicit uploaded
    child classification is present.  It establishes the immutable base
    source first, then lets ``build_effective_structures`` union the promoted
    children.

    A raw CTV/OAR volume is excluded from the migrated base only when its
    provenance explicitly points to an uploaded/manual source (or its path
    matches a promoted upload).  An unrelated model segmentation is retained;
    the migration must never infer a clinical deletion from a UI placement.
    Returns whether the registry was created.
    """
    if memory.retrieve("structure_registry_initialized"):
        return False

    generic = memory.retrieve("generic_segmentation_masks") or []
    if not isinstance(generic, list):
        return False

    uploaded_sources = {
        "manual_label",
        "manual_upload",
        "uploaded",
        "uploaded_unknown",
        "label_path",
    }

    def uploaded_promotions(classification: str) -> list[Mapping[str, Any]]:
        result = []
        for item in generic:
            if not isinstance(item, Mapping):
                continue
            if _explicit_structure_classification(item) != classification:
                continue
            source = str(item.get("source") or "").strip().lower()
            kind = str(item.get("kind") or "").strip().lower()
            if (
                source == "uploaded_mask"
                or kind == "uploaded_mask_label"
                or str(item.get("upload_mask_id") or "").strip()
            ):
                result.append(item)
        return result

    def same_path(left: Any, right: Any) -> bool:
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if not left_text or not right_text:
            return False
        try:
            return Path(left_text).expanduser().resolve() == Path(right_text).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return left_text == right_text

    def should_drop_raw(classification: str, promotions: list[Mapping[str, Any]]) -> bool:
        if not promotions:
            return False
        current_source = str(
            memory.retrieve("ctv_source" if classification == "ctv" else "oar_source")
            or ""
        ).strip().lower()
        path_keys = (
            ("ctv_mask_path", "ctv_path", "label_path", "ctv_source_path")
            if classification == "ctv"
            else ("oar_mask_path", "oar_path", "oar_source_path")
        )
        current_paths = [memory.retrieve(key) for key in path_keys]
        for item in promotions:
            source_path = item.get("source_path")
            if source_path and any(same_path(source_path, path) for path in current_paths):
                return True
        # ``manual_label`` is the provenance used by the old upload route.  If
        # the snapshot also contains an explicitly promoted Upload Mask child,
        # the raw volume belongs to that source unless a distinct path above
        # proves otherwise.
        return current_source in uploaded_sources

    def base_values(classification: str) -> tuple[Any, Any, Dict[int, Any], str]:
        if classification == "ctv":
            promotions = uploaded_promotions("ctv")
            drop = should_drop_raw("ctv", promotions)
            return (
                None if drop else _copy_array(memory.retrieve("ctv_array")),
                None if drop else _copy_array(memory.retrieve("ctv_full_labels")),
                {} if drop else dict(memory.retrieve("ctv_label_map") or {}),
                "" if drop else str(memory.retrieve("ctv_source") or ""),
            )
        promotions = uploaded_promotions("oar")
        drop = should_drop_raw("oar", promotions)
        return (
            None if drop else _copy_array(memory.retrieve("oar_array"), dtype=np.uint16),
            None,
            {} if drop else dict(memory.retrieve("organ_names") or {}),
            "" if drop else str(memory.retrieve("oar_source") or ""),
        )

    ctv_array, ctv_full, ctv_map, ctv_source = base_values("ctv")
    oar_array, _, organ_names, oar_source = base_values("oar")
    updates = {
        "structure_registry_initialized": True,
        "structure_base_ctv_array": ctv_array,
        "structure_base_ctv_full_labels": ctv_full,
        "structure_base_ctv_label_map": ctv_map,
        "structure_base_ctv_source": ctv_source,
        "structure_base_oar_array": oar_array,
        "structure_base_organ_names": organ_names,
        "structure_base_oar_source": oar_source,
        "structure_overrides": dict(memory.retrieve("structure_overrides") or {}),
        "structure_deleted_ids": list(memory.retrieve("structure_deleted_ids") or []),
    }
    _batch_memory_update(memory, updates)
    return True


def replace_structure_source(memory: Any, classification: str) -> EffectiveStructures:
    """Replace one authoritative segmentation source after a real rerun/import.

    Classification overrides and deletions are source-object transactions. A
    newly generated CTV or OAR is a new source version, so mutations belonging
    to that source must not be replayed onto unrelated labels. Mutations of the
    other source remain intact.
    """
    classification = str(classification or "").strip().lower()
    if classification not in {"ctv", "oar"}:
        raise StructureError("Structure source must be ctv or oar")

    initialize_structure_registry(memory)
    source_prefixes = (
        ("structure:ctv:", "structure:embedded:")
        if classification == "ctv"
        else ("structure:oar:",)
    )
    overrides = {
        key: value
        for key, value in dict(memory.retrieve("structure_overrides") or {}).items()
        if not str(key).startswith(source_prefixes)
    }
    deleted = [
        value
        for value in (memory.retrieve("structure_deleted_ids") or [])
        if not str(value).startswith(source_prefixes)
    ]
    if classification == "ctv":
        updates = {
            "structure_base_ctv_array": _copy_array(memory.retrieve("ctv_array")),
            "structure_base_ctv_full_labels": _copy_array(memory.retrieve("ctv_full_labels")),
            "structure_base_ctv_label_map": dict(memory.retrieve("ctv_label_map") or {}),
            "structure_base_ctv_source": str(memory.retrieve("ctv_source") or ""),
        }
    else:
        updates = {
            "structure_base_oar_array": _copy_array(memory.retrieve("oar_array"), dtype=np.uint16),
            "structure_base_organ_names": dict(memory.retrieve("organ_names") or {}),
            "structure_base_oar_source": str(memory.retrieve("oar_source") or ""),
        }
    _batch_memory_update(memory, {
        **updates,
        "structure_overrides": overrides,
        "structure_deleted_ids": deleted,
    })
    effective = build_effective_structures(memory)
    _commit_effective(memory, effective, f"{classification} segmentation source replaced")
    return effective


def _stale_updates(memory: Any, reason: str) -> Dict[str, Any]:
    planning_version = int(memory.retrieve("planning_version", 0) or 0) + 1
    updates = {
        "planning_version": planning_version,
        "structure_artifact_status": {
            "planning": "stale",
            "dose": "stale",
            "dvh": "stale",
            "evaluation": "stale",
            "report": "stale",
            "surgical_guide": "stale",
            "reason": reason,
            "updated_at": _utc_now(),
            "planning_version": planning_version,
        },
        "manual_artifact_status": {
            "planning": "stale",
            "dose": "stale",
            "dvh": "stale",
            "report": "stale",
            "quality_check": "stale",
            "surgical_guide": "stale",
            "reason": reason,
            "updated_at": _utc_now(),
            "planning_version": planning_version,
        },
    }
    guide = memory.retrieve("surgical_guide")
    if isinstance(guide, dict):
        # Reclassification changes the structure references consumed by the
        # plan. Keep the mesh and its metadata for inspection, but prevent an
        # old guide from being presented as the current clinical result.
        guide_update = dict(guide)
        guide_update["status"] = "stale"
        guide_update["stale_reason"] = reason
        guide_update["updated_at"] = _utc_now()
        updates["surgical_guide"] = guide_update
    return updates


def _commit_effective(memory: Any, effective: EffectiveStructures, reason: str) -> None:
    ctv_source_object_ids = [
        str(item.get("object_id"))
        for item in effective.structures
        if str(item.get("classification") or "").strip().lower() == "ctv"
        and item.get("object_id")
    ]
    updates = {
        "ctv_array": effective.ctv_array,
        "ctv_mask": effective.ctv_array,
        # The label-coded array is retained for viewer/Data Tree presentation;
        # this binary companion is the unambiguous planning/DVH target contract
        # and is the union of every CTV source object.
        "ctv_binary_array": (
            (np.asarray(effective.ctv_array) > 0).astype(np.uint8)
            if effective.ctv_array is not None else None
        ),
        "ctv_source_object_ids": ctv_source_object_ids,
        "ctv_label_map": effective.ctv_label_map,
        "ctv_source": "classified",
        "oar_array": effective.oar_array,
        "organ_names": effective.organ_names,
        "organ_counts": effective.organ_counts,
        "oar_source": "classified",
        "structure_catalog": effective.public_catalog(),
        **_stale_updates(memory, reason),
    }
    _batch_memory_update(memory, updates, removals=_DOWNSTREAM_KEYS)


def reclassify_structure(memory: Any, object_id: str, classification: str) -> EffectiveStructures:
    return reclassify_structures(memory, [object_id], classification)


def reclassify_generic_segmentation_masks(
    memory: Any,
    object_ids: Iterable[str],
    classification: str,
) -> EffectiveStructures:
    """Promote open segmentation masks into the effective Structure Set.

    The generic mask remains stored under ``generic_segmentation_masks`` so
    its original voxel data and stable identity are preserved.  Classification
    is the only mutable business field; the effective CTV/OAR arrays are then
    rebuilt in one transaction and all dependent clinical artifacts are marked
    stale by ``_commit_effective``.
    """
    destination = str(classification or "").strip().lower()
    if destination not in {"ctv", "oar"}:
        raise StructureError("Generic masks can only move to CTV or OAR")
    requested = {str(value or "").strip() for value in object_ids if str(value or "").strip()}
    if not requested:
        raise StructureError("No generic masks were selected")
    requested = {
        value if value.startswith("mask:") else f"mask:{value}"
        for value in requested
    }

    initialize_structure_registry(memory)
    existing = memory.retrieve("generic_segmentation_masks") or []
    if not isinstance(existing, list):
        existing = []

    # Use the current CT/structure grid as the spatial contract.  A mask from
    # another grid must be aligned/imported first; silently broadcasting it
    # would corrupt dose evaluation and make the Data Tree lie about geometry.
    reference_shape = None
    for value in (
        memory.retrieve("ct_data"),
        memory.retrieve("structure_base_ctv_array"),
        memory.retrieve("structure_base_oar_array"),
    ):
        candidate = _copy_array(value)
        if candidate is not None:
            reference_shape = tuple(candidate.shape)
            break

    updated: list[Dict[str, Any]] = []
    matched: set[str] = set()
    for raw_entry in existing:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = dict(raw_entry)
        mask_id = str(entry.get("mask_id") or "").strip()
        stable_id = str(entry.get("object_id") or f"mask:{mask_id}").strip()
        if not stable_id.startswith("mask:"):
            stable_id = f"mask:{stable_id}"
        if stable_id in requested or f"mask:{mask_id}" in requested:
            mask = _copy_array(entry.get("mask_array"), dtype=np.uint8)
            if mask is None or not np.any(mask):
                raise StructureError(f"Generic segmentation mask is empty: {stable_id}")
            if reference_shape is not None and tuple(mask.shape) != reference_shape:
                raise StructureError(
                    f"Generic segmentation mask grid does not match the current CT: {stable_id}"
                )
            if destination == "ctv":
                from web.uploaded_mask_service import is_uploaded_mask_label

                if is_uploaded_mask_label(entry):
                    # Whole-body/whole-organ labels are allowed to exist as
                    # upload candidates, but they must not become an official
                    # CTV merely because the user clicked Move. Reuse the
                    # same physical plausibility rule as manual CTV import at
                    # this explicit clinical promotion boundary.
                    volume_mm3 = entry.get("volume_mm3")
                    try:
                        volume_mm3 = float(volume_mm3)
                    except (TypeError, ValueError):
                        spacing = entry.get("spacing") or memory.retrieve("ct_spacing") or (1, 1, 1)
                        volume_mm3 = float(np.count_nonzero(mask) * np.prod(np.asarray(spacing, dtype=np.float64)[:3]))
                    try:
                        from tool_factory.CTV_seg import _implausible_manual_ctv_error

                        plausibility_error = _implausible_manual_ctv_error(
                            volume_mm3,
                            int(np.count_nonzero(mask)),
                            memory.retrieve("ct_image"),
                        )
                    except Exception as exc:
                        raise StructureError(
                            f"Could not validate uploaded CTV candidate {stable_id}: {exc}"
                        ) from exc
                    if plausibility_error:
                        raise StructureError(plausibility_error)
                    entry["ctv_promoted_from_upload"] = {
                        "upload_mask_id": str(entry.get("upload_mask_id") or ""),
                        "object_id": stable_id,
                        "source_label": int(entry.get("source_label") or 0),
                        "source_path": str(entry.get("source_path") or ""),
                    }
                    entry["ctv_promoted_at"] = _utc_now()
            entry["object_id"] = stable_id
            entry["classification"] = destination
            entry["parent_group"] = destination
            entry["moved_to"] = destination
            previous_version = entry.get("data_version")
            entry["data_version"] = (
                f"{previous_version}:classification:{destination}"
                if previous_version else f"classification:{destination}"
            )
            matched.add(stable_id)
        updated.append(entry)

    missing = sorted(requested - matched)
    if missing:
        raise StructureError(f"Generic segmentation mask was not found: {missing[0]}")

    _batch_memory_update(memory, {"generic_segmentation_masks": updated})
    effective = build_effective_structures(memory)
    _commit_effective(
        memory,
        effective,
        f"{len(matched)} generic mask(s) moved to {destination}",
    )
    return effective


def reclassify_structures(
    memory: Any,
    object_ids: Iterable[str],
    classification: str,
) -> EffectiveStructures:
    classification = str(classification or "").strip().lower()
    if classification not in {"ctv", "oar"}:
        raise StructureError("Structure classification must be ctv or oar")
    initialize_structure_registry(memory)
    current = {item["object_id"]: item for item in _source_structures(memory)}
    requested = {str(value) for value in object_ids}
    missing = sorted(requested - set(current))
    if missing:
        raise StructureError(f"Structure was not found: {missing[0]}")
    if not requested:
        raise StructureError("No structures were selected")
    overrides = dict(memory.retrieve("structure_overrides") or {})
    for object_id in requested:
        existing = dict(overrides.get(object_id) or {})
        preferred = int(existing.get("target_label") or current[object_id]["source_label"] or 1)
        overrides[object_id] = {
            **existing,
            "classification": classification,
            "target_label": preferred,
            "updated_at": _utc_now(),
        }
    _batch_memory_update(memory, {"structure_overrides": overrides})
    effective = build_effective_structures(memory)
    _commit_effective(
        memory,
        effective,
        f"{len(requested)} structure(s) moved to {classification}",
    )
    return effective


def delete_structure(memory: Any, object_id: str) -> EffectiveStructures:
    return delete_structures(memory, [object_id])


def delete_structures(memory: Any, object_ids: Iterable[str]) -> EffectiveStructures:
    initialize_structure_registry(memory)
    current = {item["object_id"]: item for item in _source_structures(memory)}
    requested = {str(value) for value in object_ids}
    missing = sorted(requested - set(current))
    if missing:
        raise StructureError(f"Structure was not found: {missing[0]}")
    if not requested:
        raise StructureError("No structures were selected")
    deleted = set(memory.retrieve("structure_deleted_ids") or [])
    deleted.update(requested)
    _batch_memory_update(memory, {"structure_deleted_ids": sorted(deleted)})
    effective = build_effective_structures(memory)
    _commit_effective(
        memory,
        effective,
        f"{len(requested)} structure(s) deleted",
    )
    return effective


def structure_catalog(memory: Any) -> list[Dict[str, Any]]:
    if memory.retrieve("structure_registry_initialized"):
        return build_effective_structures(memory).public_catalog()
    return build_effective_structures(memory).public_catalog()


def resolve_structure_object_id(memory: Any, value: str) -> str:
    """Resolve a stable object id or a legacy Data Tree transport id."""
    candidate = str(value or "").strip()
    catalog = structure_catalog(memory)
    if any(item["object_id"] == candidate for item in catalog):
        return candidate
    match = None
    if candidate.startswith("organ_"):
        match = ("oar", candidate.removeprefix("organ_"))
    elif candidate.startswith("ctv_"):
        match = ("ctv", candidate.removeprefix("ctv_"))
    if match is not None:
        classification, raw_label = match
        try:
            label = int(raw_label)
        except ValueError:
            label = -1
        for item in catalog:
            if item["classification"] == classification and int(item["target_label"]) == label:
                return str(item["object_id"])
    raise StructureError("Structure was not found")
