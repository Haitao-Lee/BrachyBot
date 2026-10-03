"""``dose_additivity`` -- internal consistency of multi-source dose summation.

DESIGN N10 check #5 (out of six).  ``cnn_dose_engine.py:166`` computes
``cumulative_dose = np.sum(np.asarray(per_seed_doses), axis=0)`` *inside the
same function that produced the contributions*; therefore this check proves
**only** that the summation arithmetic is self-consistent.

It does **not** prove that source coordinates, source strengths, particle
completeness or the single-seed physics are right -- an all-zero contribution
set passes.  Report it alongside the five independent checks of §6.A3b and
never as evidence of dose *accuracy* (that is A3a).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .base import (
    ConstraintClass,
    Oracle,
    OracleResult,
    PartialStatus,
    Violation,
    register,
)
from .tolerances import dose_additivity_eps


@register
class DoseAdditivity(Oracle):
    id = "dose_additivity"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        cumulative_dose: Any,
        per_seed_doses: Sequence[Any],
        *,
        seed_ids: Optional[Sequence[str]] = None,
        expect_seed_ids: Optional[Sequence[str]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        evidence_gaps: List[Violation] = []

        # ---- check #2 (source inventory) is cheap and rides along ---------
        # BA-4 (round 3): never fabricate the observed inventory.  If the
        # caller demands an inventory check but supplies no observation, that
        # is *unverifiable*, not a mismatch.  It belongs in ``evidence_gaps``
        # (-> INSUFFICIENT_EVIDENCE / N6 outcome G2), NOT in ``violations``
        # (which would wrongly report DOES_NOT_MEET).
        inventory_known = seed_ids is not None
        if expect_seed_ids is not None:
            if not inventory_known:
                evidence_gaps.append(
                    Violation(
                        code="seed_inventory_unknown",
                        message=(
                            "expect_seed_ids given but seed_ids not observed; "
                            "cannot verify source inventory (BA-4)"
                        ),
                        at=at,
                        detail={"expected": list(expect_seed_ids)},
                    )
                )
            elif sorted(map(str, seed_ids)) != sorted(map(str, expect_seed_ids)):
                violations.append(
                    Violation(
                        code="seed_inventory_mismatch",
                        message=(
                            f"computed seeds {sorted(map(str, seed_ids))} != "
                            f"expected {sorted(map(str, expect_seed_ids))}"
                        ),
                        at=at,
                        detail={
                            "got": list(seed_ids),
                            "expected": list(expect_seed_ids),
                        },
                    )
                )

        if cumulative_dose is None or not per_seed_doses:
            # BA-6: nothing to judge is not a pass.  Report it as an evidence
            # gap (N/A), never as a confirmed violation, so the gate returns
            # INSUFFICIENT_EVIDENCE rather than DOES_NOT_MEET.
            evidence_gaps.append(
                Violation(
                    code="insufficient_assertion_coverage",
                    message=(
                        "cumulative_dose or per_seed_doses empty; refusing to "
                        "award a pass (BA-6)"
                    ),
                    at=at,
                )
            )
            return OracleResult(
                oracle_id=self.id,
                passed=False,
                score=0.0,
                violations=violations,
                evidence_gaps=evidence_gaps,
                constraint_class=self.constraint_class,
                applicable=False,
                coverage=0.0,
                partial_status=PartialStatus.PARTIAL,
                notes=(
                    "additivity not computable (BA-6: N/A, not a pass); "
                    "N10: also vacuously true if all contributions are zero"
                ),
            )

        cum = np.asarray(cumulative_dose, dtype=np.float64)
        acc = np.zeros_like(cum, dtype=np.float64)  # M19: float64 accumulation
        for i, d in enumerate(per_seed_doses):
            arr = np.asarray(d, dtype=np.float64)
            if arr.shape != cum.shape:
                violations.append(
                    Violation(
                        code="per_seed_shape_mismatch",
                        message=f"per_seed_doses[{i}] shape {arr.shape} != {cum.shape}",
                        at=at,
                    )
                )
                return OracleResult(
                    oracle_id=self.id,
                    passed=False,
                    score=0.0,
                    violations=violations,
                    evidence_gaps=evidence_gaps,
                    constraint_class=self.constraint_class,
                    partial_status=PartialStatus.FAILED_VERIFICATION,
                )
            acc += arr

        max_abs = float(np.max(np.abs(cum))) if cum.size else 0.0
        eps = dose_additivity_eps(max_abs)  # M19: 1e-4 * max|cum|
        resid = float(np.max(np.abs(acc - cum))) if cum.size else 0.0
        additivity_ok = resid <= eps

        if not additivity_ok:
            violations.append(
                Violation(
                    code="additivity_residual",
                    message=f"|sum(per_seed)-cumulative|_inf = {resid:.6g} > eps {eps:.6g}",
                    at=at,
                    detail={"residual_inf": resid, "eps": eps, "max_abs": max_abs},
                )
            )

        passed = additivity_ok and not violations and not evidence_gaps
        return OracleResult(
            oracle_id=self.id,
            passed=passed,
            score=1.0 if passed else 0.0,
            violations=violations,
            evidence_gaps=evidence_gaps,
            partial_status=(
                PartialStatus.COMPLETED
                if passed
                else PartialStatus.FAILED_VERIFICATION
                if violations
                else PartialStatus.PARTIAL
            ),
            evidence={
                "residual_inf": resid,
                "eps": eps,
                "max_abs_cumulative": max_abs,
                "n_seeds": len(per_seed_doses),
                "accumulation": "float64",
            },
            constraint_class=self.constraint_class,
            notes=(
                "internal consistency only (N10); not a statement of dose accuracy "
                "(that is A3a vs an independent physical reference)"
            ),
        )
