"""Explicit dose-volume unit boundaries; never infer units from magnitude."""
from collections.abc import Mapping
import math
import numpy as np

PHYSICAL_UNITS = frozenset({"gy", "physical_gy"})
MODEL_UNITS = frozenset({"normalized", "normalized_model", "normalized_model_output", "model", "model_units", "doseunet_normalized"})


def calibrated_scale(*sources, explicit=None):
    """Require saved calibration, or an explicitly identified legacy model."""
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("dose_scale_gy", "dose_model_scale_gy"):
            if source.get(key) is not None:
                return _positive_scale(source[key])
    if explicit is not None:
        return _positive_scale(explicit)
    if any(isinstance(s, Mapping) and s.get("dose_calibration") == "legacy_120_gy_per_model_unit" for s in sources):
        return 120.0
    raise ValueError("Dose calibration is missing; normalized dose cannot be exported or evaluated as Gy")


def _positive_scale(value):
    scale = float(value)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("dose_scale_gy must be finite and positive")
    return scale


def physical_volume(dose, *, units, scale=None):
    array = np.asarray(dose, dtype=np.float32)
    if array.ndim != 3 or not array.size or not np.isfinite(array).all() or np.any(array < 0):
        raise ValueError("Dose must be a nonempty finite nonnegative 3D volume")
    unit = str(units or "").strip().lower()
    if unit in PHYSICAL_UNITS:
        return array
    if unit not in MODEL_UNITS:
        raise ValueError("Explicit physical Gy or normalized model dose units are required")
    result = array * np.float32(_positive_scale(scale))
    if not np.isfinite(result).all():
        raise ValueError("Physical dose conversion overflowed")
    return result


def workspace_physical_dose(retrieve):
    physical = retrieve("dose_distribution_physical_gy")
    if physical is not None:
        return physical_volume(physical, units="physical_gy")
    normalized = retrieve("dose_distribution_gy")
    if normalized is not None:
        units = workspace_field_units(retrieve, "dose_distribution_gy")
    else:
        normalized = retrieve("dose_distribution")
        units = workspace_field_units(retrieve, "dose_distribution")
    if normalized is None:
        raise ValueError("No dose distribution is available")
    scale = None if str(units).lower() in PHYSICAL_UNITS else calibrated_scale(
        retrieve("dose_metrics"), retrieve("plan_config"), explicit=retrieve("dose_scale_gy"))
    return physical_volume(normalized, units=units, scale=scale)


def workspace_field_units(retrieve, key):
    """Read a field declaration or explicit historical provenance, never size."""
    if key == "dose_distribution_physical_gy":
        return "physical_gy"
    if key in {"dose_distribution_current_normalized", "dose_distribution_legacy_normalized",
               "algorithm_plan_dose_distribution_current_normalized"}:
        return "normalized_model"
    declared = (retrieve("dose_unit_metadata") or {}).get(key)
    if declared is None:
        declared = (retrieve("dose_unit_provenance") or {}).get(key)
    if declared is None and key == 'dose_distribution_gy' and retrieve('dose_unit_schema_version') in (None, 1):
        # This is a documented schema-1 field contract, not an amplitude
        # heuristic: the historical `_gy` alias stored model output even when
        # the generic scene units said Gy. A saved calibration is still
        # mandatory. Schema-2 writers declare this field as physical Gy.
        return 'normalized_model'
    if declared is None:
        declared = retrieve("dose_units")
    unit = str(declared or "").strip().lower()
    if unit not in PHYSICAL_UNITS | MODEL_UNITS:
        raise ValueError("Explicit dose units and calibration/provenance are required for " + key)
    return unit


def workspace_normalized_dose(retrieve, *, grid="current"):
    """Compatibility readers use model output only through this unit boundary."""
    if grid not in {"current", "planning"}:
        raise ValueError("Dose grid must be current or planning")
    keys = (("dose_distribution_current_normalized", "dose_distribution_physical_gy", "dose_distribution_gy")
            if grid == "current" else ("dose_distribution",))
    for key in keys:
        dose = retrieve(key)
        if dose is None:
            continue
        units = workspace_field_units(retrieve, key)
        if units in MODEL_UNITS:
            # Validate without converting an already normalized model field.
            return physical_volume(dose, units="physical_gy")
        scale = calibrated_scale(retrieve("dose_metrics"), retrieve("plan_config"),
                                 explicit=retrieve("dose_scale_gy"))
        return physical_volume(dose, units="physical_gy") / scale
    raise ValueError("No dose distribution is available on the requested grid")
