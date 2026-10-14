"""Main-pipeline continuation boundaries, including restart and input identity.

This is server-owned state, not an LLM schema parameter. It never infers a
source strength, accepts an unreviewed implant, or registers a printed guide.
"""
from collections.abc import Mapping
import hashlib
import numpy as np

from plans.continuation import (ContinuationBaseline, grid_signature, array_sha256,
                                continuation_candidates)


def image_signature(image):
    import SimpleITK as sitk
    # Axis reordering by the product's normal LPI loader changes array layout
    # but not the captured physical image. Compare the same canonical layout;
    # this still rejects a different image with identical frame metadata.
    canonical = sitk.DICOMOrient(image, "LPI")
    digest = hashlib.sha256(grid_signature(canonical).encode())
    digest.update(array_sha256(sitk.GetArrayFromImage(canonical)).encode())
    return digest.hexdigest()


def baseline_record(baseline, current_image, *, observation_revision_id=None, timepoint_id=None):
    if not isinstance(baseline, ContinuationBaseline):
        raise TypeError("A validated ContinuationBaseline is required")
    if (observation_revision_id is None) != (timepoint_id is None):
        raise ValueError("Observation and timepoint identities must be captured together")
    if timepoint_id is not None:
        from uuid import UUID
        UUID(str(observation_revision_id))
        from web.timepoints import timepoint_id as validate_id
        validate_id(timepoint_id)
    return {"schema_version": 2, "current_image_signature": image_signature(current_image),
            "observation_revision_id": observation_revision_id, "timepoint_id": timepoint_id,
            "baseline": baseline.to_record()}


def resolve_baseline(agent, *, current_image=None, explicit=None):
    retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
    saved = retrieve("continuation_baseline_record")
    if saved is not None:
        validate_observation_binding(agent, saved)
        validate_source_binding(agent, saved)
        geometry_binding=retrieve('continuation_geometry_binding_sha256')
        if geometry_binding is not None and geometry_binding != continuation_geometry_signature(retrieve):
            raise ValueError('Current guide, in-situ needles or needle constraints changed; refresh continuation preparation')
        anatomy_binding = retrieve("continuation_anatomy_binding_sha256")
        if anatomy_binding is not None:
            from web.continuation_service import anatomy_binding_signature
            image = current_image if current_image is not None else retrieve("ct_image")
            if image is None or anatomy_binding != anatomy_binding_signature(retrieve, image):
                raise ValueError("Current CTV/OAR/reference changed; refresh continuation preparation before planning")
    if explicit is not None:
        if not isinstance(explicit, ContinuationBaseline):
            raise TypeError("Continuation may only be injected by the server as a typed baseline")
        # Supplied baseline and saved captured inputs cannot silently disagree.
        if saved is not None:
            restored = resolve_saved_baseline(saved, current_image)
            if array_sha256(restored.dose_model) != array_sha256(explicit.dose_model):
                raise ValueError("Explicit continuation conflicts with saved baseline")
            if (restored.baseline_grid_signature != explicit.baseline_grid_signature
                    or restored.dose_contract_id != explicit.dose_contract_id
                    or restored.dose_scale_gy != explicit.dose_scale_gy
                    or restored.fixed_seeds != explicit.fixed_seeds
                    or restored.fixed_needles != explicit.fixed_needles
                    or restored.candidate_paths != explicit.candidate_paths
                    or restored.needle_radius_mm != explicit.needle_radius_mm
                    or restored.clearance_mm != explicit.clearance_mm
                    or not np.array_equal(restored.complete_target_mask, explicit.complete_target_mask)
                    or [(n, array_sha256(m)) for n, m in restored.oar_masks] != [(n, array_sha256(m)) for n, m in explicit.oar_masks]):
                raise ValueError("Explicit continuation conflicts with saved geometry or source contract")
        return explicit
    if saved is not None:
        return resolve_saved_baseline(saved, current_image)
    scope = retrieve("timepoint_context") or {}
    captured = getattr(agent, "_workspace_timepoint_context", None)
    stage = captured.target.stage if captured is not None else scope.get("stage") if isinstance(scope, Mapping) else None
    if stage == "intraoperative":
        raise ValueError("Intraoperative planning requires a reviewed, current-image fixed-dose baseline; zero-based fallback is disabled")
    return None


