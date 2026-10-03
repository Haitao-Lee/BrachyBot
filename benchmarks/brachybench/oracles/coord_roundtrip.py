"""``coord_roundtrip`` -- voxel <-> physical coordinate fidelity (DESIGN A1, R32).

``tool_factory/segmentation_alignment.py:3`` states the hazard explicitly:
"NumPy arrays do not carry origin, spacing, direction, or axis semantics."
Coordinate mistakes are a recurring bug source in this codebase (historical
``VISUAL_LOCATION_FIX`` and several ``MONITOR_*`` fixes), so they get a
dedicated deterministic checker.

Checks:
1. voxel -> physical -> voxel round trip (tol 1e-6 mm)
2. origin / spacing / direction consistency between two image headers
3. direction matrix is a proper rotation (orthonormal, det = +1)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .base import ConstraintClass, Oracle, OracleResult, Violation, register
from .tolerances import (
    COORD_ROUNDTRIP_TOL_MM,
    SPATIAL_DIRECTION_ABS_TOL,
    SPATIAL_ORIGIN_TOL_MM,
    SPATIAL_SPACING_REL_TOL,
    coord_roundtrip_ok,
)


def voxel_to_physical(voxel, origin, spacing, direction) -> Tuple[float, float, float]:
    """Index (i, j, k) -> physical (LPS) using the ITK convention."""
    v = np.asarray(voxel, dtype=np.float64).reshape(-1)
    o = np.asarray(origin, dtype=np.float64).reshape(-1)
    s = np.asarray(spacing, dtype=np.float64).reshape(-1)
    d = np.asarray(direction, dtype=np.float64).reshape(3, 3)
    return tuple(float(x) for x in (d @ (v * s) + o))


def physical_to_voxel(phys, origin, spacing, direction) -> Tuple[float, float, float]:
    p = np.asarray(phys, dtype=np.float64).reshape(-1)
    o = np.asarray(origin, dtype=np.float64).reshape(-1)
    s = np.asarray(spacing, dtype=np.float64).reshape(-1)
    d = np.asarray(direction, dtype=np.float64).reshape(3, 3)
    return tuple(float(x) for x in (np.linalg.inv(d) @ (p - o) / s))


@register
class CoordRoundtrip(Oracle):
    id = "coord_roundtrip"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        *,
        samples: Optional[Sequence[Sequence[float]]] = None,
        origin: Optional[Sequence[float]] = None,
        spacing: Optional[Sequence[float]] = None,
        direction: Optional[Sequence[float]] = None,
        header_a: Optional[Dict[str, Any]] = None,
        header_b: Optional[Dict[str, Any]] = None,
        at: Optional[str] = None,
        physical_samples: Optional[Sequence[Sequence[float]]] = None,
        expected_physical: Optional[Sequence[Sequence[float]]] = None,
        require_right_handed: bool = True,
    ) -> OracleResult:
        violations: List[Violation] = []
        evidence: Dict[str, Any] = {}
        gaps: List[Violation] = []
        if direction is None and header_a is None and header_b is None:
            gaps.append(Violation("coordinate_observation_missing", "coordinate samples or complete paired headers required"))
        for value, size, label in ((origin, 3, "origin"), (spacing, 3, "spacing"), (direction, 9, "direction")):
            if value is not None:
                arr = np.asarray(value, dtype=float).reshape(-1)
                if arr.size != size or not np.isfinite(arr).all() or (label == "spacing" and np.any(arr <= 0)):
                    return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                        evidence_gaps=[Violation("coordinate_header_invalid", f"{label}: finite correct-size values required; spacing must be positive")])

        # ---- 1. direction must be a proper rotation -----------------------
        if direction is not None:
            d = np.asarray(direction, dtype=np.float64).reshape(3, 3)
            eye = d @ d.T
            ortho_err = float(np.max(np.abs(eye - np.eye(3))))
            det = float(np.linalg.det(d))
            evidence["direction_orthonormality_err"] = ortho_err
            evidence["direction_det"] = det
            if ortho_err > SPATIAL_DIRECTION_ABS_TOL:
                violations.append(
                    Violation(
                        "direction_not_orthonormal",
                        f"max|D D^T - I| = {ortho_err:.3g}",
                        at=at,
                    )
                )
            if det < 0 and require_right_handed:
                violations.append(
                    Violation(
                        "direction_reflection",
                        f"det(D) = {det:.6g} < 0 (reflection / left-handed axes)",
                        at=at,
                    )
                )

        # ---- 2. voxel -> physical -> voxel round trip ---------------------
        if samples is not None and origin is not None and spacing is not None and direction is not None:
            worst = 0.0
            for s in samples:
                phys = voxel_to_physical(s, origin, spacing, direction)
                back = physical_to_voxel(phys, origin, spacing, direction)
                err = float(np.max(np.abs(np.asarray(s) - np.asarray(back)) * np.asarray(spacing)))
                if err > COORD_ROUNDTRIP_TOL_MM:
                    # report in mm-equivalent for clarity
                    err = max(
                        abs(float(x) - float(y)) * abs(float(sp))
                        for x, y, sp in zip(s, back, spacing)
                    )
                    worst = max(worst, err)
                    violations.append(
                        Violation(
                            "coord_roundtrip_error",
                            f"voxel {list(s)} -> phys -> voxel {list(back)} "
                            f"(err {err:.3g} mm)",
                            at=at,
                        )
                    )
            evidence["worst_roundtrip_err_mm"] = worst
        if expected_physical is not None:
            if physical_samples is None:
                gaps.append(Violation("physical_observation_missing", "SUT physical outputs required for independent coordinate validation"))
            else:
                actual, expected = np.asarray(physical_samples, dtype=float), np.asarray(expected_physical, dtype=float)
                if (actual.shape != expected.shape or actual.size == 0 or not np.isfinite(actual).all()
                        or not np.isfinite(expected).all() or not np.allclose(actual, expected, atol=COORD_ROUNDTRIP_TOL_MM, rtol=0)):
                    violations.append(Violation("physical_coordinate_mismatch", "SUT transform differs from independent patient-space reference"))

        # ---- 3. header consistency ---------------------------------------
        if header_a is not None and header_b is not None:
            for key, rel in (("origin", False), ("spacing", True), ("direction", False)):
                a = np.asarray(header_a.get(key), dtype=np.float64).reshape(-1)
                b = np.asarray(header_b.get(key), dtype=np.float64).reshape(-1)
                size = 9 if key == "direction" else 3
                if (a.shape != b.shape or a.size != size or not np.isfinite(a).all() or not np.isfinite(b).all()
                        or key == "spacing" and (np.any(a <= 0) or np.any(b <= 0))):
                    violations.append(
                        Violation(
                            f"header_{key}_shape",
                            f"{key}: {a.shape} != {b.shape}",
                            at=at,
                        )
                    )
                    continue
                if rel:
                    denom = np.maximum(np.abs(a), 1e-12)
                    err = float(np.max(np.abs(a - b) / denom))
                    tol = SPATIAL_SPACING_REL_TOL
                else:
                    err = float(np.max(np.abs(a - b)))
                    tol = SPATIAL_ORIGIN_TOL_MM if key == "origin" else SPATIAL_DIRECTION_ABS_TOL
                evidence[f"header_{key}_err"] = err
                if err > tol:
                    violations.append(
                        Violation(
                            f"header_{key}_mismatch",
                            f"{key}: max err {err:.3g} > tol {tol:.3g}",
                            at=at,
                        )
                    )

        passed = not violations and not gaps
        return OracleResult(
            oracle_id=self.id,
            passed=passed,
            score=1.0 if passed else 0.0,
            violations=violations,
            evidence_gaps=gaps,
            evidence=evidence,
            constraint_class=self.constraint_class,
            notes=(
                "ITK convention: phys = D @ (voxel * spacing) + origin "
                f"(round-trip tol {COORD_ROUNDTRIP_TOL_MM} mm)"
            ),
        )
