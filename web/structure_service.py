"""Authoritative structure classification and deletion transactions.

The browser Data Tree is a presentation of this state, never the source of
truth.  A structure keeps one stable ``object_id`` while its CTV/OAR
classification and transport label may change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    "dose_metrics",
    "dvh_data",
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
    if value is None:
        return None
    array = np.asarray(value, dtype=dtype)
    if array.ndim != 3:
        return None
    return np.array(array, copy=True)


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

    if source == "model" and full_labels is not None:
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
    if ctv_source == "model" and full is not None and oar_source not in {
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

    for item in sorted(source_items, key=lambda row: row["object_id"]):
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
            "reason": reason,
            "updated_at": _utc_now(),
            "planning_version": planning_version,
        },
    }
    # A puncture guide depends only on the planned needle geometry and the CT
    # skin surface, neither of which changes when structures are reclassified
    # or deleted in the Data Tree. Marking it stale here made a valid guide
    # disappear (status=stale blocked display even though the plan signature
    # still matched). Guide invalidation is owned by the needle-geometry edit
    # paths (planning_routes manual needle/seed updates), so leave the guide
    # untouched here.
    return updates


def _commit_effective(memory: Any, effective: EffectiveStructures, reason: str) -> None:
    updates = {
        "ctv_array": effective.ctv_array,
        "ctv_mask": effective.ctv_array,
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