def resolve_saved_baseline(record, image=None):
    base_fields = {"schema_version", "current_image_signature", "baseline"}
    if not isinstance(record, Mapping):
        raise ValueError("Invalid captured continuation input")
    version = record.get("schema_version")
    allowed = base_fields if version == 1 else base_fields | {"observation_revision_id", "timepoint_id"}
    if set(record) != allowed:
        raise ValueError("Invalid captured continuation input")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("Unsupported captured continuation input")
    if image is not None and record["current_image_signature"] != image_signature(image):
        raise ValueError("The intraoperative image changed; reconstruct implants and recompute the fixed baseline")
    return ContinuationBaseline.from_record(record["baseline"])


def validate_observation_binding(agent, record):
    """A review correction must invalidate an old dose even on unchanged CT."""
    retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
    catalog = retrieve("implanted_seed_reconstruction")
    if catalog is None:
        if isinstance(record, Mapping) and record.get("observation_revision_id") is not None:
            raise ValueError("The captured implant observation is unavailable; restore it before continuation")
        return  # Typed standalone synthetic/research input, no claimed detector evidence.
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get("by_timepoint"), Mapping):
        raise ValueError("Implant observation catalog is invalid")
    target = record.get("timepoint_id") if isinstance(record, Mapping) else None
    entry = catalog["by_timepoint"].get(target)
    current = entry.get("current") if isinstance(entry, Mapping) else None
    reconstruction = current.get("reconstruction") if isinstance(current, Mapping) else None
    if not isinstance(reconstruction, Mapping) or record.get("observation_revision_id") != reconstruction.get("revision_id"):
        raise ValueError("Implant observation revision changed or was not bound; recompute the fixed baseline")
    from utils.implant_reconstruction import SeedAxisReconstruction
    typed = SeedAxisReconstruction.from_dict(reconstruction)
    if typed.image_ref.timepoint_id != target or not typed.dose_input_ready:
        raise ValueError("The captured implant geometry/coverage review is incomplete")
    baseline = ContinuationBaseline.from_record(record["baseline"])
    accepted = [s for s in typed.observations if s.review_status == "accepted"]
    if len(accepted) != len(baseline.fixed_seeds):
        raise ValueError("The fixed baseline does not contain exactly the reviewed implanted set")
    # Observation identities are a separate namespace from physical identity.
    # Compare geometry without forcing an unproved preoperative assignment.
    unmatched = list(accepted)
    for fixed in baseline.fixed_seeds:
        match = next((s for s in unmatched if (
            np.allclose(s.center_lps_mm, fixed.center_lps_mm, rtol=0, atol=1e-6)
            and abs(float(np.dot(s.axis_lps, fixed.axis_lps))) >= 1 - 1e-8
            and abs(s.dimensions.capsule_length_mm - fixed.length_mm) <= 1e-6
            and abs(s.dimensions.capsule_diameter_mm / 2 - fixed.radius_mm) <= 1e-6
            and (s.physical_seed_id is None or s.physical_seed_id == fixed.physical_seed_id))), None)
        if match is None:
            raise ValueError("Fixed seed geometry differs from the reviewed observation")
        unmatched.remove(match)


def load_continuation_model(agent, baseline):
    """Bind every supplemental map to the same reviewed checkpoint/calibration."""
    retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
    contract = retrieve("continuation_source_contract")
    if contract is None:
        return None  # Existing typed standalone tests do not claim source review.
    if not isinstance(contract, Mapping) or contract.get("contract_id") != baseline.dose_contract_id or contract.get("dose_scale_gy") != baseline.dose_scale_gy:
        raise ValueError("Continuation source/calibration contract changed")
    from tool_factory.seed_seg.seedfinder_adapter import sha256_file
    from pathlib import Path
    path = Path(retrieve("continuation_dose_model_path")).resolve(strict=True)
    if sha256_file(path) != contract.get("dose_model_sha256"):
        raise ValueError("The calibrated CNN checkpoint changed; rebuild the fixed baseline")
    from .model_support import resolve_dose_model
    params = dict(retrieve("continuation_dl_params") or {})
    params["dose_model_path"] = str(path)
    return resolve_dose_model({}, params)


