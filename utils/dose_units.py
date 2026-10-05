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
        # Despite its historical name this key is normalized by contract.
        units = "normalized"
    else:
        normalized = retrieve("dose_distribution")
        units = retrieve("dose_units")
    if normalized is None:
        raise ValueError("No dose distribution is available")
    scale = None if str(units).lower() in PHYSICAL_UNITS else calibrated_scale(
        retrieve("dose_metrics"), retrieve("plan_config"), explicit=retrieve("dose_scale_gy"))
    return physical_volume(normalized, units=units, scale=scale)
