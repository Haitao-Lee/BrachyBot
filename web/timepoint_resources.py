"""Content-based clinical dependencies for a single captured timepoint.

Presentation is deliberately absent. A hidden structure/source still participates
in planning and dose. These fingerprints describe current inputs, not permission
to accept a detection, register anatomy, or reinterpret delivered dose.
"""
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
import hashlib
import json

import numpy as np


DEPENDENCIES = {
    "implanted_dose": ("image", "observation", "source", "model"),
    "planned_dose": ("image", "planned_sources", "source", "model"),
    "total_dose": ("implanted_dose", "planned_dose"),
    "metrics": ("total_dose", "ctv", "oar", "constraints"),
    "supplemental_plan": ("implanted_dose", "ctv", "oar", "obstacle_policy", "guide", "needles", "constraints", "planning_settings"),
    "manufactured_guide": ("image", "planned_sources", "needles", "guide_profile"),
    "report": ("metrics", "supplemental_plan", "manufactured_guide"),
}

INFERENCE_FIELDS = ("image_normalize", "infer_img_size", "dose_cal_features",
                    "dose_spatial_dims", "dose_in_channel", "dose_out_channel")


def fingerprint(value):
    """Stable numerical/content identity; never serialize a live model or path."""
    def canonical(item):
        if isinstance(item, np.ndarray):
            if item.dtype.hasobject:
                raise ValueError("Clinical resource arrays cannot contain objects")
            array = np.ascontiguousarray(item)
            return {"shape": list(array.shape), "dtype": array.dtype.str,
                    "sha256": hashlib.sha256(array.tobytes()).hexdigest()}
        if isinstance(item, np.generic):
            return canonical(item.item())
        if is_dataclass(item):
            return canonical(asdict(item))
        if isinstance(item, Mapping):
            return {str(k): canonical(v) for k, v in sorted(item.items(), key=lambda x: str(x[0]))}
        if isinstance(item, (list, tuple)):
            return [canonical(v) for v in item]
        if isinstance(item, (set, frozenset)):
            return sorted((canonical(v) for v in item), key=lambda v: json.dumps(v, sort_keys=True))
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        raise ValueError("Unsupported clinical resource value: " + type(item).__name__)
    raw = json.dumps(canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def clinical_sources(seeds):
    """Freeze every physical source; UI visibility/opacity do not exclude it."""
    sources = []
    for item in seeds or ():
        if not isinstance(item, Mapping):
            raise ValueError("Source records must contain physical geometry")
        identity = str(item.get("physical_seed_id") or item.get("id") or "")
        if not identity:
            raise ValueError("Dose sources require stable identities")
        center = np.asarray(item.get("physical_position", item.get("position")), dtype=float)
        axis = np.asarray(item.get("direction"), dtype=float)
        if (center.shape != (3,) or axis.shape != (3,) or not np.isfinite(center).all()
                or not np.isfinite(axis).all() or np.linalg.norm(axis) <= 1e-12):
            raise ValueError("Dose sources require finite physical centers and axes")
        weight = float(item.get("weight", 1.0))
        if not np.isfinite(weight) or weight <= 0:
            raise ValueError("Relative source strength must be finite and positive")
        sources.append({"id": identity, "position": center.tolist(),
                        "direction": (axis / np.linalg.norm(axis)).tolist(), "weight": weight})
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("Duplicate physical source identity would double count dose")
    return sorted(sources, key=lambda s: s["id"])


def observation_content(reconstruction):
    if reconstruction is None:
        return None
    value = reconstruction.to_dict() if hasattr(reconstruction, "to_dict") else dict(reconstruction)
    fields = ("observation_id", "physical_seed_id", "detection_id", "center_lps_mm",
              "axis_lps", "dimensions")
    # Numeric dose depends on physical inclusion/geometry, not on a review
    # note, visibility, or the UUID of an otherwise identical signed revision.
    # Head/coverage authorization is independently checked at publication and
    # before continuation; reuse never grants that authorization.
    rows = [{**{k: row.get(k) for k in fields}, "excluded": row.get("review_status") == "rejected"}
            for row in value.get("observations", ())]
    return {"image_ref": value.get("image_ref"),
            "observations": sorted(rows, key=lambda row: str(row.get("observation_id")))}


def capture_resources(retrieve, image, *, reconstruction=None, planned_sources=(),
                      source=None, model_sha256=None, dl_params=None, seed_info=None):
    """Capture the selected current CT and exact downstream clinical inputs."""
    from tool_factory.seed_plan.continuation_support import image_signature
    from plans.dose_pre.model_loader import resolve_prescription_gy
    from utils.ctv_targets import resolve_ctv_target
    from web.planning_config import current_evaluation_config, planning_settings_content
    plan = current_evaluation_config(retrieve)
    defaults = {"image_normalize": [-1000, 3000, 255], "infer_img_size": [64, 64, 64],
                "dose_cal_features": [16, 32, 64, 128, 256], "dose_spatial_dims": 3,
                "dose_in_channel": 3, "dose_out_channel": 1}
    try:
        target = resolve_ctv_target(retrieve)
    except (TypeError, ValueError):
        # Unusable anatomy blocks evaluation/planning, not source-only CNN dose.
        target = {"invalid_current_target": {k: retrieve(k) for k in (
            "ctv_binary_array", "ctv_array", "ctv_full_labels", "ctv_source", "target_semantics")}}
    receipt = retrieve("planning_reference_receipt") or {}
    values = {
        "image": {"content": image_signature(image), "reference_image_id": retrieve("planning_reference_image_id"),
                  "reference": {k: receipt.get(k) for k in ("image_id", "source_sha256", "volume_sha256",
                    "voxel_sha256", "geometry_signature", "frame_index", "modality")}},
        "ctv": {"mask": target, "source": retrieve("ctv_source"),
                "semantics": retrieve("target_semantics"), "model": retrieve("ctv_model_provenance")},
        "oar": {"array": retrieve("oar_array"), "names": retrieve("organ_names")},
        'obstacle_policy': obstacle_policy_content(retrieve),
        "observation": observation_content(reconstruction),
        "planned_sources": clinical_sources(planned_sources),
        "source": {"contract": source, "seed_info": seed_info},
        "model": {"checkpoint_sha256": model_sha256,
                  "preprocessing": {k: (dl_params or {}).get(k, defaults[k]) for k in INFERENCE_FIELDS}},
        "guide": retrieve("continuation_search_record"),
        "needles": retrieve("verified_needle_geometry") or retrieve("manual_needles"),
        "guide_profile": retrieve("surgical_guide_config"),
        "planning_settings": planning_settings_content(retrieve),
        "constraints": {
            **{k: plan.get(k) for k in ("in_lowest_dose_gy", "in_lowest_energy",
                "out_highest_dose_gy", "out_highest_energy", "DVH_rate", "oar_constraints", "tumor_type")},
            # Use the same prescription resolver as total-dose evaluation.
            # This invalidates quality without invalidating numerical dose.
            "resolved_prescription_gy": resolve_prescription_gy(plan),
            "dose_value_unit": plan.get("dose_value_unit"),
            "planning_dose_unit": plan.get("planning_dose_unit"),
        },
    }
    return dependency_fingerprints({name: fingerprint(value) for name, value in values.items()})


def obstacle_policy_content(retrieve):
    """Persisted clinical classification, never colors/visibility/opacity."""
    fields=('classification','traversability','category','target_label','label_id','object_id')
    overrides=retrieve('structure_overrides') or {}
    catalog=retrieve('structure_catalog') or {}
    def rows(value):
        if isinstance(value,Mapping):
            return {str(key):{field:row.get(field) for field in fields if field in row}
                    for key,row in value.items() if isinstance(row,Mapping)}
        if isinstance(value,(list,tuple)):
            return [{field:row.get(field) for field in fields if field in row}
                    for row in value if isinstance(row,Mapping)]
        return None
    return {'overrides':rows(overrides),'catalog':rows(catalog),
        'embedded_mask':retrieve('ctv_embedded_oar_array'),
        'embedded_labels':retrieve('embedded_obstacle_label_ids'),
        'ctv_label_map':retrieve('ctv_label_map')}


def dependency_fingerprints(leaves):
    result = dict(leaves)
    for name, dependencies in DEPENDENCIES.items():
        result[name] = fingerprint({key: result.get(key) for key in dependencies})
    return result


def resource_state(previous, current, *, ready=()):
    """Report exact transitive invalidation; retain inputs for lazy recovery."""
    before = (previous or {}).get("fingerprints", {})
    changed = sorted(name for name, value in current.items() if before.get(name) != value)
    invalidated = [name for name in changed if name in DEPENDENCIES]
    return {"schema_version": 1, "fingerprints": dict(current), "changed": changed,
            "invalidated": invalidated, "reused": sorted(set(current) - set(changed)),
            "ready": sorted(set(ready)), "dependencies": {k: list(v) for k, v in DEPENDENCIES.items()}}


def component_current(record, source_set, resources, image):
    """Payload and grid must match, not only a claimed success/fingerprint."""
    from plans.continuation import grid_signature
    if not isinstance(record, Mapping):
        return False
    if record.get("status") == "stale" or record.get("dose_status") == "stale":
        return False
    key = source_set + "_dose"
    try:
        from utils.dose_units import physical_volume
        dose = physical_volume(record["dose_distribution_physical_gy"], units=record["dose_units"])
        return (record.get("source_set") == source_set and record.get("dose_units") == "physical_gy"
                and record.get("dependency_fingerprint") == resources[key]
                and record.get("grid_signature") == grid_signature(image)
                and dose.shape == tuple(image.GetSize()[::-1])
                and record.get("source_geometry_sha256") == fingerprint(clinical_sources(record.get("source_geometry") or ()))
                and record.get("dose_sha256") == fingerprint(dose))
    except (KeyError, TypeError, ValueError):
        return False