def source_contract_signature(contract):
    import json
    return hashlib.sha256(json.dumps(dict(contract), sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


class ContinuationSourceGeometryMismatch(ValueError):
    code = 'continuation_source_geometry_mismatch'


def same_continuation_source_geometry(requested, reviewed):
    """Spacing policy is not the physical source/capsule geometry.

    `margin_rate` and `seed_avr_dose` are placement/search heuristics, not
    DoseUNet source geometry/calibration. The independent source contract still
    binds model, calibration and nominal strength. Physical and unknown fields remain
    strict; this never permits length/radius/model changes to the fixed facts.
    """
    if not isinstance(requested, Mapping) or not isinstance(reviewed, Mapping):
        return False
    placement_fields = {'margin_rate', 'seed_avr_dose'}
    return ({key: value for key, value in requested.items() if key not in placement_fields}
            == {key: value for key, value in reviewed.items() if key not in placement_fields})


def validate_source_binding(agent, record):
    """Even a zero-addition result must use its original source/calibration."""
    retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
    contract = retrieve("continuation_source_contract")
    if contract is None:
        return  # Explicit standalone numerical baselines have no claimed source review.
    baseline = ContinuationBaseline.from_record(record["baseline"])
    if (not isinstance(contract, Mapping) or contract.get("contract_id") != baseline.dose_contract_id
            or contract.get("dose_scale_gy") != baseline.dose_scale_gy
            or retrieve("continuation_source_binding_sha256") != source_contract_signature(contract)):
        raise ValueError("Continuation source/calibration/time contract changed; rebuild the fixed baseline")
    inference_binding = retrieve("continuation_inference_binding_sha256")
    if inference_binding is not None and inference_binding != inference_settings_signature(retrieve):
        raise ValueError("Continuation source geometry or CNN preprocessing changed; rebuild the fixed baseline")
    from tool_factory.seed_seg.seedfinder_adapter import sha256_file
    from pathlib import Path
    path = Path(retrieve("continuation_dose_model_path")).resolve(strict=True)
    if sha256_file(path) != contract.get("dose_model_sha256"):
        raise ValueError("The calibrated CNN checkpoint changed; rebuild the fixed baseline")


def inference_settings_signature(retrieve):
    from web.timepoint_resources import fingerprint, INFERENCE_FIELDS
    dl = retrieve("continuation_dl_params") or {}
    return fingerprint({"seed_info": retrieve("continuation_input_seed_info"),
                        "profile": retrieve("implant_dose_profile") or {},
                        "preprocessing": {key: dl.get(key) for key in INFERENCE_FIELDS}})


def continuation_geometry_signature(retrieve):
    from web.timepoint_resources import fingerprint
    return fingerprint({key:retrieve(key) for key in ('guide_placement','continuation_review_profile',
        'in_situ_needles','guide_channel_states','continuation_search_policy','continuation_search_record')})


def pipeline_baseline(config, agent, image=None, *, allow_unplaced_guide=False):
    value = (config or {}).get("_continuation_baseline")
    baseline = resolve_baseline(agent, current_image=image, explicit=value)
    retrieve = getattr(getattr(agent, "memory", None), "retrieve", lambda *_: None)
    requirement = retrieve("continuation_guide_requirement")
    if (not allow_unplaced_guide and isinstance(requirement, Mapping) and requirement.get("manufactured_guide_present")
            and not requirement.get("placement_prepared") and not baseline_reaches_target(baseline, config)):
        raise ValueError("The associated printed guide has not been placed/reviewed; dose evaluation is available but additional path planning is blocked")
    return baseline


def realized_candidates(baseline, image):
    """Real channel geometries replace, rather than supplement, freehand init."""
    if baseline is None or baseline.candidate_paths is None:
        return None
    baseline.validate_grid(image)
    candidates = [[np.array(p.geometry[0]), np.array(p.geometry[1]),
                   list(p.geometry[2]), list(p.geometry[3]), sum(p.geometry[2])]
                  for p in baseline.candidate_paths]
    return continuation_candidates(baseline, candidates, image)


def baseline_reaches_target(baseline, config):
    if baseline is None:
        return False
    from plans.config import setting
    from tool_factory.seed_plan.planning_pipeline import _apply_planning_overrides
    from .model_support import continuation_dose_threshold
    args = _apply_planning_overrides(setting(), config or {})
    threshold = continuation_dose_threshold(args.in_lowest_energy, getattr(args, "dose_value_unit", "gy"), baseline)
    return float(np.mean(baseline.dose_model[baseline.complete_target_mask] >= threshold)) >= float(args.DVH_rate)
