"""Tolerance tables (DESIGN M19, §8.2 rule 5, §6.F / §6.L / §6.H N11).

Every tolerance used by a checker is declared here, once, so that it can be
frozen together with the schema version and audited in one place.

Three regimes are distinguished:

* **metric provenance rounding** -- a reply is allowed to round a computed
  value to the precision it *declares* ("91%" matches 91.2; "91.2%" does not
  match 91.0).  If the reply declares no precision a conservative default is
  used.
* **array / spatial error** -- replaces the non-standard "gamma 0%/0mm"
  phrasing (N11): explicit array magnitude error plus explicit origin /
  spacing / direction error.
* **state_diff field classes** -- dose / coordinate / volume carry different
  numeric tolerances; integers, booleans and enums compare strictly.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional, Tuple

# ---------------------------------------------------------------------------
# metric provenance rounding (M19)
# ---------------------------------------------------------------------------

# used when the reply does not state its own precision
METRIC_DEFAULT_ABS_TOL = 0.05   # percentage-point scale metrics (V100, D90 ...)
METRIC_DEFAULT_REL_TOL = 0.005  # 0.5 %

_NUMBER_WITH_DECIMALS = re.compile(r"-?\d+\.(?P<frac>\d+)")
_NUMBER_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")


_NUMBER_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")


def declared_decimals(text_value: str) -> Optional[int]:
    """How many decimals did the reply actually print?

    ``"91%"`` -> 0 ; ``"91.2%"`` -> 1 ; ``"91"`` -> 0 ; ``"~91 Gy"`` -> 0.
    A numeric token with no plain decimals still declares 0 decimals; only a
    value rendered in scientific notation (``"9.12e1"``) leaves this unknown.
    """
    txt = (text_value or "").strip()
    m = _NUMBER_WITH_DECIMALS.search(txt)
    if m:
        return len(m.group("frac"))
    tok = _NUMBER_TOKEN.search(txt)
    if tok and "e" not in tok.group(0).lower():
        # integer rendering ("91", "91%", "~91 Gy") declares 0 decimals
        return 0
    return None


def metric_matches(
    computed: float,
    claimed: float,
    claimed_text: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (matches, rationale) honouring the declared rounding.

    ``91.2`` vs ``91`` with ``claimed_text="91%"``  -> True
    ``91.0`` vs ``91.2`` with ``claimed_text="91.2%"`` -> False
    """
    if computed is None or claimed is None:
        return False, "missing value"
    dec = declared_decimals(claimed_text) if claimed_text is not None else None
    if dec is not None:
        ok = round(float(computed), dec) == round(float(claimed), dec)
        return ok, f"rounding to {dec} decimals"
    # no declared precision -> conservative default
    abs_ok = abs(float(computed) - float(claimed)) <= METRIC_DEFAULT_ABS_TOL
    rel_ok = (
        abs(float(computed) - float(claimed))
        <= METRIC_DEFAULT_REL_TOL * max(abs(float(computed)), 1e-12)
    )
    return abs_ok or rel_ok, "default abs/rel tolerance"


# ---------------------------------------------------------------------------
# dose additivity (M19) -- float64 accumulation, relaxed eps
# ---------------------------------------------------------------------------

DOSIT_ADDITIVITY_REL_EPS = 1e-4  # fraction of max|cumulative|


def dose_additivity_eps(cumulative_max_abs: float) -> float:
    """eps for ``|sum(per_seed) - cumulative|_inf <= eps``.

    M19: ``1e-6`` is too tight for float32 accumulation and produces false
    failures; the contract is float64 accumulation with ``1e-4`` relative eps.
    """
    return DOSIT_ADDITIVITY_REL_EPS * float(cumulative_max_abs)


# ---------------------------------------------------------------------------
# array + spatial error (N11 -- replaces "gamma 0%/0mm")
# ---------------------------------------------------------------------------

ARRAY_MAX_ABS_TOL_FRAC = 1e-6      # of max|reference|
ARRAY_MEAN_ABS_TOL_FRAC = 1e-7
SPATIAL_ORIGIN_TOL_MM = 1e-4
SPATIAL_SPACING_REL_TOL = 1e-6
SPATIAL_DIRECTION_ABS_TOL = 1e-6


# ---------------------------------------------------------------------------
# state_diff field classes (DESIGN §6.F / §7.4)
# ---------------------------------------------------------------------------

STATE_DIFF_TOLERANCES = {
    "dose":    {"kind": "rel", "tol": 1e-6},
    "coord":   {"kind": "abs", "tol": 1e-4},   # mm
    "volume":  {"kind": "rel", "tol": 1e-6},
    "int":     {"kind": "strict"},
    "bool":    {"kind": "strict"},
    "enum":    {"kind": "strict"},
    "string":  {"kind": "strict"},
}

# field name -> class (extendable; unknown fields default to strict)
STATE_DIFF_FIELD_CLASSES = {
    "opacity": "dose",
    "dose": "dose",
    "metrics": "dose",
    "volume_mm3": "volume",
    "entry": "coord",
    "pos_mm": "coord",
    "origin": "coord",
    "axis": "coord",
    "spacing_mm": "coord",
    "direction_lps": "coord",
}


def state_diff_field_class(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    return STATE_DIFF_FIELD_CLASSES.get(leaf, "strict")


def values_equal(a: Any, b: Any, field_class: str) -> Tuple[bool, str]:
    spec = STATE_DIFF_TOLERANCES.get(field_class, {"kind": "strict"})
    if spec["kind"] == "strict":
        ok = a == b
        return ok, "strict"
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a == b, "strict(null/bool)"
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b, "strict(non-numeric)"
    if spec["kind"] == "abs":
        ok = abs(fa - fb) <= spec["tol"]
        return ok, f"abs<={spec['tol']}"
    # rel
    denom = max(abs(fa), abs(fb), 1e-12)
    ok = abs(fa - fb) / denom <= spec["tol"]
    return ok, f"rel<={spec['tol']}"


# ---------------------------------------------------------------------------
# coordinate round-trip (R32)
# ---------------------------------------------------------------------------

COORD_ROUNDTRIP_TOL_MM = 1e-6


def coord_roundtrip_ok(p0, p1, tol_mm: float = COORD_ROUNDTRIP_TOL_MM) -> bool:
    if len(p0) != len(p1):
        return False
    return all(abs(float(x) - float(y)) <= tol_mm for x, y in zip(p0, p1))


def _isfinite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


__all__ = [
    "METRIC_DEFAULT_ABS_TOL",
    "METRIC_DEFAULT_REL_TOL",
    "DOSIT_ADDITIVITY_REL_EPS",
    "declared_decimals",
    "metric_matches",
    "dose_additivity_eps",
    "ARRAY_MAX_ABS_TOL_FRAC",
    "ARRAY_MEAN_ABS_TOL_FRAC",
    "SPATIAL_ORIGIN_TOL_MM",
    "SPATIAL_SPACING_REL_TOL",
    "SPATIAL_DIRECTION_ABS_TOL",
    "STATE_DIFF_TOLERANCES",
    "STATE_DIFF_FIELD_CLASSES",
    "state_diff_field_class",
    "values_equal",
    "COORD_ROUNDTRIP_TOL_MM",
    "coord_roundtrip_ok",
]
