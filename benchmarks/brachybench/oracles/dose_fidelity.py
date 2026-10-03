"""Dose fidelity against an **independent** physical reference (DESIGN A3a).

Implements ``analytic_dose_fidelity`` (§8.3).

**Construct separation (N1/R1) -- read before using.**  This oracle measures
how faithful the *engine* is to an independent physical reference.  It says
nothing about whether the *agent* drove the dose workflow correctly (that is
A3b: ``dose_additivity`` + ``seed_geometry_fidelity`` + ``metric_provenance``)
and it is **excluded from any agent composite** (DESIGN M4).

The reference must be one of (§6.A3a, two-layer TG-186 framework):

* **layer 1** -- an offline TG-43U1 implementation on a homogeneous water
  phantom (validates the realisation of a stated formalism);
* **layer 2** -- an open Monte-Carlo pre-computation (OpenMC / EGSnrc / MCNP)
  or a commissioned TPS export on heterogeneous geometry.

Both layers are required; neither substitutes for the other.

**Physics definitions must be fixed *before* scoring (N9).**  Eight items:
nuclide & source model, source strength & reference instant, integration time
and dose definition, source orientation, material/density mapping,
dose-to-water vs dose-to-medium, grid/boundary/in-source handling, and the MC
statistical uncertainty.  Where the model's training assumptions differ from
the reference, the residual is reported as ``physics_assumption_gap`` and
**never absorbed by relaxing the pass threshold** (N9 forbids post-hoc
threshold relaxation).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .base import ConstraintClass, Oracle, OracleResult, Violation, register
from .tolerances import ARRAY_MAX_ABS_TOL_FRAC, ARRAY_MEAN_ABS_TOL_FRAC

# N9: the eight items that must be pinned before A3a can be interpreted
PHYSICS_DEFINITION_KEYS = (
    "nuclide_source_model",
    "source_strength_and_reference_instant",
    "integration_time_and_dose_definition",
    "source_orientation",
    "material_density_mapping",
    "dose_to_water_or_medium",
    "grid_boundary_and_in_source_handling",
    "mc_statistical_uncertainty",
)


@register
class AnalyticDoseFidelity(Oracle):
    """§8.3 ``analytic_dose_fidelity``: gamma pass rate + DVH metric deltas.

    Tolerances are declared **a priori** from the physics task, the reference
    uncertainty and the application purpose (N9).  There is deliberately no
    API to relax them after the fact.
    """

    id = "analytic_dose_fidelity"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        model_dose: Any,
        reference_dose: Any,
        *,
        spacing_mm: Sequence[float] = (1.0, 1.0, 1.0),
        dose_definition: Optional[str] = None,
        reference: Optional[Dict[str, Any]] = None,
        physics_definition: Optional[Dict[str, Any]] = None,
        gamma_criteria: Sequence[tuple] = ((3.0, 2.0),),
        gamma_pass_min: float = 0.95,
        dvh_tol_frac: float = 0.02,
        model_dvh: Optional[Dict[str, float]] = None,
        reference_dvh: Optional[Dict[str, float]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        m = np.asarray(model_dose, dtype=np.float64)
        r = np.asarray(reference_dose, dtype=np.float64)
        violations: List[Violation] = []
        gaps: List[Violation] = []

        # ---- N9: refuse to score without a pinned physics definition ------
        phys = physics_definition or {}
        missing = [k for k in PHYSICS_DEFINITION_KEYS if not phys.get(k)]
        if missing:
            gaps.append(Violation(
                "physics_definition_incomplete",
                f"N9: cannot interpret A3a without all 8 definition items; missing {missing}",
                at=at, detail={"missing": missing},
            ))

        if m.shape != r.shape:
            violations.append(Violation(
                "dose_shape_mismatch", f"{m.shape} vs {r.shape}", at=at))
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                violations=violations, evidence_gaps=gaps,
                constraint_class=self.constraint_class,
                applicable=False,
                notes="A3a engine fidelity; excluded from agent composite (M4)",
            )

        # ---- layer provenance must be declared -----------------------------
        ref = reference or {}
        layer = ref.get("layer")
        if layer not in ("TG-43U1 homogeneous", "MC/TPS heterogeneous"):
            gaps.append(Violation(
                "reference_layer_undeclared",
                "reference.layer must be one of the two TG-186 layers",
                at=at, detail={"layer": layer}))

        # ---- gamma ---------------------------------------------------------
        spacing = np.asarray(spacing_mm, dtype=np.float64)
        gamma_results = {}
        for dose_crit, dta_mm in gamma_criteria:
            rate = self._gamma_pass_rate(m, r, spacing, dose_crit, dta_mm)
            key = f"gamma_{dose_crit:g}pct_{dta_mm:g}mm"
            gamma_results[key] = rate
            if rate < gamma_pass_min:
                violations.append(Violation(
                    "gamma_pass_rate_below_threshold",
                    f"{key} = {rate:.4f} < {gamma_pass_min} (threshold fixed a priori, N9)",
                    at=at, detail={key: rate, "min": gamma_pass_min}))

        # ---- DVH metric deltas ---------------------------------------------
        dvh: Dict[str, Any] = {}
        if model_dvh and reference_dvh:
            for k in sorted(set(model_dvh) | set(reference_dvh)):
                mv, rv = model_dvh.get(k), reference_dvh.get(k)
                if mv is None or rv is None:
                    continue
                rel = abs(float(mv) - float(rv)) / max(abs(float(rv)), 1e-12)
                dvh[k] = {"model": float(mv), "reference": float(rv), "rel_err": rel}
                if rel > dvh_tol_frac:
                    violations.append(Violation(
                        "dvh_metric_rel_err_above_tolerance",
                        f"{k}: |Δ|/ref = {rel:.4%} > {dvh_tol_frac:.2%}",
                        at=at, detail=dvh[k]))

        # ---- array + spatial error (N11: replaces "gamma 0%/0mm") ----------
        max_abs = float(np.max(np.abs(m - r)))
        mean_abs = float(np.mean(np.abs(m - r)))
        ref_max = float(np.max(np.abs(r))) or 1.0
        array_err = {
            "max_abs": max_abs, "mean_abs": mean_abs,
            "max_abs_frac_of_ref": max_abs / ref_max,
            "within_max_tol": max_abs <= ARRAY_MAX_ABS_TOL_FRAC * ref_max,
            "within_mean_tol": mean_abs <= ARRAY_MEAN_ABS_TOL_FRAC * ref_max,
        }

        # ---- N9: report the assumption gap separately ----------------------
        gap = None
        if phys.get("model_training_assumption") and phys.get("reference_assumption"):
            if phys["model_training_assumption"] != phys["reference_assumption"]:
                gap = {
                    "model_training_assumption": phys["model_training_assumption"],
                    "reference_assumption": phys["reference_assumption"],
                }
                gaps.append(Violation(
                    "physics_assumption_gap",
                    "model and reference rest on different physical assumptions; "
                    "the residual must be reported, never absorbed by lowering "
                    "the pass threshold (N9)",
                    at=at, detail=gap))

        applicable = not any(v.code == "physics_definition_incomplete" for v in gaps)
        passed = applicable and not violations
        return OracleResult(
            oracle_id=self.id, passed=passed,
            score=float(next(iter(gamma_results.values()), 0.0)) if gamma_results else 0.0,
            violations=violations, evidence_gaps=gaps,
            evidence={
                "layer": layer,
                "dose_definition": dose_definition or phys.get("dose_to_water_or_medium"),
                "gamma": gamma_results, "gamma_pass_min": gamma_pass_min,
                "dvh": dvh, "dvh_tol_frac": dvh_tol_frac,
                "array_and_spatial_error": array_err,
                "reference_uncertainty": ref.get("statistical_uncertainty"),
                "physics_assumption_gap": gap,
            },
            constraint_class=self.constraint_class,
            applicable=applicable,
            notes=(
                "A3a engine fidelity vs an independent reference -- NOT an agent "
                "score (M4), NOT absolute human dose accuracy (§1.2)"
            ),
        )

    @staticmethod
    def _gamma_pass_rate(m: np.ndarray, r: np.ndarray, spacing: np.ndarray,
                         dose_crit_pct: float, dta_mm: float,
                         dose_threshold_pct: float = 10.0,
                         search_radius_mm: float = 6.0) -> float:
        """Standard gamma index on the high-dose region.

        A reference point is evaluated only above ``dose_threshold_pct`` of the
        reference maximum (the usual convention); for each we search a local
        neighbourhood for a model point satisfying the combined criterion.
        A KD-tree-free brute force is used on a cropped window -- adequate for
        the phantom sizes in this suite and free of extra dependencies.
        """
        rmax = float(np.max(np.abs(r))) or 1.0
        thresh = (dose_threshold_pct / 100.0) * rmax
        crit = (dose_crit_pct / 100.0) * rmax
        idx = np.argwhere(r > thresh)
        if idx.size == 0:
            return 1.0
        step = spacing[::-1] if spacing.size == 3 else np.ones(3)
        # index order is [z, y, x]; spacing is given [x, y, z]
        sz = np.asarray([spacing[2], spacing[1], spacing[0]], dtype=np.float64) \
            if spacing.size == 3 else np.ones(3)
        rad_vox = np.ceil(search_radius_mm / np.maximum(sz, 1e-9)).astype(int)
        passed = 0
        for ijk in idx:
            z, y, x = int(ijk[0]), int(ijk[1]), int(ijk[2])
            z0, z1 = max(0, z - rad_vox[0]), min(r.shape[0], z + rad_vox[0] + 1)
            y0, y1 = max(0, y - rad_vox[1]), min(r.shape[1], y + rad_vox[1] + 1)
            x0, x1 = max(0, x - rad_vox[2]), min(r.shape[2], x + rad_vox[2] + 1)
            sub = m[z0:z1, y0:y1, x0:x1]
            if sub.size == 0:
                continue
            zz, yy, xx = np.meshgrid(
                np.arange(z0, z1) * sz[0] - z * sz[0],
                np.arange(y0, y1) * sz[1] - y * sz[1],
                np.arange(x0, x1) * sz[2] - x * sz[2],
                indexing="ij",
            )
            dist = np.sqrt(zz * zz + yy * yy + xx * xx)
            val = r[z, y, x]
            # gamma^2 = (dist/dta)^2 + ((m - r)/crit)^2
            g2 = (dist / max(dta_mm, 1e-9)) ** 2 + ((sub - val) / max(crit, 1e-12)) ** 2
            if float(np.min(g2)) <= 1.0:
                passed += 1
        return passed / float(idx.shape[0])
