"""Shared, unit-aware helpers for advisory clinical review agents.

This module does not define clinical limits. Limits must come from a
source-backed runtime configuration or the clinical knowledge base.
"""

import re
from typing import Any, Dict, Iterable, Optional, Tuple


def parse_numeric(value: Any) -> Tuple[Optional[float], str]:
    """Return a numeric value and its explicit unit marker, if present."""
    if isinstance(value, bool) or value is None:
        return None, ""
    if isinstance(value, (int, float)):
        return float(value), ""
    text = str(value).strip()
    match = re.fullmatch(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(%|Gy)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, ""
    unit = match.group(2) or ""
    return float(match.group(1)), unit.lower()


def first_numeric(values: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    if not isinstance(values, dict):
        return None
    for key in keys:
        if key not in values:
            continue
        value, _ = parse_numeric(values[key])
        if value is not None:
            return value
    return None


def normalized_fraction(value: Any) -> Optional[float]:
    numeric, unit = parse_numeric(value)
    if numeric is None:
        return None
    if unit == "%" or numeric > 1.5:
        return numeric / 100.0
    return numeric


def metric_value(metrics: Dict[str, Any], key: str) -> Optional[float]:
    return first_numeric(metrics, (key, key.upper(), key.capitalize()))


def dose_ratio(dose_metrics: Dict[str, Any], plan_config: Dict[str, Any],
               key: str) -> Optional[float]:
    """Convert a dose metric to prescription ratio without assuming 120 Gy."""
    value = metric_value(dose_metrics, key)
    if value is None:
        return None
    if value <= 5.0:
        return value

    prescription = first_numeric(
        dose_metrics, ("prescribed_dose", "prescription", "prescription_dose")
    )
    if prescription is None:
        prescription = first_numeric(
            plan_config, ("prescribed_dose", "prescription_dose", "in_lowest_energy")
        )
    if prescription is None:
        return None

    if prescription <= 5.0:
        scale = first_numeric(dose_metrics, ("dose_scale_gy",))
        if scale is None:
            scale = first_numeric(plan_config, ("dose_scale_gy",))
        if scale is None:
            return None
        prescription *= scale
    return value / prescription if prescription > 0 else None


def canonical_organ_name(name: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return normalized[4:] if normalized.startswith("oar_") else normalized


def match_constraint_name(organ_name: Any,
                          constraints: Dict[str, dict]) -> Optional[str]:
    """Match exact organ names, allowing only explicit laterality suffixes."""
    organ = canonical_organ_name(organ_name)
    canonical = {canonical_organ_name(k): k for k in constraints}
    if organ in canonical:
        return canonical[organ]
    for suffix in ("_left", "_right"):
        if organ.endswith(suffix) and organ[:-len(suffix)] in canonical:
            return canonical[organ[:-len(suffix)]]
    return None


def cumulative_dvh_consistency(dose_metrics: Dict[str, Any]) -> list[str]:
    """Check mathematical DVH invariants, not clinical acceptability."""
    concerns: list[str] = []
    fractions = {
        key: normalized_fraction(dose_metrics.get(key, dose_metrics.get(key.upper())))
        for key in ("v100", "v150", "v200")
    }
    for key, value in fractions.items():
        if value is not None and not 0.0 <= value <= 1.0:
            concerns.append(f"{key.upper()}={value:.3g} is outside the valid [0, 1] range.")
    ordered = [fractions[k] for k in ("v100", "v150", "v200")]
    if all(value is not None for value in ordered) and not (
        ordered[0] >= ordered[1] >= ordered[2]
    ):
        concerns.append("Cumulative DVH invariant violated: V100 must be >= V150 >= V200.")

    dose_order = [metric_value(dose_metrics, key) for key in ("max_dose", "d2", "d90", "min_dose")]
    available = [value for value in dose_order if value is not None]
    if any(value < 0 for value in available):
        concerns.append("Dose metrics contain a negative value.")
    if len(available) == len(dose_order) and not (
        dose_order[0] >= dose_order[1] >= dose_order[2] >= dose_order[3]
    ):
        concerns.append("Dose-order invariant violated: max >= D2 >= D90 >= min is expected.")
    return concerns
