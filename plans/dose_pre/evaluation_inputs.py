"""Assemble one grid-consistent ``dose_evaluation`` input tuple from memory.

The workspace keeps dose arrays on several grids and in two unit systems:
``dose_distribution_gy`` is *normalized model output* (a historical key name),
``dose_distribution_physical_gy`` is true Gy, and ``dose_distribution`` is the
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
# ``dose_distribution_gy`` stays normalized model output by contract (see the
# store sites in chat_workflows/server_support), so it carries the plan's
# calibration; the physical-Gy grid is already Gy.
_DOSE_SOURCES_GY = (
    ("dose_distribution_gy", "normalized"),
    ("dose_distribution_physical_gy", "physical"),
    ("dose_distribution", "normalized"),
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

    plan_config = retrieve("plan_config") or {}
    if not isinstance(plan_config, dict):
        plan_config = {}
    previous_metrics = retrieve("dose_metrics") or retrieve("metrics") or {}
    if not isinstance(previous_metrics, dict):
        previous_metrics = {}
    dose_scale = resolve_dose_scale_gy(
        plan_config,
        previous_metrics,
        dose_scale_gy=retrieve("dose_scale_gy"),
    )

    def _first(*keys: str) -> Any:
        # NumPy arrays do not define a scalar truth value; never select
        # workspace values with ``or``.
        for key in keys:
            value = retrieve(key)
            if value is not None:
                return value
        return None

    ct_grid_ctv = _as_array(_first("ctv_mask", "ctv_array", "ctv_binary_array"))
    ct_grid_oar = _as_array(_first("oar_array", "oar_label_data"))
    plan_grid_ctv = _as_array(retrieve("resampled_ctv"))
    plan_grid_oar = _as_array(retrieve("resampled_oar"))
    ct_spacing = retrieve("ct_spacing")
    try:
        ct_spacing = [float(v) for v in ct_spacing][:3] if ct_spacing is not None else None
    except (TypeError, ValueError):
        ct_spacing = None

    mask_pairs: Tuple[Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[list]], ...] = (
        (ct_grid_ctv, ct_grid_oar, ct_spacing),
        (plan_grid_ctv, plan_grid_oar, _planning_grid_spacing(retrieve) or ct_spacing),
    )

    seen_shapes = []
    for dose_key, unit in _DOSE_SOURCES_GY:
        dose = _as_array(retrieve(dose_key))
        if dose is None:
            continue
        seen_shapes.append((dose_key, dose.shape))
        to_gy = float(dose_scale) if unit == "normalized" else 1.0
        for ctv, oar, spacing in mask_pairs:
            if ctv is None or ctv.shape != dose.shape:
                continue
            oar_in = oar if (oar is not None and oar.shape == dose.shape) else None
            dose_gy = (dose.astype(np.float32, copy=False) * np.float32(to_gy))
            params: Dict[str, Any] = {
                "dose_array": dose_gy,
                "ctv_mask": ctv,
                "prescribed_dose": resolve_prescription_gy(
                    plan_config,
                    previous_metrics,
                    dose_scale_gy=dose_scale,
                    default_gy=DEFAULT_PRESCRIPTION_GY,
                ),
                "organ_names": retrieve("organ_names") or {},
                "tumor_type": str(
                    retrieve("tumor_type_used") or retrieve("tumor_type") or ""
                ),
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
