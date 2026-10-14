"""Assemble one grid-consistent ``dose_evaluation`` input tuple from memory.

The workspace keeps dose arrays on several grids and in two unit systems:
``dose_distribution_gy`` and ``dose_distribution_physical_gy`` are physical Gy
in schema 2; historical fields require explicit units/provenance. ``dose_distribution`` is the
planning-grid model output.  Masks live either on the CT grid (``ctv_array`` /
``oar_array``) or on the resampled planning grid (``resampled_ctv`` /
``resampled_oar``).  Pairing the stale planning-grid dose alias with CT-grid
masks failed with "ctv_mask shape must match dose_array", which the chat
surface then misreported as "planning not completed" on an already-finished
case.  This resolver pairs dose and masks by grid and converts dose to Gy the
same way the published metrics were computed.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from .model_loader import (
    DEFAULT_PRESCRIPTION_GY,
    resolve_dose_scale_gy,
    resolve_prescription_gy,
)

Retrieve = Callable[..., Any]

MISSING_INPUT_ERROR = (
    "dose_array and ctv_mask are required but not loaded in the workspace: "
    "no CTV mask or dose distribution is available for dose_evaluation"
)

# Workspace dose keys paired with the factor that converts them to Gy.
# Historical poorly named fields cross the explicit units adapter.
_DOSE_SOURCES_GY = (
    ("dose_distribution_physical_gy", "physical"),
    ("dose_distribution_gy", "declared"),
    ("dose_distribution_current_normalized", "normalized_model"),
    ("dose_distribution", "declared"),
)


def _as_array(value: Any) -> Optional[np.ndarray]:
    """Return a usable ndarray for a workspace value, else None."""
    if value is None:
        return None
    if hasattr(value, "GetArrayFromImage"):
        try:
            value = value.GetArrayFromImage()
        except Exception:
            return None
    try:
        array = np.asarray(value)
    except Exception:
        return None
    if array.dtype == object or array.ndim == 0:
        return None
    return array


def _planning_grid_spacing(retrieve: Retrieve) -> Optional[list]:
    resampled_ct = retrieve("resampled_ct")
    get_spacing = getattr(resampled_ct, "GetSpacing", None)
    if callable(get_spacing):
        try:
            spacing = [float(v) for v in get_spacing()][:3]
            if len(spacing) == 3:
                return spacing
        except Exception:
            pass
    return None


def resolve_dose_evaluation_inputs(retrieve: Retrieve) -> Dict[str, Any]:
    """Resolve injected ``dose_evaluation`` parameters from workspace memory.

    Returns ``{"resolution_error": None, "params": {...}}`` on success with one
    shared-grid tuple: ``dose_array`` in Gy, ``ctv_mask``, optional ``oar_mask``
    and defaults for ``prescribed_dose`` / ``organ_names`` / ``spacing`` /
    ``tumor_type``.  On failure ``resolution_error`` carries an actionable
    error string ("… are required but not loaded" or "… grids do not match")
    and ``params`` is empty.
    """
    if not callable(retrieve):
        return {"resolution_error": MISSING_INPUT_ERROR, "params": {}}

    from web.planning_config import current_evaluation_config
    plan_config = current_evaluation_config(retrieve)
    # QA may be stale after changing Rx while the physical dose is reusable.
    # A source/geometry edit, however, invalidates dose itself; evaluating a
    # retained array would falsely restore clinical authority.
    from collections.abc import Mapping
    from utils.resource_status import resource_is_stale
    for key in ("manual_artifact_status", "artifact_status"):
        status = retrieve(key)
        if isinstance(status, Mapping) and resource_is_stale(status.get("dose")):
            return {"resolution_error": "Current source dose is stale; recompute dose before evaluation", "params": {}}
    bundle = retrieve("dose_components")
    total = None
    if bundle is not None:
        try:
            from web.timepoint_resources import capture_resources, component_current, fingerprint
            from web.dose_components import total_component
            image = retrieve("ct_image")
            if not isinstance(bundle, Mapping) or image is None:
                raise ValueError("Missing current-image dose components")
            resources = (retrieve("timepoint_resource_state") or {}).get("fingerprints") or {}
            if resources.get("image") != capture_resources(retrieve, image)["image"]:
                raise ValueError("The dose acquisition is no longer current")
            if not all(component_current(bundle.get(name), name, resources, image)
                       for name in ("implanted", "planned")):
                raise ValueError("Source dose components are stale for the current inputs")
            total = total_component(bundle["implanted"], bundle["planned"], resources)
            if fingerprint(total) != fingerprint(bundle.get("total")):
                raise ValueError("Total dose differs from its current source components")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            return {"resolution_error": f"Current source dose is stale; recompute dose before evaluation: {exc}", "params": {}}
    previous_metrics = retrieve("dose_metrics") or retrieve("metrics") or {}
    if not isinstance(previous_metrics, dict):
        previous_metrics = {}
    from utils.dose_units import calibrated_scale, physical_volume, workspace_field_units, MODEL_UNITS
    dose_scale = None

    def _first(*keys: str) -> Any:
        # NumPy arrays do not define a scalar truth value; never select
        # workspace values with ``or``.
        for key in keys:
            value = retrieve(key)
            if value is not None:
                return value
        return None

    from utils.ctv_targets import resolve_ctv_target, project_target
    try:
        ct_grid_ctv = resolve_ctv_target(retrieve)
        plan_grid_ctv = project_target(
            retrieve("resampled_ctv"), source=retrieve("ctv_source"),
            semantics=retrieve("target_semantics"),
        )
    except ValueError as exc:
        return {"resolution_error": str(exc), "params": {}}
    ct_grid_oar = _as_array(_first("oar_array", "oar_label_data"))
    plan_grid_oar = _as_array(retrieve("resampled_oar"))
    ct_spacing = retrieve("ct_spacing")
    try:
        ct_spacing = [float(v) for v in ct_spacing][:3] if ct_spacing is not None else None
    except (TypeError, ValueError):
        ct_spacing = None

    mask_pairs: Tuple[Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[list]], ...] = (
        (ct_grid_ctv, ct_grid_oar, ct_spacing),
        # A resampled grid cannot inherit the acquisition grid's voxel volume.
        # Even matching array shapes do not establish matching physical spacing.
        (plan_grid_ctv, plan_grid_oar, _planning_grid_spacing(retrieve)),
    )

    seen_shapes = []
    oar_mismatch = False
    sources = (("dose_components.total", "physical"),) if total is not None else _DOSE_SOURCES_GY
    for dose_key, unit in sources:
        dose = _as_array(total["dose_distribution_physical_gy"] if total is not None else retrieve(dose_key))
        if dose is None:
            continue
        seen_shapes.append((dose_key, dose.shape))
        for ctv, oar, spacing in mask_pairs:
            if ctv is None or ctv.shape != dose.shape:
                continue
            oar_in = oar if (oar is not None and oar.shape == dose.shape) else None
            if (ct_grid_oar is not None or plan_grid_oar is not None) and oar_in is None:
                oar_mismatch = True
                continue
            try:
                if spacing is None or len(spacing) != 3 or not np.isfinite(spacing).all() or np.any(np.asarray(spacing) <= 0):
                    raise ValueError("Valid dose-grid spacing is required for volume and Dxcc evaluation")
                field_unit = workspace_field_units(retrieve, dose_key) if unit == "declared" else (
                    "physical_gy" if unit == "physical" else unit)
                if field_unit in MODEL_UNITS:
                    dose_scale = calibrated_scale(previous_metrics, plan_config, explicit=retrieve("dose_scale_gy"))
                dose_gy = physical_volume(dose, units=field_unit, scale=dose_scale)
            except (ValueError, TypeError) as exc:
                return {"resolution_error": str(exc), "params": {}}
            params: Dict[str, Any] = {
                "dose_array": dose_gy,
                "ctv_mask": ctv,
                "target_semantics": "single_target",
                "prescribed_dose": resolve_prescription_gy(
                    plan_config,
                    previous_metrics,
                    dose_scale_gy=dose_scale,
                    default_gy=DEFAULT_PRESCRIPTION_GY,
                ),
                "organ_names": retrieve("organ_names") or {},
                "tumor_type": str(
                    plan_config.get("tumor_type") or retrieve("tumor_type_used") or retrieve("tumor_type") or ""
                ),
                "oar_constraints": plan_config.get("oar_constraints") or {},
            }
            if not isinstance(params["organ_names"], dict):
                params["organ_names"] = {}
            if isinstance(spacing, (list, tuple)) and len(spacing) == 3:
                params["spacing"] = list(spacing)
            if oar_in is not None:
                params["oar_mask"] = oar_in
            return {"resolution_error": None, "params": params}

    if not seen_shapes:
        return {"resolution_error": MISSING_INPUT_ERROR, "params": {}}
    if oar_mismatch:
        return {"resolution_error": "Loaded OAR and dose grids do not match; OAR evaluation cannot be silently omitted", "params": {}}

    mask_shapes = [
        (name, mask.shape)
        for name, mask in (
            ("ctv_mask", ct_grid_ctv),
            ("ctv_mask(resampled)", plan_grid_ctv),
        )
        if mask is not None
    ]
    if not mask_shapes:
        return {"resolution_error": MISSING_INPUT_ERROR, "params": {}}
    detail = ", ".join(
        f"{name}={tuple(int(v) for v in shape)}"
        for name, shape in (seen_shapes[:2] + mask_shapes[:2])
    )
    return {
        "resolution_error": (
            "dose_array and ctv_mask grids do not match "
            f"({detail}); no workspace dose shares the mask grid, "
            "so dose_evaluation cannot run on this pair"
        ),
        "params": {},
    }
